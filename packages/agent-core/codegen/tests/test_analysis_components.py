"""M2.4: manifest facts and class roles (Activity, Fragment, ViewModel, Service, ...)."""

from __future__ import annotations

from analysis_fixtures import (
    GOOGLE_KEY,
    analyse,
    d,
    edges,
    fact,
    hilt_project,
    ids,
    java_xml_project,
    no_errors,
)

NS = 'xmlns:android="http://schemas.android.com/apk/res/android"'


def project(manifest: str = "", **sources: str) -> dict[str, str]:
    """One module ``app`` (namespace ``com.x``) with a manifest and Kotlin/Java sources."""
    files = {
        "settings.gradle.kts": 'include(":app")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "app/src/main/AndroidManifest.xml": manifest or f"<manifest {NS}><application/></manifest>",
    }
    for name, text in sources.items():
        suffix = ".java" if name.endswith("_java") else ".kt"
        stem = name.removesuffix("_java")
        files[f"app/src/main/java/com/x/{stem}{suffix}"] = d(text)
    return files


# -- manifest -----------------------------------------------------------------------------------


def test_application_and_component_facts_carry_manifest_attributes_and_evidence():
    report = analyse(hilt_project())
    app = fact(report, "application:com.example.notes.NotesApp")
    assert app.attributes["allow_backup"] == "true"
    assert app.attributes["cleartext_traffic"] == "false"
    assert app.attributes["theme"] == "@style/Theme.Notes"
    assert app.evidence[0].path == "app/src/main/AndroidManifest.xml"
    assert app.evidence[0].excerpt.startswith("<application")  # the tag spans several lines
    main = fact(report, "activity:com.example.notes.MainActivity")
    assert main.attributes["launcher"] is True
    assert main.attributes["exported"] == "true"
    assert main.attributes["deep_links"] == ("https://notes.example.com/n",)
    assert "launcher" in main.tags and "entry-point" in main.tags
    service = fact(report, "service:com.example.notes.sync.SyncService")
    assert service.attributes["exported"] == "false" and service.attributes["launcher"] is False
    receiver = fact(report, "receiver:com.example.notes.BootReceiver")
    assert receiver.attributes["actions"] == ("android.intent.action.BOOT_COMPLETED",)
    assert fact(report, "permission:android.permission.INTERNET").status == "confirmed"


def test_relative_class_names_resolve_against_the_gradle_namespace():
    manifest = (
        f"<manifest {NS}><application>"
        '<activity android:name=".ui.Home"/><activity android:name="Plain"/>'
        '<activity android:name="org.other.Full"/></application></manifest>'
    )
    assert ids(analyse(project(manifest)), "activity") == [
        "com.x.Plain",
        "com.x.ui.Home",
        "org.other.Full",
    ]


def test_the_manifest_package_is_used_when_there_is_no_namespace():
    files = {
        "build.gradle": "",
        "src/main/AndroidManifest.xml": (
            f'<manifest {NS} package="old.pkg"><application><activity android:name=".A"/>'
            "</application></manifest>"
        ),
    }
    assert ids(analyse(files), "activity") == ["old.pkg.A"]


def test_an_activity_alias_is_its_own_kind_and_keeps_its_target():
    manifest = (
        f"<manifest {NS}><application>"
        '<activity-alias android:name=".Alias" android:targetActivity=".Real"/>'
        "</application></manifest>"
    )
    alias = fact(analyse(project(manifest)), "activity_alias:com.x.Alias")
    assert alias.attributes["target_activity"] == ".Real"


def test_meta_data_values_that_could_be_secrets_are_never_recorded():
    report = analyse(hilt_project())
    key = fact(report, "meta_data:com.google.android.geo.API_KEY")
    assert key.attributes["value"] == "[REDACTED]"
    assert GOOGLE_KEY not in report.model_dump_json()
    assert fact(report, "meta_data:com.example.notes.MODE").attributes["value"] == "demo"


def test_a_resource_reference_in_meta_data_is_kept_because_it_holds_no_value():
    manifest = (
        f"<manifest {NS}><application>"
        '<meta-data android:name="com.google.maps.API_KEY" android:value="@string/maps_key"/>'
        "</application></manifest>"
    )
    assert (
        fact(analyse(project(manifest)), "meta_data:com.google.maps.API_KEY").attributes["value"]
        == "@string/maps_key"
    )


def test_a_manifest_that_does_not_parse_is_a_limitation_and_makes_the_report_incomplete():
    report = analyse(project("<manifest><application></manifest>"))
    assert any(
        m.code == "malformed_source" and m.scope.endswith("AndroidManifest.xml")
        for m in report.limitations
    )
    assert report.complete is False
    assert ids(report, "activity") == []  # nothing is invented from a manifest that cannot be read


def test_a_manifest_with_a_doctype_is_refused_not_expanded():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f'<manifest {NS}><application><activity android:name="&b;"/></application></manifest>'
    )
    report = analyse(project(bomb))
    no_errors(report)
    assert ids(report, "activity") == []
    assert report.complete is False


def test_a_class_named_in_the_manifest_is_linked_to_its_source_declaration():
    report = analyse(hilt_project())
    assert (
        "activity:com.example.notes.MainActivity",
        "type:com.example.notes.MainActivity",
    ) in edges(report, "implemented_by")
    # a class that is only in the manifest gets a fact but no edge, and no claim about the source
    manifest = f'<manifest {NS}><application><activity android:name=".FromLibrary"/></application></manifest>'
    report = analyse(project(manifest))
    assert ids(report, "activity") == ["com.x.FromLibrary"]
    assert edges(report, "implemented_by") == set()


# -- roles from source --------------------------------------------------------------------------


def test_a_framework_base_class_named_by_import_gives_a_confirmed_role():
    report = analyse(
        project(
            A="""
            package com.x
            import androidx.appcompat.app.AppCompatActivity
            import androidx.lifecycle.ViewModel
            class A : AppCompatActivity()
            class V : ViewModel()
            """
        )
    )
    activity = fact(report, "activity:com.x.A")
    assert activity.status == "confirmed" and activity.basis == "source"
    assert activity.attributes["base"] == "AppCompatActivity"
    assert fact(report, "viewmodel:com.x.V").status == "confirmed"
    assert ("activity:com.x.A", "type:com.x.A") in edges(report, "role_of")


def test_a_fully_qualified_base_class_and_a_wildcard_import_are_confirmed():
    report = analyse(
        project(
            A="""
            package com.x
            import androidx.fragment.app.*
            class F : Fragment()
            class G : android.app.Service()
            """
        )
    )
    assert fact(report, "fragment:com.x.F").status == "confirmed"
    assert fact(report, "service:com.x.G").status == "confirmed"


def test_a_base_class_matched_by_name_alone_is_inferred_and_says_why():
    report = analyse(project(A="package com.x\nclass A : AppCompatActivity()\n"))
    activity = fact(report, "activity:com.x.A")
    assert activity.status == "inferred"
    assert "name only" in activity.note


def test_a_project_class_that_shadows_a_framework_name_is_not_the_framework_class():
    report = analyse(
        project(
            Fragment="package com.x\nopen class Fragment\n",
            Mine="package com.x\nclass Mine : Fragment()\n",
        )
    )
    assert ids(report, "fragment") == []


def test_a_class_with_a_different_library_of_the_same_name_gets_no_role():
    report = analyse(
        project(A="package com.x\nimport com.other.ViewModel\nclass A : ViewModel()\n")
    )
    assert ids(report, "viewmodel") == []


def test_roles_are_inherited_through_project_classes_and_the_chain_is_recorded():
    report = analyse(
        project(
            Base="package com.x\nimport androidx.fragment.app.Fragment\nabstract class BaseFragment : Fragment()\n",
            Mid="package com.x\nopen class Mid : BaseFragment()\n",
            Leaf="package com.x\nclass Leaf : Mid()\n",
        )
    )
    leaf = fact(report, "fragment:com.x.Leaf")
    assert leaf.status == "confirmed"
    assert leaf.attributes["inherited_via"] == ("com.x.Mid", "com.x.BaseFragment")
    assert fact(report, "fragment:com.x.BaseFragment").attributes["abstract"] is True


def test_a_role_inherited_through_a_class_matched_only_by_name_is_inferred():
    report = analyse(
        project(
            Base="package com.x.base\nimport androidx.fragment.app.Fragment\nopen class BaseFragment : Fragment()\n",
            Leaf="package com.x.ui\nclass Leaf : BaseFragment()\n",
        )
    )
    leaf = fact(report, "fragment:com.x.ui.Leaf")
    assert leaf.status == "inferred"
    assert "BaseFragment" in leaf.note


def test_inheritance_cycles_terminate():
    report = analyse(
        project(
            A="package com.x\nclass A : B()\nclass B : A()\n",
        )
    )
    no_errors(report)
    assert ids(report, "fragment") == [] and ids(report, "activity") == []


def test_only_classes_get_roles_and_tests_and_build_logic_are_skipped():
    files = project(
        A="package com.x\nimport androidx.fragment.app.Fragment\ninterface I : Fragment\nenum class E : Fragment\n",
    )
    files["app/src/test/java/com/x/T.kt"] = (
        "package com.x\nimport androidx.fragment.app.Fragment\nclass T : Fragment()\n"
    )
    files["buildSrc/src/main/kotlin/B.kt"] = (
        "package b\nimport androidx.fragment.app.Fragment\nclass B : Fragment()\n"
    )
    assert ids(analyse(files), "fragment") == []


def test_java_roles_adapters_custom_views_and_helpers():
    report = analyse(java_xml_project())
    assert (
        fact(report, "adapter:com.example.legacy.ui.ItemAdapter").attributes["base"]
        == "RecyclerView.Adapter"
    )
    assert fact(report, "custom_view:com.example.legacy.ui.CounterView").status == "confirmed"
    detail = fact(report, "fragment:com.example.legacy.ui.DetailFragment")
    assert detail.attributes["inherited_via"] == ("com.example.legacy.ui.BaseFragment",)


def test_services_receivers_providers_workers_and_applications():
    report = analyse(
        project(
            A="""
            package com.x
            import android.app.Application
            import android.app.Service
            import android.content.BroadcastReceiver
            import android.content.ContentProvider
            import androidx.work.CoroutineWorker
            class App : Application()
            class S : Service()
            class R : BroadcastReceiver()
            class P : ContentProvider()
            class W : CoroutineWorker()
            """
        )
    )
    for kind, name in (
        ("application", "App"),
        ("service", "S"),
        ("receiver", "R"),
        ("provider", "P"),
        ("worker", "W"),
    ):
        assert fact(report, f"{kind}:com.x.{name}").status == "confirmed"


def test_tags_follow_the_roles_read_from_the_code_not_the_class_names():
    report = analyse(
        project(
            Misleading="package com.x\nclass HomeActivityViewModelFragment\n",
            Real="package com.x\nimport androidx.lifecycle.ViewModel\nclass Plain : ViewModel()\n",
        )
    )
    tagged = {f.subject for f in report.facts if "role:viewmodel" in f.tags}
    assert tagged == {"com.x.Plain"}
    assert "layer:presentation" in fact(report, "type:com.x.Plain").tags
    assert "role:viewmodel" not in fact(report, "type:com.x.HomeActivityViewModelFragment").tags
