"""Context retrieval: the right files for a prompt, with reasons, deterministically."""

import sys

sys.path.insert(0, ".")

from analysis_fixtures import hilt_project

from androai_codegen.analysis import analyse_mapping
from androai_codegen.retrieval import retrieve_context, tokens

REPORT = analyse_mapping(hilt_project())


def _paths(bundle, role=None):
    return [f.path for f in bundle.files if role is None or f.role == role]


def test_tokens_split_camel_and_snake():
    assert tokens("AddNoteScreen add_note-list") == ["add", "note", "screen", "add", "note", "list"]


def test_named_screen_is_primary():
    bundle = retrieve_context(REPORT, "Add a date picker to the AddNote screen")
    assert bundle.confidence in ("high", "medium")
    assert any(p.endswith("AddNoteScreen.kt") for p in _paths(bundle, "primary"))
    assert bundle.seeds and bundle.seeds[0].kind in (
        "composable",
        "compose_screen",
        "compose_route",
    )


def test_related_and_impact_come_from_the_graph():
    bundle = retrieve_context(REPORT, "change the AddNote screen layout")
    others = set(_paths(bundle)) | {f.path for f in bundle.impact}
    assert len(others) > 1  # more than the screen file alone


def test_gibberish_matches_nothing_and_falls_back():
    bundle = retrieve_context(REPORT, "frobnicate the zxqv widget")
    assert bundle.confidence == "none" and not bundle.seeds
    assert bundle.notes and all(f.role == "overview" for f in bundle.files)


def test_kind_word_alone_selects_nothing():
    bundle = retrieve_context(REPORT, "improve the screen")
    assert bundle.confidence == "none"


def test_unmatched_terms_reported():
    bundle = retrieve_context(REPORT, "AddNote screen with holographic sparkles")
    assert "holographic" in bundle.unmatched_terms


def test_deterministic_and_bounded():
    from androai_codegen.retrieval import RetrievalConfig

    cfg = RetrievalConfig(max_files=2, max_seeds=1)
    a = retrieve_context(REPORT, "AddNote screen", cfg)
    b = retrieve_context(REPORT, "AddNote screen", cfg)
    assert a == b and len(a.files) <= 2 and len(a.seeds) == 1


def test_empty_prompt():
    assert retrieve_context(REPORT, "").confidence == "none"
    assert retrieve_context(REPORT, "   ").terms == ()


def test_exact_identifier_beats_shared_words():
    bundle = retrieve_context(REPORT, "Add a date picker to the AddNote screen")
    assert bundle.files[0].path.endswith("AddNoteScreen.kt")
    assert not any(p.endswith("NoteDetailScreen.kt") for p in _paths(bundle, "primary"))


def test_network_request_finds_the_api_file():
    bundle = retrieve_context(REPORT, "add a new retrofit endpoint for notes")
    assert any(p.endswith("NotesApi.kt") for p in _paths(bundle, "primary"))


def test_permission_request_points_at_manifest_and_build_files():
    bundle = retrieve_context(REPORT, "add camera permission")
    assert any(p.endswith("AndroidManifest.xml") for p in _paths(bundle, "build"))
