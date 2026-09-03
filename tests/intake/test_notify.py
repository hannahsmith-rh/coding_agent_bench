import base64
from unittest.mock import MagicMock, patch

from coding_agent_bench.intake.notify import (
    send_queued_email,
    send_completed_email,
    send_failed_email,
)


def _extract_email_body(mock_service: MagicMock) -> str:
    """Decode the plain-text body passed to the mocked Gmail client."""
    call_args = mock_service.users().messages().send.call_args
    raw = call_args[1]["body"]["raw"] if "body" in call_args[1] else call_args[0][0]["body"]["raw"]
    return base64.urlsafe_b64decode(raw).decode()


@patch("coding_agent_bench.intake.notify._build_gmail_service")
def test_send_queued_email_contains_job_details(mock_build):
    """Include request details in the queued notification."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().messages().send.return_value.execute.return_value = {}

    send_queued_email(
        to="user@example.com",
        agent="codex",
        dataset="swe-bench/swe-bench-verified",
        model_name="Qwen/Qwen3-32B",
        job_id="abc-123",
        sender="bench@example.com",
        gmail_credentials_path="/fake/path.json",
    )

    mock_service.users().messages().send.assert_called_once()
    body = _extract_email_body(mock_service)
    assert "codex" in body
    assert "swe-bench/swe-bench-verified" in body
    assert "abc-123" in body


@patch("coding_agent_bench.intake.notify._build_gmail_service")
def test_send_completed_email_contains_job_id(mock_build):
    """Include the job ID and completion state in the completion email."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().messages().send.return_value.execute.return_value = {}

    send_completed_email(
        to="user@example.com",
        job_id="abc-123",
        sender="bench@example.com",
        gmail_credentials_path="/fake/path.json",
    )

    mock_service.users().messages().send.assert_called_once()
    body = _extract_email_body(mock_service)
    assert "abc-123" in body
    assert "completed" in body.lower()


@patch("coding_agent_bench.intake.notify._build_gmail_service")
def test_send_failed_email_contains_error(mock_build):
    """Include the queue error in the failure notification."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().messages().send.return_value.execute.return_value = {}

    send_failed_email(
        to="user@example.com",
        job_id="abc-123",
        error="Pod crashed",
        sender="bench@example.com",
        gmail_credentials_path="/fake/path.json",
    )

    mock_service.users().messages().send.assert_called_once()
    body = _extract_email_body(mock_service)
    assert "abc-123" in body
    assert "Pod crashed" in body
