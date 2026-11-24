"""Source symbols as facts: files, types and their members.

``type`` facts say a declaration exists (confirmed: the declaration is in the text). What a type
*is* in Android terms (an Activity, a ViewModel, a Room database) is a separate role fact built
by the other extractors, so a type can be confirmed while its role is only inferred.

Members are reported for application code only. Tests and build logic keep their ``type`` facts
(tagged ``scope:test`` / ``scope:build_logic``) but not their members: that is bulk nobody asks
about, and it would crowd the fact cap.
"""

from __future__ import annotations

from androai_codegen.review.source import SourceFile

from .context import Run
from .members import Member, TypeInfo, parse_file
from .store import make_id


def parse_sources(run: Run) -> None:
    """Parse every Kotlin and Java file into ``run.infos`` and record what could not be read."""
    store = run.store
    for path, source in run.a.sources.items():
        if run.expired():
            return
        try:
            info = parse_file(source, run.config)
        except Exception as exc:  # noqa: BLE001 - a hostile file must not stop the analysis
            # The tests assert that no valid or fuzzed input ever lands here, so a bug in a parser
            # shows up as a failing test instead of being hidden by this handler.
            store.limit(
                "extractor_error",
                path,
                f"the file could not be parsed and was skipped ({type(exc).__name__})",
            )
            continue
        run.infos[path] = info
        if info.issues:
            kinds = ", ".join(sorted(set(info.issues)))
            store.limit(
                "malformed_source",
                path,
                f"the file has unbalanced brackets, an unterminated string or comment ({kinds}); "
                "facts read from it may be incomplete",
            )


def extract_symbols(run: Run) -> None:
    store = run.store
    for path in sorted(run.infos):
        if run.expired():
            return
        info = run.infos[path]
        source: SourceFile = info.source
        tags = run.path_tags(path)
        store.fact(
            "file",
            path,
            basis="source",
            evidence=[run.path_evidence(path)],
            attrs={
                "file_kind": "kotlin" if path.endswith(".kt") else "java",
                "package": info.package,
                "lines": source.text.count("\n") + 1,
            },
            tags=tags,
        )
        app_code = not (run.is_test(path) or run.is_build_logic(path))
        for decl in info.types:
            _type_fact(run, info, decl, tags, app_code)
            if app_code:
                for member in decl.members:
                    _member_fact(run, info, member, tags)
        if app_code:
            for member in info.top_level:
                _member_fact(run, info, member, tags)
            if info.top_level_truncated:
                _top_level_truncated(run, path, tags)
            if info.top_level_truncated or any(decl.truncated for decl in info.types):
                # Members are reported for application code only, so that is where a dropped
                # member could make an answer wrong: nothing may be concluded from their absence.
                run.store.limit(
                    "member_cap_reached",
                    path,
                    f"a type or the top level of this file has more than "
                    f"{run.config.max_members_per_type} members; the members beyond the limit "
                    "were not read (see the type_members facts)",
                )


def _truncation_reason(run: Run, what: str) -> str:
    cap = run.config.max_members_per_type
    return (
        f"{what} has more than {cap} members; only the first {cap} are reported, so a member "
        "that is not listed may still exist"
    )


def _top_level_truncated(run: Run, path: str, tags: tuple[str, ...]) -> None:
    """The top level of a file holds more members than the limit: say so, as an ``unknown``."""
    fact_id = run.fact(
        "type_members",
        path,
        basis="source",
        status="unknown",
        reason=_truncation_reason(run, "the top level of this file"),
        attrs={"scope": "top_level", "limit": run.config.max_members_per_type},
        tags=tags,
    )
    run.store.relate(
        fact_id,
        "describes",
        make_id("file", path),
        basis="source",
        status="unknown",
        reason="the member list of this file's top level is truncated",
    )


def _type_fact(run: Run, info, decl: TypeInfo, tags: tuple[str, ...], app_code: bool) -> None:
    attrs: dict = {
        "kind": decl.kind,
        "name": decl.name,
        "package": decl.package,
        "visibility": decl.visibility,
        "files": (decl.path,),
        "exact": decl.exact,
        "members": len(decl.members),
    }
    if decl.truncated:
        attrs["members_truncated"] = True  # ``members`` is the limit, not the real count
    if decl.owner:
        attrs["owner"] = decl.owner
    if decl.supertypes:
        attrs["supertypes"] = tuple(s.written for s in decl.supertypes)
    if decl.annotations:
        attrs["annotations"] = tuple(sorted({a.simple for a in decl.annotations}))
    if decl.modifiers:
        attrs["modifiers"] = tuple(sorted(set(decl.modifiers)))
    if decl.entries:
        attrs["enum_entries"] = decl.entries
    if decl.constructor_params:
        attrs["constructor_params"] = tuple(
            f"{p.name}: {p.type_text}" for p in decl.constructor_params
        )
    fact_id = run.fact(
        "type",
        decl.fqn,
        basis="source",
        evidence=[info.view.evidence(decl.offset)],
        attrs=attrs,
        tags=tags,
    )
    truncated = decl.truncated and app_code
    if not decl.exact or truncated:
        reasons: list[str] = []
        why: list[str] = []
        if not decl.exact:
            reasons.append(
                "the declaration header could not be read completely, so its supertypes and "
                "members are not reported"
            )
            why.append("declaration not fully readable")
        if truncated:
            reasons.append(_truncation_reason(run, "the type"))
            why.append("member list truncated")
        run.fact(
            "type_members",
            decl.fqn,
            basis="source",
            status="unknown",
            reason="; ".join(reasons),
            tags=tags,
        )
        run.store.relate(
            make_id("type_members", decl.fqn),
            "describes",
            fact_id,
            basis="source",
            status="unknown",
            reason="; ".join(why),
        )


def _member_fact(run: Run, info, member: Member, tags: tuple[str, ...]) -> None:
    attrs: dict = {
        "member_kind": member.kind,
        "name": member.name,
        "owner": member.owner,
        "visibility": member.visibility,
    }
    if member.modifiers:
        attrs["modifiers"] = tuple(member.modifiers)
    if member.type_text:
        attrs["type"] = member.type_text
    if member.params:
        attrs["params"] = tuple(f"{p.name}: {p.type_text}" for p in member.params)
    if member.annotations:
        attrs["annotations"] = tuple(sorted({a.simple for a in member.annotations}))
    if member.companion:
        attrs["companion"] = True
    if member.delegated:
        attrs["delegated"] = True
    run.fact(
        "member",
        f"{member.owner}#{member.signature}",
        basis="source",
        evidence=[info.view.evidence(member.offset)],
        attrs=attrs,
        tags=tags,
    )
