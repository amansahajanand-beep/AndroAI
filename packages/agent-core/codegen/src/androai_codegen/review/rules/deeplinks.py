"""Deep-link rules: intent-filter hygiene and whether a navigation deep link can be reached.

Documented behaviour these rest on (developer.android.com, "Create deep links" and "Verify Android
App Links"):

* ``BROWSABLE`` "is required in order for the intent filter to be accessible from a web browser";
  ``DEFAULT`` lets the activity answer implicit intents, "without this, the activity can be started
  only if the intent specifies your app component name".
* An ``autoVerify`` filter is verified only with action VIEW, categories BROWSABLE and DEFAULT
  and an
  http/https scheme, and "do not include other schemes, as this will prevent verification".
* Several ``<data>`` elements of one filter are merged into a cross product of schemes and hosts.
* Compose and Kotlin-DSL graphs need hand-written manifest intent filters; an XML graph's implicit
  deep links need a ``<nav-graph>`` element. A navigation URI without a scheme means http or https.

Every finding is a warning: a deep link may be intentionally reachable only from inside the app.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from ..analysis import COMPONENT_TAGS, ProjectAnalysis
from ..models import Finding, Severity, finding
from ..navigation import nav_resource_name

_WEB = ("http", "https")
_PATH_ATTRS = (
    "android:path",
    "android:pathPrefix",
    "android:pathPattern",
    "android:pathAdvancedPattern",
    "android:pathSuffix",
)
_VIEW = "android.intent.action.VIEW"
_BROWSABLE = "android.intent.category.BROWSABLE"
_DEFAULT = "android.intent.category.DEFAULT"
_URI = re.compile(r"^(?:([A-Za-z][A-Za-z0-9+.-]*)://)?([^/?#:]*)")


@dataclass(frozen=True)
class IntentFilterInfo:
    path: str
    component: str
    line: int
    actions: frozenset[str]
    categories: frozenset[str]
    datas: tuple[tuple[str | None, str | None, tuple[tuple[str, str], ...]], ...]
    auto_verify: bool

    @property
    def schemes(self) -> set[str]:
        return {s for s, _h, _p in self.datas if s}

    @property
    def hosts(self) -> set[str]:
        return {h for _s, h, _p in self.datas if h}


def filters(a: ProjectAnalysis) -> list[IntentFilterInfo]:
    found: list[IntentFilterInfo] = []
    for path, info in a.manifests.items():
        if info.application is None:
            continue
        for node in info.application.children:
            if node.tag not in COMPONENT_TAGS:
                continue
            name = node.attrs.get("android:name", node.tag)
            for intent_filter in node.child_nodes("intent-filter"):
                datas = tuple(
                    (
                        data.attrs.get("android:scheme"),
                        data.attrs.get("android:host"),
                        tuple((k, data.attrs[k]) for k in _PATH_ATTRS if k in data.attrs),
                    )
                    for data in intent_filter.child_nodes("data")
                )
                found.append(
                    IntentFilterInfo(
                        path,
                        name,
                        intent_filter.line,
                        frozenset(
                            x.attrs.get("android:name", "")
                            for x in intent_filter.child_nodes("action")
                        ),
                        frozenset(
                            x.attrs.get("android:name", "")
                            for x in intent_filter.child_nodes("category")
                        ),
                        datas,
                        intent_filter.attrs.get("android:autoVerify") == "true",
                    )
                )
    return found


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    if not a.manifests:
        return
    all_filters = filters(a)
    for item in all_filters:
        yield from _hygiene(item)
    yield from _duplicate_app_links(all_filters)
    yield from _xml_graphs_without_nav_graph(a)
    yield from _compose_uris(a, all_filters)


def _hygiene(item: IntentFilterInfo) -> Iterator[Finding]:
    web = bool(item.schemes & set(_WEB))
    viewing = _VIEW in item.actions
    if viewing and web and _BROWSABLE not in item.categories:
        yield finding(
            Severity.WARNING,
            "deeplink.missing_browsable",
            "deeplinks",
            item.path,
            f"{item.component} has a web-link intent filter without the BROWSABLE "
            "category, which is "
            "required for the filter to be reachable from a web browser.",
            line=item.line,
            fix='Add <category android:name="android.intent.category.BROWSABLE" />.',
            key=f"{item.component}:{item.line}",
        )
    if viewing and item.datas and _DEFAULT not in item.categories:
        yield finding(
            Severity.WARNING,
            "deeplink.missing_default",
            "deeplinks",
            item.path,
            f"{item.component} has a link intent filter without the DEFAULT category, "
            "so the activity "
            "can only be started by an intent that names the component.",
            line=item.line,
            fix='Add <category android:name="android.intent.category.DEFAULT" />.',
            key=f"{item.component}:{item.line}",
        )
    if item.auto_verify:
        reasons = []
        if not viewing:
            reasons.append("no VIEW action")
        if _BROWSABLE not in item.categories:
            reasons.append("no BROWSABLE category")
        if _DEFAULT not in item.categories:
            reasons.append("no DEFAULT category")
        if not web:
            reasons.append("no http or https scheme")
        other = sorted(item.schemes - set(_WEB))
        if other:
            reasons.append(f"another scheme ({', '.join(other)}), which prevents verification")
        if reasons:
            yield finding(
                Severity.WARNING,
                "deeplink.autoverify_ineffective",
                "deeplinks",
                item.path,
                f"autoVerify on {item.component} cannot take effect: the filter has "
                + "; ".join(reasons)
                + ". Android only verifies filters with VIEW, BROWSABLE, DEFAULT and http/https.",
                line=item.line,
                fix="Give the App Link its own filter with those parts and nothing else, "
                "and keep other "
                "schemes in a separate filter.",
                key=f"{item.component}:{item.line}",
            )
    yield from _merged_data(item)


def _merged_data(item: IntentFilterInfo) -> Iterator[Finding]:
    """``<data scheme=https host=a/>`` + ``<data scheme=app host=b/>`` also matches app://a and
    https://b: the elements of one filter are combined."""
    pairs = [(s, h) for s, h, _p in item.datas if s and h]
    for index, (scheme, host) in enumerate(pairs):
        for other_scheme, other_host in pairs[index + 1 :]:
            if scheme != other_scheme and host != other_host:
                yield finding(
                    Severity.WARNING,
                    "deeplink.merged_data_elements",
                    "deeplinks",
                    item.path,
                    f"The <data> elements of one filter in {item.component} are merged: "
                    f"{scheme}://{host} and {other_scheme}://{other_host} also match "
                    f"{scheme}://{other_host} and {other_scheme}://{host}.",
                    line=item.line,
                    fix="Declare each scheme and host combination in its own <intent-filter>.",
                    key=f"{item.component}:{item.line}",
                )
                return


def _duplicate_app_links(all_filters: list[IntentFilterInfo]) -> Iterator[Finding]:
    """The same verified App Link in two components: Android does not say which one is used."""
    owners: dict[tuple[str, tuple], list[IntentFilterInfo]] = defaultdict(list)
    for item in all_filters:
        if not item.auto_verify:
            continue
        for scheme, host, paths in item.datas:
            if host and (scheme is None or scheme in _WEB):
                owners[(host, paths)].append(item)
    reported: set[tuple[str, tuple]] = set()
    for (host, paths), items in owners.items():
        components = {(i.path, i.component) for i in items}
        if len(components) > 1 and (host, paths) not in reported:
            reported.add((host, paths))
            second = next(
                i for i in items if (i.path, i.component) != (items[0].path, items[0].component)
            )
            names = ", ".join(sorted(c for _p, c in components))
            yield finding(
                Severity.WARNING,
                "deeplink.duplicate_app_link",
                "deeplinks",
                second.path,
                f"{names} all declare a verified link for {host}; if several activities "
                "resolve to the "
                "same verified App Link there is no guarantee which one handles it.",
                line=second.line,
                fix="Keep the verified link in one activity.",
                key=host,
            )


def _xml_graphs_without_nav_graph(a: ProjectAnalysis) -> Iterator[Finding]:
    """An XML graph with ``<deepLink>`` whose implicit links nothing in the manifest enables."""
    facts = a.navigation
    if not facts.xml_deeplinks:
        return
    referenced = {
        node.attrs.get("android:value", "").removeprefix("@navigation/")
        for info in a.manifests.values()
        for node in info.root.iter()
        if node.tag == "nav-graph"
    }
    included = {name for graph in facts.graphs for name in graph.includes}
    reported: set[str] = set()
    for link in facts.xml_deeplinks:
        name = nav_resource_name(link.path)
        if name is None or name in referenced or name in included or link.path in reported:
            continue
        reported.add(link.path)
        yield finding(
            Severity.WARNING,
            "deeplink.nav_graph_not_in_manifest",
            "deeplinks",
            link.path,
            f"This graph declares a <deepLink> ({link.uri}) but no <nav-graph android:value="
            f'"@navigation/{name}"> in any manifest enables implicit deep links for it, so outside '
            "links cannot reach it (it still works for explicit deep links).",
            line=link.line,
            fix=f'Add <nav-graph android:value="@navigation/{name}" /> to the activity '
            "that hosts it.",
            key=name,
        )


def _covers(item: IntentFilterInfo, scheme: str | None, host: str) -> bool:
    schemes = {scheme} if scheme else set(_WEB)
    if not (item.schemes & schemes):
        return False
    hosts = item.hosts
    return not hosts or any(
        h == host or (h.startswith("*.") and host.endswith(h[1:])) for h in hosts
    )


def _compose_uris(a: ProjectAnalysis, all_filters: list[IntentFilterInfo]) -> Iterator[Finding]:
    """A ``navDeepLink`` URI that no manifest intent filter matches."""
    nav = a.navigation.compose
    if nav.unsupported:
        return
    viewing = [f for f in all_filters if _VIEW in f.actions]
    for link in nav.deeplinks:
        match = _URI.match(link.pattern)
        if not match:
            continue
        scheme, host = match.group(1), match.group(2)
        if not host or any(c in (scheme or "") + host for c in "${}*"):
            continue  # a template or wildcard: the target is not known
        if any(_covers(f, scheme, host) for f in viewing):
            continue
        yield finding(
            Severity.WARNING,
            "deeplink.uri_not_in_manifest",
            "deeplinks",
            link.path,
            f"The navigation deep link {link.pattern} has no matching <intent-filter> in "
            "any manifest. "
            "Compose navigation graphs do not generate manifest filters, so links from outside the "
            "app cannot reach it (explicit deep links still work).",
            line=link.line,
            fix="Add an <intent-filter> with action VIEW, DEFAULT and BROWSABLE and "
            f'<data android:scheme="{scheme or "https"}" android:host="{host}" /> to the '
            "activity that hosts the NavHost.",
            key=link.pattern,
        )
