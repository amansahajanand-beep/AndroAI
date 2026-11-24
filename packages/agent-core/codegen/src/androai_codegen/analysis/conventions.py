"""Architecture and coding conventions (M2B, task M2.8).

A ``convention`` fact describes how the project is written: its architecture signals, UI toolkit,
languages, DI, state and async style, package organisation, naming, tests and formatting.

Rules that hold for every convention here:

* **Evidence, not names.** An architecture is never concluded from a package or a file name. The
  signals are structural and come from facts M2A already read: which screens use a ViewModel
  (``uses_viewmodel``), which interface a screen implements and which class receives it, which
  ViewModel exposes a state holder and takes one sealed event type, which classes sit between a
  ViewModel and a DAO or a service. A class name is only ever used together with such a structure
  (MVP needs a ``*Presenter`` that receives an interface its screen implements), or to describe
  naming itself.
* **Several conventions can hold at once.** Each label carries ``support`` (how many), ``total``
  (out of how many), ``percent`` and ``strength``: ``dominant`` from 70 %, ``partial`` from 30 %,
  ``weak`` below. When two architecture patterns are both at least ``partial`` an
  ``architecture|mixed`` fact lists them.
* **Sparse evidence is unknown, not a guess.** A label needs ``MIN_SUPPORT`` examples; the
  architecture and the package layout also need ``MIN_SAMPLE`` things to look at. Without them the
  result is an ``unknown`` fact that says how many there were.
* **Counts are confirmed, readings are inferred.** A count of files, layouts, DI facts or test
  imports is read directly (``confirmed``, with example paths). A pattern, a naming habit or a
  layout style is a reading of those facts (``inferred``, with a note saying how many of how many).

Nothing here says a project is *not* written some way: a missing label is "not observed".
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .context import Run, module_label
from .model import Evidence
from .store import make_id
from .text import type_name

MIN_SAMPLE = 3
MIN_SUPPORT = 3
DOMINANT_PCT = 70
PRESENT_PCT = 30
MAX_EXAMPLES = 5
MAX_FORMAT_LINES = 200_000

_DI_KINDS = {
    "hilt": (
        "hilt_application",
        "hilt_android_entry",
        "hilt_viewmodel",
        "hilt_worker",
        "hilt_entry_point",
    ),
    "dagger": ("dagger_component",),
    "koin": ("koin_module", "koin_start", "koin_definition"),
}
_STATE_IMPORTS = {
    "stateflow": ("kotlinx.coroutines.flow.",),
    "livedata": (
        "androidx.lifecycle.LiveData",
        "androidx.lifecycle.MutableLiveData",
        "androidx.lifecycle.MediatorLiveData",
        "androidx.lifecycle.liveData",
    ),
    "compose_state": (
        "androidx.compose.runtime.mutableStateOf",
        "androidx.compose.runtime.MutableState",
        "androidx.compose.runtime.mutableIntStateOf",
        "androidx.compose.runtime.mutableStateListOf",
        "androidx.compose.runtime.State",
        "androidx.compose.runtime.collectAsState",
        "androidx.lifecycle.compose.collectAsStateWithLifecycle",
    ),
    "rxjava": ("io.reactivex.", "rx."),
}
_ASYNC_IMPORTS = {
    "coroutines": (
        "kotlinx.coroutines.",
        "androidx.lifecycle.viewModelScope",
        "androidx.lifecycle.lifecycleScope",
    ),
    "rxjava": ("io.reactivex.", "rx."),
    "executors_handlers": ("java.util.concurrent.", "android.os.AsyncTask", "android.os.Handler"),
}
_TEST_IMPORTS = {
    "junit4": ("org.junit.",),
    "junit5": ("org.junit.jupiter.",),
    "mockk": ("io.mockk.",),
    "mockito": ("org.mockito.",),
    "espresso": ("androidx.test.espresso.",),
    "compose_test": ("androidx.compose.ui.test.",),
    "robolectric": ("org.robolectric.",),
    "turbine": ("app.cash.turbine.",),
    "truth": ("com.google.common.truth.",),
    "kotest": ("io.kotest.",),
}
_NAMING = (
    ("viewmodel", "ViewModel"),
    ("fragment", "Fragment"),
    ("activity", "Activity"),
    ("adapter", "Adapter"),
    ("worker", "Worker"),
    ("room_dao", "Dao"),
)
_LAYOUT_WORDS = {
    "by_layer": "organised by layer",
    "by_feature": "organised by feature",
    "mixed": "no single style",
}
_STATE_TYPES = re.compile(r"\b(?:Mutable)?(?:StateFlow|SharedFlow|LiveData)\b")
_LAYER_GROUP = {
    "ui": "ui",
    "presentation": "ui",
    "data": "data",
    "network": "data",
    "di": "di",
}


def extract_conventions(run: Run) -> None:
    steps = (
        ("language", _language),
        ("ui_toolkit", _ui_toolkit),
        ("app_structure", _app_structure),
        ("architecture", _architecture),
        ("di", _di),
        ("state", lambda r: _imports_style(r, "state", _STATE_IMPORTS)),
        ("async", lambda r: _imports_style(r, "async", _ASYNC_IMPORTS)),
        ("package_layout", _package_layout),
        ("naming", _naming),
        ("testing", _testing),
        ("formatting", _formatting),
    )
    for name, step in steps:
        if run.expired():
            return
        try:
            step(run)
        except Exception as exc:  # noqa: BLE001 - one dimension failing must not hide the others
            run.store.limit(
                "extractor_error",
                f"conventions:{name}",
                f"the {name} convention step failed ({type(exc).__name__}); its facts are missing",
            )


# -- helpers -------------------------------------------------------------------------------------


def _percent(support: int, total: int) -> int:
    return support * 100 // total if total else 0


def _strength(percent: int) -> str:
    if percent >= DOMINANT_PCT:
        return "dominant"
    return "partial" if percent >= PRESENT_PCT else "weak"


def _evidence_of(run: Run, fact_ids: list[str]) -> list[Evidence]:
    found: list[Evidence] = []
    for fact_id in fact_ids[:MAX_EXAMPLES]:
        evidence = run.store.evidence_of(fact_id)
        if evidence:
            found.append(evidence[0])
    return found


def _path_evidence(paths: list[str]) -> list[Evidence]:
    return [Evidence(path=path) for path in sorted(paths)[:MAX_EXAMPLES]]


def _short(fact_ids: list[str]) -> tuple[str, ...]:
    return tuple(sorted(fact_ids)[:MAX_EXAMPLES])


def _count_fact(
    run: Run,
    dimension: str,
    label: str,
    *,
    attrs: dict,
    evidence: list[Evidence],
    module: str | None = None,
) -> str | None:
    """A convention that is a plain count: read directly, so ``confirmed`` (needs evidence)."""
    if not evidence:
        return None
    return _emit(run, dimension, label, "confirmed", attrs, evidence, module=module)


def _reading_fact(
    run: Run,
    dimension: str,
    label: str,
    *,
    support: int,
    total: int,
    what: str,
    examples: list[str],
    extra: dict | None = None,
    module: str | None = None,
) -> str:
    """A convention that is a reading of facts: ``inferred``, with how many of how many."""
    percent = _percent(support, total)
    attrs = {
        "support": support,
        "total": total,
        "percent": percent,
        "strength": _strength(percent),
        "examples": _short(examples),
        **(extra or {}),
    }
    note = f"{support} of {total} {what}"
    return _emit(
        run,
        dimension,
        label,
        "inferred",
        attrs,
        _evidence_of(run, examples),
        note=note,
        module=module,
    )


def _unknown(run: Run, dimension: str, label: str, reason: str) -> str:
    return _emit(run, dimension, label, "unknown", {}, [], reason=reason)


def _emit(
    run: Run,
    dimension: str,
    label: str,
    status: str,
    attrs: dict,
    evidence: list[Evidence],
    *,
    note: str | None = None,
    reason: str | None = None,
    module: str | None = None,
) -> str:
    subject = f"{dimension}|{label}" + (f"|{module}" if module else "")
    full = {"dimension": dimension, "label": label, **attrs}
    tags = ["convention"]
    if module is not None:
        full["module"] = module
        tags.append(f"module:{module}")
    return run.fact(
        "convention",
        subject,
        basis="heuristic" if status != "confirmed" else "source",
        status=status,  # type: ignore[arg-type]
        evidence=evidence,
        attrs=full,
        note=note,
        reason=reason,
        tags=tuple(tags),
    )


def _app_files(run: Run) -> list[tuple[str, str]]:
    """``(path, module label)`` of every Kotlin or Java file of application code."""
    return [
        (info.path, module_label(run.module_of(info.path)))
        for info in run.app_sources()
        if info.path.endswith((".kt", ".java"))
    ]


# -- counts: language, UI toolkit, structure, DI, tests ------------------------------------------


def _language(run: Run) -> None:
    by_module: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path, module in _app_files(run):
        by_module[module]["kotlin" if path.endswith(".kt") else "java"].append(path)
    for module in sorted(by_module):
        kotlin, java = by_module[module]["kotlin"], by_module[module]["java"]
        total = len(kotlin) + len(java)
        label = "mixed" if kotlin and java else ("kotlin" if kotlin else "java")
        percent = _percent(len(kotlin), total)
        dominant = (
            "kotlin"
            if percent >= DOMINANT_PCT
            else "java"
            if 100 - percent >= DOMINANT_PCT
            else "none"
        )
        _count_fact(
            run,
            "language",
            label,
            attrs={
                "kotlin_files": len(kotlin),
                "java_files": len(java),
                "dominant": dominant,
            },
            evidence=_path_evidence(kotlin[:3] + java[:2] if kotlin and java else kotlin or java),
            module=module,
        )


def _ui_toolkit(run: Run) -> None:
    store = run.store
    compose: dict[str, list[str]] = defaultdict(list)
    xml: dict[str, list[str]] = defaultdict(list)
    for fact_id in store.ids_of_kind("composable"):
        attrs = store.attributes_of(fact_id)
        if attrs.get("preview") is True:
            continue
        for tag in store.tags_of(fact_id):
            if tag.startswith("module:"):
                compose[tag[7:]].append(fact_id)
    for fact_id in store.ids_of_kind("layout"):
        for tag in store.tags_of(fact_id):
            if tag.startswith("module:"):
                xml[tag[7:]].append(fact_id)
    for module in sorted(set(compose) | set(xml)):
        c, x = compose.get(module, []), xml.get(module, [])
        label = "mixed" if c and x else ("compose" if c else "xml_views")
        _count_fact(
            run,
            "ui_toolkit",
            label,
            attrs={"composables": len(c), "layouts": len(x)},
            evidence=_evidence_of(
                run, sorted(c)[:3] + sorted(x)[:2] if c and x else sorted(c or x)
            ),
            module=module,
        )


def _app_structure(run: Run) -> None:
    store = run.store
    activities = [
        fact_id
        for fact_id in store.ids_of_kind("activity")
        if "manifest" in store.attributes_of(fact_id)
    ]
    inside = len(store.ids_of_kind("nav_destination")) + len(store.ids_of_kind("compose_route"))
    count = len(activities)
    if count == 0:
        return
    attrs = {"activities": count, "destinations_inside_activities": inside}
    evidence = _evidence_of(run, activities)
    if count == 1 and inside >= 2:
        _count_fact(run, "app_structure", "single_activity", attrs=attrs, evidence=evidence)
    if count >= 2:
        _count_fact(run, "app_structure", "multi_activity", attrs=attrs, evidence=evidence)
        if inside >= 3:
            _count_fact(run, "app_structure", "mixed", attrs=attrs, evidence=evidence)


def _di(run: Run) -> None:
    store = run.store
    present: dict[str, list[str]] = {}
    for label, kinds in _DI_KINDS.items():
        ids = sorted(fid for kind in kinds for fid in store.ids_of_kind(kind))
        if ids:
            present[label] = ids
    for label, ids in sorted(present.items()):
        _count_fact(
            run,
            "di",
            label,
            attrs={"facts": len(ids), "styles_present": len(present)},
            evidence=_evidence_of(run, ids),
        )
    if len(present) >= 2:
        first = sorted(present.values())[0]
        _count_fact(
            run,
            "di",
            "mixed",
            attrs={
                "facts": sum(len(v) for v in present.values()),
                "styles": tuple(sorted(present)),
            },
            evidence=_evidence_of(run, first),
        )


def _imports_style(run: Run, dimension: str, table: dict[str, tuple[str, ...]]) -> None:
    files: dict[str, list[str]] = defaultdict(list)
    app = [info for info in run.app_sources() if info.path.endswith((".kt", ".java"))]
    for info in app:
        imported = [imp.fqn for imp in info.source.imports]
        for label, prefixes in table.items():
            if any(fqn.startswith(prefix) for fqn in imported for prefix in prefixes):
                files[label].append(info.path)
        if dimension == "async" and "suspend " in info.view.masked:
            files["coroutines"].append(info.path)
    for label in files:
        files[label] = sorted(set(files[label]))
    present = {label: paths for label, paths in files.items() if len(paths) >= 1}
    for label, paths in sorted(present.items()):
        _count_fact(
            run,
            dimension,
            label,
            attrs={"files": len(paths), "app_files": len(app)},
            evidence=_path_evidence(paths),
        )
    leading = [label for label, paths in present.items() if len(paths) >= MIN_SUPPORT]
    if len(leading) >= 2:
        _count_fact(
            run,
            dimension,
            "mixed",
            attrs={"styles": tuple(sorted(leading)), "app_files": len(app)},
            evidence=_path_evidence(present[sorted(leading)[0]]),
        )


def _testing(run: Run) -> None:
    files: dict[str, list[str]] = defaultdict(list)
    tests = 0
    for path in sorted(run.infos):
        if not run.is_test(path) or run.is_build_logic(path):
            continue
        tests += 1
        imported = [imp.fqn for imp in run.infos[path].source.imports]
        for label, prefixes in _TEST_IMPORTS.items():
            hit = any(
                fqn.startswith(prefix)
                and not (label == "junit4" and fqn.startswith("org.junit.jupiter."))
                for fqn in imported
                for prefix in prefixes
            )
            if hit:
                files[label].append(path)
    for label, paths in sorted(files.items()):
        _count_fact(
            run,
            "testing",
            label,
            attrs={"files": len(paths), "test_files": tests},
            evidence=_path_evidence(paths),
        )
    if files.get("junit4") and files.get("junit5"):
        _count_fact(
            run,
            "testing",
            "mixed",
            attrs={"styles": ("junit4", "junit5"), "test_files": tests},
            evidence=_path_evidence(files["junit4"][:2] + files["junit5"][:2]),
        )


# -- architecture --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Screen:
    fact_id: str
    aliases: tuple[str, ...]  # the ids an edge may start from


def _screens(run: Run) -> list[_Screen]:
    """Fragments, Compose screens, and activities that show their own content (an activity that
    only hosts fragments, a NavHost or a navigation graph is a container, not a screen)."""
    store = run.store
    containers = {
        s
        for kind in ("hosts_fragment", "hosts_content", "uses_nav_graph")
        for s, _ in store.relation_pairs(kind)
    }
    screens: list[_Screen] = []
    for kind in ("activity", "fragment"):
        for fact_id in store.ids_of_kind(kind):
            fqn = fact_id.split(":", 1)[1]
            aliases = (fact_id, make_id("type", fqn))
            if kind == "activity" and any(a in containers for a in aliases):
                continue
            screens.append(_Screen(fact_id, aliases))
    for fact_id in store.ids_of_kind("compose_screen"):
        subject = fact_id.split(":", 1)[1]
        screens.append(_Screen(fact_id, (fact_id, make_id("composable", subject))))
    return sorted(screens, key=lambda s: s.fact_id)


def _viewmodel_types(run: Run) -> list[str]:
    store = run.store
    return sorted(
        {
            fid.split(":", 1)[1]
            for kind in ("viewmodel", "hilt_viewmodel")
            for fid in store.ids_of_kind(kind)
        }
        & set(run.types)
    )


def _param_fqn(run: Run, decl, param) -> str | None:
    info = run.infos.get(decl.path)
    name = param.type_simple
    if info is None or not name:
        return None
    resolved = run.resolver.resolve(info.source, name, decl.owner)
    return resolved.fqn if resolved.fqn in run.types else None


def _architecture(run: Run) -> None:
    """Each pattern is measured against what it is about, and needs ``MIN_SAMPLE`` of those to be
    spoken of at all: MVVM and MVP against screens, MVI against ViewModels."""
    store = run.store
    screens = _screens(run)
    models = _viewmodel_types(run)
    emitted: list[tuple[str, int]] = []  # screen patterns: (label, percent of screens)
    other = 0
    if len(screens) >= MIN_SAMPLE:
        users = {s for s, _ in store.relation_pairs("uses_viewmodel")}
        patterns = (
            (
                "mvvm",
                [s.fact_id for s in screens if any(a in users for a in s.aliases)],
                "screens use a ViewModel",
            ),
            ("mvp", _mvp_screens(run, screens), "screens have a presenter"),
        )
        for label, support_ids, what in patterns:
            if len(support_ids) >= MIN_SUPPORT:
                _reading_fact(
                    run,
                    "architecture",
                    label,
                    support=len(support_ids),
                    total=len(screens),
                    what=what,
                    examples=support_ids,
                )
                emitted.append((label, _percent(len(support_ids), len(screens))))
    if len(models) >= MIN_SAMPLE:
        mvi = _mvi_viewmodels(run, models)
        if len(mvi) >= MIN_SUPPORT:
            other += 1
            _reading_fact(
                run,
                "architecture",
                "mvi",
                support=len(mvi),
                total=len(models),
                what="ViewModels expose a state holder and take one sealed event type",
                examples=[make_id("viewmodel", m) for m in mvi],
            )
    other += _layers(run)
    present = [label for label, pct in emitted if pct >= PRESENT_PCT]
    if len(present) >= 2:
        _emit(
            run,
            "architecture",
            "mixed",
            "inferred",
            {"labels": tuple(sorted(present)), "total": len(screens)},
            [],
            note=f"{' and '.join(sorted(present))} each cover at least {PRESENT_PCT}% of "
            f"{len(screens)} screens",
        )
    if not emitted and not other:
        _unknown(
            run,
            "architecture",
            "undetermined",
            f"{len(screens)} screens and {len(models)} ViewModels were found; a pattern needs "
            f"at least {MIN_SAMPLE} of them and {MIN_SUPPORT} that share it",
        )


def _mvp_screens(run: Run, screens: list[_Screen]) -> list[str]:
    store = run.store
    implemented: dict[str, set[str]] = defaultdict(set)  # screen class -> project interfaces
    for source, target in store.relation_pairs("implements"):
        implemented[source].add(target)
    held: dict[str, set[str]] = defaultdict(set)  # interface -> presenters that receive it
    for fqn in sorted(run.types):
        decl = run.types[fqn]
        if decl.kind != "class" or not decl.name.endswith("Presenter"):
            continue
        for param in decl.constructor_params:
            target = _param_fqn(run, decl, param)
            if target is not None:
                held[make_id("type", target)].add(fqn)
    found: list[str] = []
    for screen in screens:
        for alias in screen.aliases:
            if any(held.get(interface) for interface in implemented.get(alias, ())):
                found.append(screen.fact_id)
                break
    return sorted(set(found))


def _mvi_viewmodels(run: Run, models: list[str]) -> list[str]:
    found: list[str] = []
    for fqn in models:
        decl = run.types[fqn]
        info = run.infos.get(decl.path)
        if info is None:
            continue
        holds_state = any(
            m.kind == "property" and _STATE_TYPES.search(m.type_text or "") for m in decl.members
        )
        takes_sealed_event = False
        for member in decl.members:
            if member.kind != "function" or len(member.params) != 1:
                continue
            param = member.params[0]
            name = type_name(param.type_text)
            resolved = run.resolver.resolve(info.source, name, decl.owner) if name else None
            event = run.types.get(resolved.fqn or "") if resolved else None
            if event is not None and "sealed" in event.modifiers:
                takes_sealed_event = True
                break
        if holds_state and takes_sealed_event:
            found.append(fqn)
    return found


def _layers(run: Run) -> int:
    """Repository and use-case signals: classes between a ViewModel and a DAO or a service.
    Returns how many conventions it reported."""
    store = run.store
    models = _viewmodel_types(run)
    injected: set[str] = set()
    for fqn in models:
        decl = run.types[fqn]
        for param in decl.constructor_params:
            target = _param_fqn(run, decl, param)
            if target is not None:
                injected.add(target)
    if len(injected) < MIN_SAMPLE:
        return 0
    sources = {
        fid.split(":", 1)[1]
        for kind in ("room_dao", "retrofit_service")
        for fid in store.ids_of_kind(kind)
    }
    implemented_by: dict[str, set[str]] = defaultdict(set)
    for source, target in store.relation_pairs("implements") + store.relation_pairs("extends"):
        implemented_by[target.split(":", 1)[1]].add(source.split(":", 1)[1])
    repositories: list[str] = []
    use_cases: list[str] = []
    for fqn in sorted(injected):
        candidates = {fqn, *implemented_by.get(fqn, ())}
        for candidate in sorted(candidates):
            decl = run.types.get(candidate)
            if decl is None or decl.kind != "class":
                continue
            if any(_param_fqn(run, decl, p) in sources for p in decl.constructor_params):
                repositories.append(fqn)
                break
        decl = run.types.get(fqn)
        if decl is not None and any(
            m.kind == "function" and m.name == "invoke" and "operator" in m.modifiers
            for m in decl.members
        ):
            use_cases.append(fqn)
    total = len(injected)
    reported = 0
    for label, found, what in (
        ("repository", repositories, "classes injected into ViewModels reach a DAO or a service"),
        ("use_case", use_cases, "classes injected into ViewModels are operator-invoke classes"),
    ):
        if len(found) >= MIN_SUPPORT:
            reported += 1
            _reading_fact(
                run,
                "architecture",
                label,
                support=len(found),
                total=total,
                what=what,
                examples=[make_id("type", f) for f in found],
            )
    return reported


# -- package layout, naming, formatting ----------------------------------------------------------


def _package_layout(run: Run) -> None:
    store = run.store
    packages: dict[str, set[str]] = defaultdict(set)  # package -> layer groups of its types
    for _info, decl in run.app_types():
        groups = {
            _LAYER_GROUP[t[6:]]
            for t in store.tags_of(make_id("type", decl.fqn))
            if t.startswith("layer:") and t[6:] in _LAYER_GROUP
        }
        if groups:
            packages[decl.package].update(groups)
    if not packages:
        return
    segments = [p.split(".") for p in packages]
    root: list[str] = []
    for column in zip(*segments, strict=False):
        if len(set(column)) == 1:
            root.append(column[0])
        else:
            break
    children: dict[str, set[str]] = defaultdict(set)
    for package, groups in packages.items():
        parts = package.split(".")
        if len(parts) <= len(root):
            continue
        children[parts[len(root)]].update(groups)
    for groups in children.values():
        if len(groups) > 1:
            groups.discard("di")  # an @Inject repository next to a DAO is still data
    if len(children) < MIN_SAMPLE:
        found = (
            "all classes with a known layer are in one package"
            if len(packages) == 1
            else f"{len(children)} top-level packages hold classes with a known layer"
        )
        _unknown(
            run,
            "package_layout",
            "undetermined",
            f"{found}; at least {MIN_SAMPLE} top-level packages are needed to describe the layout",
        )
        return
    single = sorted(c for c, g in children.items() if len(g) == 1)
    multi = sorted(c for c, g in children.items() if len(g) >= 2)
    total = len(children)
    if _percent(len(single), total) >= DOMINANT_PCT:
        label, count, examples = "by_layer", len(single), single
    elif _percent(len(multi), total) >= DOMINANT_PCT:
        label, count, examples = "by_feature", len(multi), multi
    else:  # neither style reaches 70 %: report it as mixed, with both counts
        label, count, examples = "mixed", max(len(single), len(multi)), sorted(children)
    _emit(
        run,
        "package_layout",
        label,
        "inferred",
        {
            "support": count,
            "total": total,
            "percent": _percent(count, total),
            "single_layer_packages": len(single),
            "multi_layer_packages": len(multi),
            "packages": tuple(examples[:MAX_EXAMPLES]),
        },
        [],
        note=(
            f"{len(single)} of {total} top-level packages under {'.'.join(root) or '(root)'} hold "
            f"classes of one layer and {len(multi)} hold several ({_LAYOUT_WORDS[label]}); "
            "layers come from what the classes are, not from package names"
        ),
    )


def _naming(run: Run) -> None:
    store = run.store
    for kind, suffix in _NAMING:
        subjects = sorted(
            s for s in {fid.split(":", 1)[1] for fid in store.ids_of_kind(kind)} if s in run.types
        )
        names = {s: run.types[s].name for s in subjects}
        if len(names) < MIN_SAMPLE:
            continue
        with_suffix = sorted(s for s, n in names.items() if n.endswith(suffix))
        percent = _percent(len(with_suffix), len(names))
        label = (
            f"{kind}_suffix"
            if percent >= DOMINANT_PCT
            else f"{kind}_mixed"
            if percent >= PRESENT_PCT
            else f"{kind}_unsuffixed"
        )
        _reading_fact(
            run,
            "naming",
            label,
            support=len(with_suffix),
            total=len(names),
            what=f"{kind} classes end in '{suffix}'",
            examples=[make_id(kind, s) for s in (with_suffix or sorted(names))],
            extra={"suffix": suffix, "role": kind},
        )


def _formatting(run: Run) -> None:
    tabs = spaces = lines = 0
    widths: Counter[int] = Counter()
    lengths: Counter[int] = Counter()
    files: list[str] = []
    for info in run.app_sources():
        if not info.path.endswith((".kt", ".java")):
            continue
        if lines >= MAX_FORMAT_LINES:
            break
        files.append(info.path)
        for line in info.view.text.split("\n"):
            if lines >= MAX_FORMAT_LINES:
                break
            if not line.strip():
                continue
            lines += 1
            lengths[len(line.rstrip("\r"))] += 1
            if line.startswith("\t"):
                tabs += 1
            elif line.startswith(" "):
                spaces += 1
                widths[len(line) - len(line.lstrip(" "))] += 1
    if not lines or not files:
        return
    indented = tabs + spaces
    if indented:
        style = "tabs" if tabs and not spaces else "spaces" if spaces and not tabs else "mixed"
        if spaces and _percent(sum(c for w, c in widths.items() if w % 4 == 0), spaces) >= 90:
            width = 4
        elif spaces and _percent(sum(c for w, c in widths.items() if w % 2 == 0), spaces) >= 90:
            width = 2
        else:
            width = 0
        _count_fact(
            run,
            "formatting",
            "indent",
            attrs={
                "style": style,
                "width": width,
                "indented_lines": indented,
                "lines": lines,
                "sampled": lines >= MAX_FORMAT_LINES,
            },
            evidence=_path_evidence(files),
        )
    ordered = sorted(lengths)
    cumulative = 0
    p95 = ordered[-1]
    for length in ordered:
        cumulative += lengths[length]
        if cumulative * 100 >= lines * 95:
            p95 = length
            break
    hint = next((limit for limit in (80, 100, 120, 140) if p95 <= limit), 0)
    _count_fact(
        run,
        "formatting",
        "line_length",
        attrs={
            "max": ordered[-1],
            "p95": p95,
            "limit_hint": hint,
            "lines": lines,
            "sampled": lines >= MAX_FORMAT_LINES,
        },
        evidence=_path_evidence(files),
    )
