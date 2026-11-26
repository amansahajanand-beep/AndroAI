"""The NVIDIA chat client, driven by a fake transport (no network, no key)."""

import json

import pytest

from androai_codegen.llm_nvidia import LlmError, NvidiaClient
from androai_codegen.modify import ProposedEdits

KEY = "nvapi-SECRET-KEY-123"
GOOD = {"edits": [{"action": "delete", "path": "a.txt", "description": "d"}], "notes": "n"}


def reply(content, status=200, usage=None):
    body = {"choices": [{"message": {"content": content}}], "usage": usage or {}}
    return status, json.dumps(body).encode()


class Fake:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(*responses, **kw):
    fake = Fake(*responses)
    kw.setdefault("sleep", lambda _s: None)
    return NvidiaClient(KEY, transport=fake, **kw), fake


def ask(c):
    return c.complete_json("sys", "user", ProposedEdits, max_output_tokens=500)


def test_valid_json_reply_is_parsed_and_request_is_well_formed():
    c, fake = client(reply(json.dumps(GOOD), usage={"prompt_tokens": 10, "completion_tokens": 5}))
    assert ask(c).edits[0].path == "a.txt"
    url, headers, body, _ = fake.calls[0]
    assert url.endswith("/chat/completions") and headers["Authorization"] == f"Bearer {KEY}"
    assert (
        body["messages"][0]["role"] == "system" and "JSON Schema" in body["messages"][0]["content"]
    )
    assert body["max_tokens"] == 500 and body["stream"] is False
    assert c.usage == {"input_tokens": 10, "output_tokens": 5, "calls": 1}


@pytest.mark.parametrize(
    "text",
    [
        "```json\n" + json.dumps(GOOD) + "\n```",
        "Sure! Here you go:\n" + json.dumps(GOOD) + "\nHope it helps.",
    ],
)
def test_json_in_a_fence_or_prose_is_found(text):
    c, _ = client(reply(text))
    assert ask(c).notes == "n"


def test_invalid_reply_gets_one_repair_attempt():
    c, fake = client(reply("I cannot do that"), reply(json.dumps(GOOD)))
    assert ask(c).notes == "n" and len(fake.calls) == 2
    assert "not valid JSON" in fake.calls[1][2]["messages"][-1]["content"]


def test_still_invalid_after_repair_fails_without_leaking():
    c, _ = client(reply("nope"), reply('{"edits": [{"action": "explode"}]}'))
    with pytest.raises(LlmError) as err:
        ask(c)
    assert KEY not in str(err.value)


def test_rate_limit_is_retried_then_succeeds():
    c, fake = client((429, b"slow down"), reply(json.dumps(GOOD)))
    assert ask(c).notes == "n" and len(fake.calls) == 2


def test_server_errors_give_up_after_max_attempts():
    c, fake = client((503, b""), (503, b""), (503, b""))
    with pytest.raises(LlmError, match="HTTP 503"):
        ask(c)
    assert len(fake.calls) == 3


def test_bad_key_is_not_retried_and_message_is_safe():
    c, fake = client((401, b'{"detail":"bad key nvapi-SECRET-KEY-123"}'))
    with pytest.raises(LlmError) as err:
        ask(c)
    assert len(fake.calls) == 1 and KEY not in str(err.value) and "401" in str(err.value)


def test_network_error_is_retried():
    c, fake = client(LlmError("network error: TimeoutError"), reply(json.dumps(GOOD)))
    assert ask(c).notes == "n" and len(fake.calls) == 2


def test_unexpected_shapes_are_errors():
    for bad in [(200, b"not json"), (200, b'{"choices": []}'), reply("   ")]:
        c, _ = client(bad)
        with pytest.raises(LlmError):
            ask(c)


def test_missing_key_is_an_error(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(LlmError, match="NVIDIA_API_KEY"):
        NvidiaClient()


def test_key_comes_from_the_environment_and_never_shows_in_repr(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    monkeypatch.setenv("NVIDIA_MODEL", "some/model")
    c = NvidiaClient(transport=Fake())
    assert c.model == "some/model" and KEY not in repr(c) and KEY not in str(vars(c).get("model"))


def cut(content="{"):
    body = {"choices": [{"message": {"content": content}, "finish_reason": "length"}], "usage": {}}
    return 200, json.dumps(body).encode()


def test_cut_off_reply_is_retried_asking_for_less_without_resending_the_fragment():
    c, fake = client(
        cut('{"edits": [{"action": "modify", "path": "a" ' + "x" * 500), reply(json.dumps(GOOD))
    )
    assert ask(c).notes == "n" and len(fake.calls) == 2
    second = fake.calls[1][2]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "user"]
    assert "cut off" in second[-1]["content"] and "x" * 100 not in json.dumps(second)


def test_cut_off_twice_gives_a_clear_safe_error():
    c, _ = client(cut(), cut())
    with pytest.raises(LlmError) as err:
        ask(c)
    assert "cut off twice" in err.value.safe_message and KEY not in err.value.safe_message


def test_reasoning_block_is_ignored_even_if_it_contains_braces():
    text = '<think>maybe {"edits": 1} hmm</think>\n' + json.dumps(GOOD)
    c, _ = client(reply(text))
    assert ask(c).notes == "n"


def test_output_limit_can_be_overridden_from_the_environment(monkeypatch):
    c, fake = client(reply(json.dumps(GOOD)))
    ask(c)
    assert fake.calls[0][2]["max_tokens"] == 500  # the caller's limit by default
    monkeypatch.setenv("NVIDIA_MAX_OUTPUT_TOKENS", "24000")
    c2, fake2 = client(reply(json.dumps(GOOD)))
    ask(c2)
    assert fake2.calls[0][2]["max_tokens"] == 24000
    monkeypatch.setenv("NVIDIA_MAX_OUTPUT_TOKENS", "not-a-number")
    c3, fake3 = client(reply(json.dumps(GOOD)))
    ask(c3)
    assert fake3.calls[0][2]["max_tokens"] == 500


def test_several_objects_in_one_reply_take_the_first_without_a_repair_call():
    two = json.dumps(GOOD) + json.dumps({"edits": [], "notes": "second"})
    c, fake = client(reply(two))
    assert ask(c).notes == "n" and len(fake.calls) == 1
    spaced = json.dumps(GOOD) + chr(10) + json.dumps({"edits": [], "notes": "second"})
    c2, fake2 = client(reply(spaced))
    assert ask(c2).notes == "n" and len(fake2.calls) == 1


def test_first_object_is_found_after_prose_and_before_more_prose():
    text = "I will do this first: " + json.dumps(GOOD) + " and then more text {not json"
    c, _ = client(reply(text))
    assert ask(c).notes == "n"


def test_debug_dump_is_off_unless_asked_for(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_DEBUG_DIR", raising=False)
    c, _ = client(reply("nope"), reply("still nope"))
    with pytest.raises(LlmError):
        ask(c)
    monkeypatch.setenv("NVIDIA_DEBUG_DIR", str(tmp_path / "dbg"))
    c2, _ = client(reply("nope"), reply("still nope"))
    with pytest.raises(LlmError):
        ask(c2)
    assert len(list((tmp_path / "dbg").glob("bad_reply_*.txt"))) == 2


def ask_many(c, limit=5):
    return c.complete_json_many("sys", "user", ProposedEdits, max_output_tokens=500, limit=limit)


def test_several_objects_can_all_be_kept():
    a = {"edits": [], "notes": "one"}
    b = {"edits": [], "notes": "two"}
    text = json.dumps(a) + chr(10) + json.dumps(b) + json.dumps({"edits": [], "notes": "three"})
    c, fake = client(reply(text))
    assert [x.notes for x in ask_many(c)] == ["one", "two", "three"] and len(fake.calls) == 1
    c2, _ = client(reply(text))
    assert [x.notes for x in ask_many(c2, limit=2)] == ["one", "two"]


def test_pieces_that_are_not_valid_are_skipped_not_fatal():
    # the second "object" is the argument dictionary of a malformed step
    text = json.dumps({"edits": [], "notes": "ok"}) + ', "tool": "x", "args": {"path": "p"}}'
    c, _ = client(reply(text))
    assert [x.notes for x in ask_many(c)] == ["ok"]


def test_nothing_valid_gets_the_usual_repair_attempt():
    c, fake = client(reply("no json here"), reply(json.dumps(GOOD)))
    assert [x.notes for x in ask_many(c)] == ["n"] and len(fake.calls) == 2


def _sse(*pieces):
    import json as _json

    lines = [("data: " + _json.dumps({"choices": [{"delta": {"content": p}}]}) + "\n").encode() for p in pieces]
    return [*lines, b"\n", b"data: [DONE]\n"]


def test_stream_text_yields_pieces_in_order_and_drops_reasoning():
    from androai_codegen.llm_nvidia import NvidiaClient

    client = NvidiaClient(
        "k", stream_transport=lambda *a: iter(_sse("<thi", "nk>secret</think>", "Hel", "lo ", "there"))
    )
    assert list(client.stream_text("s", "u")) == ["Hel", "lo ", "there"]


def test_stream_text_reports_a_failed_call_without_the_key():
    import pytest

    from androai_codegen.llm_nvidia import LlmError, NvidiaClient

    def broken(*a):
        raise LlmError("the API call failed (HTTP 503)")
        yield b""

    with pytest.raises(LlmError) as info:
        list(NvidiaClient("secret-key", stream_transport=broken).stream_text("s", "u"))
    assert "secret-key" not in str(info.value)
