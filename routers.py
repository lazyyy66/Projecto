from typing import Literal, Annotated
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
import bcrypt
import secrets
from database import SessionDep, User, Project, Task, UserSession

from schemas import (
    UserCreate, UserRead, UserLogin, TokenRead,
    ProjectCreate, ProjectRead, ProjectUpdate,
    TaskCreate, TaskRead, TaskUpdate,
)

bearer_scheme = HTTPBearer()
SESSION_LIFETIME = timedelta(days=7)

async def get_current_user(
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),):
    token = credentials.credentials

    user_session = await session.scalar(
        select(UserSession).where(UserSession.token == token))

    if not user_session or user_session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "Невалидный или истёкший токен")
    
    user = await session.get(User, user_session.user_id)
    if not user:
        raise HTTPException(401, "Пользователь не найден")

    return user

CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_owned_project(project_id: int, session: SessionDep, current_user: CurrentUser) -> Project:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    if project.owner_id != current_user.id:
        raise HTTPException(403, "Нет доступа к этому проекту")
    return project

OwnedProject = Annotated[Project, Depends(get_owned_project)]


async def get_owned_task(task_id: int, session: SessionDep, current_user: CurrentUser) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Таск не найден")

    project = await session.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(403, "Нет доступа к этому таску")

    return task

OwnedTask = Annotated[Task, Depends(get_owned_task)]



router = APIRouter()

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())



# ---------------АВТОРИЗАЦИЯ---------------
@router.post(
        "/auth/register",
        tags=["Авторизация"],
        response_model=UserRead, 
        status_code=201)
async def register(data: UserCreate, session: SessionDep):
    is_exists = await session.scalar(select(User).where(User.email == data.email))
    if is_exists:
        raise HTTPException(400, "Email занят")

    if await session.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(400, "Имя пользователя занято")

    user = User(
        email=data.email,
        username=data.username,
        hashed_password=await run_in_threadpool(hash_password, data.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(400, "Email или имя пользователя заняты")
    await session.refresh(user)
    return user



@router.post(
        "/auth/login", 
        tags=["Авторизация"],
        response_model=TokenRead)
async def login(data: UserLogin, session: SessionDep):
    user = await session.scalar(select(User).where(User.email == data.email))
    if not user or not await run_in_threadpool(verify_password, data.password, user.hashed_password):
        raise HTTPException(401, "Неверный Email или пароль")

    token = secrets.token_hex(32)
    user_session = UserSession(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + SESSION_LIFETIME,)
    
    session.add(user_session)
    await session.commit()

    return TokenRead(access_token=token)


@router.post(
        "/auth/logout",
        tags=["Авторизация"])
async def logout(session: SessionDep, credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    user_session = await session.scalar(
        select(UserSession).where(UserSession.token == credentials.credentials))
    
    if user_session:
        await session.delete(user_session)
        await session.commit()
    return {"success": True}



# ---------------ПРОЕКТЫ---------------
@router.post("/projects", tags=["Проекты"], response_model=ProjectRead, status_code=201)
async def create_project(data: ProjectCreate, session: SessionDep, current_user: CurrentUser):
    project = Project(
        name=data.name,
        description=data.description,
        owner_id=current_user.id,
        )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("/projects", tags=["Проекты"], response_model=list[ProjectRead])
async def get_projects(session: SessionDep, current_user: CurrentUser):
    projects = await session.scalars(select(Project).where(Project.owner_id == current_user.id).order_by(Project.id))
    return projects.all()


@router.get("/projects/{project_id}", tags=["Проекты"], response_model=ProjectRead)
async def get_project_by_id(project: OwnedProject):
    return project


@router.patch("/projects/{project_id}", tags=["Проекты"], response_model=ProjectRead)
async def update_project(project: OwnedProject, data: ProjectUpdate, session: SessionDep):
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)
    await session.commit()
    await session.refresh(project)
    return project


@router.delete("/projects/{project_id}", tags=["Проекты"])
async def delete_project(project: OwnedProject, session: SessionDep):
    await session.delete(project)
    await session.commit()
    return {"success": True}



# ---------------ТАСКИ---------------
@router.post("/projects/{project_id}/tasks", tags=["таски"], response_model=TaskRead, status_code=201)
async def create_task(project: OwnedProject, data: TaskCreate, session: SessionDep):
    task = Task(project_id=project.id, **data.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.get("/projects/{project_id}/tasks", tags=["таски"], response_model=list[TaskRead])
async def get_tasks(
    project: OwnedProject,
    session: SessionDep,
    status: Literal["done", "not done", "in process"] | None = None,
    priority: Literal["low", "medium", "high"] | None = None,):
    query = select(Task).where(Task.project_id == project.id).order_by(Task.id)
    if status is not None:
        query = query.where(Task.status == status)
    if priority is not None:
        query = query.where(Task.priority == priority)

    tasks = await session.scalars(query)
    return tasks.all()


@router.patch("/tasks/{task_id}", tags=["таски"], response_model=TaskRead)
async def update_task(task: OwnedTask, data: TaskUpdate, session: SessionDep):
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task, key, value)
    await session.commit()
    await session.refresh(task)
    return task


@router.delete("/tasks/{task_id}", tags=["таски"])
async def delete_task(task: OwnedTask, session: SessionDep):
    await session.delete(task)
    await session.commit()
    return {"success": True}
