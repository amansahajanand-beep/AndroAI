"""Security rules: exported components, provider grants, cleartext traffic, PendingIntent
mutability, receiver export flags and permission consistency.

Documented behaviour these rest on (developer.android.com; checked against the pages, not from
memory):

* ``PendingIntent``: from Android 12 (API 31) the mutability must be given explicitly with
  ``FLAG_IMMUTABLE`` or ``FLAG_MUTABLE``. For apps targeting Android 14 (API 34), creating a
  ``FLAG_MUTABLE`` PendingIntent around an implicit Intent throws ``IllegalArgumentException``
  unless ``FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT`` is passed.
* ``Context.registerReceiver``: apps targeting Android 14 must say ``RECEIVER_EXPORTED`` or
  ``RECEIVER_NOT_EXPORTED`` when registering for anything other than system broadcasts.
* ``<provider>``: ``android:exported`` is false by default (API 17+); ``grantUriPermissions="true"``
  lets permission be granted for any of the provider's data, and ``<grant-uri-permission>`` with a
  path prefix of ``/`` or a pattern ``.*`` shares all of it. The security tips say to export only
  what other apps must reach, and to protect what is exported with a permission.
* Cleartext: ``usesCleartextTraffic`` defaults to true up to API 27 and false from API 28; it is
  ignored on API 24+ when a ``networkSecurityConfig`` is present, and ``cleartextTrafficPermitted``
  there "should be avoided whenever possible".
* Permissions: a "dangerous" permission (the reference page states the protection level) must be
  declared in the manifest and granted by the user at run time.

Every rule is silent when it cannot read what it needs: a flag held in a variable, an intent built
elsewhere, a filter in a field, a target SDK that is not a literal, a network security config that
cannot be found. A finding that is wrong would block a correct patch.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator

from ..analysis import ManifestInfo, ProjectAnalysis
from ..catalog import DANGEROUS_PERMISSIONS
from ..models import Finding, Severity, finding
from ..securityfacts import SecurityFacts
from ..xmlparse import XmlNode
from .manifest import _nodes, _removed

_ANDROID_PERMISSION = "android.permission."
_FRAMEWORK_ACTIONS = ("android.", "androidx.", "com.android.", "com.google.")
_PROTECTING = ("android:permission", "android:readPermission", "android:writePermission")
_LOCAL_SUFFIXES = (".local", ".localhost", ".test", ".example", ".invalid", ".internal", ".lan")
_PLACEHOLDER_HOSTS = (
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "schemas.android.com",
    "www.w3.org",
    "xmlpull.org",
    "java.sun.com",
    "xml.org",
)
_PERMISSION_TEXT = re.compile(r"android\.permission\.([A-Z][A-Z0-9_]*)")


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    if a.manifests:
        yield from _components(a)
        yield from _provider_grants(a)
        yield from _cleartext_config(a)
        yield from _permissions(a)
    facts: SecurityFacts = a.security
    yield from _pending_intents(a, facts)
    yield from _receivers(a, facts)
    yield from _cleartext_urls(a, facts)


# -- helpers ------------------------------------------------------------------------------------


def _target_for(a: ProjectAnalysis, path: str) -> int | None:
    """The target SDK that applies to ``path``: its own module's, or for a library module the
    application modules'. ``None`` unless it is certain: a library used by an app whose target
    cannot be read is not judged."""
    module = a.module_of(path)
    if module is not None:
        for script in a.module_scripts(module):
            declared = a.target_sdk_of(script)
            if declared:
                return declared[0]
    app_targets: list[int | None] = []
    for candidate in sorted(a.modules):
        if a.is_application(candidate):
            found = [d[0] for s in a.module_scripts(candidate) if (d := a.target_sdk_of(s))]
            app_targets.append(found[0] if found else None)
    if app_targets:
        return None if None in app_targets else min(t for t in app_targets if t is not None)
    return a.target.target_sdk


# -- suppressions the project already made ------------------------------------------------------
#
# A finding the developer has already acknowledged with Android lint's own mechanisms is not news.
# The lint issue ids below are the ones documented for the same condition ("Receiver does not
# require permission" = ExportedReceiver, and so on); where no id is documented, no suppression is
# honoured. Honouring one anywhere in a file or project errs towards silence.

_LINT_ID = {
    "security.provider_exported_unprotected": "ExportedContentProvider",
    "security.service_exported_unprotected": "ExportedService",
    "security.receiver_exported_unprotected": "ExportedReceiver",
    "security.provider_grants_all": "GrantAllUris",
    "security.cleartext_permitted": "InsecureBaseConfiguration",
    "security.pending_intent_mutability": "UnspecifiedImmutableFlag",
    "security.pending_intent_mutable_implicit": "MutableImplicitPendingIntent",
    "security.receiver_export_flag_missing": "UnspecifiedRegisterReceiverFlag",
}
_GRADLE_DISABLE = re.compile(r"\b(?:disable|ignore)\b")


def _ignored(nodes: tuple[XmlNode | None, ...], rule: str) -> bool:
    """``tools:ignore="ExportedReceiver"`` (or ``all``) on the element or an enclosing one."""
    lint_id = _LINT_ID[rule]
    for node in nodes:
        if node is None:
            continue
        listed = {part.strip() for part in node.attrs.get("tools:ignore", "").split(",")}
        if lint_id in listed or "all" in listed:
            return True
    return False


def _lint_disabled(a: ProjectAnalysis) -> frozenset[str]:
    """Lint ids switched off for the whole project: ``lint.xml`` entries with severity ``ignore``
    and no path restriction, and ids named after ``disable`` / ``ignore`` in a Gradle script that
    configures lint."""
    cached = a.__dict__.get("_security_lint_disabled")
    if cached is not None:
        return cached
    ids = set(_LINT_ID.values())
    off: set[str] = set()
    for path, text in a.files.texts.items():
        name = path.rsplit("/", 1)[-1]
        if name == "lint.xml":
            doc = a.xml_docs.get(path)
            for node in doc.root.find_all("issue") if doc and doc.root else []:
                if node.attrs.get("severity") == "ignore" and not node.child_nodes("ignore"):
                    off.add(node.attrs.get("id", ""))
        elif name.endswith((".gradle", ".kts")) and "lint" in text:
            for match in _GRADLE_DISABLE.finditer(text):
                window = text[match.end() : match.end() + 400]
                off.update(i for i in ids if re.search(rf"\b{i}\b", window))
    result = frozenset(off)
    a.__dict__["_security_lint_disabled"] = result
    return result


def _suppressed_in_code(a: ProjectAnalysis, path: str, rule: str) -> bool:
    """``@SuppressLint("UnspecifiedImmutableFlag")`` / ``@Suppress(...)`` / ``@file:Suppress(...)``
    anywhere in the file, or the id disabled for the whole project."""
    lint_id = _LINT_ID[rule]
    if lint_id in _lint_disabled(a):
        return True
    source = a.sources.get(path)
    return source is not None and bool(
        re.search(
            rf"@(?:file:)?(?:SuppressLint|Suppress|SuppressWarnings)\s*\([^)]*\b{lint_id}\b",
            source.text,
        )
    )


def _suppressed_in_manifest(
    a: ProjectAnalysis, nodes: tuple[XmlNode | None, ...], rule: str
) -> bool:
    return _LINT_ID[rule] in _lint_disabled(a) or _ignored(nodes, rule)


def _manifests(a: ProjectAnalysis) -> list[tuple[str, ManifestInfo]]:
    """(path, info) of manifests that ship in a build: not those of test source sets."""
    return [(p, i) for p, i in a.manifests.items() if not a.is_test_source(p)]


def _manifests_complete(a: ProjectAnalysis) -> bool:
    """Every shipping manifest parsed: a permission or setting we did not see may be in one that
    did not."""
    return all(
        doc.root is not None
        for path, doc in a.xml_docs.items()
        if path.endswith("AndroidManifest.xml") and not a.is_test_source(path)
    )


def _components_of(a: ProjectAnalysis, kinds: tuple[str, ...]):
    """(manifest path, component element, the elements whose ``tools:ignore`` also covers it)."""
    for path, info in _manifests(a):
        for node in _nodes(info).values():
            if node.tag in kinds and not _removed(node):
                yield path, node, (node, info.application, info.root)


def _actions(node: XmlNode) -> set[str]:
    return {
        action.attrs.get("android:name", "")
        for intent_filter in node.child_nodes("intent-filter")
        for action in intent_filter.child_nodes("action")
    }


def _name(node: XmlNode) -> str:
    return node.attrs.get("android:name", node.tag)


def _local_host(host: str) -> bool:
    """A host that is not a real internet server: loopback, private ranges, ``.local`` names,
    documentation placeholders. Plain HTTP to these is ordinary development."""
    host = host.lower()  # a dotless host (localhost, an IPv6 literal, an intranet name) is local
    if "." not in host or host.endswith(_LOCAL_SUFFIXES):
        return True
    if any(host == d or host.endswith("." + d) for d in _PLACEHOLDER_HOSTS):
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        first, second = int(parts[0]), int(parts[1])
        return (
            first in (0, 10, 127)
            or (first == 192 and second == 168)
            or (first == 172 and 16 <= second <= 31)
            or (first == 169 and second == 254)
        )
    return False


# -- exported components ------------------------------------------------------------------------


def _components(a: ProjectAnalysis) -> Iterator[Finding]:
    for path, node, scope in _components_of(a, ("provider", "service", "receiver")):
        if node.attrs.get("android:exported") != "true":
            continue
        name = _name(node)
        rule = (
            "security.provider_exported_unprotected"
            if node.tag == "provider"
            else f"security.{node.tag}_exported_unprotected"
        )
        if _suppressed_in_manifest(a, scope, rule):
            continue
        if node.tag == "provider":
            if any(node.attrs.get(k) for k in _PROTECTING) or node.child_nodes("path-permission"):
                continue
            grants = (
                " and it can grant URI permissions"
                if node.attrs.get("android:grantUriPermissions") == "true"
                else ""
            )
            yield finding(
                Severity.WARNING,
                rule,
                "security",
                path,
                f"The <provider> {name} is exported and sets no permission, so any app on the "
                f"device can query and modify its data{grants}.",
                line=node.line,
                fix='Set android:exported="false", or protect it with android:permission '
                "(or readPermission and writePermission).",
                key=f"provider:{name}",
            )
            continue
        if node.attrs.get("android:permission") or any(
            action.startswith(_FRAMEWORK_ACTIONS) for action in _actions(node)
        ):
            continue  # protected, or a platform contract (media browser, system service...)
        what = "start or bind to it" if node.tag == "service" else "send it broadcasts"
        yield finding(
            Severity.WARNING,
            rule,
            "security",
            path,
            f"The <{node.tag}> {name} is exported and requires no permission, so any app on the "
            f"device can {what}.",
            line=node.line,
            fix='Set android:exported="false" unless other apps must reach it, or require a '
            "permission with android:permission.",
            key=f"{node.tag}:{name}",
        )


def _provider_grants(a: ProjectAnalysis) -> Iterator[Finding]:
    """``<grant-uri-permission>`` with a path prefix of ``/`` or the pattern ``.*``: permission can
    be granted for every path of the provider, however narrow the intent was."""
    for path, node, scope in _components_of(a, ("provider",)):
        if _suppressed_in_manifest(a, scope, "security.provider_grants_all"):
            continue
        for grant in node.child_nodes("grant-uri-permission"):
            prefix = grant.attrs.get("android:pathPrefix")
            pattern = grant.attrs.get("android:pathPattern")
            if prefix == "/" or pattern in (".*", "/.*"):
                shown = f'pathPrefix="{prefix}"' if prefix == "/" else f'pathPattern="{pattern}"'
                yield finding(
                    Severity.WARNING,
                    "security.provider_grants_all",
                    "security",
                    path,
                    f"The <provider> {_name(node)} declares <grant-uri-permission {shown}>, which "
                    "lets permission be granted to every path it serves.",
                    line=grant.line,
                    fix="List only the paths that really need granting (a narrower pathPrefix or "
                    "several <grant-uri-permission> elements).",
                    key=f"provider:{_name(node)}",
                )


# -- cleartext traffic --------------------------------------------------------------------------


def _network_config(a: ProjectAnalysis, path: str, application: XmlNode) -> XmlNode | None | bool:
    """The application's network security config document root; ``None`` if it declares none,
    ``False`` if it declares one that cannot be read."""
    reference = application.attrs.get("android:networkSecurityConfig")
    if reference is None:
        return None
    match = re.fullmatch(r"@xml/([A-Za-z_]\w*)", reference.strip())
    if not match:
        return False
    doc = a.xml_docs.get(f"{path.rsplit('/', 1)[0]}/res/xml/{match.group(1)}.xml")
    if doc is None or doc.root is None or doc.root.tag != "network-security-config":
        return False
    return doc.root


def _permitting(root: XmlNode) -> list[tuple[XmlNode, str]]:
    """The elements of a network security config that permit cleartext traffic, with what they
    apply to. Configs for local development hosts are skipped."""
    found: list[tuple[XmlNode, str]] = []
    for node in root.iter():
        if node.tag not in ("base-config", "domain-config"):
            continue
        if node.attrs.get("cleartextTrafficPermitted") != "true":
            continue
        if node.tag == "base-config":
            found.append((node, "all domains"))
            continue
        domains = [d.text for d in node.child_nodes("domain") if d.text]
        if domains and all(_local_host(d) for d in domains):
            continue
        found.append((node, ", ".join(domains) if domains else "its domains"))
    return found


def _cleartext_config(a: ProjectAnalysis) -> Iterator[Finding]:
    for path, info in _manifests(a):
        application = info.application
        if application is None or a.source_set(path) != "main":
            continue  # a debug or flavour manifest is not what every build ships
        config = _network_config(a, path, application)
        if application.attrs.get("android:usesCleartextTraffic") == "true" and config is None:
            target = _target_for(a, path)
            default = (
                " (the platform default for apps targeting Android 9 or later is to block it)"
                if target is not None and target >= 28
                else ""
            )
            yield finding(
                Severity.WARNING,
                "security.cleartext_enabled",
                "security",
                path,
                'android:usesCleartextTraffic="true" lets the whole app use plain HTTP'
                f"{default}; the traffic can be read and changed by anyone on the network.",
                line=application.line,
                fix="Use HTTPS, or permit cleartext only for the hosts that need it in a network "
                "security config.",
                key="usesCleartextTraffic",
            )
        if isinstance(config, XmlNode):
            for node, scope in _permitting(config):
                if node.tag == "base-config" and _suppressed_in_manifest(
                    a, (node, config), "security.cleartext_permitted"
                ):
                    continue
                yield finding(
                    Severity.WARNING,
                    "security.cleartext_permitted",
                    "security",
                    f"{path.rsplit('/', 1)[0]}/res/xml/"
                    f"{application.attrs['android:networkSecurityConfig'].split('/', 1)[1]}.xml",
                    f"The network security config permits cleartext traffic for {scope}; "
                    "plain HTTP can be read and changed by anyone on the network.",
                    line=node.line,
                    fix="Use HTTPS, or restrict cleartext to the specific hosts that need it.",
                    key=f"{node.tag}:{scope}",
                )


def _cleartext_blocked(a: ProjectAnalysis) -> bool:
    """True only if every shipping manifest leaves the platform default in force: no
    ``usesCleartextTraffic`` other than false, no network security config that permits cleartext,
    and nothing that cannot be read."""
    if not a.manifests or not _manifests_complete(a):
        return False
    for path, info in _manifests(a):
        application = info.application
        if application is None:
            continue
        if application.attrs.get("android:usesCleartextTraffic") not in (None, "false"):
            return False
        config = _network_config(a, path, application)
        if config is False:
            return False  # a config we cannot read may permit anything
        if isinstance(config, XmlNode) and any(
            node.attrs.get("cleartextTrafficPermitted") == "true" for node in config.iter()
        ):
            return False  # even for local hosts only: some HTTP is deliberate, so none is judged
    return True


def _cleartext_urls(a: ProjectAnalysis, facts: SecurityFacts) -> Iterator[Finding]:
    if not facts.urls or not _cleartext_blocked(a):
        return
    seen: Counter[tuple[str, str]] = Counter()
    for use in facts.urls:
        target = _target_for(a, use.path)
        if target is None or target < 28 or _local_host(use.host):
            continue
        seen[(use.path, use.url)] += 1
        yield finding(
            Severity.WARNING,
            "security.cleartext_url_blocked",
            "security",
            use.path,
            f"{use.url} is a plain-HTTP URL, but apps targeting Android 9 (API 28) or later block "
            "cleartext traffic by default and nothing in the project's manifests or network "
            "security config permits it, so the request is refused at run time.",
            line=use.line,
            column=use.column,
            fix="Use an https:// URL, or permit cleartext for this host in a network security "
            "config.",
            key=f"{use.url}#{seen[(use.path, use.url)]}",
        )


# -- PendingIntent and registerReceiver ---------------------------------------------------------


def _pending_intents(a: ProjectAnalysis, facts: SecurityFacts) -> Iterator[Finding]:
    seen: Counter[tuple[str, str]] = Counter()
    for call in facts.pending:
        target = _target_for(a, call.path)
        if target is None or not call.flags_readable:
            continue
        signature = f"{call.kind}({call.flags})"
        seen[(call.path, signature)] += 1
        key = f"{signature}#{seen[(call.path, signature)]}"
        if call.mutability is None and not call.no_create and target >= 31:
            if _suppressed_in_code(a, call.path, "security.pending_intent_mutability"):
                continue
            yield finding(
                Severity.ERROR,
                "security.pending_intent_mutability",
                "security",
                call.path,
                f"PendingIntent.{call.kind} is created without FLAG_IMMUTABLE or FLAG_MUTABLE. "
                f"An app targeting Android 12 or later (targetSdk {target}) must state the "
                "mutability, otherwise the call throws IllegalArgumentException.",
                line=call.line,
                column=call.column,
                fix="Add PendingIntent.FLAG_IMMUTABLE (use FLAG_MUTABLE only when something must "
                "modify the intent, such as inline reply or bubbles).",
                key=key,
            )
        elif (
            call.mutability == "mutable"
            and call.implicit_intent
            and not call.allows_unsafe_implicit
            and target >= 34
            and not _suppressed_in_code(a, call.path, "security.pending_intent_mutable_implicit")
        ):
            yield finding(
                Severity.ERROR,
                "security.pending_intent_mutable_implicit",
                "security",
                call.path,
                f"PendingIntent.{call.kind} wraps an implicit Intent with FLAG_MUTABLE. An app "
                f"targeting Android 14 or later (targetSdk {target}) gets an "
                "IllegalArgumentException for this combination.",
                line=call.line,
                column=call.column,
                fix="Make the Intent explicit (setPackage or setClass), or use FLAG_IMMUTABLE.",
                key=key,
            )


def _receivers(a: ProjectAnalysis, facts: SecurityFacts) -> Iterator[Finding]:
    seen: Counter[tuple[str, str]] = Counter()
    for call in facts.receivers:
        if call.has_flags or not call.filter_readable or not call.custom_actions:
            continue
        target = _target_for(a, call.path)
        if target is None or target < 34:
            continue
        if _suppressed_in_code(a, call.path, "security.receiver_export_flag_missing"):
            continue
        signature = "registerReceiver(" + ",".join(sorted(call.custom_actions)) + ")"
        seen[(call.path, signature)] += 1
        yield finding(
            Severity.ERROR,
            "security.receiver_export_flag_missing",
            "security",
            call.path,
            f"registerReceiver listens for {', '.join(sorted(call.custom_actions))} without "
            "RECEIVER_EXPORTED or RECEIVER_NOT_EXPORTED. An app targeting Android 14 or later "
            f"(targetSdk {target}) must say which when it registers for anything but system "
            "broadcasts, otherwise the call throws SecurityException.",
            line=call.line,
            column=call.column,
            fix="Use ContextCompat.registerReceiver(context, receiver, filter, "
            "ContextCompat.RECEIVER_NOT_EXPORTED) (RECEIVER_EXPORTED if other apps send it).",
            key=f"{signature}#{seen[(call.path, signature)]}",
        )


# -- permissions --------------------------------------------------------------------------------


def _declared(a: ProjectAnalysis) -> dict[str, tuple[str, XmlNode]]:
    """Permissions the shipping manifests declare (``tools:node="remove"`` ones are not)."""
    found: dict[str, tuple[str, XmlNode]] = {}
    for path, info in _manifests(a):
        for node in info.root.iter():
            if node.tag in ("uses-permission", "uses-permission-sdk-23") and not _removed(node):
                found.setdefault(node.attrs.get("android:name", ""), (path, node))
    return found


def _other_mentions(a: ProjectAnalysis) -> set[str]:
    """Permission names written in files that are neither sources nor manifests (a resource
    array of permissions a helper requests, a Gradle script)."""
    names: set[str] = set()
    for path, text in a.files.texts.items():
        if (
            path.endswith(("AndroidManifest.xml", ".kt", ".java"))
            or _ANDROID_PERMISSION not in text
        ):
            continue
        names.update(_PERMISSION_TEXT.findall(text))
    return names


def _permissions(a: ProjectAnalysis) -> Iterator[Finding]:
    if not _manifests_complete(a):
        return
    facts: SecurityFacts = a.security
    declared = _declared(a)
    reported: set[str] = set()
    for ref in facts.requested_refs:
        if (
            ref.name in DANGEROUS_PERMISSIONS
            and ref.name not in reported
            and _ANDROID_PERMISSION + ref.name not in declared
        ):
            reported.add(ref.name)
            yield finding(
                Severity.WARNING,
                "security.permission_not_declared",
                "security",
                ref.path,
                f"The code requests or checks {ref.name}, but no AndroidManifest.xml in the "
                "project declares it (a library's manifest could, and cannot be read here); "
                "without a declaration the request is always denied.",
                line=ref.line,
                fix=f'Add <uses-permission android:name="{_ANDROID_PERMISSION}{ref.name}" /> '
                "to the manifest.",
                key=ref.name,
            )
    # A declared permission is judged only in a module whose own code already requests or checks
    # permissions: where nothing does, an SDK may be asking on the app's behalf (ARCore's
    # ArFragment, a scanner library), and "never requested" would be a guess.
    modules_that_ask = {a.module_of(r.path) for r in facts.requested_refs}
    mentioned = {r.name for r in facts.permission_refs} | _other_mentions(a)
    for path, info in _manifests(a):
        if a.source_set(path) != "main" or a.module_of(path) not in modules_that_ask:
            continue
        target = _target_for(a, path)
        if target is None or target < 23:
            continue
        for node in info.root.iter():
            if node.tag not in ("uses-permission", "uses-permission-sdk-23") or _removed(node):
                continue
            full = node.attrs.get("android:name", "")
            name = full.removeprefix(_ANDROID_PERMISSION)
            if (
                not full.startswith(_ANDROID_PERMISSION)
                or name not in DANGEROUS_PERMISSIONS
                or name in mentioned
                or node.attrs.get("android:maxSdkVersion")
            ):
                continue
            mentioned.add(name)  # one finding per permission, however many manifests declare it
            yield finding(
                Severity.WARNING,
                "security.permission_never_requested",
                "security",
                path,
                f"The manifest declares {name}, a permission the user must grant at run time, "
                "but no code in the project requests or checks it (a library might ask on the "
                "app's behalf); the features that need it will fail until it is granted.",
                line=node.line,
                fix="Request it with ActivityResultContracts.RequestPermission, or remove the "
                "declaration if it is not needed.",
                key=name,
            )
