"""Manifest facts and class roles: Application, Activities, Services, Receivers, Providers,
Fragments, ViewModels, Workers, adapters and custom views.

Two independent sources describe the same component, and they are merged into one fact:

* the **manifest** says a class is declared as an Activity (basis ``manifest``);
* the **source** says a class extends an Activity base class (basis ``source``).

A role read from the source is ``confirmed`` when the base class is identified by its import (or
written with its package), and also when it is inherited through project classes whose own links
are confirmed. It is ``inferred`` when any link matched by simple name only. Nothing here says a
class is *not* an Activity: a class without a role fact is simply not recognised as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from androai_codegen.review.analysis import COMPONENT_TAGS
from androai_codegen.review.xmlparse import XmlNode

from .catalog import ROLE_BASES, ROLE_FACT_KINDS
from .context import Run, module_label
from .members import TypeInfo
from .model import Evidence
from .resolve import level_for, resolve_known
from .store import make_id
from .text import redact_url, safe, safe_value

_KIND_OF_TAG = {
    "activity": "activity",
    "activity-alias": "activity_alias",
    "service": "service",
    "receiver": "receiver",
    "provider": "provider",
}
_SECRET_NAME = re.compile(r"key|secret|token|password|passwd|credential|auth", re.IGNORECASE)
_RESOURCE_REF = re.compile(r"^@[\w.]*/[\w.]+$")
_PATH_ATTRS = ("android:path", "android:pathPrefix", "android:pathPattern", "android:pathSuffix")


def resolve_class_name(name: str, package: str | None) -> str:
    """A class name as written in a manifest, resolved against the application package."""
    if name.startswith("."):
        return f"{package}{name}" if package else name[1:]
    if "." not in name:
        return f"{package}.{name}" if package else name
    return name


def extract_components(run: Run) -> None:
    for path in sorted(run.a.manifests):
        _manifest(run, path)
    _roles(run)
    _link_manifest_to_types(run)


# -- manifests -----------------------------------------------------------------------------------


def _manifest(run: Run, path: str) -> None:
    a = run.a
    info = a.manifests[path]
    module = run.module_of(path)
    label = module_label(module)
    tag = f"module:{label}"
    package = a.manifest_package(info)
    ev = lambda node: [run.xml_evidence(path, node.line)]  # noqa: E731
    run.fact(
        "file",
        path,
        basis="manifest",
        evidence=[run.path_evidence(path)],
        attrs={"file_kind": "manifest", "package": package or ""},
        tags=(tag,),
    )
    for node in info.root.child_nodes("uses-sdk"):
        for attr, name in (
            ("android:minSdkVersion", "minSdk"),
            ("android:targetSdkVersion", "targetSdk"),
        ):
            value = node.attrs.get(attr, "")
            if value.isdigit():
                run.fact(
                    "sdk_level",
                    f"{label}|{name}",
                    basis="manifest",
                    evidence=ev(node),
                    attrs={"value": int(value), "module": label, "resolved_via": "manifest"},
                    tags=(tag,),
                )
    for name, line in info.permissions:
        run.fact(
            "permission",
            name,
            basis="manifest",
            evidence=[run.xml_evidence(path, line)],
            attrs={"declared_in": path},
            tags=(tag,),
        )
    for node in info.root.child_nodes("permission"):
        if node.attrs.get("android:name"):
            run.fact(
                "permission_defined",
                node.attrs["android:name"],
                basis="manifest",
                evidence=ev(node),
                attrs={"protection_level": node.attrs.get("android:protectionLevel", "")},
                tags=(tag,),
            )
    for node in info.root.child_nodes("uses-feature"):
        name = node.attrs.get("android:name") or node.attrs.get("android:glEsVersion")
        if name:
            run.fact(
                "uses_feature",
                name,
                basis="manifest",
                evidence=ev(node),
                attrs={"required": node.attrs.get("android:required", "true")},
                tags=(tag,),
            )
    application = info.application
    if application is None:
        return
    _application(run, path, application, package, tag, label)
    for node in application.children:
        if node.tag in COMPONENT_TAGS:
            _component(run, path, node, package, tag, label)
    for node in application.iter():
        if node.tag == "meta-data" and node.attrs.get("android:name"):
            _meta_data(run, path, node, tag)


def _application(
    run: Run, path: str, node: XmlNode, package: str | None, tag: str, label: str
) -> None:
    name = node.attrs.get("android:name")
    fqn = resolve_class_name(name, package) if name else None
    attrs: dict = {"manifest": path, "module": label}
    for attr, key in (
        ("android:allowBackup", "allow_backup"),
        ("android:usesCleartextTraffic", "cleartext_traffic"),
        ("android:debuggable", "debuggable"),
        ("android:theme", "theme"),
        ("android:label", "label"),
        ("android:networkSecurityConfig", "network_security_config"),
        ("android:requestLegacyExternalStorage", "legacy_external_storage"),
    ):
        if attr in node.attrs:
            attrs[key] = safe(node.attrs[attr], 100)
    if fqn:
        attrs["class"] = fqn
    run.fact(
        "application",
        fqn or f"(default)@{label}",
        basis="manifest",
        evidence=[run.xml_evidence(path, node.line)],
        attrs=attrs,
        tags=(tag, "role:application"),
    )


def _component(
    run: Run, path: str, node: XmlNode, package: str | None, tag: str, label: str
) -> None:
    kind = _KIND_OF_TAG[node.tag]
    name = node.attrs.get("android:name") or node.attrs.get("android:targetActivity")
    if not name:
        return
    fqn = resolve_class_name(name, package)
    actions: set[str] = set()
    categories: set[str] = set()
    links: set[str] = set()
    launcher = False
    for intent_filter in node.child_nodes("intent-filter"):
        local_actions = {
            a.attrs.get("android:name", "") for a in intent_filter.child_nodes("action")
        }
        local_categories = {
            c.attrs.get("android:name", "") for c in intent_filter.child_nodes("category")
        }
        actions |= local_actions
        categories |= local_categories
        if (
            "android.intent.action.MAIN" in local_actions
            and "android.intent.category.LAUNCHER" in local_categories
        ):
            launcher = True
        for data in intent_filter.child_nodes("data"):
            scheme = data.attrs.get("android:scheme")
            host = data.attrs.get("android:host", "")
            if scheme:
                path_value = next((data.attrs[k] for k in _PATH_ATTRS if k in data.attrs), "")
                links.add(redact_url(f"{scheme}://{host}{path_value}", 120))
    attrs: dict = {
        "class": fqn,
        "manifest": path,
        "module": label,
        "has_intent_filter": bool(node.child_nodes("intent-filter")),
        "launcher": launcher,
    }
    for attr, key in (
        ("android:exported", "exported"),
        ("android:enabled", "enabled"),
        ("android:permission", "permission"),
        ("android:targetActivity", "target_activity"),
        ("android:launchMode", "launch_mode"),
    ):
        if attr in node.attrs:
            attrs[key] = safe(node.attrs[attr], 100)
    if actions - {""}:
        attrs["actions"] = tuple(sorted(actions - {""}))
    if categories - {""}:
        attrs["categories"] = tuple(sorted(categories - {""}))
    if links:
        attrs["deep_links"] = tuple(sorted(links))
    tags = [tag, f"role:{kind}"]
    if launcher:
        tags.append("launcher")
    run.fact(
        kind,
        fqn,
        basis="manifest",
        evidence=[run.xml_evidence(path, node.line)],
        attrs=attrs,
        tags=tags,
    )


def _meta_data(run: Run, path: str, node: XmlNode, tag: str) -> None:
    name = node.attrs["android:name"]
    value = node.attrs.get("android:value")
    resource = node.attrs.get("android:resource")
    attrs: dict = {"manifest": path}
    if resource:
        attrs["resource"] = safe(resource, 100)
    if value is not None:
        if _RESOURCE_REF.match(value):
            attrs["value"] = safe(value, 100)  # a reference such as @string/maps_key, not a value
        elif _SECRET_NAME.search(name):
            attrs["value"] = "[REDACTED]"
        else:
            # a value under an innocent name can still be a generated token (a hex id, a UUID)
            attrs["value"] = safe_value(value, 100)
    evidence = run.xml_evidence(path, node.line)
    if value is not None and not _RESOURCE_REF.match(value) and _SECRET_NAME.search(name):
        # the excerpt is the raw line: for a key that looks like a secret, hide its value as well
        hidden = re.sub(
            r'(android:value\s*=\s*)(["\'])[^"\']*\2', r"\1\2[REDACTED]\2", evidence.excerpt
        )
        evidence = Evidence(path=evidence.path, line=evidence.line, excerpt=hidden)
    run.fact(
        "meta_data",
        name,
        basis="manifest",
        evidence=[evidence],
        attrs=attrs,
        tags=(tag,),
    )


# -- roles from source ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleHit:
    status: str  # confirmed | inferred
    base: str  # the framework class, by simple name
    via: tuple[str, ...]  # project classes the role was inherited through
    evidence: tuple[Evidence, ...]
    note: str | None


def role_hit(run: Run, t: TypeInfo, role: str) -> RoleHit | None:
    """Does ``t`` extend a framework base class of ``role``, directly or through project classes?"""
    memo: dict[tuple[str, str], RoleHit | None] = run.__dict__.setdefault("_role_memo", {})
    return _role_hit(run, t, role, memo, ())


def _role_hit(
    run: Run,
    t: TypeInfo,
    role: str,
    memo: dict[tuple[str, str], RoleHit | None],
    trail: tuple[str, ...],
) -> RoleHit | None:
    key = (t.fqn, role)
    if key in memo:
        return memo[key]
    if t.fqn in trail or len(trail) > 25:
        return None  # an inheritance cycle (or absurd depth)
    info = run.infos.get(t.path)
    if info is None or t.kind not in ("class",):
        memo[key] = None
        return None
    table = ROLE_BASES[role]
    best: RoleHit | None = None
    for sup in t.supertypes:
        accepted = table.get(sup.written) or table.get(sup.simple) or ()
        project_res = run.resolver.resolve(info.source, sup.written, t.owner)
        if accepted:
            known_res = resolve_known(info.source, sup.written, table)
            # a class of the project itself (same package, or imported) is what the name means;
            # it beats a guess that the name stands for a framework class
            shadowed = known_res.how == "by_name" and project_res.exact
            level = None if shadowed else level_for(known_res, accepted)
            if level:
                note = (
                    None
                    if level == "confirmed"
                    else f"{sup.written} matches a framework class by name only; "
                    "no import shows its package"
                )
                best = _stronger(
                    best, RoleHit(level, _base_name(sup), (), (info.view.evidence(t.offset),), note)
                )
                continue
        parent_res = project_res
        parent = run.types.get(parent_res.fqn or "")
        if parent is None or parent_res.how == "unresolved":
            continue
        sub = _role_hit(run, parent, role, memo, (*trail, t.fqn))
        if sub is None:
            continue
        status = "confirmed" if parent_res.exact and sub.status == "confirmed" else "inferred"
        note = None
        if status == "inferred":
            note = (
                f"inherits through {parent.fqn}, matched by simple name"
                if not parent_res.exact
                else sub.note
            )
        best = _stronger(
            best,
            RoleHit(
                status,
                sub.base,
                (parent.fqn, *sub.via),
                (info.view.evidence(t.offset), *sub.evidence[:2]),
                note,
            ),
        )
    memo[key] = best
    return best


def _base_name(sup) -> str:
    """``Fragment`` for ``androidx.fragment.app.Fragment``, but ``RecyclerView.Adapter`` whole."""
    return sup.written if sup.written[:1].isupper() else sup.simple


def _stronger(old: RoleHit | None, new: RoleHit) -> RoleHit:
    if old is None:
        return new
    return new if (new.status == "confirmed" and old.status != "confirmed") else old


def _roles(run: Run) -> None:
    for fqn in sorted(run.types):
        if run.expired():
            return
        t = run.types[fqn]
        if run.is_test(t.path) or run.is_build_logic(t.path):
            continue
        for role in ROLE_FACT_KINDS:
            hit = role_hit(run, t, role)
            if hit is None:
                continue
            attrs: dict = {
                "class": t.fqn,
                "base": hit.base,
                "abstract": t.is_abstract,
                "visibility": t.visibility,
            }
            if hit.via:
                attrs["inherited_via"] = hit.via
            tags = (*run.path_tags(t.path), f"role:{role}")
            fact_id = run.fact(
                role,
                t.fqn,
                basis="source",
                status=hit.status,
                evidence=list(hit.evidence),
                attrs=attrs,
                note=hit.note,
                tags=tags,
            )
            run.store.relate(
                fact_id,
                "role_of",
                make_id("type", t.fqn),
                basis="source",
                status=hit.status,
                evidence=list(hit.evidence[:1]),
                note=hit.note,
            )


def _link_manifest_to_types(run: Run) -> None:
    """A manifest entry and the class it names are one component seen from two sides."""
    store = run.store
    for kind in ("activity", "activity_alias", "service", "receiver", "provider", "application"):
        for fact_id in store.ids_of_kind(kind):
            subject = fact_id.split(":", 1)[1]
            type_id = make_id("type", subject)
            if not store.has(type_id) or store.attribute(fact_id, "manifest") is None:
                continue
            manifest = str(store.attribute(fact_id, "manifest"))
            store.relate(
                fact_id,
                "implemented_by",
                type_id,
                basis="manifest",
                evidence=[run.path_evidence(manifest)],
            )
