"""Локальный Qwen не должен уходить в reasoning на structured-запросе."""

from paper2data.core.project import LlmProfileConfig
from paper2data.llm.client import (
    _THINK_PREFILL,
    apply_thinking_controls,
    is_local_base_url,
    relax_rejected_payload,
)


def _profile(base_url: str, model: str) -> LlmProfileConfig:
    return LlmProfileConfig(
        id="p",
        name="p",
        base_url=base_url,
        model=model,
        secret_ref="p",
    )


def test_local_qwen_disables_thinking():
    profile = _profile("http://127.0.0.1:1234/v1", "qwen3.8-27b@iq3_xxs")
    messages, extra = apply_thinking_controls(
        profile,
        [{"role": "user", "content": "верни json"}],
        disable_thinking=True,
    )
    assert extra["reasoning_effort"] == "none"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == _THINK_PREFILL


def test_tailscale_and_lan_are_local():
    assert is_local_base_url("http://100.64.0.2:1234/v1") is True
    assert is_local_base_url("http://192.168.1.10:1234/v1") is True
    assert is_local_base_url("http://10.0.0.5:1234/v1") is True
    assert is_local_base_url("https://api.openai.com/v1") is False


def test_default_chat_timeout_local_vs_cloud():
    from paper2data.llm.client import default_chat_timeout

    local = _profile("http://100.64.0.2:1234/v1", "qwen")
    cloud = _profile("https://api.openai.com/v1", "gpt-4o")
    assert default_chat_timeout(local) == 600.0
    assert default_chat_timeout(cloud) == 180.0


def test_salvage_truncated_entities_json():
    from paper2data.llm.client import extract_json_object

    truncated = (
        '```json\n{"entities": ['
        '{"temp_id": "e1", "type": "Layer", "label": "ITO (Device 1)", '
        '"attributes": {"role": "anode"}, "quote": "Device 1: ITO"},'
        '{"temp_id": "e2", "type": "Material", "label": "HAT-CN", '
        '"attributes": {"name": "HAT-CN"}, "quote": "HAT-CN (10 nm)"},'
        '{"temp_id": "e3", "type": "Layer", "label": "broken", "attributes": {'
    )
    parsed = extract_json_object(truncated)
    assert len(parsed["entities"]) == 2
    assert parsed["entities"][0]["label"] == "ITO (Device 1)"
    assert parsed["entities"][1]["type"] == "Material"


def test_cloud_profile_keeps_thinking_controls_off():
    profile = _profile("https://api.openai.com/v1", "gpt-4o")
    messages, extra = apply_thinking_controls(
        profile,
        [{"role": "user", "content": "верни json"}],
        disable_thinking=False,
    )
    assert extra == {}
    assert messages == [{"role": "user", "content": "верни json"}]
    assert is_local_base_url(profile.base_url) is False
    assert is_local_base_url("http://localhost:1234/v1") is True


def test_json_mode_rejection_keeps_reasoning_off():
    payload = {
        "model": "qwen3.8-27b@iq3_xxs",
        "response_format": {"type": "json_object"},
        "reasoning_effort": "none",
        "messages": [
            {"role": "user", "content": "json"},
            {"role": "assistant", "content": _THINK_PREFILL},
        ],
    }
    body = "'response_format.type' must be 'json_schema' or 'text'"
    relaxed = relax_rejected_payload(payload, body)
    assert relaxed is not None
    assert "response_format" not in relaxed
    assert relaxed["reasoning_effort"] == "none"
    assert relaxed["messages"][-1]["content"] == _THINK_PREFILL
