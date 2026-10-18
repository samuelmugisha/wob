"""Outgoing email: invitations and password-reset links.

Backends (EMAIL_BACKEND):
  disabled  nothing is sent; admins share the link shown on screen (the default)
  console   messages are written to the API log (local development)
  smtp      any SMTP provider. DigitalOcean blocks ports 25, 465 and 587 on droplets, so use a
            provider that also listens on 2525 (Brevo, Mailgun, Postmark, Resend, SendGrid…)
  memory    kept in OUTBOX (tests only)
"""

import html
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import Settings
from app.models import Role, User

log = logging.getLogger("wob.email")

ROLE_NAMES = {
    Role.ADMIN: "administrator",
    Role.SECRETARIAT: "awards coordinator",
    Role.REVIEWER: "evidence reviewer",
    Role.JUDGE: "judge",
    Role.COMMITTEE: "committee member",
}


class EmailError(Exception):
    pass


@dataclass
class SentEmail:
    to: str
    subject: str
    text: str
    html: str


OUTBOX: list[SentEmail] = []


def enabled(settings: Settings) -> bool:
    return settings.email_backend != "disabled"


def send(settings: Settings, to: str, subject: str, text: str, body_html: str) -> None:
    """Send one message, or raise EmailError. Never logs message bodies (they hold links)."""
    backend = settings.email_backend
    if backend == "disabled":
        raise EmailError("email is not configured (EMAIL_BACKEND=disabled)")
    if backend == "memory":
        if settings.environment == "production":
            raise EmailError("the memory email backend is for tests only")
        OUTBOX.append(SentEmail(to, subject, text, body_html))
        return
    if backend == "console":
        if settings.environment == "production":
            raise EmailError("the console email backend would log secrets in production")
        log.warning("EMAIL (console backend) to=%s subject=%s\n%s", to, subject, text)
        return

    if not settings.smtp_host or not settings.email_from:
        raise EmailError("SMTP_HOST and EMAIL_FROM must be set for EMAIL_BACKEND=smtp")
    message = EmailMessage()
    message["From"] = formataddr((settings.email_from_name, settings.email_from))
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=settings.email_from.split("@")[-1])
    if settings.email_reply_to:
        message["Reply-To"] = settings.email_reply_to
    message.set_content(text)
    message.add_alternative(body_html, subtype="html")

    context = ssl.create_default_context()
    password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
    try:
        if settings.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=20, context=context
            )
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if settings.smtp_security == "starttls":
                server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, password or "")
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("email to %s failed: %s", to, type(exc).__name__)
        raise EmailError(f"the email could not be sent ({type(exc).__name__}: {exc})") from exc


def send_invitation(
    settings: Settings, user: User, link: str, invited_by: User | None, *, reset: bool
) -> None:
    """The set-password email for a new account (reset=False) or a new link (reset=True)."""
    hours = settings.invite_ttl_hours
    role = ROLE_NAMES.get(user.role, user.role.value)
    site = settings.email_site_name
    if reset:
        subject = f"Set a new password for {site}"
        intro = (
            f"A new password link has been created for your {site} account. Your previous "
            "password no longer works, and you have been signed out everywhere."
        )
        action = "Set a new password"
    else:
        subject = f"You're invited to {site}"
        intro = (
            f"{invited_by.display_name} has invited you to {site} as a {role}."
            if invited_by
            else f"You have been invited to {site} as a {role}."
        )
        action = "Create your password"
    closing = (
        f"The link works once and expires in {hours} hours. Don't forward this email: the link "
        "gives access to your account. If you weren't expecting it, you can ignore it."
    )

    text = (
        f"Dear {user.display_name},\n\n{intro}\n\n{action}:\n{link}\n\n{closing}\n\n"
        f"Your sign-in email is {user.email}.\n\n— {settings.email_from_name}\n"
    )
    e = html.escape
    body_html = f"""<!doctype html>
<html><body style="margin:0;background:#f7f2eb;font-family:Arial,Helvetica,sans-serif;color:#2d1b2e">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f2eb;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#fffdf9;border:1px solid #ebe0d1;border-radius:10px">
<tr><td style="background:#3a1340;border-radius:10px 10px 0 0;padding:20px 28px">
<div style="font-family:Georgia,serif;font-size:20px;color:#ffffff">Women on Boards Awards</div>
<div style="font-family:Georgia,serif;font-size:14px;color:#c9a45c">AI-Powered Evaluation and Ranking System</div>
</td></tr>
<tr><td style="padding:28px">
<p style="margin:0 0 14px">Dear {e(user.display_name)},</p>
<p style="margin:0 0 22px;line-height:1.5">{e(intro)}</p>
<p style="margin:0 0 22px"><a href="{e(link)}" style="display:inline-block;background:#9a6c22;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:bold">{e(action)}</a></p>
<p style="margin:0 0 8px;font-size:13px;color:#7a6672">If the button doesn't work, paste this link into your browser:</p>
<p style="margin:0 0 22px;font-size:13px;word-break:break-all"><a href="{e(link)}" style="color:#5e2558">{e(link)}</a></p>
<p style="margin:0 0 8px;font-size:13px;color:#7a6672;line-height:1.5">{e(closing)}</p>
<p style="margin:0;font-size:13px;color:#7a6672">Your sign-in email is {e(user.email)}.</p>
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""
    send(settings, user.email, subject, text, body_html)
