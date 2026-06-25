"""Integration tests for :mod:`track_aiops.cli`.

Exercises ``main()`` end-to-end with the collaborators (config, observability,
and the Bedrock client) mocked out, so the test asserts the orchestration
contract without making real AWS or Datadog calls:

- the success path prints the response text to stdout and returns exit code 0;
- a missing/invalid prompt prints a usage message to stderr and returns a
  non-zero code;
- ``flush()`` is always called, even when ``traced_llm`` raises.

Requirements: 1.1, 1.2, 1.3, 1.4, 4.4
"""

from types import SimpleNamespace
from unittest.mock import patch

from track_aiops import cli
from track_aiops.bedrock_client import BedrockResponse


def _fake_settings():
    """A minimal stand-in for ``Settings`` with the fields ``main()`` reads."""
    return SimpleNamespace(aws_region="us-east-1", model_id="amazon.nova-pro-v1:0")


# --- Success path -----------------------------------------------------------


def test_main_success_prints_response_and_returns_zero(capsys):
    """The happy path prints the response text to stdout and exits 0.

    Validates: Requirements 1.1, 1.2
    """
    response = BedrockResponse(
        text="hello world",
        usage={"inputTokens": 1, "outputTokens": 2, "totalTokens": 3},
        stop_reason="end_turn",
    )

    with (
        patch("track_aiops.cli.config") as mock_config,
        patch("track_aiops.cli.enable_llmobs") as mock_enable,
        patch("track_aiops.cli.BedrockClient") as mock_client_cls,
        patch("track_aiops.cli.traced_llm", return_value=response) as mock_traced,
        patch("track_aiops.cli.flush") as mock_flush,
    ):
        mock_config.load.return_value = _fake_settings()

        rc = cli.main(["ask", "some prompt"])

    assert rc == 0

    out = capsys.readouterr().out
    assert "hello world" in out

    # The orchestration wired collaborators together as designed.
    mock_config.load.assert_called_once()
    mock_enable.assert_called_once()
    mock_client_cls.assert_called_once_with(
        region="us-east-1", model_id="amazon.nova-pro-v1:0"
    )
    mock_traced.assert_called_once()
    mock_flush.assert_called_once()


# --- Missing / invalid prompt ----------------------------------------------


def test_main_no_args_prints_usage_and_returns_nonzero(capsys):
    """Invoking with no args prints usage to stderr and exits non-zero.

    Validates: Requirements 1.4
    """
    rc = cli.main([])

    assert rc != 0

    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_main_ask_without_prompt_prints_usage_and_returns_nonzero(capsys):
    """``ask`` with no prompt prints usage to stderr and exits non-zero.

    Validates: Requirements 1.4
    """
    rc = cli.main(["ask"])

    assert rc != 0

    err = capsys.readouterr().err
    assert "usage" in err.lower()


# --- flush() always runs ----------------------------------------------------


def test_main_flushes_even_when_traced_llm_raises(capsys):
    """When the invocation fails, ``main()`` returns 1 and still flushes spans.

    Validates: Requirements 1.3, 4.4
    """
    with (
        patch("track_aiops.cli.config") as mock_config,
        patch("track_aiops.cli.enable_llmobs"),
        patch("track_aiops.cli.BedrockClient"),
        patch(
            "track_aiops.cli.traced_llm", side_effect=RuntimeError("boom")
        ),
        patch("track_aiops.cli.flush") as mock_flush,
    ):
        mock_config.load.return_value = _fake_settings()

        rc = cli.main(["ask", "p"])

    assert rc == 1

    # The error was surfaced to stderr and spans were still flushed.
    err = capsys.readouterr().err
    assert "boom" in err
    mock_flush.assert_called_once()
