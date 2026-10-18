"""The real SDK path for research, against replayed streams with server tool blocks."""

import base64
import json

import anthropic
import httpx2

from app.config import get_settings
from app.services.research.llm import AnthropicResearchLLM
from tests import fixture_files

OUTPUT = {"findings": [], "not_found": [], "identity_concerns": []}


def event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def stream(blocks: list[dict], stop_reason: str) -> bytes:
    out = [
        event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 500, "output_tokens": 1},
                },
            },
        )
    ]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            out.append(
                event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": i,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )
            out.append(
                event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "text_delta", "text": block["text"]},
                    },
                )
            )
        elif block["type"] == "server_tool_use":
            out.append(
                event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": i,
                        "content_block": {**block, "input": {}},
                    },
                )
            )
            out.append(
                event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(block["input"]),
                        },
                    },
                )
            )
        else:
            out.append(
                event(
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": block},
                )
            )
        out.append(event("content_block_stop", {"type": "content_block_stop", "index": i}))
    out.append(
        event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 200},
            },
        )
    )
    out.append(event("message_stop", {"type": "message_stop"}))
    return "".join(out).encode()


def fetch_result(tool_id: str, url: str, source: dict) -> dict:
    return {
        "type": "web_fetch_tool_result",
        "tool_use_id": tool_id,
        "content": {
            "type": "web_fetch_result",
            "url": url,
            "retrieved_at": "2026-10-01T09:30:00Z",
            "content": {"type": "document", "source": source, "title": "Page"},
        },
    }


FIRST = [
    {
        "type": "server_tool_use",
        "id": "srv_1",
        "name": "web_search",
        "input": {"query": "Jane Doe Example Holdings audit committee"},
    },
    {
        "type": "web_search_tool_result",
        "tool_use_id": "srv_1",
        "content": [
            {
                "type": "web_search_result",
                "url": "https://example-holdings.com/board",
                "title": "Board",
                "encrypted_content": "abc",
                "page_age": None,
            }
        ],
    },
    {
        "type": "server_tool_use",
        "id": "srv_2",
        "name": "web_fetch",
        "input": {"url": "https://example-holdings.com/board"},
    },
    fetch_result(
        "srv_2",
        "https://example-holdings.com/board",
        {
            "type": "text",
            "media_type": "text/plain",
            "data": "Jane Doe chairs the Audit Committee.",
        },
    ),
    {
        "type": "server_tool_use",
        "id": "srv_3",
        "name": "web_fetch",
        "input": {"url": "https://example-holdings.com/annual-report.pdf"},
    },
    fetch_result(
        "srv_3",
        "https://example-holdings.com/annual-report.pdf",
        {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(fixture_files.pdf_with_structure()).decode(),
        },
    ),
]


def test_tool_loop_resumes_paused_turns_and_collects_pages() -> None:
    requests: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            payload = stream(FIRST, "pause_turn")
        else:
            payload = stream([{"type": "text", "text": json.dumps(OUTPUT)}], "end_turn")
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=payload)

    client = anthropic.Anthropic(
        api_key="test",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    settings = get_settings().model_copy(
        update={"research_enabled": True, "llm_provider": "anthropic"}
    )
    result = AnthropicResearchLLM(settings, client=client).research("SYSTEM", "USER")

    first, second = requests
    tools = {t["name"]: t for t in first["tools"]}
    assert tools["web_search"]["type"] == "web_search_20250305"
    assert tools["web_fetch"]["type"] == "web_fetch_20250910"
    assert "linkedin.com" in tools["web_search"]["blocked_domains"]
    assert tools["web_search"]["user_location"] == {"type": "approximate", "country": "UG"}
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["fallbacks"] == "default"
    # The paused turn is resent as-is, with no extra user message.
    assert [m["role"] for m in second["messages"]] == ["user", "assistant"]
    assert second["messages"][1]["content"][0]["type"] == "server_tool_use"

    assert result.searches == 1
    assert [p.url for p in result.pages] == [
        "https://example-holdings.com/board",
        "https://example-holdings.com/annual-report.pdf",
    ]
    assert result.pages[0].text == "Jane Doe chairs the Audit Committee."
    assert "Nomination statement" in result.pages[1].text  # PDF text extracted locally
    assert result.usage == {"input_tokens": 1000, "output_tokens": 400}
