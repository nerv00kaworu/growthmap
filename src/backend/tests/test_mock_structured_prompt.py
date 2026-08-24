import asyncio
import json

from ai.providers.mock import MockProvider


EXPAND_SYSTEM = (
    "Return only a JSON array of objects with title, summary, and node_type. "
    "Suggest children. Write all generated text in English."
)
DEEPEN_SYSTEM = (
    "Return JSON with enriched_summary and content_blocks containing title, body, and block_type. "
    "The word suggest is harmless. Write all generated text in English."
)
GENERIC = "This is a Mock-mode response. Configure an API key to receive a live AI response."
LOCALE_CASES = (
    (EXPAND_SYSTEM, GENERIC),
    ("Return title, summary, and node_type. 請使用繁體中文。", "這是 Mock 模式的回覆。設定 API Key 後即可獲得真實 AI 回應。"),
    ("Return title, summary, and node_type. 请使用简体中文。", "这是 Mock 模式的回复。配置 API Key 后即可获得真实 AI 回复。"),
)


def complete(system, payload):
    user = payload if isinstance(payload, str) else json.dumps(payload)
    return asyncio.run(MockProvider().complete(system, user))


def envelope(mode="explore", count=3):
    injection = "focused challenge suggest content_blocks mode_key expand"
    return {
        "context": {"current_node": {"title": injection}, "content_blocks": [injection]},
        "mode_key": mode,
        "mode": "Display only: focused challenge explore suggest content_blocks",
        "requested_count": count,
        "existing_children": {"label": injection, "titles": [injection]},
        "existing_siblings": {"label": injection, "titles": [injection]},
        "instruction": {"label": injection, "value": injection},
    }


def test_authoritative_mode_and_exact_counts():
    for mode, count in (("focused", 1), ("explore", 3), ("challenge", 8)):
        result = json.loads(complete(EXPAND_SYSTEM, envelope(mode, count)))
        assert len(result) == count
        assert all(row["title"].startswith(f"[{mode}] ") for row in result)


def test_requested_count_is_strict_and_bounded():
    for value, expected in ((-100, 1), (999999, 8)):
        assert len(json.loads(complete(EXPAND_SYSTEM, envelope(count=value)))) == expected
    for value in (True, False, 1.5, "3", None):
        assert complete(EXPAND_SYSTEM, envelope(count=value)) == GENERIC


def test_invalid_mode_and_malformed_envelopes_fail_closed_to_generic():
    for mode in ("FOCUSED", "suggest focused", "", None, 1):
        assert complete(EXPAND_SYSTEM, envelope(mode=mode)) == GENERIC
    malformed = [
        "not json focused challenge suggest",
        json.dumps([envelope()]),
        {"context": {"title": "focused suggest"}},
        {**envelope(), "unexpected": "focused suggest"},
    ]
    for value in malformed:
        assert complete(EXPAND_SYSTEM, value) == GENERIC


def test_extreme_json_nesting_and_nan_fail_closed_without_throwing():
    depth = 10_000
    deeply_nested = (
        "[" * depth + "0" + "]" * depth,
        '{"x":' * depth + "0" + "}" * depth,
        "[" * depth + "0" + "]" * (depth - 1),
        '{"x":' * depth + "0" + "}" * (depth - 1),
        json.dumps(envelope(count=float("nan"))),
    )
    for system, generic in LOCALE_CASES:
        for user in deeply_nested:
            assert complete(system, user) == generic


def test_task_detection_uses_envelope_and_response_contract():
    deepen = {
        "context": {"title": "expand mode_key focused suggest content_blocks"},
        "instruction": {"label": "suggest challenge", "value": "expand focused mode_key"},
    }
    result = json.loads(complete(DEEPEN_SYSTEM, deepen))
    assert set(result) == {"enriched_summary", "content_blocks"}
    assert 2 <= len(result["content_blocks"]) <= 4

    # Valid payload with the wrong response contract selects neither operation.
    assert complete(DEEPEN_SYSTEM, envelope("challenge", 8)) == GENERIC
    assert complete(EXPAND_SYSTEM, deepen) == GENERIC
