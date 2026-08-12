# Task Tracker API

Backend для трекера задач на FastAPI: пользователи, проекты и задачи с авторизацией и проверкой прав доступа.

## Стек
- FastAPI
- SQLAlchemy (async, aiosqlite)
- Pydantic
- SQLite
- Pytest (тесты)

## Возможности
- Регистрация и логин пользователей
- Авторизация через сессионный токен (хранится в таблице sessions)
- CRUD для проектов и задач
- Проверка владения (403, если чужой проект/задача)
- Фильтрация задач по статусу и приоритету
- Простой фронтенд на vanilla HTML/CSS/JS (папка `frontend`)

## Структура проекта
task_tracker/
├── main.py # точка входа
├── database.py # модели и подключение к БД
├── routers.py # эндпоинты
├── schemas.py # Pydantic-схемы
├── test_api.py # тесты
├── frontend/ # HTML/CSS/JS клиент
└── requirements.txt

## Установка и запуск

1. Клонировать репозиторий и перейти в папку проекта
2. Создать и активировать виртуальное окружение:
```bash
python -m venv venv
venv\Scripts\activate
```
3. Установить зависимости:
```bash
pip install -r requirements.txt
```
4. Запустить сервер:
```bash
uvicorn main:app --reload
```
5. Открыть `frontend/index.html` (например, через Live Server в VS Code)

## Тесты
```bash
pytest
```