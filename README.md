# Task Tracker

Простой учебный трекер задач на FastAPI и PostgreSQL. Можно зарегистрироваться,
создавать проекты и задачи, менять статус и приоритет, фильтровать задачи.
Каждый пользователь видит только свои проекты. Фронтенд — обычные HTML, CSS и JS.

## Запуск

Нужны Python 3.10+ и Docker Desktop (либо свой PostgreSQL).
Команды ниже — для PowerShell из папки проекта.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d --wait
python -m uvicorn main:app --reload
```

Адрес API: http://127.0.0.1:8000. Документация: http://127.0.0.1:8000/docs.
Таблицы создаются при запуске. Подключение задаётся в `.env` через `DATABASE_URL`.
Если PostgreSQL уже установлен, создай базу и укажи свои данные подключения
в формате `postgresql+asyncpg://user:password@host:5432/database`.
Docker в таком случае не нужен.

В другом терминале запусти фронтенд:

```powershell
.\venv\Scripts\python.exe -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Открой http://127.0.0.1:5500. Токен хранится в памяти страницы: после обновления
нужно войти заново. Если адрес API другой, поменяй `API_BASE` в `frontend/script.js`.
Для другого адреса фронтенда обнови `allow_origins` в `main.py`.

Остановить PostgreSQL: `docker compose stop`. Данные сохраняются в Docker volume.

## Старые данные SQLite

Если остался `task_tracker.db`, его можно перенести в **пустую** PostgreSQL-базу.
Сначала подними PostgreSQL и настрой `.env`, затем до запуска API выполни:

```powershell
python migrate_sqlite.py task_tracker.db
```

Скрипт сохраняет id, пользователей, хеши паролей, проекты, задачи и сессии.
Исходный SQLite-файл остаётся на месте. Повторный перенос в заполненную базу запрещён.
Даты без часового пояса считаются UTC; новые даты тоже хранятся в UTC.

## Тесты

Тесты используют настоящий PostgreSQL. Для базы из Docker один раз выполни:

```powershell
docker compose exec db createdb -U task_tracker task_tracker_test
```

Затем:

```powershell
python -m pytest -q
```

Подключение для тестов задаётся через `TEST_DATABASE_URL` в `.env`.
Каждый тест создаёт и удаляет свою временную схему; пользователь базы должен
иметь право создавать схемы. Рабочая база приложения в тестах не используется.

Если установлен Node.js, логику фронтенда можно проверить без браузера:

```powershell
node --test test_frontend.cjs
```

## Файлы

- `main.py` — запуск приложения.
- `database.py` — модели и подключение к PostgreSQL.
- `routers.py` — авторизация, проекты и задачи.
- `schemas.py` — проверка входных данных и ответы API.
- `frontend/` — интерфейс.
- `test_api.py` — тесты API.
- `test_frontend.cjs` — проверки логики фронтенда.
- `migrate_sqlite.py` — перенос старых данных.
