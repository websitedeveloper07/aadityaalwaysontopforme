import asyncpg
import os
import json
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
            custom_urls JSONB DEFAULT '[]'
        );
    """)
    await conn.close()

# === Normalize JSONB fields ===
def normalize_json_field(value):
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return []
    if isinstance(value, list):
        return value
    return []

# === Get or create user ===
async def get_user(user_id):
    conn = await connect()
    row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if row:
        await conn.close()
        user_data = dict(row)
        user_data["custom_urls"] = normalize_json_field(user_data.get("custom_urls"))
        return user_data
    else:
        now = datetime.now().strftime('%d-%m-%Y')
        # Insert new user with JSONB casting
        await conn.execute(
            """
            INSERT INTO users (
                id, credits, plan, status, plan_expiry, keys_redeemed, registered_at, custom_urls
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            """,
            user_id,
            DEFAULT_FREE_CREDITS,
            DEFAULT_PLAN,
            DEFAULT_STATUS,
            DEFAULT_PLAN_EXPIRY,
            DEFAULT_KEYS_REDEEMED,
            now,
            []  # Python list is cast to JSONB
        )
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        await conn.close()
        user_data = dict(row)
        user_data["custom_urls"] = []
        return user_data

# === Update user fields ===
async def update_user(user_id, **kwargs):
    if not kwargs:
        return
    conn = await connect()
    sets = []
    values = []
    i = 1
    for k, v in kwargs.items():
        if k == "custom_urls":
            # cast custom_urls to JSONB
            sets.append(f"{k} = ${i}::jsonb")
        else:
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
    rows = await conn.fetch("SELECT id, plan, custom_urls FROM users")
    await conn.close()
    print(f"[DEBUG] Fetched {len(rows)} users from DB")
    result = []
    for row in rows:
        r = dict(row)
        r["custom_urls"] = normalize_json_field(r.get("custom_urls"))
        result.append(r)
    return result

# === Get total user count ===
async def get_user_count():
    conn = await connect()
    count = await conn.fetchval("SELECT COUNT(*) FROM users")
    await conn.close()
    return count
