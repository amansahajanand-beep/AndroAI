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
