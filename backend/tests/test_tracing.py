"""LangSmith tracing sends metadata only: never prompts, outputs or error messages."""

from unittest.mock import MagicMock

import pytest
from langsmith import tracing_context

from app.services.tracing import tag_model, trace_job, trace_llm, usage_metadata

SECRET = "Jane Doe chairs the audit committee"


class Failure(ValueError):
    pass


@trace_llm("claude", lambda result: {"usage_metadata": usage_metadata(result[1])})
def call(system: str, user: str, fail: bool = False) -> tuple[str, dict[str, int]]:
    tag_model("anthropic", "claude-opus-5-5")
    if fail:
        raise Failure(f"could not parse {SECRET}") from KeyError("cause")
    return SECRET, {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50}


@trace_job("job", "run_id")
def job(run_id: str, nominee: str, fail: bool = False) -> str:
    return call("system", nominee, fail)[0]


def sent(client: MagicMock) -> str:
    return " ".join(str(c) for c in client.method_calls)


def test_traces_carry_ids_usage_and_model_but_no_content() -> None:
    client = MagicMock()
    with tracing_context(enabled=True, client=client):
        assert job("run-1", SECRET) == SECRET  # the caller still gets the real result
    traced = sent(client)
    assert SECRET not in traced
    assert "'run_id': 'run-1'" in traced
    assert "'total_tokens': 170" in traced and "'cache_read': 50" in traced
    assert "'ls_model_name': 'claude-opus-5-5'" in traced


def test_errors_reach_the_trace_as_their_type_only() -> None:
    client = MagicMock()
    with tracing_context(enabled=True, client=client), pytest.raises(Failure) as raised:
        job("run-2", SECRET, fail=True)
    # The caller sees the original exception, message and cause.
    assert SECRET in str(raised.value) and isinstance(raised.value.__cause__, KeyError)
    traced = sent(client)
    assert SECRET not in traced and "Failure" in traced


def test_tracing_off_is_a_pass_through() -> None:
    assert job("run-3", SECRET) == SECRET
    with pytest.raises(Failure):
        job("run-4", SECRET, fail=True)
