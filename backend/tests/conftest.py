import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import User
from app.security.auth import get_authenticated_user, get_current_user
from app.services.embeddings import HashingEmbedder
from app.services.extraction import Ocr
from app.services.scanning import DisabledScanner
from app.services.storage import build_storage, generate_key
from app.workers.ingest import Pipeline

BACKEND_DIR = Path(__file__).resolve().parents[1]

ClientFactory = Callable[[str], TestClient]

# One file-encryption key for the test session; storage refuses to write plaintext.
FILE_KEYS = {
    "file_encryption_keys": SecretStr(f"t1:{generate_key()}"),
    "file_encryption_active_key": "t1",
}


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    test_url = get_settings().test_database_url
    if not test_url:
        pytest.skip("TEST_DATABASE_URL is not set")

    # Point the app and Alembic at the test database for the whole session.
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()

    engine = create_engine(test_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("test database is not reachable (is `make db-up` running?)")

    # Rebuild from scratch so the downgrade path is exercised too.
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")

    yield engine
    engine.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """A connection whose work is rolled back after each test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


TEST_USER_HEADER = "x-test-user"


def _user_from_header(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    """Each TestClient identifies its own user, so clients of different roles can coexist."""
    user = session.scalar(select(User).where(User.email == request.headers[TEST_USER_HEADER]))
    assert user is not None
    return user


@pytest.fixture
def client_for(engine: Engine, tmp_path: Path) -> Iterator[ClientFactory]:
    """Returns a TestClient acting as a new user with the given role."""
    settings = get_settings().model_copy(
        update={
            "environment": "development",
            "storage_dir": tmp_path / "storage",
            **FILE_KEYS,
            "max_file_bytes": 256 * 1024,
            "embedding_provider": "fake",
            "reranker_provider": "fake",
            "llm_provider": "fake",
            # Test the production defaults whatever the local .env says.
            "mfa_required_roles": ["admin", "committee"],
            "upload_requires_consent": False,
            "email_backend": "disabled",
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_current_user] = _user_from_header
    app.dependency_overrides[get_authenticated_user] = _user_from_header

    def factory(role: str) -> TestClient:
        email = f"{role}-{uuid.uuid4().hex}@example.org"
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (email, display_name, role) VALUES (:e, 'Test', :r)"),
                {"e": email, "r": role},
            )
        return TestClient(app, headers={TEST_USER_HEADER: email})

    yield factory
    app.dependency_overrides.clear()


@pytest.fixture
def coordinator(client_for: ClientFactory) -> TestClient:
    return client_for("secretariat")


@pytest.fixture
def empty_queue(engine: Engine) -> None:
    """Earlier tests leave pending documents behind; take them out of this test's queue."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE documents SET processing_status = 'rejected', next_attempt_at = NULL "
                "WHERE processing_status NOT IN ('indexed', 'rejected')"
            )
        )


@pytest.fixture
def make_pipeline(engine: Engine, tmp_path: Path) -> Callable[..., Pipeline]:
    def factory(scanner=None, **overrides) -> Pipeline:
        settings = get_settings().model_copy(
            update={"storage_dir": tmp_path / "storage", **FILE_KEYS, **overrides}
        )
        return Pipeline(
            sessions=sessionmaker(engine, expire_on_commit=False),
            storage=build_storage(settings),
            scanner=scanner or DisabledScanner(),
            embedder=HashingEmbedder(settings.embedding_dim),
            ocr=Ocr(),
            settings=settings,
        )

    return factory


def drain(pipeline: Pipeline) -> int:
    processed = 0
    while pipeline.run_once():
        processed += 1
    return processed
