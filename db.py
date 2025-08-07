import asyncpg
import os
from datetime import datetime

DB_URL = os.getenv("DATABASE_URL")

async def connect():
    return await asyncpg.connect(DB_URL)

async def init_db():
    conn = await connect()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            credits INT DEFAULT 30,
            plan TEXT DEFAULT 'Free',
            status TEXT DEFAULT 'Free',
            plan_expiry TEXT DEFAULT 'N/A',
            keys_redeemed INT DEFAULT 0,
            registered_at TEXT
        );
    """)
    await conn.close()

async def get_user(user_id):
    conn = await connect()
    row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if row:
        await conn.close()
        return dict(row)
    else:
        now = datetime.now().strftime('%d-%m-%Y')
        await conn.execute(
            "INSERT INTO users (id, registered_at) VALUES ($1, $2)", user_id, now
        )
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        await conn.close()
        return dict(row)

async def update_user(user_id, **kwargs):
    conn = await connect()
    sets = []
    values = []
    i = 1
    for k, v in kwargs.items():
        sets.append(f"{k} = ${i}")
        values.append(v)
        i += 1
    values.append(user_id)
    await conn.execute(
        f"UPDATE users SET {', '.join(sets)} WHERE id = ${i}", *values
    )
    await conn.close()

async def get_all_users():
    conn = await connect()
    rows = await conn.fetch("SELECT id, plan FROM users")
    await conn.close()
    return [dict(row) for row in rows]
