import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="linguascene-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["CACHE_BACKEND"] = "memory"
os.environ["AI_PROVIDER"] = "mock"
os.environ["ALLOW_PUBLIC_REGISTRATION"] = "true"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_EMAIL"] = "admin@linguascene.app"
os.environ["ADMIN_PASSWORD"] = "admin12345"
os.environ["SPEECH_PREWARM"] = "false"
os.environ["LOCAL_ASR"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client: TestClient, username: str, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth_client(client):
    suffix = uuid.uuid4().hex[:8]
    token = _register(
        client, f"tester{suffix}", f"tester{suffix}@example.com", "tester12345"
    )
    client.headers.update(_auth_headers(token))
    return client


@pytest.fixture
def admin_user(client):
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        return db.execute(
            select(User).where(User.email == settings.admin_email)
        ).scalar_one()
    finally:
        db.close()


@pytest.fixture
def admin_client(client):
    from app.core.config import settings

    response = client.post(
        "/api/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    assert response.status_code == 200, response.text
    client.headers.update(_auth_headers(response.json()["access_token"]))
    return client
