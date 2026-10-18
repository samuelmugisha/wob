"""Invitation emails: sent on account creation and new links, and reported when they fail."""

import smtplib

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.services import email
from tests.test_auth import admin_client, settings  # noqa: F401 (fixtures)


@pytest.fixture(autouse=True)
def _outbox():
    email.OUTBOX.clear()
    yield
    email.OUTBOX.clear()


def test_new_user_is_emailed_their_link(engine: Engine, settings) -> None:  # noqa: F811
    settings.email_backend = "memory"
    admin = admin_client(engine, settings)

    response = admin.post(
        "/api/v1/users",
        json={"email": "new.judge@example.org", "display_name": "Ada <Judge>", "role": "judge"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email_sent"] is True and body["email_error"] is None

    [message] = email.OUTBOX
    assert message.to == "new.judge@example.org"
    assert message.subject.startswith("You're invited")
    assert body["invite_link"] in message.text and "as a judge" in message.text
    assert "Ada &lt;Judge&gt;" in message.html and "<Judge>" not in message.html

    # A new link is sent as a password reset.
    again = admin.post(f"/api/v1/users/{body['user']['id']}/invite").json()
    assert again["email_sent"] is True
    assert email.OUTBOX[-1].subject.startswith("Set a new password")
    assert again["invite_link"] in email.OUTBOX[-1].text

    with engine.connect() as conn:
        actions = conn.scalars(
            text("SELECT action FROM audit_events WHERE entity_id = :u ORDER BY id"),
            {"u": body["user"]["id"]},
        ).all()
    assert actions.count("auth.invite_emailed") == 2


def test_failed_email_still_returns_the_link(engine: Engine, settings, monkeypatch) -> None:  # noqa: F811
    settings.email_backend = "smtp"
    settings.smtp_host = "smtp.invalid"
    settings.email_from = "awards@example.org"

    def refuse(*args, **kwargs):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    admin = admin_client(engine, settings)
    body = admin.post(
        "/api/v1/users",
        json={"email": "fail@example.org", "display_name": "Fay", "role": "reviewer"},
    ).json()
    assert body["email_sent"] is False
    assert "could not be sent" in body["email_error"]
    assert body["invite_link"].startswith("http")


def test_no_email_when_disabled(engine: Engine, settings) -> None:  # noqa: F811
    settings.email_backend = "disabled"
    body = (
        admin_client(engine, settings)
        .post(
            "/api/v1/users",
            json={"email": "quiet@example.org", "display_name": "Quinn", "role": "judge"},
        )
        .json()
    )
    assert body["email_enabled"] is False and body["email_sent"] is False
    assert email.OUTBOX == []


def test_smtp_uses_starttls_and_login(monkeypatch, settings) -> None:  # noqa: F811
    calls: list = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, message):
            calls.append(("send", message["To"], message["From"], message.is_multipart()))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    configured = settings.model_copy(
        update={
            "email_backend": "smtp",
            "smtp_host": "smtp.example.org",
            "smtp_port": 2525,
            "smtp_username": "apikey",
            "smtp_password": SecretStr("s3cret"),
            "email_from": "awards@example.org",
        }
    )
    email.send(configured, "to@example.org", "Subject", "text", "<p>html</p>")
    assert calls == [
        ("connect", "smtp.example.org", 2525),
        ("starttls",),
        ("login", "apikey", "s3cret"),
        ("send", "to@example.org", "Women on Boards Awards <awards@example.org>", True),
    ]


def test_console_and_memory_backends_are_refused_in_production(settings) -> None:  # noqa: F811
    for backend in ("console", "memory"):
        production = settings.model_copy(
            update={"environment": "production", "email_backend": backend}
        )
        with pytest.raises(email.EmailError):
            email.send(production, "to@example.org", "s", "t", "h")
