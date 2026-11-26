"""Build-free checks of an edited project, and the agent fixing what they find."""

import json

import pytest
from sample_project import good_project
from test_agent_loop import STRINGS, Script, make_task, project, tool  # noqa: F401

from androai_codegen.agent.checks import check_project
from androai_codegen.agent.loop import AgentConfig, AgentEditProposer
from androai_codegen.modify import ModifyConfig, ModifyOutcome, run_modification
from androai_codegen.review import ReviewSession

NEW = "com.photoemitter"
GRADLE = "app/build.gradle.kts"
CONFIG = "app/google-services.json"


class View:
    """A dict-backed project for the pure checks."""

    def __init__(self, files, changed=()):
        self.files, self._changed = dict(files), set(changed)

    def paths(self):
        return sorted(self.files)

    def text(self, path):
        value = self.files.get(path)
        return value if isinstance(value, str) else None

    def changed(self):
        return set(self._changed)


def firebase(package):
    return json.dumps(
        {
            "client": [
                {"client_info": {"android_client_info": {"package_name": package}}},
            ]
        },
        indent=2,
    )


def with_firebase(app_id="com.example.todo", config_package="com.example.todo"):
    files = good_project()
    files[GRADLE] = files[GRADLE].replace(
        "alias(libs.plugins.ksp)", "alias(libs.plugins.ksp)\n    id(\"com.google.gms.google-services\")"
    )
    files[GRADLE] = files[GRADLE].replace(
        'applicationId = "com.example.todo"', f'applicationId = "{app_id}"'
    )
    files[CONFIG] = firebase(config_package)
    return files


def test_the_sample_project_has_no_problems():
    assert check_project(View(good_project())) == []


def test_a_matching_firebase_config_is_fine():
    assert check_project(View(with_firebase())) == []


def test_firebase_config_missing_the_application_id_is_reported():
    problems = check_project(View(with_firebase(app_id=NEW)))
    assert len(problems) == 1
    assert CONFIG in problems[0] and NEW in problems[0] and "com.example.todo" in problems[0]


def test_firebase_is_ignored_without_the_google_services_plugin():
    files = with_firebase(app_id=NEW)
    files[GRADLE] = files[GRADLE].replace('id("com.google.gms.google-services")', "")
    assert check_project(View(files)) == []


def test_firebase_is_ignored_when_ids_use_suffixes():
    files = with_firebase(app_id=NEW)
    files[GRADLE] = files[GRADLE].replace("minSdk = 24", 'applicationIdSuffix = ".debug"\n        minSdk = 24')
    assert check_project(View(files)) == []


def test_an_import_of_r_from_a_package_that_is_gone_is_reported():
    files = good_project()
    path = "app/src/main/java/com/example/todo/ui/TodoApp.kt"
    files[path] = files[path].replace("import com.example.todo.R", "import com.example.old.R")
    problems = check_project(View(files, changed=[path]))
    assert len(problems) == 1 and "com.example.old.R" in problems[0]


def test_library_r_imports_are_not_flagged():
    files = good_project()
    path = "app/src/main/java/com/example/todo/ui/TodoApp.kt"
    files[path] = files[path].replace(
        "import com.example.todo.R", "import com.example.todo.R\nimport androidx.appcompat.R as AppR"
    )
    assert check_project(View(files, changed=[path])) == []


def test_a_manifest_pointing_at_a_missing_class_is_reported():
    files = good_project()
    manifest = "app/src/main/AndroidManifest.xml"
    files[manifest] = files[manifest].replace(".MainActivity", ".GoneActivity")
    problems = check_project(View(files, changed=[manifest]))
    assert len(problems) == 1 and "com.example.todo.GoneActivity" in problems[0]


def test_a_library_component_in_the_manifest_is_left_alone():
    files = good_project()
    manifest = "app/src/main/AndroidManifest.xml"
    files[manifest] = files[manifest].replace(
        "</application>",
        '<service android:name="com.google.firebase.messaging.FirebaseMessagingService" /></application>',
    )
    assert check_project(View(files, changed=[manifest])) == []


def test_a_java_file_in_the_wrong_folder_is_reported():
    files = good_project()
    files["app/src/main/java/com/other/Thing.java"] = "package com.example.todo;\nclass Thing {}\n"
    problems = check_project(View(files, changed=["app/src/main/java/com/other/Thing.java"]))
    assert len(problems) == 1 and "matching folder" in problems[0]


def test_broken_xml_and_json_are_reported_only_when_changed():
    files = good_project()
    files[STRINGS] = "<resources><string name='a'>x</resources>"
    files["app/data.json"] = "{not json"
    assert check_project(View(files)) == []
    problems = check_project(View(files, changed=[STRINGS, "app/data.json"]))
    assert len(problems) == 2 and any("XML" in p for p in problems) and any("JSON" in p for p in problems)


def test_xml_with_entities_is_not_parsed():
    files = good_project()
    files[STRINGS] = '<!DOCTYPE x [<!ENTITY a "b">]><resources/>'
    assert check_project(View(files, changed=[STRINGS])) == []


# ---- the agent gets the problems back and fixes them ---------------------------------------------


@pytest.fixture
def firebase_project(put, ws_root):
    for path, content in with_firebase().items():
        put(path, content)
    return ws_root


@pytest.fixture
def go(manager, engine):
    session = ReviewSession(engine)

    def _go(model, config=None, **kw):
        proposer = AgentEditProposer(model, engine, config=config, **kw)
        return run_modification(manager, session, proposer, make_task(), ModifyConfig()), proposer

    return _go


def set_id():
    return tool("edit_file", "new id", path=GRADLE, old='applicationId = "com.example.todo"',
                new=f'applicationId = "{NEW}"')


def test_the_agent_is_told_what_the_checks_found_and_fixes_it(go, firebase_project):
    # Editing the gradle file by hand leaves the Firebase config behind; the checks catch it and the
    # agent repairs it in the next round, so the user is only shown a project that is consistent.
    events = []
    model = Script(
        set_id(),
        tool("finish", summary="Changed the id."),
        tool("read_file", "look at the config", path=CONFIG),
        tool("write_file", "register the package", path=CONFIG, content=firebase(NEW)),
        tool("finish", summary="Changed the id and the Firebase config."),
    )
    result, _ = go(model, activity=events.append)
    assert result.outcome is ModifyOutcome.COMPLETED, result
    assert "The project checks found problems" in model.prompts[2] and CONFIG in model.prompts[2]
    assert check_project(View({p: (firebase_project / p).read_text() for p in
                               (GRADLE, CONFIG)})) == []
    assert [e["ok"] for e in events if e["kind"] == "check"] == [False, True]
    assert "NOTE" not in result.notes


def test_what_the_agent_cannot_fix_is_reported_in_the_summary(go, firebase_project):
    model = Script(set_id(), tool("finish", summary="Changed the id."),
                   tool("finish", summary="I did nothing more."),
                   tool("finish", summary="Still nothing."))
    result, _ = go(model, config=AgentConfig(verify_rounds=2))
    assert result.outcome is ModifyOutcome.COMPLETED
    assert "NOTE: the project checks still report 1 problem" in result.notes
    assert CONFIG in result.notes


def test_checks_can_be_switched_off(go, firebase_project):
    model = Script(set_id(), tool("finish", summary="Changed the id."))
    result, _ = go(model, verify=None)
    assert result.outcome is ModifyOutcome.COMPLETED and "NOTE" not in result.notes
    assert len(model.prompts) == 2


def test_a_crashing_check_never_loses_the_work(go, project):  # noqa: F811
    def boom(_staged):
        raise RuntimeError("bug in a check")

    events = []
    model = Script(
        tool("edit_file", path=STRINGS, old='<string name="empty_list">Nothing to do</string>',
             new='<string name="empty_list">Done</string>'),
        tool("finish", summary="ok"),
    )
    result, _ = go(model, verify=boom, activity=events.append)
    assert result.outcome is ModifyOutcome.COMPLETED
    assert any(e["kind"] == "check" and not e["ok"] for e in events)


def test_the_proposer_defaults_to_running_the_checks():
    assert check_project in AgentEditProposer.__init__.__kwdefaults__.values()
