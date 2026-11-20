"""Authentication rules: recognised sign-in integrations, OAuth redirect configuration, hardcoded
secrets and private keys, signing passwords and credentials in plain preferences.

Documented behaviour these rest on (developer.android.com, the AppAuth-Android README and the
Android security tips; checked against the pages, not from memory):

* Credential Manager's setup lists both ``androidx.credentials:credentials`` and
  ``androidx.credentials:credentials-play-services-auth``; a request without the second fails with a
  ``*ProviderConfigurationException`` ("Your app is missing the provider configuration dependency").
* AppAuth captures redirects for a custom scheme "through a manifest placeholder"
  (``manifestPlaceholders = ['appAuthRedirectScheme': 'com.example.app']``), or by declaring an
  intent filter for ``net.openid.appauth.RedirectUriReceiverActivity`` (``tools:node="replace"``).
* "Never commit API keys to your source code repository"; an attacker can decompile an app and find
  keys in its source (security tips). Signing information in a Gradle signing configuration is "in
  plain text in your Gradle build files" and should be moved out of them (app signing guide).
* Credentials: "don't store passwords on the device" (use ``AccountManager``); "if only one
  application uses the credential, you might use a KeyStore for storage". Internal storage is
  app-private, which "is sufficient for most applications", so a token in SharedPreferences is an
  advisory, not a vulnerability. ``androidx.security:security-crypto`` deprecated all of its APIs
  "in favour of existing platform APIs and direct use of Android Keystore".

Nothing here verifies an app's authorization model. Every rule stays silent when it cannot read
what it needs, and no finding repeats a secret.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator

from ..analysis import _BUILD_SOURCE, ProjectAnalysis
from ..authfacts import AuthFacts
from ..catalog import AUTH_INTEGRATIONS
from ..models import Finding, Severity, finding

# ``\s*+`` is possessive: with a plain ``\s*`` the negative lookahead below could be satisfied by
# backtracking the whitespace away, and every literal value would look computed.
_REDIRECT_KEY = r"""appAuthRedirectScheme["']?\]?\s*(?:[:=,]|\bto\b)\s*+"""
_REDIRECT_PLACEHOLDER = re.compile(_REDIRECT_KEY + r"""["']([^"'$\s]+)["']""")
_REDIRECT_COMPUTED = re.compile(_REDIRECT_KEY + r"""(?!["'][^"'$\s]+["'])""")
_APPAUTH = "net.openid:appauth"
_REDIRECT_ACTIVITY = "net.openid.appauth.RedirectUriReceiverActivity"


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    facts: AuthFacts = a.auth
    yield from _private_keys(facts)
    yield from _secrets(facts)
    yield from _signing_passwords(facts)
    yield from _preference_credentials(facts)
    yield from _credential_manager_provider(a)
    yield from _appauth_not_configured(a)
    yield from _redirect_scheme_unmatched(a, facts)


# -- hardcoded secrets and private keys ---------------------------------------------------------


def _private_keys(facts: AuthFacts) -> Iterator[Finding]:
    seen: Counter[tuple[str, str]] = Counter()
    for item in facts.private_keys:
        seen[(item.path, "key")] += 1
        yield finding(
            Severity.ERROR,
            "auth.private_key_in_source",
            "authentication",
            item.path,
            "A PEM private key is written into this file. Anyone who can read the source (or the "
            "repository history) has the key, and the security tips say never to commit keys.",
            line=item.line,
            fix="Remove it, treat the key as compromised and replace it, and load keys from "
            "outside the repository.",
            key=f"private-key#{seen[(item.path, 'key')]}",
        )


def _secrets(facts: AuthFacts) -> Iterator[Finding]:
    seen: Counter[tuple[str, str]] = Counter()
    for item in facts.secrets:
        base = item.what.lower() if item.named else f"token:{item.what}"
        seen[(item.path, base)] += 1
        what = (
            f"`{item.what}` is assigned a {item.length}-character literal that looks like a secret"
            if item.named
            else f"A literal that looks like {item.what} ({item.length} characters) is written"
        )
        yield finding(
            Severity.WARNING,
            "auth.hardcoded_secret",
            "authentication",
            item.path,
            f"{what}. A secret in source can be read by anyone who gets the repository or "
            "decompiles the app.",
            line=item.line,
            fix="Keep it out of the repository (a Gradle property or secrets plugin for build-time "
            "values, a server for real secrets); a mobile app cannot keep a secret.",
            key=f"{base}#{seen[(item.path, base)]}",
        )


def _signing_passwords(facts: AuthFacts) -> Iterator[Finding]:
    seen: Counter[tuple[str, str]] = Counter()
    for item in facts.signing:
        seen[(item.path, item.field)] += 1
        yield finding(
            Severity.WARNING,
            "auth.signing_password_in_build_script",
            "authentication",
            item.path,
            f"{item.field} is a literal in the build script, so the signing password is in plain "
            "text in a file that is shared with the code.",
            line=item.line,
            fix="Move it to a keystore.properties file kept out of source control (or an "
            "environment variable) and read it from there.",
            key=f"{item.field}#{seen[(item.path, item.field)]}",
        )


def _preference_credentials(facts: AuthFacts) -> Iterator[Finding]:
    seen: Counter[tuple[str, str]] = Counter()
    for item in facts.credentials:
        seen[(item.path, item.key)] += 1
        if re.sub(r"[^a-z]", "", item.key.lower()) in ("password", "passwd"):
            why = (
                "writes a password to SharedPreferences. The security tips say not to store "
                "passwords on the device: use an authorization token and refresh it, and "
                "AccountManager for the credential."
            )
        else:
            why = (
                f'writes "{item.key}" to SharedPreferences, which is not encrypted. App-private '
                "storage is enough for most data, but this is a credential: the security tips "
                "suggest the Android Keystore for credentials only your app uses (Jetpack's "
                "security-crypto, with EncryptedSharedPreferences, is deprecated in favour of the "
                "platform APIs and the Keystore)."
            )
        yield finding(
            Severity.WARNING,
            "auth.credential_in_plain_preferences",
            "authentication",
            item.path,
            f"This code {why}",
            line=item.line,
            column=item.column,
            fix="Keep the credential in Keystore-backed storage, or keep only short-lived tokens "
            "and refresh them.",
            key=f"{item.key}#{seen[(item.path, item.key)]}",
        )


# -- recognised integrations ----------------------------------------------------------------------


def _project_coordinates(a: ProjectAnalysis) -> frozenset[str] | None:
    """Every ``group:artifact`` any module declares, or ``None`` if some module is not readable."""
    found: set[str] = set()
    for module in a.modules:
        coordinates = a.dependency_coordinates_for(module)
        if coordinates is None:
            return None
        found |= coordinates
    return frozenset(found)


def _first_import(a: ProjectAnalysis, prefixes: tuple[str, ...]) -> tuple[str, int] | None:
    for path, source in a.sources.items():
        if _BUILD_SOURCE.search(path) or a.is_test_source(path):
            continue
        for imp in source.imports:
            # a wildcard import names the package itself, so compare with a trailing dot
            if any(f"{imp.fqn}.".startswith(p) for p in prefixes):
                return path, imp.line
    return None


def _credential_manager_provider(a: ProjectAnalysis) -> Iterator[Finding]:
    """Credential Manager without ``credentials-play-services-auth``: the documented setup adds
    both, and a request without the second one fails with a provider-configuration exception."""
    integration = next(i for i in AUTH_INTEGRATIONS if i.name == "Credential Manager")
    coordinates = _project_coordinates(a)
    if coordinates is None or "androidx.credentials:credentials" not in coordinates:
        return
    if any(
        c.startswith("androidx.credentials:credentials-play-services-auth") for c in coordinates
    ):
        return
    spot = _first_import(a, integration.imports)
    if spot is None:
        return
    yield finding(
        Severity.WARNING,
        "auth.credential_manager_provider_missing",
        "authentication",
        spot[0],
        "The project uses Credential Manager and declares androidx.credentials:credentials, but "
        "not androidx.credentials:credentials-play-services-auth. The documented setup adds both; "
        'without the second, a request fails with a ProviderConfigurationException ("missing the '
        'provider configuration dependency").',
        line=spot[1],
        fix='Add implementation("androidx.credentials:credentials-play-services-auth:<version>") '
        "next to androidx.credentials:credentials.",
        key="credentials-play-services-auth",
    )


def _module_script_text(a: ProjectAnalysis, module: str) -> str:
    return "\n".join(a.files.texts.get(s.path, "") for s in a.module_scripts(module))


def _manifests_declare_redirect_activity(a: ProjectAnalysis) -> bool:
    return any(
        c.fqn == _REDIRECT_ACTIVITY
        for path, info in a.manifests.items()
        if not a.is_test_source(path)
        for c in info.components
    )


def _appauth_not_configured(a: ProjectAnalysis) -> Iterator[Finding]:
    """An application module that ships AppAuth but neither sets ``appAuthRedirectScheme`` nor
    declares the redirect activity itself: AppAuth's redirect scheme is then not configured."""
    redirect_activity = _manifests_declare_redirect_activity(a)
    for module in sorted(a.modules):
        if not a.is_application(module):
            continue
        coordinates = a.dependency_coordinates_for(module)
        if coordinates is None or not any(c.startswith(_APPAUTH) for c in coordinates):
            continue
        if "appAuthRedirectScheme" in _module_script_text(a, module) or redirect_activity:
            continue
        scripts = a.module_scripts(module)
        yield finding(
            Severity.WARNING,
            "auth.appauth_redirect_not_configured",
            "authentication",
            scripts[0].path,
            "This application module includes AppAuth but sets no appAuthRedirectScheme manifest "
            "placeholder and no manifest declares net.openid.appauth.RedirectUriReceiverActivity, "
            "so the redirect scheme that brings the user back to the app is not configured.",
            line=1,
            fix="Add manifestPlaceholders = ['appAuthRedirectScheme': 'com.example.app'] to "
            "defaultConfig (a reverse-domain scheme), or declare the redirect activity with your "
            'own intent filter (tools:node="replace").',
            key=module or ".",
        )


def _manifest_schemes(a: ProjectAnalysis) -> set[str] | None:
    """Every ``<data android:scheme>`` of the shipping manifests (``${appAuthRedirectScheme}``
    resolved to its Gradle values), or ``None`` if one is a placeholder we cannot resolve."""
    resolved: set[str] = set()
    for text in a.files.texts.values():
        resolved.update(m.group(1) for m in _REDIRECT_PLACEHOLDER.finditer(text))
    schemes: set[str] = set()
    for path, info in a.manifests.items():
        if a.is_test_source(path):
            continue
        for node in info.root.find_all("data"):
            value = node.attrs.get("android:scheme")
            if value is None:
                continue
            if value == "${appAuthRedirectScheme}":
                continue  # the library's own placeholder: its Gradle values are added below
            if "${" in value:
                return None
            schemes.add(value.lower())
    for path, text in a.files.texts.items():
        if path.endswith((".gradle", ".kts")) and _REDIRECT_COMPUTED.search(text):
            return None  # a placeholder whose value is computed
    return schemes | resolved


def _redirect_scheme_unmatched(a: ProjectAnalysis, facts: AuthFacts) -> Iterator[Finding]:
    """A literal AppAuth redirect URI whose scheme no manifest intent filter (and no
    ``appAuthRedirectScheme`` value) receives: the browser cannot return to the app."""
    if not facts.redirects:
        return
    schemes = _manifest_schemes(a)
    if schemes is None or not a.manifests:
        return
    seen: Counter[tuple[str, str]] = Counter()
    for use in facts.redirects:
        if use.scheme in schemes:
            continue
        seen[(use.path, use.scheme)] += 1
        yield finding(
            Severity.WARNING,
            "auth.appauth_redirect_scheme_unmatched",
            "authentication",
            use.path,
            f'The AppAuth redirect URI uses the scheme "{use.scheme}", but no manifest intent '
            "filter receives it and no appAuthRedirectScheme placeholder sets it, so the "
            "authorization response cannot return to the app.",
            line=use.line,
            column=use.column,
            fix="Make the redirect URI's scheme the appAuthRedirectScheme, or add an intent filter "
            "for it to RedirectUriReceiverActivity.",
            key=f"{use.scheme}#{seen[(use.path, use.scheme)]}",
        )
