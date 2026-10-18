"""The real Anthropic SDK code path, against a replayed streaming response (no API key needed)."""

import json

import anthropic
import httpx2
import pytest

from app.config import get_settings
from app.services.claims.llm import (
    AnthropicClaimLLM,
    ExtractionLLMError,
    ExtractionRefused,
    OutputTruncated,
    request_options,
)

OUTPUT = {
    "claims": [
        {
            "statement": "Jane Doe has chaired the audit committee of Example Holdings since 2019.",
            "claim_type": "position",
            "entity": "Example Holdings",
            "role": "Audit committee chair",
            "period_start": "2019",
            "period_end": None,
            "period_text": "since 2019",
            "quantitative_outcomes": [],
            "supporting_evidence": [{"passage_id": "P1", "quote": "chaired the audit committee"}],
            "contradicting_evidence": [],
            "limitations": None,
        }
    ],
    "contradictions": [],
    "missing_information": ["No board appointment letter is provided."],
}


def sse(stop_reason: str = "end_turn", text: str | None = None, stop_details=None) -> bytes:
    body = json.dumps(OUTPUT) if text is None else text
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 1200,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": body[:40]},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": body[40:]},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                    "stop_details": stop_details,
                },
                "usage": {"output_tokens": 350},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events).encode()


def make_llm(handler) -> AnthropicClaimLLM:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicClaimLLM("claude-opus-5-5", "high", 64000, client=client)


def streaming(body: bytes) -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def test_request_shape_and_parsed_output() -> None:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return streaming(sse())

    result = make_llm(handler).extract("SYSTEM", "USER")

    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    schema = body["output_config"]["format"]["schema"]
    assert "claims" in schema["properties"]
    assert body["system"] == "SYSTEM"
    assert body["messages"] == [{"role": "user", "content": "USER"}]

    assert result.served_by == "claude-opus-5-5"
    assert result.output.claims[0].period_start == "2019"
    assert result.output.missing_information == ["No board appointment letter is provided."]
    assert result.usage["input_tokens"] == 1200
    assert result.usage["output_tokens"] == 350


def test_refusal_is_reported() -> None:
    llm = make_llm(
        lambda r: streaming(
            sse(
                stop_reason="refusal",
                text="",
                stop_details={"type": "refusal", "category": "cyber", "explanation": None},
            )
        )
    )
    with pytest.raises(ExtractionRefused, match="cyber"):
        llm.extract("S", "U")


def test_truncated_output() -> None:
    llm = make_llm(lambda r: streaming(sse(stop_reason="max_tokens", text='{"claims": [')))
    with pytest.raises(OutputTruncated):
        llm.extract("S", "U")


def test_overload_is_retryable_and_bad_request_is_not() -> None:
    overloaded = make_llm(
        lambda r: httpx2.Response(
            529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
        )
    )
    with pytest.raises(ExtractionLLMError) as info:
        overloaded.extract("S", "U")
    assert info.value.retryable

    bad = make_llm(
        lambda r: httpx2.Response(
            400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "no"}}
        )
    )
    with pytest.raises(ExtractionLLMError) as info:
        bad.extract("S", "U")
    assert not info.value.retryable


def test_openrouter_request_pins_routing_and_drops_server_fallback() -> None:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return streaming(sse())

    settings = get_settings().model_copy(update={"llm_provider": "openrouter"})
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    llm = AnthropicClaimLLM(
        settings.llm_model,
        "high",
        64000,
        client=client,
        provider="openrouter",
        options=request_options(settings),
    )
    result = llm.extract("SYSTEM", "USER")

    body = seen["body"]
    assert llm.model_id == "openrouter:anthropic/claude-opus-5.5"
    assert body["model"] == "anthropic/claude-opus-5.5"
    assert "fallbacks" not in body
    assert "server-side-fallback" not in seen["headers"].get("anthropic-beta", "")
    assert body["provider"] == {
        "only": ["anthropic"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert result.output.claims[0].period_start == "2019"
