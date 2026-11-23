import time

from androai_codegen.review.xmlparse import parse_xml

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <application android:label="@string/app_name">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""


def test_parses_structure_attributes_and_positions():
    doc = parse_xml(MANIFEST)
    assert doc.error is None and doc.root.tag == "manifest"
    activity = doc.root.find_all("activity")[0]
    assert activity.attrs["android:name"] == ".MainActivity"  # prefixes kept as written
    assert activity.line == 5
    assert [n.tag for n in doc.root.iter()][:3] == ["manifest", "uses-permission", "application"]
    assert doc.root.find_all("action")[0].attrs["android:name"].endswith("MAIN")
    application = doc.root.child_nodes("application")[0]
    assert [c.tag for c in application.children] == ["activity"]
    assert doc.root.child_nodes("activity") == []  # direct children only, not descendants


def test_text_content_is_collected():
    doc = parse_xml("<resources><string name='a'>  Hello  </string></resources>")
    assert doc.root.find_all("string")[0].text == "Hello"


def test_malformed_xml_reports_a_position_and_never_raises():
    doc = parse_xml("<a>\n  <b>\n</a>")
    assert doc.root is None
    assert doc.error is not None and doc.error.line == 3 and doc.error.message


def test_empty_and_garbage_input_are_errors_not_exceptions():
    assert parse_xml("").error is not None
    assert parse_xml("not xml at all").error is not None
    assert parse_xml("<a><b></a>").error is not None


def test_utf8_bom_is_accepted():
    assert parse_xml("﻿<a/>").error is None


def test_doctype_and_entities_are_rejected():
    for payload in (
        '<!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>',
        '<!DOCTYPE a SYSTEM "http://evil.example/x.dtd"><a/>',
        '<?xml version="1.0"?><!DOCTYPE a [<!ELEMENT a ANY>]><a/>',
    ):
        doc = parse_xml(payload)
        assert doc.root is None and "not allowed" in doc.error.message


def test_entity_expansion_bomb_is_rejected_instantly():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz ['
        '<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
        "]><lolz>&lol3;</lolz>"
    )
    started = time.perf_counter()
    doc = parse_xml(bomb)
    assert time.perf_counter() - started < 1
    assert doc.root is None and "not allowed" in doc.error.message


def test_deep_nesting_is_rejected():
    doc = parse_xml("<a>" * 1000 + "</a>" * 1000)
    assert doc.root is None and "too" in doc.error.message


def test_large_flat_document_is_fine():
    body = "".join(f'<string name="s{i}">v</string>' for i in range(20_000))
    started = time.perf_counter()
    doc = parse_xml(f"<resources>{body}</resources>")
    assert doc.error is None and len(doc.root.children) == 20_000
    assert time.perf_counter() - started < 5
