"""
Тесты для FastAPI-бэкенда таск-трекера.

Как запускать:
    pip install pytest pytest-asyncio httpx aiosqlite
    pytest -v

Тесты используют отдельную in-memory SQLite базу (не трогают твой
task_tracker.db) и подменяют dependency get_session на тестовую сессию.
Перед КАЖДЫМ тестом база пересоздаётся с нуля (fixture prepare_database,
autouse=True) — тесты не мешают друг другу и порядок запуска не важен.

Если имена твоих файлов отличаются от main.py / database.py / routers.py —
поправь импорты ниже под свою структуру.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_session


# ---------- Тестовая база данных ----------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# StaticPool обязателен для in-memory SQLite: без него каждая новая сессия
# открывала бы СВОЮ отдельную пустую базу, и таблицы "терялись" бы между
# запросами внутри одного теста.
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


async def override_get_session():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest_asyncio.fixture(autouse=True)
async def prepare_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Вспомогательные fixtures для авторизации ----------

@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict:
    await client.post("/auth/register", json={
        "email": "alice@example.com",
        "username": "alice",
        "password": "strongpassword123",
    })
    response = await client.post("/auth/login", json={
        "email": "alice@example.com",
        "password": "strongpassword123",
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def other_auth_headers(client: AsyncClient) -> dict:
    await client.post("/auth/register", json={
        "email": "bob@example.com",
        "username": "bob",
        "password": "strongpassword456",
    })
    response = await client.post("/auth/login", json={
        "email": "bob@example.com",
        "password": "strongpassword456",
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def create_project(client: AsyncClient, headers: dict, name: str = "Project") -> int:
    response = await client.post(
        "/projects", json={"name": name, "description": "desc"}, headers=headers
    )
    return response.json()["id"]


async def create_task(client: AsyncClient, headers: dict, project_id: int, **overrides) -> dict:
    payload = {
        "title": "Task",
        "description": "desc",
        "due_date": "2026-08-01T00:00:00",
    }
    payload.update(overrides)
    response = await client.post(f"/projects/{project_id}/tasks", json=payload, headers=headers)
    return response.json()


# ---------- Авторизация ----------

class TestAuth:
    async def test_register_success(self, client):
        response = await client.post("/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "password123",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"
        assert "hashed_password" not in data
        assert "password" not in data

    async def test_register_duplicate_email(self, client):
        payload = {"email": "dup@example.com", "username": "dup1", "password": "password123"}
        await client.post("/auth/register", json=payload)

        response = await client.post("/auth/register", json={**payload, "username": "dup2"})
        assert response.status_code == 400

    async def test_login_success(self, client):
        await client.post("/auth/register", json={
            "email": "login@example.com", "username": "loginuser", "password": "password123",
        })
        response = await client.post("/auth/login", json={
            "email": "login@example.com", "password": "password123",
        })
        assert response.status_code == 200
        assert "access_token" in response.json()

    async def test_login_wrong_password(self, client):
        await client.post("/auth/register", json={
            "email": "wrongpass@example.com", "username": "wronguser", "password": "password123",
        })
        response = await client.post("/auth/login", json={
            "email": "wrongpass@example.com", "password": "totallywrong",
        })
        assert response.status_code == 401

    async def test_login_unknown_email(self, client):
        response = await client.post("/auth/login", json={
            "email": "ghost@example.com", "password": "whatever123",
        })
        assert response.status_code == 401

    async def test_logout_invalidates_token(self, client, auth_headers):
        response = await client.post("/auth/logout", headers=auth_headers)
        assert response.status_code == 200

        response = await client.get("/projects", headers=auth_headers)
        assert response.status_code == 401


# ---------- Проекты ----------

class TestProjects:
    async def test_create_and_read_back(self, client, auth_headers):
        response = await client.post(
            "/projects", json={"name": "My project", "description": "desc"}, headers=auth_headers
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My project"
        assert "id" in data  # ловит баг с отсутствующим id в ProjectRead

    async def test_create_project_requires_auth(self, client):
        response = await client.post("/projects", json={"name": "X", "description": "d"})
        # HTTPBearer без заголовка Authorization отдаёт 403, а не 401 — так устроен FastAPI
        assert response.status_code in (401, 403)

    async def test_list_returns_only_own_projects(self, client, auth_headers, other_auth_headers):
        await create_project(client, auth_headers, name="Alice project")
        await create_project(client, other_auth_headers, name="Bob project")

        response = await client.get("/projects", headers=auth_headers)
        names = [p["name"] for p in response.json()]
        assert "Alice project" in names
        assert "Bob project" not in names

    async def test_get_by_id_not_found(self, client, auth_headers):
        response = await client.get("/projects/99999", headers=auth_headers)
        assert response.status_code == 404

    async def test_get_by_id_forbidden_for_other_user(self, client, auth_headers, other_auth_headers):
        project_id = await create_project(client, auth_headers, name="Secret")

        response = await client.get(f"/projects/{project_id}", headers=other_auth_headers)
        assert response.status_code == 403

    async def test_update_project(self, client, auth_headers):
        project_id = await create_project(client, auth_headers, name="Old name")

        response = await client.patch(
            f"/projects/{project_id}", json={"name": "New name"}, headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New name"

    async def test_update_forbidden_for_other_user(self, client, auth_headers, other_auth_headers):
        project_id = await create_project(client, auth_headers)

        response = await client.patch(
            f"/projects/{project_id}", json={"name": "Hacked"}, headers=other_auth_headers
        )
        assert response.status_code == 403

    async def test_delete_project(self, client, auth_headers):
        project_id = await create_project(client, auth_headers, name="To delete")

        response = await client.delete(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200

        response = await client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 404


# ---------- Таски ----------

class TestTasks:
    async def test_create_task_defaults(self, client, auth_headers):
        project_id = await create_project(client, auth_headers)

        task = await create_task(client, auth_headers, project_id)
        assert task["status"] == "not done"
        assert task["priority"] == "medium"
        assert task["project_id"] == project_id

    async def test_create_task_forbidden_for_other_user(self, client, auth_headers, other_auth_headers):
        project_id = await create_project(client, auth_headers)

        response = await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "T", "description": "d", "due_date": "2026-08-01T00:00:00"},
            headers=other_auth_headers,
        )
        assert response.status_code == 403

    async def test_filter_by_status(self, client, auth_headers):
        project_id = await create_project(client, auth_headers)
        await create_task(client, auth_headers, project_id, title="Done task", status="done")
        await create_task(client, auth_headers, project_id, title="Pending task", status="not done")

        response = await client.get(f"/projects/{project_id}/tasks?status=done", headers=auth_headers)
        titles = [t["title"] for t in response.json()]
        assert titles == ["Done task"]

    async def test_filter_by_priority(self, client, auth_headers):
        project_id = await create_project(client, auth_headers)
        await create_task(client, auth_headers, project_id, title="Urgent", priority="high")
        await create_task(client, auth_headers, project_id, title="Whenever", priority="low")

        response = await client.get(f"/projects/{project_id}/tasks?priority=high", headers=auth_headers)
        titles = [t["title"] for t in response.json()]
        assert titles == ["Urgent"]

    async def test_list_tasks_scoped_to_project(self, client, auth_headers):
        project_a = await create_project(client, auth_headers, name="A")
        project_b = await create_project(client, auth_headers, name="B")
        await create_task(client, auth_headers, project_a, title="Task in A")
        await create_task(client, auth_headers, project_b, title="Task in B")

        response = await client.get(f"/projects/{project_a}/tasks", headers=auth_headers)
        titles = [t["title"] for t in response.json()]
        assert titles == ["Task in A"]

    async def test_update_task_partial(self, client, auth_headers):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id)

        response = await client.patch(
            f"/tasks/{task['id']}", json={"status": "done"}, headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        assert data["priority"] == "medium"  # не должно затереться, раз не передавали

    async def test_update_task_forbidden_for_other_user(self, client, auth_headers, other_auth_headers):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id)

        response = await client.patch(
            f"/tasks/{task['id']}", json={"status": "done"}, headers=other_auth_headers
        )
        assert response.status_code == 403

    async def test_delete_task(self, client, auth_headers):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id)

        response = await client.delete(f"/tasks/{task['id']}", headers=auth_headers)
        assert response.status_code == 200

        response = await client.patch(
            f"/tasks/{task['id']}", json={"status": "done"}, headers=auth_headers
        )
        assert response.status_code == 404

    async def test_delete_task_forbidden_for_other_user(self, client, auth_headers, other_auth_headers):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id)

        response = await client.delete(f"/tasks/{task['id']}", headers=other_auth_headers)
        assert response.status_code == 403