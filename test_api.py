"""Тесты API на PostgreSQL. Каждый тест работает в собственной временной схеме."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import func, select
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from main import app
from database import Base, Task, UserSession, get_session


# ---------- Тестовая база данных ----------

TEST_DATABASE_URL = os.getenv(
    'TEST_DATABASE_URL',
    'postgresql+asyncpg://task_tracker:task_tracker@127.0.0.1:5432/task_tracker_test',
)


@pytest_asyncio.fixture
async def test_session_factory():
    schema = f'test_{uuid4().hex}'
    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=NullPool,
        execution_options={'schema_translate_map': {None: schema}},
    )
    try:
        async with test_engine.begin() as conn:
            await conn.execute(CreateSchema(schema))
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(test_engine, expire_on_commit=False)
    finally:
        try:
            async with test_engine.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True, if_exists=True))
        finally:
            await test_engine.dispose()


@pytest_asyncio.fixture
async def client(test_session_factory):
    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


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
    async def test_register_duplicate_username(self, client):
        payload = {'email': 'first@example.com', 'username': 'same', 'password': 'password123'}
        assert (await client.post('/auth/register', json=payload)).status_code == 201
        response = await client.post('/auth/register', json={**payload, 'email': 'second@example.com'})
        assert response.status_code == 400

    @pytest.mark.parametrize('password', ['x' * 73, 'я' * 37])
    @pytest.mark.parametrize('path', ['/auth/register', '/auth/login'])
    async def test_password_byte_limit(self, client, path, password):
        response = await client.post(path, json={
            'email': 'limit@example.com', 'username': 'limit', 'password': password,
        })
        assert response.status_code == 422

    async def test_multibyte_password_at_limit(self, client):
        payload = {'email': 'unicode@example.com', 'username': 'unicode', 'password': 'я' * 36}
        assert (await client.post('/auth/register', json=payload)).status_code == 201
        response = await client.post('/auth/login', json=payload)
        assert response.status_code == 200

    @pytest.mark.parametrize('patch', [
        {'username': 'x' * 31}, {'username': '   '}, {'password': '12345'}, {'email': 'invalid'},
    ])
    async def test_invalid_registration(self, client, patch):
        payload = {'email': 'invalid@example.com', 'username': 'valid', 'password': 'password123'}
        response = await client.post('/auth/register', json={**payload, **patch})
        assert response.status_code == 422

    async def test_expired_session(self, client, auth_headers, test_session_factory):
        token = auth_headers['Authorization'].split()[1]
        async with test_session_factory() as session:
            user_session = await session.scalar(select(UserSession).where(UserSession.token == token))
            user_session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()
        assert (await client.get('/projects', headers=auth_headers)).status_code == 401

    async def test_unknown_token(self, client):
        response = await client.get('/projects', headers={'Authorization': 'Bearer unknown'})
        assert response.status_code == 401

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
    async def test_delete_cascades_to_tasks(self, client, auth_headers, test_session_factory):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id)
        assert (await client.delete(f'/projects/{project_id}', headers=auth_headers)).status_code == 200
        async with test_session_factory() as session:
            assert await session.get(Task, task['id']) is None
            assert await session.scalar(select(func.count()).select_from(Task)) == 0

    async def test_delete_project_forbidden(self, client, auth_headers, other_auth_headers):
        project_id = await create_project(client, auth_headers)
        response = await client.delete(f'/projects/{project_id}', headers=other_auth_headers)
        assert response.status_code == 403
        assert (await client.get(f'/projects/{project_id}', headers=auth_headers)).status_code == 200

    @pytest.mark.parametrize('patch', [
        {'name': None}, {'description': None}, {'name': '   '}, {'name': 'x' * 26},
    ])
    async def test_invalid_update_leaves_project_unchanged(self, client, auth_headers, patch):
        project_id = await create_project(client, auth_headers, name='Original')
        response = await client.patch(f'/projects/{project_id}', json=patch, headers=auth_headers)
        assert response.status_code == 422
        response = await client.get(f'/projects/{project_id}', headers=auth_headers)
        assert response.json()['name'] == 'Original'
        assert response.json()['description'] == 'desc'

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
    @pytest.mark.parametrize('due_date, expected', [
        ('2026-08-01T00:00:00', '2026-08-01T00:00:00+00:00'),
        ('2026-08-01T00:00:00Z', '2026-08-01T00:00:00+00:00'),
        ('2026-08-01T05:00:00+05:00', '2026-08-01T00:00:00+00:00'),
    ])
    async def test_due_date_timezone(self, client, auth_headers, due_date, expected):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id, due_date=due_date)
        assert datetime.fromisoformat(task['due_date'].replace('Z', '+00:00')).isoformat() == expected
        response = await client.get(f'/projects/{project_id}/tasks', headers=auth_headers)
        assert response.json()[0]['due_date'] == task['due_date']

    @pytest.mark.parametrize('patch', [
        {'status': None}, {'priority': None}, {'status': 'invalid'}, {'priority': 'invalid'},
    ])
    async def test_invalid_update_leaves_task_unchanged(self, client, auth_headers, patch):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id)
        response = await client.patch(f"/tasks/{task['id']}", json=patch, headers=auth_headers)
        assert response.status_code == 422
        response = await client.get(f'/projects/{project_id}/tasks', headers=auth_headers)
        assert response.json()[0]['status'] == 'not done'
        assert response.json()[0]['priority'] == 'medium'

    async def test_list_tasks_forbidden(self, client, auth_headers, other_auth_headers):
        project_id = await create_project(client, auth_headers)
        response = await client.get(f'/projects/{project_id}/tasks', headers=other_auth_headers)
        assert response.status_code == 403

    async def test_combined_filters(self, client, auth_headers):
        project_id = await create_project(client, auth_headers)
        await create_task(client, auth_headers, project_id, title='Match', status='done', priority='high')
        await create_task(client, auth_headers, project_id, title='Wrong status', priority='high')
        await create_task(client, auth_headers, project_id, title='Wrong priority', status='done')
        response = await client.get(
            f'/projects/{project_id}/tasks?status=done&priority=high', headers=auth_headers,
        )
        assert [task['title'] for task in response.json()] == ['Match']

    async def test_update_changes_timestamp(self, client, auth_headers, test_session_factory):
        project_id = await create_project(client, auth_headers)
        task = await create_task(client, auth_headers, project_id)
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        async with test_session_factory() as session:
            stored_task = await session.get(Task, task['id'])
            stored_task.updated_at = old_time
            await session.commit()
        response = await client.patch(f"/tasks/{task['id']}", json={'status': 'done'}, headers=auth_headers)
        assert response.status_code == 200
        assert datetime.fromisoformat(response.json()['updated_at'].replace('Z', '+00:00')) > old_time

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
