"""Storage and network facts: Room, Retrofit, SharedPreferences, DataStore, SQLite, files.

Room and Retrofit are read from their annotations, so a fact is ``confirmed`` when the annotation
resolves to the library's package (by import) and ``inferred`` when only the simple name matches.
URLs never carry credentials or query strings into a report (``redact_url``); a base URL that is
computed or comes from a build config field is an ``unknown`` fact, not a guess.
"""

from __future__ import annotations

import re

from .annotations import Annotation
from .catalog import accepted
from .components import role_hit
from .context import Run
from .members import FileInfo, Member, TypeInfo
from .store import make_id
from .text import redact_url, safe, type_name

_HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")
_DAO_OPS = ("Query", "Insert", "Update", "Delete", "Upsert", "RawQuery", "Transaction")
_SQL_TABLE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+[`\"']?([A-Za-z_]\w*)", re.IGNORECASE)
_STRING = re.compile(r'"([^"\\\n]*)"')
_CAP_WORD = re.compile(r"\b[A-Z]\w*")
_MIGRATION = re.compile(r"(?<![\w.])Migration\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
_FALLBACK = re.compile(r"\bfallbackToDestructiveMigration\w*\s*\(")
_BASE_URL = re.compile(r"\.\s*baseUrl\s*\(")
_SHARED_PREFS = re.compile(r"(?<![\w])(getSharedPreferences|getDefaultSharedPreferences)\s*\(")
_DATASTORE = re.compile(r"(?<![\w.])(preferencesDataStore|dataStore)\s*\(")
_FILE_STORAGE = (
    ("internal", re.compile(r"(?<![\w])(?:filesDir|openFileOutput|openFileInput|getFilesDir)\b")),
    (
        "external",
        re.compile(r"(?<![\w])(?:getExternalFilesDir|externalCacheDir|getExternalStorage\w*)\b"),
    ),
    ("cache", re.compile(r"(?<![\w])(?:cacheDir|getCacheDir)\b")),
    ("media_store", re.compile(r"(?<![\w.])MediaStore\b")),
)
_CONST_STRING = re.compile(
    r'\bconst[ \t]+val[ \t]+([A-Za-z_]\w*)[ \t]*(?::[ \t]*String[ \t]*)?=[ \t]*"([^"\n$]*)"'
)


def _level(annotation: Annotation | None, name: str) -> str | None:
    return annotation.level(accepted(name)) if annotation else None


def _find(annotations: tuple[Annotation, ...], name: str) -> tuple[Annotation | None, str | None]:
    for annotation in annotations:
        level = _level(annotation, name)
        if annotation.simple == name and level:
            return annotation, level
    return None, None


def _note(level: str, what: str) -> str | None:
    return (
        None
        if level == "confirmed"
        else f"{what} matches by name only; no import shows its package"
    )


def extract_data(run: Run) -> None:
    constants = _string_constants(run)
    _room(run)
    _retrofit(run, constants)
    _local_storage(run)
    _interceptors(run)


def _string_constants(run: Run) -> dict[str, str]:
    found: dict[str, str] = {}
    clashing: set[str] = set()
    for info in run.app_sources():
        masked, raw = info.view.masked, info.view.text
        for match in _CONST_STRING.finditer(raw):
            if not masked.startswith("const", match.start()):
                continue
            name, value = match.group(1), match.group(2)
            if found.setdefault(name, value) != value:
                clashing.add(name)
    return {k: v for k, v in found.items() if k not in clashing}


# -- Room ----------------------------------------------------------------------------------------


def _room(run: Run) -> None:
    entities: dict[str, str] = {}  # table name -> fact id
    for info, decl in run.app_types():
        annotation, level = _find(decl.annotations, "Entity")
        if annotation is None or level is None or decl.kind not in ("class",):
            continue
        entities[_entity(run, info, decl, annotation, level)] = make_id("room_entity", decl.fqn)
    daos: list[tuple[FileInfo, TypeInfo, str]] = []
    for info, decl in run.app_types():
        annotation, level = _find(decl.annotations, "Dao")
        if annotation is not None and level is not None:
            _dao(run, info, decl, level)
            daos.append((info, decl, level))
    for info, decl in run.app_types():
        annotation, level = _find(decl.annotations, "Database")
        hit = role_hit(run, decl, "room_database")
        if annotation is None and hit is None:
            continue
        status = level or (hit.status if hit else "inferred")
        _database(run, info, decl, annotation, status, entities)
    for info, dao, _ in daos:
        _dao_edges(run, info, dao, entities)
    _migrations(run)
    _schema_export(run)


def _entity(run: Run, info: FileInfo, decl: TypeInfo, annotation: Annotation, level: str) -> str:
    table_arg = annotation.arg("tableName")
    explicit = table_arg.string_value if table_arg else None
    table = explicit or decl.name
    primary: list[str] = []
    columns: list[str] = []
    for param in decl.constructor_params:
        if param.kind in ("val", "var"):
            columns.append(param.name)
            if _find(param.annotations, "PrimaryKey")[1]:
                primary.append(param.name)
    for member in decl.members:
        if member.kind in ("property", "field") and "static" not in member.modifiers:
            if _find(member.annotations, "Ignore")[1]:
                continue
            columns.append(member.name)
            if _find(member.annotations, "PrimaryKey")[1]:
                primary.append(member.name)
    keys_arg = annotation.arg("primaryKeys")
    if keys_arg:
        primary.extend(_STRING.findall(keys_arg.text))
    attrs: dict = {
        "class": decl.fqn,
        "table_name": safe(table, 80),
        "table_name_source": "annotation" if explicit else "default",
        "columns": tuple(columns[:60]),
        "column_count": len(columns),
    }
    if primary:
        attrs["primary_keys"] = tuple(dict.fromkeys(primary))
    if annotation.arg("foreignKeys"):
        attrs["has_foreign_keys"] = True
    if annotation.arg("indices"):
        attrs["has_indices"] = True
    fact_id = run.fact(
        "room_entity",
        decl.fqn,
        basis="source",
        status=level,  # type: ignore[arg-type]
        note=_note(level, "@Entity"),
        evidence=[info.view.evidence(annotation.offset)],
        attrs=attrs,
        tags=(*run.path_tags(info.path), "tech:room", "layer:data"),
    )
    run.store.relate(
        fact_id,
        "role_of",
        make_id("type", decl.fqn),
        basis="source",
        status=level,  # type: ignore[arg-type]
        evidence=[info.view.evidence(decl.offset)],
        note=_note(level, "@Entity"),
    )
    return table


def _dao(run: Run, info: FileInfo, decl: TypeInfo, level: str) -> None:
    operations: list[str] = []
    tables: set[str] = set()
    for member in decl.members:
        if member.kind != "function":
            continue
        for annotation in member.annotations:
            if annotation.simple in _DAO_OPS and _level(annotation, annotation.simple):
                operations.append(f"{annotation.simple}:{member.name}")
                if annotation.simple in ("Query", "RawQuery"):
                    arg = annotation.arg()
                    if arg:
                        tables.update(_SQL_TABLE.findall(arg.text))
    attrs: dict = {
        "class": decl.fqn,
        "operations": tuple(operations[:100]),
        "operation_count": len(operations),
    }
    if tables:
        attrs["tables_referenced"] = tuple(sorted(tables))
    annotation, _ = _find(decl.annotations, "Dao")
    fact_id = run.fact(
        "room_dao",
        decl.fqn,
        basis="source",
        status=level,  # type: ignore[arg-type]
        note=_note(level, "@Dao"),
        evidence=[info.view.evidence(annotation.offset if annotation else decl.offset)],
        attrs=attrs,
        tags=(*run.path_tags(info.path), "tech:room", "layer:data"),
    )
    run.store.relate(
        fact_id,
        "role_of",
        make_id("type", decl.fqn),
        basis="source",
        status=level,  # type: ignore[arg-type]
        evidence=[info.view.evidence(decl.offset)],
        note=_note(level, "@Dao"),
    )


def _dao_edges(run: Run, info: FileInfo, dao: TypeInfo, entities: dict[str, str]) -> None:
    store = run.store
    dao_id = make_id("room_dao", dao.fqn)
    for member in dao.members:
        if member.kind != "function":
            continue
        for annotation in member.annotations:
            if not _level(annotation, annotation.simple):
                continue
            evidence = [info.view.evidence(member.offset)]
            if annotation.simple in ("Insert", "Update", "Delete", "Upsert"):
                for param in member.params:
                    for word in _CAP_WORD.findall(param.type_text):
                        resolved = run.resolver.resolve(info.source, word, dao.fqn)
                        target = make_id("room_entity", resolved.fqn or "")
                        if resolved.fqn and store.has(target):
                            store.relate(
                                dao_id,
                                "accesses",
                                target,
                                basis="source",
                                status="confirmed" if resolved.exact else "inferred",
                                evidence=evidence,
                                note=None
                                if resolved.exact
                                else "the entity type is matched by name only",
                            )
            elif annotation.simple in ("Query", "RawQuery"):
                arg = annotation.arg()
                for table in _SQL_TABLE.findall(arg.text if arg else ""):
                    for name, target in entities.items():
                        if name.lower() == table.lower():
                            store.relate(
                                dao_id,
                                "accesses",
                                target,
                                basis="source",
                                status="inferred",
                                evidence=evidence,
                                note="a table name in the SQL text matches an entity's table name",
                            )


def _database(
    run: Run,
    info: FileInfo,
    decl: TypeInfo,
    annotation: Annotation | None,
    level: str,
    entities: dict[str, str],
) -> None:
    store = run.store
    attrs: dict = {"class": decl.fqn}
    entity_refs: tuple[str, ...] = ()
    if annotation is not None:
        entities_arg = annotation.arg("entities")
        if entities_arg:
            entity_refs = entities_arg.class_refs()
            attrs["entities"] = entity_refs
        version = annotation.arg("version")
        if version and version.text.strip().isdigit():
            attrs["version"] = int(version.text.strip())
        export = annotation.arg("exportSchema")
        if export:
            attrs["export_schema"] = export.text.strip().lower() == "true"
        if annotation.arg("autoMigrations"):
            attrs["has_auto_migrations"] = True
    converters, _ = _find(decl.annotations, "TypeConverters")
    if converters and converters.arg():
        attrs["type_converters"] = converters.arg().class_refs()  # type: ignore[union-attr]
    evidence = [info.view.evidence(annotation.offset if annotation else decl.offset)]
    fact_id = run.fact(
        "room_database",
        decl.fqn,
        basis="source",
        status=level,  # type: ignore[arg-type]
        note=_note(level, "@Database / RoomDatabase"),
        evidence=evidence,
        attrs=attrs,
        tags=(*run.path_tags(info.path), "tech:room", "layer:data"),
    )
    store.relate(
        fact_id,
        "role_of",
        make_id("type", decl.fqn),
        basis="source",
        status=level,  # type: ignore[arg-type]
        evidence=evidence,
        note=_note(level, "@Database"),
    )
    for ref in entity_refs:
        resolved = run.resolver.resolve(info.source, ref, decl.fqn)
        target = make_id("room_entity", resolved.fqn or "")
        if resolved.fqn and store.has(target):
            store.relate(
                fact_id,
                "contains_entity",
                target,
                basis="source",
                status="confirmed" if resolved.exact else "inferred",
                evidence=evidence,
                note=None if resolved.exact else "the entity class is matched by name only",
            )
    for member in decl.members:
        if member.kind != "function" or member.params or not member.type_text:
            continue
        resolved = run.resolver.resolve(info.source, type_name(member.type_text), decl.fqn)
        target = make_id("room_dao", resolved.fqn or "")
        if resolved.fqn and store.has(target):
            store.relate(
                fact_id,
                "exposes_dao",
                target,
                basis="source",
                status="confirmed" if resolved.exact else "inferred",
                evidence=[info.view.evidence(member.offset)],
                note=None if resolved.exact else "the DAO type is matched by name only",
            )


def _migrations(run: Run) -> None:
    for info in run.app_sources():
        masked = info.view.masked
        if "Migration" not in masked:  # also true of "fallbackToDestructiveMigration"
            continue
        for match in _MIGRATION.finditer(masked):
            run.fact(
                "room_migration",
                f"{match.group(1)}->{match.group(2)}",
                basis="source",
                evidence=[info.view.evidence(match.start())],
                attrs={"from_version": int(match.group(1)), "to_version": int(match.group(2))},
                tags=(*run.path_tags(info.path), "tech:room", "layer:data"),
            )
        for match in _FALLBACK.finditer(masked):
            run.fact(
                "room_policy",
                "fallbackToDestructiveMigration",
                basis="source",
                evidence=[info.view.evidence(match.start())],
                attrs={"effect": "the database is deleted and recreated when no migration matches"},
                tags=(*run.path_tags(info.path), "tech:room", "layer:data"),
            )


def _schema_export(run: Run) -> None:
    for _, script in sorted(run.a.gradle_scripts.items()):
        for literal in script.lexed.strings:
            if script.lexed.string_value(literal) == "room.schemaLocation":
                line = script.line(literal.start)
                run.fact(
                    "room_policy",
                    "schemaLocation",
                    basis="gradle",
                    evidence=[run.gradle_evidence(script, line)],
                    attrs={"effect": "Room exports its schema JSON for migration testing"},
                    tags=("tech:room", "layer:data"),
                )
                break


# -- Retrofit ------------------------------------------------------------------------------------


def _http(member: Member) -> tuple[str, str, Annotation, str] | None:
    """``(method, path, annotation, level)`` of a Retrofit endpoint function, if it is one."""
    for annotation in member.annotations:
        name = annotation.simple
        level = _level(annotation, name)
        if not level:
            continue
        if name in _HTTP_METHODS:
            arg = annotation.arg()
            return name, (arg.string_value or "" if arg else ""), annotation, level
        if name == "HTTP":
            method = annotation.arg("method")
            path = annotation.arg("path")
            return (
                (method.string_value or "HTTP") if method else "HTTP",
                (path.string_value or "") if path else "",
                annotation,
                level,
            )
    return None


def _retrofit(run: Run, constants: dict[str, str]) -> None:
    store = run.store
    for info, decl in run.app_types():
        if decl.kind not in ("interface",):
            continue
        endpoints = [(m, hit) for m in decl.members if m.kind == "function" and (hit := _http(m))]
        if not endpoints:
            continue
        levels = {hit[3] for _, hit in endpoints}
        level = "confirmed" if levels == {"confirmed"} else "inferred"
        summary = tuple(
            f"{hit[0]} {redact_url(hit[1], 100)} -> {m.name}" for m, hit in endpoints[:60]
        )
        fact_id = run.fact(
            "retrofit_service",
            decl.fqn,
            basis="source",
            status=level,  # type: ignore[arg-type]
            note=None if level == "confirmed" else "an HTTP annotation matches by name only",
            evidence=[info.view.evidence(endpoints[0][0].offset)],
            attrs={"class": decl.fqn, "endpoints": summary, "endpoint_count": len(endpoints)},
            tags=(*run.path_tags(info.path), "tech:retrofit", "layer:network"),
        )
        store.relate(
            fact_id,
            "role_of",
            make_id("type", decl.fqn),
            basis="source",
            status=level,  # type: ignore[arg-type]
            evidence=[info.view.evidence(decl.offset)],
            note=None if level == "confirmed" else "an HTTP annotation matches by name only",
        )
        for member, (method, path, _annotation, mlevel) in endpoints:
            path_text = redact_url(path, 120)
            attrs: dict = {
                "http_method": method,
                "path": path_text,
                "function": member.name,
                "service": decl.fqn,
                "suspend": "suspend" in member.modifiers,
            }
            if member.type_text:
                attrs["returns"] = member.type_text
            endpoint_id = run.fact(
                "http_endpoint",
                f"{decl.fqn}#{method} {path_text} {member.name}",
                basis="source",
                status=mlevel,  # type: ignore[arg-type]
                note=None if mlevel == "confirmed" else "an HTTP annotation matches by name only",
                evidence=[info.view.evidence(member.offset)],
                attrs=attrs,
                tags=(*run.path_tags(info.path), "tech:retrofit", "layer:network"),
            )
            store.relate(
                fact_id,
                "declares_endpoint",
                endpoint_id,
                basis="source",
                status=mlevel,  # type: ignore[arg-type]
                evidence=[info.view.evidence(member.offset)],
                note=None if mlevel == "confirmed" else "an HTTP annotation matches by name only",
            )
            texts = [member.type_text, *(p.type_text for p in member.params)]
            for word in dict.fromkeys(w for t in texts for w in _CAP_WORD.findall(t)):
                resolved = run.resolver.resolve(info.source, word, decl.fqn)
                target = make_id("type", resolved.fqn or "")
                if resolved.fqn and store.has(target):
                    store.relate(
                        endpoint_id,
                        "uses_model",
                        target,
                        basis="source",
                        status="confirmed" if resolved.exact else "inferred",
                        evidence=[info.view.evidence(member.offset)],
                        note=None if resolved.exact else "the model type is matched by name only",
                    )
    _base_urls(run, constants)


def _first_arg(info: FileInfo, open_index: int) -> tuple[int, int] | None:
    close = info.view.close.get(open_index)
    if close is None:
        return None
    start = info.view.skip_space(open_index + 1, close)
    return (start, close) if start < close else None


def _base_urls(run: Run, constants: dict[str, str]) -> None:
    for info in run.app_sources():
        masked = info.view.masked
        if "baseUrl" not in masked:
            continue
        for match in _BASE_URL.finditer(masked):
            span = _first_arg(info, match.end() - 1)
            if span is None:
                continue
            literal = info.source.lexed.string_starting_at(span[0])
            value: str | None = None
            if literal is not None and literal.terminated:
                value = info.source.lexed.string_value(literal)
            else:
                name = re.match(r"([A-Za-z_][\w.]*)", masked[span[0] : span[1]])
                if name:
                    value = constants.get(name.group(1).rsplit(".", 1)[-1])
            evidence = [info.view.evidence(match.start())]
            if value is not None and "$" not in value:
                run.fact(
                    "base_url",
                    redact_url(value, 200),
                    basis="source",
                    evidence=evidence,
                    attrs={"client": "retrofit"},
                    tags=(*run.path_tags(info.path), "tech:retrofit", "layer:network"),
                )
            else:
                run.fact(
                    "base_url",
                    f"{info.path}:{info.view.line(match.start())}",
                    basis="source",
                    status="unknown",
                    reason="the base URL is computed, a template, or comes from a build "
                    "config field",
                    evidence=evidence,
                    attrs={"client": "retrofit"},
                    tags=(*run.path_tags(info.path), "tech:retrofit", "layer:network"),
                )


# -- local storage -------------------------------------------------------------------------------


def _local_storage(run: Run) -> None:
    for info in run.app_sources():
        if run.expired():
            return
        masked = info.view.masked
        if "SharedPreferences" in masked:
            for match in _SHARED_PREFS.finditer(masked):
                span = _first_arg(info, match.end() - 1)
                name = "(default)"
                if span is not None and match.group(1) == "getSharedPreferences":
                    literal = info.source.lexed.string_starting_at(span[0])
                    if literal is not None and literal.terminated:
                        name = safe(info.source.lexed.string_value(literal), 80) or "(default)"
                    elif masked[span[0] : span[1]].strip():
                        name = "(computed)"
                run.fact(
                    "shared_preferences",
                    name,
                    basis="source",
                    evidence=[info.view.evidence(match.start())],
                    attrs={"named": name not in ("(default)", "(computed)")},
                    tags=(*run.path_tags(info.path), "layer:data"),
                )
        for match in _DATASTORE.finditer(masked):
            span = _first_arg(info, match.end() - 1)
            kind = "preferences" if match.group(1) == "preferencesDataStore" else "typed"
            name = ""
            if span is not None:
                text = info.view.text[span[0] : span[1]]
                found = _STRING.search(text)
                name = safe(found.group(1), 80) if found else ""
            run.fact(
                "datastore",
                name or f"{info.path}:{info.view.line(match.start())}",
                basis="source",
                evidence=[info.view.evidence(match.start())],
                attrs={"datastore_kind": kind},
                tags=(*run.path_tags(info.path), "layer:data"),
            )
        for place, pattern in _FILE_STORAGE:
            match = pattern.search(masked)
            if match:
                run.fact(
                    "file_storage",
                    place,
                    basis="source",
                    evidence=[info.view.evidence(match.start())],
                    attrs={"location": place},
                    tags=(*run.path_tags(info.path), "layer:data"),
                )
        for decl in info.types:
            hit = role_hit(run, decl, "sqlite_helper")
            if hit is not None:
                fact_id = run.fact(
                    "sqlite_helper",
                    decl.fqn,
                    basis="source",
                    status=hit.status,  # type: ignore[arg-type]
                    note=hit.note,
                    evidence=list(hit.evidence),
                    attrs={"class": decl.fqn},
                    tags=(*run.path_tags(info.path), "layer:data"),
                )
                run.store.relate(
                    fact_id,
                    "role_of",
                    make_id("type", decl.fqn),
                    basis="source",
                    status=hit.status,  # type: ignore[arg-type]
                    evidence=list(hit.evidence[:1]),
                    note=hit.note,
                )


def _interceptors(run: Run) -> None:
    for info, decl in run.app_types():
        hit = role_hit(run, decl, "http_interceptor")
        if hit is None:
            continue
        fact_id = run.fact(
            "http_interceptor",
            decl.fqn,
            basis="source",
            status=hit.status,  # type: ignore[arg-type]
            note=hit.note,
            evidence=list(hit.evidence),
            attrs={"class": decl.fqn},
            tags=(*run.path_tags(info.path), "tech:okhttp", "layer:network"),
        )
        run.store.relate(
            fact_id,
            "role_of",
            make_id("type", decl.fqn),
            basis="source",
            status=hit.status,  # type: ignore[arg-type]
            evidence=list(hit.evidence[:1]),
            note=hit.note,
        )
