"""Real authentication flows, with no test bypass (spec §9 bearer auth, §12 access control)."""

import re
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app
from app.models import Role, User
from app.security import accounts
from app.security.auth import SESSION_COOKIE
from tests.conftest import FILE_KEYS

STRONG = "correct-horse-battery-staple"


@pytest.fixture
def settings(engine: Engine, tmp_path):  # noqa: ANN001
    s = get_settings().model_copy(
        update={
            "cookie_secure": False,
            "secret_key": SecretStr("test-secret-key-for-mfa-encryption"),
            "storage_dir": tmp_path / "storage",
            **FILE_KEYS,
            "embedding_provider": "fake",
            "reranker_provider": "fake",
            "mfa_required_roles": ["admin", "committee"],  # whatever the local .env says
            "email_backend": "disabled",
        }
    )
    app.dependency_overrides[get_settings] = lambda: s
    yield s
    app.dependency_overrides.clear()


@pytest.fixture
def client(settings) -> Iterator[TestClient]:  # noqa: ANN001
    yield TestClient(app)


def make_user(engine: Engine, settings, role: str = "secretariat") -> tuple[str, str]:  # noqa: ANN001
    """A new user and their invite token."""
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.org"
    with Session(engine) as session:
        user = User(email=email, display_name=f"Test {role}", role=Role(role))
        session.add(user)
        session.flush()
        link = accounts.create_invite(session, user, None, settings)
        session.commit()
    return email, link.split("token=")[1]


def signed_in(engine, settings, role: str = "secretariat") -> tuple[TestClient, str]:  # noqa: ANN001
    email, token = make_user(engine, settings, role)
    client = TestClient(app)
    response = client.post("/api/v1/auth/accept-invite", json={"token": token, "password": STRONG})
    assert response.status_code == 200, response.text
    return client, email


def test_invitation_sets_password_and_signs_in(client, engine, settings) -> None:
    email, token = make_user(engine, settings)
    weak = client.post("/api/v1/auth/accept-invite", json={"token": token, "password": "short"})
    assert weak.status_code == 400 and weak.json()["detail"]["code"] == "weak_password"
    based_on_email = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": token, "password": email.split("@")[0] + "123!"},
    )
    assert based_on_email.status_code == 400

    response = client.post("/api/v1/auth/accept-invite", json={"token": token, "password": STRONG})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "wob_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/api/v1/me").json()["email"] == email
    assert client.get("/api/v1/categories").status_code == 200

    reuse = TestClient(app).post(
        "/api/v1/auth/accept-invite", json={"token": token, "password": STRONG}
    )
    assert reuse.status_code == 400 and reuse.json()["detail"]["code"] == "invalid_invite"


def test_unauthenticated_requests_are_refused(client) -> None:
    for path in ("/api/v1/me", "/api/v1/categories", "/api/v1/users", "/api/v1/judges-pack"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"
    assert client.get("/api/v1/health").status_code == 200  # monitoring stays open


def test_login_failures_are_uniform_and_lock_the_account(client, engine, settings) -> None:
    _, email = signed_in(engine, settings)
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.org", "password": STRONG}
    )
    wrong = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()  # nothing reveals whether the account exists

    for _ in range(settings.login_max_failures - 1):
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    locked = client.post("/api/v1/auth/login", json={"email": email.upper(), "password": STRONG})
    assert locked.status_code == 401 and locked.json() == wrong.json()

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET locked_until = now() - interval '1 minute' WHERE email = :e"),
            {"e": email},
        )
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": STRONG}).status_code
        == 200
    )
    with engine.connect() as conn:
        actions = (
            conn.execute(
                text(
                    "SELECT action FROM audit_events a JOIN users u ON u.id = a.entity_id "
                    "WHERE u.email = :e ORDER BY a.id"
                ),
                {"e": email},
            )
            .scalars()
            .all()
        )
    assert actions.count("auth.login_failed") == settings.login_max_failures
    assert "auth.login_locked" in actions and actions[-1] == "auth.login"


def test_logout_revokes_the_session(engine, settings) -> None:
    client, _ = signed_in(engine, settings)
    old_cookie = client.cookies.get(SESSION_COOKIE)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 401
    # The old cookie, as a page kept from before signing out would send it, is refused too.
    replay = TestClient(app, cookies={SESSION_COOKIE: old_cookie})
    assert replay.get("/api/v1/me").status_code == 401


def test_bearer_tokens_for_api_clients(engine, settings) -> None:
    _, email = signed_in(engine, settings)
    response = TestClient(app).post(
        "/api/v1/auth/login", json={"email": email, "password": STRONG, "issue_bearer_token": True}
    )
    assert "set-cookie" not in response.headers
    token = response.json()["token"]
    api = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert api.get("/api/v1/me").json()["email"] == email
    assert (
        TestClient(app, headers={"Authorization": "Bearer nonsense"}).get("/api/v1/me").status_code
        == 401
    )
    browser = TestClient(app).post("/api/v1/auth/login", json={"email": email, "password": STRONG})
    assert "token" not in browser.json()  # browsers never see the token in script


def test_idle_sessions_expire(engine, settings) -> None:
    client, email = signed_in(engine, settings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE user_sessions SET last_seen_at = now() - make_interval(mins => :m) "
                "WHERE user_id = (SELECT id FROM users WHERE email = :e)"
            ),
            {"m": settings.session_idle_minutes + 1, "e": email},
        )
    assert client.get("/api/v1/me").status_code == 401


def test_admins_must_set_up_two_factor(engine, settings) -> None:
    admin, email = signed_in(engine, settings, "admin")
    me = admin.get("/api/v1/me").json()
    assert me["mfa_setup_required"] is True
    blocked = admin.get("/api/v1/users")
    assert blocked.status_code == 403 and "mfa_setup_required" in blocked.json()["detail"]

    setup = admin.post("/api/v1/auth/mfa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT mfa_secret_encrypted FROM users WHERE email = :e"), {"e": email}
        ).scalar_one()
    assert setup["secret"] not in stored  # encrypted at rest
    totp = pyotp.TOTP(setup["secret"])
    assert admin.post("/api/v1/auth/mfa/enable", json={"otp": "000000"}).status_code == 400
    assert admin.post("/api/v1/auth/mfa/enable", json={"otp": totp.now()}).status_code == 200
    assert admin.get("/api/v1/users").status_code == 200

    fresh = TestClient(app)
    need = fresh.post("/api/v1/auth/login", json={"email": email, "password": STRONG})
    assert need.status_code == 401 and need.json()["detail"]["code"] == "mfa_required"
    bad = fresh.post(
        "/api/v1/auth/login", json={"email": email, "password": STRONG, "otp": "123456"}
    )
    assert bad.json()["detail"]["code"] == "invalid_otp"
    ok = fresh.post(
        "/api/v1/auth/login", json={"email": email, "password": STRONG, "otp": totp.now()}
    )
    assert ok.status_code == 200


def admin_client(engine, settings) -> TestClient:  # noqa: ANN001
    admin, email = signed_in(engine, settings, "admin")
    secret = admin.post("/api/v1/auth/mfa/setup").json()["secret"]
    admin.post("/api/v1/auth/mfa/enable", json={"otp": pyotp.TOTP(secret).now()})
    return admin


def test_user_administration(engine, settings) -> None:
    admin = admin_client(engine, settings)
    created = admin.post(
        "/api/v1/users",
        json={"email": "Judge.One@example.org", "display_name": "Judge One", "role": "judge"},
    )
    assert created.status_code == 201
    body = created.json()
    assert re.match(r"http://localhost:3000/accept-invite\?token=[\w-]{40,}", body["invite_link"])
    assert body["user"]["has_password"] is False
    duplicate = admin.post(
        "/api/v1/users",
        json={"email": "judge.one@example.org", "display_name": "x", "role": "judge"},
    )
    assert duplicate.status_code == 409

    judge = TestClient(app)
    judge.post(
        "/api/v1/auth/accept-invite",
        json={"token": body["invite_link"].split("token=")[1], "password": STRONG},
    )
    assert judge.get("/api/v1/me").json()["role"] == "judge"
    assert judge.get("/api/v1/users").status_code == 403

    user_id = body["user"]["id"]
    admin.patch(f"/api/v1/users/{user_id}", json={"role": "reviewer"})
    assert judge.get("/api/v1/me").status_code == 401  # role change ends sessions
    relogin = TestClient(app).post(
        "/api/v1/auth/login", json={"email": "judge.one@example.org", "password": STRONG}
    )
    assert relogin.json()["user"]["role"] == "reviewer"

    admin.patch(f"/api/v1/users/{user_id}", json={"is_active": False})
    assert (
        TestClient(app)
        .post("/api/v1/auth/login", json={"email": "judge.one@example.org", "password": STRONG})
        .status_code
        == 401
    )

    admin_id = admin.get("/api/v1/me").json()["id"]
    assert admin.patch(f"/api/v1/users/{admin_id}", json={"role": "judge"}).status_code == 409


def test_reissued_invite_resets_password(engine, settings) -> None:
    admin = admin_client(engine, settings)
    user, email = signed_in(engine, settings, "reviewer")
    user_id = user.get("/api/v1/me").json()["id"]
    link = admin.post(f"/api/v1/users/{user_id}/invite").json()["invite_link"]
    assert user.get("/api/v1/me").status_code == 401
    assert (
        TestClient(app)
        .post("/api/v1/auth/login", json={"email": email, "password": STRONG})
        .status_code
        == 401
    )
    assert (
        TestClient(app)
        .post(
            "/api/v1/auth/accept-invite",
            json={"token": link.split("token=")[1], "password": "another-long-passphrase"},
        )
        .status_code
        == 200
    )


def test_password_change_signs_out_other_sessions(engine, settings) -> None:
    first, email = signed_in(engine, settings)
    second = TestClient(app)
    second.post("/api/v1/auth/login", json={"email": email, "password": STRONG})
    wrong = first.post(
        "/api/v1/auth/password",
        json={"current_password": "nope", "new_password": "a-new-long-passphrase"},
    )
    assert wrong.status_code == 400
    ok = first.post(
        "/api/v1/auth/password",
        json={"current_password": STRONG, "new_password": "a-new-long-passphrase"},
    )
    assert ok.status_code == 204
    assert first.get("/api/v1/me").status_code == 200
    assert second.get("/api/v1/me").status_code == 401


def test_expired_invites_are_refused(client, engine, settings) -> None:
    _, token = make_user(engine, settings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE user_invites SET expires_at = now() - interval '1 second' "
                "WHERE token_hash = :h"
            ),
            {"h": accounts.token_hash(token)},
        )
    response = client.post("/api/v1/auth/accept-invite", json={"token": token, "password": STRONG})
    assert response.status_code == 400


def test_sessions_expire(engine, settings) -> None:
    client, email = signed_in(engine, settings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE user_sessions SET expires_at = now() - interval '1 second' "
                "WHERE user_id = (SELECT id FROM users WHERE email = :e)"
            ),
            {"e": email},
        )
    assert client.get("/api/v1/me").status_code == 401
    assert timedelta(hours=settings.session_ttl_hours) == timedelta(hours=12)
