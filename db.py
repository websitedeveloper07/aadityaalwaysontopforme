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
            custom_urls JSONB DEFAULT '[]',
            serp_key TEXT UNIQUE   -- 👈 per-user SERP key (must be unique)
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
            json.dumps([])
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
            sets.append(f"{k} = ${i}::jsonb")
            values.append(json.dumps(v))
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
    rows = await conn.fetch("SELECT id, plan, custom_urls, serp_key FROM users")
    await conn.close()
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

# === SERP key functions ===
async def set_serp_key(user_id: int, serp_key: str) -> bool:
    """
    Save a SERP key for a user.
    Returns True if success, False if the key already belongs to another user.
    """
    conn = await connect()
    try:
        # Ensure the user exists
        row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
        if not row:
            now = datetime.now().strftime('%d-%m-%Y')
            await conn.execute(
                """
                INSERT INTO users (
                    id, credits, plan, status, plan_expiry, keys_redeemed, registered_at, custom_urls, serp_key
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                """,
                user_id,
                DEFAULT_FREE_CREDITS,
                DEFAULT_PLAN,
                DEFAULT_STATUS,
                DEFAULT_PLAN_EXPIRY,
                DEFAULT_KEYS_REDEEMED,
                now,
                json.dumps([]),
                serp_key
            )
        else:
            await conn.execute("UPDATE users SET serp_key = $1 WHERE id = $2", serp_key, user_id)

        await conn.close()
        return True
    except Exception as e:
        await conn.close()
        if "unique" in str(e).lower():
            return False
        raise

async def get_serp_key(user_id: int):
    conn = await connect()
    row = await conn.fetchrow("SELECT serp_key FROM users WHERE id = $1", user_id)
    await conn.close()
    return row["serp_key"] if row and row["serp_key"] else None

async def delete_serp_key(user_id: int) -> bool:
    """
    Remove a user's serp_key.
    Returns True if a key was deleted, False if no key existed.
    """
    conn = await connect()
    row = await conn.fetchrow("SELECT serp_key FROM users WHERE id = $1", user_id)
    if not row or not row["serp_key"]:
        await conn.close()
        return False
    await conn.execute("UPDATE users SET serp_key = NULL WHERE id = $1", user_id)
    await conn.close()
    return True

# Alias (optional, for compatibility with your older clear_serp_key usage)
clear_serp_key = delete_serp_key

async def serp_key_exists(serp_key: str, exclude_user: int = None) -> bool:
    conn = await connect()
    if exclude_user:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE serp_key = $1 AND id <> $2",
            serp_key, exclude_user
        )
    else:
        row = await conn.fetchrow("SELECT id FROM users WHERE serp_key = $1", serp_key)
    await conn.close()
    return bool(row)
