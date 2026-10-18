"""Accounts, passwords, TOTP and sessions (spec §9 bearer auth, §12 access control).

Tokens (sessions, invitations) are random 256-bit values; only their SHA-256 is stored.
Passwords use Argon2id. TOTP secrets are encrypted with a key derived from SECRET_KEY.
"""

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User, UserInvite, UserSession
from app.services import audit

_hasher = PasswordHasher()
# Verifying against this keeps the response time the same for unknown emails.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")
ISSUER = "WOB Awards 2026"
# One message for every login failure, so responses never reveal whether an account exists
# or is locked.
LOGIN_FAILED = (
    "email or password is incorrect (accounts lock for a while after repeated failed attempts)"
)


class AuthError(Exception):
    """`code` is safe to show to the client; messages never reveal whether an email exists."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def now() -> datetime:
    return datetime.now(UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


# --- Passwords ---------------------------------------------------------------------------------


def password_problem(password: str, user: User, settings: Settings) -> str | None:
    if len(password) < settings.password_min_length:
        return f"use at least {settings.password_min_length} characters"
    if len(password) > 256:
        return "use at most 256 characters"
    lowered = password.lower()
    if user.email.lower().split("@")[0] in lowered or lowered in user.email.lower():
        return "don't base the password on your email address"
    if len(set(password)) < 5:
        return "use a less repetitive password"
    return None


def set_password(user: User, password: str, settings: Settings) -> None:
    problem = password_problem(password, user, settings)
    if problem:
        raise AuthError("weak_password", problem)
    user.password_hash = _hasher.hash(password)
    user.password_set_at = now()
    user.failed_logins = 0
    user.locked_until = None


def check_password(user: User | None, password: str) -> bool:
    try:
        _hasher.verify(user.password_hash if user and user.password_hash else _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return bool(user and user.password_hash)


# --- TOTP --------------------------------------------------------------------------------------


def _fernet(settings: Settings) -> Fernet:
    if settings.secret_key is None:
        raise RuntimeError("SECRET_KEY must be set to use two-factor authentication")
    digest = hashlib.sha256(b"wob-mfa:" + settings.secret_key.get_secret_value().encode())
    return Fernet(base64.urlsafe_b64encode(digest.digest()))


def _totp(user: User, settings: Settings) -> pyotp.TOTP:
    try:
        secret = _fernet(settings).decrypt(user.mfa_secret_encrypted.encode()).decode()
    except (InvalidToken, AttributeError) as exc:
        raise AuthError("mfa_unavailable", "two-factor setup is invalid; ask an admin") from exc
    return pyotp.TOTP(secret)


def start_mfa_setup(user: User, settings: Settings) -> tuple[str, str]:
    """A new secret (not yet active) and its otpauth:// URI for authenticator apps."""
    if user.mfa_enabled:
        raise AuthError("mfa_enabled", "two-factor authentication is already on")
    secret = pyotp.random_base32()
    user.mfa_secret_encrypted = _fernet(settings).encrypt(secret.encode()).decode()
    return secret, pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)


def verify_otp(user: User, code: str, settings: Settings) -> bool:
    code = (code or "").replace(" ", "")
    return bool(code.isdigit() and _totp(user, settings).verify(code, valid_window=1))


def enable_mfa(session: Session, user: User, code: str, settings: Settings) -> None:
    if not user.mfa_secret_encrypted:
        raise AuthError("mfa_not_started", "start two-factor setup first")
    if not verify_otp(user, code, settings):
        raise AuthError("invalid_otp", "that code is not valid; check your device's clock")
    user.mfa_enabled = True
    audit.record(session, user, "auth.mfa_enabled", "user", user.id)


def mfa_required(user: User, settings: Settings) -> bool:
    return user.role.value in settings.mfa_required_roles


# --- Login and sessions ------------------------------------------------------------------------


def authenticate(
    session: Session,
    email: str,
    password: str,
    otp: str | None,
    settings: Settings,
    ip: str | None,
) -> User:
    user = session.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower()).with_for_update()
    )
    if user and user.locked_until and user.locked_until > now():
        audit.record(session, user, "auth.login_locked", "user", user.id, ip=ip)
        raise AuthError("invalid_credentials", LOGIN_FAILED)
    if not check_password(user, password) or not user.is_active:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.login_max_failures:
                user.locked_until = now() + timedelta(minutes=settings.lockout_minutes)
                user.failed_logins = 0
        audit.record(
            session,
            user,
            "auth.login_failed",
            "user",
            user.id if user else None,
            email=email.strip().lower()[:200],
            ip=ip,
        )
        raise AuthError("invalid_credentials", LOGIN_FAILED)
    if user.mfa_enabled:
        if not otp:
            raise AuthError("mfa_required", "enter the code from your authenticator app")
        if not verify_otp(user, otp, settings):
            user.failed_logins += 1
            audit.record(session, user, "auth.otp_failed", "user", user.id, ip=ip)
            raise AuthError("invalid_otp", "that code is not valid")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now()
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    return user


def create_session(
    session: Session,
    user: User,
    settings: Settings,
    *,
    kind: str = "browser",
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, datetime]:
    token, hashed = new_token()
    lifetime = (
        timedelta(days=settings.api_token_ttl_days)
        if kind == "api"
        else timedelta(hours=settings.session_ttl_hours)
    )
    expires = now() + lifetime
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hashed,
            kind=kind,
            expires_at=expires,
            ip_address=ip,
            user_agent=(user_agent or "")[:300],
        )
    )
    audit.record(session, user, "auth.login", "user", user.id, kind=kind, ip=ip)
    return token, expires


def resolve_session(session: Session, token: str, settings: Settings) -> User | None:
    record = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    current = now()
    if record is None or record.revoked_at or record.expires_at <= current:
        return None
    if record.kind == "browser" and (
        current - record.last_seen_at > timedelta(minutes=settings.session_idle_minutes)
    ):
        record.revoked_at = current
        session.commit()
        return None
    user = session.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    if current - record.last_seen_at > timedelta(minutes=1):
        record.last_seen_at = current
        session.commit()
    return user


def revoke_token(session: Session, token: str) -> None:
    session.execute(
        update(UserSession)
        .where(UserSession.token_hash == token_hash(token), UserSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )


def revoke_all_sessions(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )


# --- Invitations -------------------------------------------------------------------------------


def create_invite(session: Session, user: User, created_by: User | None, settings: Settings) -> str:
    """A one-time link for the user to set their password; earlier unused links stop working."""
    session.execute(
        update(UserInvite)
        .where(
            UserInvite.user_id == user.id,
            UserInvite.used_at.is_(None),
            UserInvite.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )
    token, hashed = new_token()
    session.add(
        UserInvite(
            user_id=user.id,
            token_hash=hashed,
            created_by=created_by.id if created_by else None,
            expires_at=now() + timedelta(hours=settings.invite_ttl_hours),
        )
    )
    audit.record(session, created_by, "auth.invite_created", "user", user.id)
    return f"{settings.public_base_url.rstrip('/')}/accept-invite?token={token}"


def accept_invite(session: Session, token: str, password: str, settings: Settings) -> User:
    invite = session.scalar(
        select(UserInvite).where(UserInvite.token_hash == token_hash(token)).with_for_update()
    )
    if invite is None or invite.used_at or invite.revoked_at or invite.expires_at <= now():
        raise AuthError("invalid_invite", "this link is invalid or has expired; ask for a new one")
    user = session.get_one(User, invite.user_id)
    if not user.is_active:
        raise AuthError("invalid_invite", "this link is invalid or has expired; ask for a new one")
    set_password(user, password, settings)
    invite.used_at = now()
    revoke_all_sessions(session, user.id)
    audit.record(session, user, "auth.invite_accepted", "user", user.id)
    return user
