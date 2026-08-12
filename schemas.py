from typing import Literal, Annotated
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict, Field


# ---------------АВТОРИЗАЦИЯ---------------
class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str

class UserRead(BaseModel):
    id: int
    email: EmailStr
    username: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"



# ---------------ПРОЕКТЫ---------------
class ProjectCreate(BaseModel):
    name: str = Field(max_length=25)
    description: str = Field(max_length=250)

    
class ProjectRead(BaseModel):
    id: int
    name: str = Field(max_length=25)
    description: str = Field(max_length=250)
    owner_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=25)
    description: str | None = Field(default=None, max_length=250)



# ---------------ТАСКИ---------------
class TaskCreate(BaseModel):
    title: str = Field(max_length=100)
    description: str = Field(max_length=400)
    due_date: datetime
    status: Literal["done", "not done", "in process"] = "not done"
    priority: Literal["low", "medium", "high"] = "medium"


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


class TaskUpdate(BaseModel):
    status: Literal["done", "not done", "in process"] | None = None
    priority: Literal["low", "medium", "high"] | None = None