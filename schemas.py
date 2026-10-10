from typing import Literal
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator


class PasswordInput(BaseModel):
    password: str = Field(min_length=1)

    @field_validator('password')
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value.encode('utf-8')) > 72:
            raise ValueError('Пароль должен занимать не более 72 байт UTF-8')
        return value


class PartialUpdate(BaseModel):
    @field_validator('*')
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError('Поле не может быть null')
        return value


# ---------------АВТОРИЗАЦИЯ---------------
class UserCreate(PasswordInput):
    email: EmailStr
    username: str = Field(min_length=1, max_length=30, pattern=r'\S')
    password: str = Field(min_length=6)

class UserRead(BaseModel):
    id: int
    email: EmailStr
    username: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserLogin(PasswordInput):
    email: EmailStr

class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"



# ---------------ПРОЕКТЫ---------------
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=25, pattern=r'\S')
    description: str = Field(max_length=250)

    
class ProjectRead(BaseModel):
    id: int
    name: str = Field(max_length=25)
    description: str = Field(max_length=250)
    owner_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectUpdate(PartialUpdate):
    name: str | None = Field(default=None, min_length=1, max_length=25, pattern=r'\S')
    description: str | None = Field(default=None, max_length=250)



# ---------------ТАСКИ---------------
class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100, pattern=r'\S')
    description: str = Field(max_length=400)
    due_date: datetime
    status: Literal["done", "not done", "in process"] = "not done"
    priority: Literal["low", "medium", "high"] = "medium"

    @field_validator('due_date')
    @classmethod
    def normalize_due_date(cls, value: datetime) -> datetime:
        # Даты без часового пояса считаем UTC, включая ввод из фронтенда.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TaskRead(BaseModel):
    id: int
    project_id: int
    title: str
    description: str
    due_date: datetime
    status: Literal["done", "not done", "in process"]
    priority: Literal["low", "medium", "high"]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskUpdate(PartialUpdate):
    status: Literal["done", "not done", "in process"] | None = None
    priority: Literal["low", "medium", "high"] | None = None
