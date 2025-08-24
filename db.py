import asyncpg
import os
from datetime import datetime

# === Default constants ===
DEFAULT_FREE_CREDITS = 200
DEFAULT_PLAN = "Free"
DEFAULT_STATUS = "Free"
DEFAULT_PLAN_EXPIRY = "N/A"
DEFAULT_KEYS_REDEEMED = 0

# === Database URL (use environment variable if available) ===
DB_URL = os.getenv("DATABASE_URL", "postgresql://cardsuser:yourpassword@localhost/cardsdb")

# === Connection helper ===
async def connect():
    return await asyncpg.connect(DB_URL)

# === Initialize DB ===
async def init_db():
    conn = await connect()
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            credits INT DEFAULT {DEFAULT_FREE_CREDITS},
            plan TEXT DEFAULT '{DEFAULT_PLAN}',
            status TEXT DEFAULT '{DEFAULT_STATUS}',
            plan_expiry TEXT DEFAULT '{DEFAULT_PLAN_EXPIRY}',
            keys_redeemed INT DEFAULT {DEFAULT_KEYS_REDEEMED},
            registered_at TEXT,
            custom_url TEXT DEFAULT NULL
        );
    """)
    await conn.close()

# === Get or create user ===
async def get_user(user_id):
    conn = await connect()
    row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if row:
        await conn.close()
        return dict(row)
    else:
        now = datetime.now().strftime('%d-%m-%Y')
        await conn.execute(
            """
            INSERT INTO users (id, credits, plan, status, plan_expiry, keys_redeemed, registered_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            user_id,
            DEFAULT_FREE_CREDITS,
            DEFAULT_PLAN,
            DEFAULT_STATUS,
            DEFAULT_PLAN_EXPIRY,
            DEFAULT_KEYS_REDEEMED,
            now
        )
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        await conn.close()
        return dict(row)

# === Update user fields ===
async def update_user(user_id, **kwargs):
    if not kwargs:
        return
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

# === Get all users ===
async def get_all_users():
    conn = await connect()
    rows = await conn.fetch("SELECT id, plan, custom_url FROM users")
    await conn.close()
    print(f"[DEBUG] Fetched {len(rows)} users from DB")
    return [dict(row) for row in rows]

# === Get total user count ===
async def get_user_count():
    conn = await connect()
    count = await conn.fetchval("SELECT COUNT(*) FROM users")
    await conn.close()
    return count
