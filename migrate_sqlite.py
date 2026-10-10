"""Однократный перенос данных из SQLite в пустую PostgreSQL-базу."""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from sqlalchemy import DateTime, func, select, text

from database import Base, engine


def read_sqlite(source: Path) -> dict[str, list[dict]]:
    connection = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        data = {}
        for table in Base.metadata.sorted_tables:
            rows = [dict(row) for row in connection.execute(f'SELECT * FROM "{table.name}"')]
            for row in rows:
                for column in table.columns:
                    if isinstance(column.type, DateTime) and row[column.name] is not None:
                        value = datetime.fromisoformat(row[column.name])
                        row[column.name] = (
                            value.replace(tzinfo=timezone.utc)
                            if value.tzinfo is None else value.astimezone(timezone.utc)
                        )
            data[table.name] = rows
        return data
    finally:
        connection.close()


async def migrate(source: Path):
    try:
        data = read_sqlite(source)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            for table in Base.metadata.sorted_tables:
                await connection.execute(text(f'LOCK TABLE "{table.name}" IN ACCESS EXCLUSIVE MODE'))
            for table in Base.metadata.sorted_tables:
                if await connection.scalar(select(func.count()).select_from(table)):
                    raise RuntimeError('Перенос разрешён только в пустую PostgreSQL-базу')
            for table in Base.metadata.sorted_tables:
                rows = data[table.name]
                if rows:
                    await connection.execute(table.insert(), rows)
                    await connection.execute(
                        text("SELECT setval(pg_get_serial_sequence(:table_name, 'id'), :last_id, true)"),
                        {'table_name': table.name, 'last_id': max(row['id'] for row in rows)},
                    )
        print('Imported:', {name: len(rows) for name, rows in data.items()})
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Путь к старому task_tracker.db')
    asyncio.run(migrate(parser.parse_args().source))
