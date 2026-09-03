import base64
import json
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _build_gmail_service(credentials_path: str) -> Any:
    """Build a Gmail client from a mailbox OAuth credential file.

    The Sheets client uses a service account, but a service account is not a
    Gmail mailbox. Without domain-wide delegation it cannot send through
    ``users.messages.send(userId='me')``. Gmail notifications therefore use an
    authorized-user credential containing a refresh token for the sender's
    mailbox (or an allowed From alias).
    """
    with open(credentials_path, encoding="utf-8") as credential_file:
        credential_info = json.load(credential_file)
    if credential_info.get("type") == "service_account":
        raise ValueError(
            "Gmail notifications require mailbox OAuth credentials; a service-account "
            "credential cannot send as a mailbox without domain-wide delegation"
        )
    try:
        creds = Credentials.from_authorized_user_file(
            credentials_path,
            scopes=GMAIL_SCOPES,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Gmail credentials must be an authorized-user OAuth token file"
        ) from exc
    return build("gmail", "v1", credentials=creds)


def _send_email(service, sender: str, to: str, subject: str, body_text: str) -> None:
    """Encode and send a plain-text message through Gmail."""
    message = MIMEText(body_text)
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_queued_email(
    to: str,
    agent: str,
    dataset: str,
    model_name: str,
    job_id: str,
    sender: str,
    gmail_credentials_path: str,
) -> None:
    """Notify a requester that their benchmark has entered the queue."""
    service = _build_gmail_service(gmail_credentials_path)
    subject = f"Benchmark request queued: {agent} / {dataset}"
    body = (
        f"Your benchmark request has been queued.\n\n"
        f"Agent: {agent}\n"
        f"Dataset: {dataset}\n"
        f"Model: {model_name}\n"
        f"Job ID: {job_id}\n"
    )
    _send_email(service, sender, to, subject, body)


def send_completed_email(
    to: str,
    job_id: str,
    sender: str,
    gmail_credentials_path: str,
) -> None:
    """Notify a requester that their benchmark completed and link to results."""
    service = _build_gmail_service(gmail_credentials_path)
    subject = f"Benchmark job completed: {job_id}"
    body = (
        f"Your benchmark job {job_id} has completed.\n\n"
        f"You can view the results on the Coding Agent Leaderboard:\n"
        f"https://huggingface.co/spaces/taagarwa/coding-agent-leaderboard\n"
    )
    _send_email(service, sender, to, subject, body)


def send_failed_email(
    to: str,
    job_id: str,
    error: str,
    sender: str,
    gmail_credentials_path: str,
) -> None:
    """Notify a requester that their benchmark failed and explain how to get help."""
    service = _build_gmail_service(gmail_credentials_path)
    subject = f"Benchmark job failed: {job_id}"
    body = (
        f"Your benchmark job {job_id} has failed.\n\n"
        f"Error: {error}\n\n"
        f"Reply to this email and the team will look into it or help you resubmit.\n"
    )
    _send_email(service, sender, to, subject, body)
