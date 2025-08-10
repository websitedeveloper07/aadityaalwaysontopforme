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
AUTHORIZATION_CONTACT = "@enough69s"
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

# --- User Data & Credits Functions ---
def get_user_from_db(user_id):
    """Fetches or initializes user data from the in-memory 'database'."""
    if user_id not in USER_DATA_DB:
        USER_DATA_DB[user_id] = {
            'credits': DEFAULT_FREE_CREDITS,
            'plan': 'Free',
            'status': 'Free',
            'plan_expiry': 'N/A',
            'keys_redeemed': 0,
            'registered_at': datetime.now().strftime('%d-%m-%Y')
        }
    return USER_DATA_DB.get(user_id)
    
async def consume_credit(user_id):
    user_data = await get_user(user_id)
    if user_data and user_data.get('credits', 0) > 0:
        await update_user(user_id, credits=user_data['credits'] - 1)
        return True
    return False


async def add_credits_to_user(user_id, amount):
    user_data = await get_user(user_id)
    if not user_data:
        return None  # or raise an exception / handle as needed
    current_credits = user_data.get('credits', 0)
    new_credits = current_credits + amount
    await update_user(user_id, credits=new_credits)
    return new_credits


import aiohttp
import logging

logger = logging.getLogger(__name__)

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
                "Use /plans to upgrade or join our group to access tools for free\\.\n"
                "Get a subscription from @enough69s to use this bot\\.",
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
                "Please contact @enough69s to get approved\\.",
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
    
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command, displaying user info and main menu."""
    user = update.effective_user
    logger.info(f"/start called by user: {user.id} (@{user.username})")

    indian_timezone = pytz.timezone('Asia/Kolkata')
    now = datetime.now(indian_timezone).strftime('%I:%M %p')
    today = datetime.now(indian_timezone).strftime('%d-%m-%Y')

    user_data = await get_user(user.id)
    credits = user_data.get('credits', 0)
    plan = user_data.get('plan', 'Free')

    # Escape all values for MarkdownV2
    escaped_user_id = escape_markdown_v2(str(user.id))
    escaped_username = escape_markdown_v2(user.username or 'N/A')
    escaped_today = escape_markdown_v2(today)
    escaped_now = escape_markdown_v2(now)
    escaped_credits = escape_markdown_v2(str(credits))
    escaped_plan = escape_markdown_v2(plan)

    welcome_message = (
        f"👋 *Welcome to 𝓒𝓪𝓻d𝓥𝓪𝒖𝓵𝒕𝑿* ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 𝙄𝘿: `{escaped_user_id}`\n"
        f"👤 𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚: @{escaped_username}\n"
        f"📅 𝘿𝙖𝙩𝙚: `{escaped_today}`\n"
        f"🕒 𝙏𝙞𝙢𝙚: `{escaped_now}`\n"
        f"💳 𝘾𝙧𝙚𝙙𝙞𝙩𝙨: `{escaped_credits}`\n"
        f"📋 𝙋𝙡𝙖𝙣: `{escaped_plan}`\n\n"
        f"𝓤𝓼𝓮 𝓽𝓱𝓮 𝓫𝓾𝓽𝓽𝓸𝓷𝓼 𝓫𝓮𝓵𝓸𝔀 𝓽𝓸 𝓰𝓮𝓽 𝓼𝓽𝓪𝓻𝓽𝓮𝓭 👇"
    )

    keyboard = [
        [
            InlineKeyboardButton("🛠 Tools", callback_data="tools_menu"),
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
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Error editing message: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )




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
        "╰━━━━━━━━━━━━━━━━━━⬣"
    )
    await update.effective_message.reply_text(help_message, parse_mode=ParseMode.MARKDOWN_V2)


async def show_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the list of tools and their status."""
    query = update.callback_query
    await query.answer()
    tools_message = (
        "*✦ All Commands ✦*\n"
        "All commands are live, `Online`, and have `100%` health\\.\n"
        "• `/gen <BIN>` \\- Generates 10 cards\n"
        "• `/fk <country>` \\- Generates fake info\n"
        "• `/fl <dump>` \\- Extracts cards from dumps\n"
        "• `/credits` \\- Shows your credits\n"
        "• `/bin <BIN>` \\- Performs BIN lookup\n"
        "• `/status` \\- Checks bot health\n"
        "• `/info` \\- Shows your info\n"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(tools_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main callback handler for all inline keyboard buttons."""
    query = update.callback_query
    await query.answer()
    if query.data == "tools_menu":
        await show_tools_menu(update, context)
    elif query.data == "back_to_start":
        await start(update, context)



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
    """Generates cards from a given BIN."""
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

    # Get BIN input
    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.effective_message and update.effective_message.text:
        command_text = update.effective_message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]

    if not bin_input or not bin_input.isdigit() or len(bin_input) != 6:
        return await update.effective_message.reply_text(
            "❌ Please provide a valid 6\\-digit BIN\\. Usage: `/gen [bin]` or `\\.gen [bin]`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # BIN lookup
    bin_details = await get_bin_details(bin_input)
    brand = bin_details["scheme"]
    bank = bin_details["bank"]
    country_name = bin_details["country_name"]
    country_emoji = bin_details["country_emoji"]

    # Generate cards
    cards = []
    while len(cards) < 10:
        card_length = 15 if brand.lower() in ["american express", "amex"] else 16
        suffix_len = card_length - len(bin_input)
        card_number = bin_input + ''.join(str(random.randint(0, 9)) for _ in range(suffix_len))

        if not luhn_checksum(card_number):
            continue

        mm = str(random.randint(1, 12)).zfill(2)
        yyyy = str(datetime.now().year + random.randint(1, 5))

        cvv = (
            str(random.randint(0, 9999)).zfill(4)
            if brand.lower() in ["american express", "amex"]
            else str(random.randint(0, 999)).zfill(3)
        )

        cards.append(f"`{card_number}|{mm}|{yyyy[-2:]}|{cvv}`")

    cards_list = "\n".join(cards)  # Don't escape cards to preserve monospace

    # Escape fields safely
    escaped_bin = escape_markdown_v2(bin_input)
    escaped_brand = escape_markdown_v2(brand)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country_name = escape_markdown_v2(country_name)
    escaped_country_emoji = escape_markdown_v2(country_emoji)

    # BIN Info block (minimalist)
    bin_info_block = (
        f"┣ ❏ 𝐁𝐈𝐍        ➳ `{escaped_bin}`\n"
        f"┣ ❏ 𝐁𝐫𝐚𝐧𝐝      ➳ `{escaped_brand}`\n"
        f"┣ ❏ 𝐁𝐚𝐧𝐤       ➳ `{escaped_bank}`\n"
        f"┣ ❏ 𝐂𝐨𝐮𝐧𝐭𝐫𝐲    ➳ `{escaped_country_name}`{escaped_country_emoji}\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    # Final output message
    final_message = (
        f"> *Generated 10 Cards 💳*\n\n"
        f"{cards_list}\n"
        f">\n"
        f"> {bin_info_block.replace(chr(10), '\n> ')}"
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
        f"┣ ❏ *𝐁𝐨𝐭 𝐛𝐲*       ➳ kคli liຖนxx\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    final_message = f"{bin_info_box}\n\n{user_info_box}"

    await update.effective_message.reply_text(
        final_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )

import time
import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

# This function is not needed anymore as we are using standard MarkdownV2
# formatting and the official escape function.
# def format_stylish_text(text):
#     """Converts text to a specific stylish, bolded italic Unicode font."""
#     # ... (code removed)
#     return formatted_text

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Beast /chk: processing box -> BIN lookup + Darkboy API -> edit to final box.
        Blocks private usage unless authorized, shows subscription message if blocked.
    """
    # Block private usage unless authorized
    if update.effective_chat.type == "private":
        if not await check_authorization(update, context):
            return await update.effective_message.reply_text(
                "❌ Private access is blocked\\.\n"
                "Contact @YourOwnerUsername to buy subscription\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

    user = update.effective_user
    user_id = user.id

    # Enforce cooldown
    if not await enforce_cooldown(user_id, update):
        return

    # Load user data
    user_data = await get_user(user_id)
    if user_data.get('credits', 0) <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Parse card input
    raw = None
    if context.args:
        raw = context.args[0]
    elif update.effective_message and update.effective_message.text:
        parts = update.effective_message.text.split(maxsplit=1)
        raw = parts[1] if len(parts) > 1 else None

    if not raw or "|" not in raw:
        return await update.effective_message.reply_text(
            "Usage: /chk number\\|mm\\|yy\\|cvv",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    parts = raw.split("|")
    if len(parts) != 4:
        return await update.effective_message.reply_text(
            "Invalid format\\. Use number\\|mm\\|yy\\|cvv \\(or yyyy for year\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Normalize year to 2 digits
    if len(parts[2]) == 4:
        parts[2] = parts[2][-2:]
    cc_normalized = "|".join(parts)

    # BIN lookup
    bin_number = parts[0][:6]
    bin_details = await get_bin_details(bin_number)
    # Handle the case where antipublic.cc returns None
    if bin_details is None:
        bin_details = {}
    brand = (bin_details.get("scheme") or "N/A").upper()
    issuer = (bin_details.get("type") or "N/A").upper()
    country_name = (bin_details.get("country_name") or "N/A").upper()

    # Deduct credit
    if not await consume_credit(user_id):
        return await update.effective_message.reply_text(
            "❌ No credits left\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Processing box
    processing_text = (
        "═══\\[ 𝑷𝑹𝑶𝑪𝑬𝑺𝑺𝑰𝑵𝑮 \\]═══\n"
        f"• 𝘾𝙖𝙧𝙙 ➜ `{cc_normalized}`\n"
        "• 𝙂𝙖𝙩𝙚𝙬𝙖𝙮 ➜ 𝓢𝘁𝗿𝗶𝗽𝗲 𝘈𝘂𝘁𝗵\n"
        "• 𝙎𝙩𝙖𝙩𝙪𝙨 ➜ 𝑪𝒉𝒆𝒄𝒌𝒊𝒏𝒈\\.\\.\\.\n"
        "═════════════════════"
    )
    processing_msg = await update.effective_message.reply_text(
        processing_text,
        parse_mode=ParseMode.MARKDOWN_V2
    )

    start_time = time.time()

    # Darkboy API call
    api_url = f"https://darkboy-auto-stripe.onrender.com/gateway=autostripe/key=darkboy/site=buildersdiscountwarehouse.com.au/cc={cc_normalized}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=25) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()
    except Exception as e:
        return await processing_msg.edit_text(
            f"❌ API Error: `{escape_markdown(str(e), version=2)}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    api_status = (data.get("status") or "Unknown").title()
    api_response = data.get("response") or "N/A"
    time_taken = round(time.time() - start_time, 2)

    # Final headers and text with MarkdownV2 for formatting
    if api_status.lower() == "approved":
        header = "❖❖❖\\[ 𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗 ✅ \\]❖❖❖"
    elif api_status.lower() == "declined":
        header = "❖❖❖\\[ 𝗗𝗘𝗖𝗟𝗜𝗡𝗘𝗗 ❌ \\]❖❖❖"
    else:
        header = f"❖❖❖\\[ {escape_markdown(api_status, version=2)} \\]❖❖❖"
    
    # Use MarkdownV2 italic syntax `_text_` for the response
    formatted_response = f"_{escape_markdown(api_response, version=2)}_"

    final_text = (
        f"{header}\n"
        f"✘ Card        ➜ `{cc_normalized}`\n"
        "✘ Gateway     ➜ 𝓢𝘁𝗿𝗶𝗽𝗲 𝘈𝘂𝘁𝗵\n"
        f"✘ Response    ➜ {formatted_response}\n"
        "――――――――――――――――\n"
        f"✘ Brand       ➜ {escape_markdown(brand, version=2)}\n"
        f"✘ Issuer      ➜ {escape_markdown(issuer, version=2)}\n"
        f"✘ Country    ➜ {escape_markdown(country_name, version=2)}\n"
        "――――――――――――――――\n"
        f"✘ Request By  ➜ {escape_markdown(user.first_name, version=2)}\\[{escape_markdown(user_data.get('plan','Free'), version=2)}\\]\n"
        "✘ Developer   ➜ kคli liຖนxx\n"
        f"✘ Time        ➜ {escape_markdown(str(time_taken), version=2)} seconds\n"
        "――――――――――――――――"
    )

    await processing_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN_V2)

import time
import aiohttp
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import Application, CommandHandler, ContextTypes

# Placeholder functions that must be implemented for the bot to run.
# You will need to fill in the actual logic for these.
async def check_authorization(update, context):
    """Placeholder to check if a user is authorized. Always returns True for this example."""
    return True

async def enforce_cooldown(user_id, update):
    """Placeholder to enforce a cooldown on the command."""
    return True

async def get_user(user_id):
    """Placeholder to get user data from a database or storage."""
    return {"credits": 100}  # Example user with 100 credits

async def consume_credit(user_id):
    """Placeholder to consume one credit from a user."""
    return True

async def get_bin_details(bin_number):
    """Placeholder to get BIN details from an external API."""
    return {} # Example placeholder

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks multiple cards on the same API with a detailed summary at the end."""

    # Block private usage unless authorized
    if update.effective_chat.type == "private":
        if not await check_authorization(update, context):
            return await update.effective_message.reply_text(
                "❌ Private access is blocked.\n"
                "Contact @YourOwnerUsername to buy subscription.",
                parse_mode=None
            )

    user = update.effective_user
    user_id = user.id

    # Enforce cooldown for batch command
    if not await enforce_cooldown(user_id, update):
        return

    raw_cards = ""
    if context.args:
        raw_cards = ' '.join(context.args)
    elif update.effective_message.reply_to_message and update.effective_message.reply_to_message.text:
        raw_cards = update.effective_message.reply_to_message.text

    if not raw_cards:
        return await update.effective_message.reply_text(
            "Usage: /mchk number|mm|yy|cvv",
            parse_mode=None
        )

    # Use a regex to find all valid card formats
    card_pattern = re.compile(r"(\d{13,16}\|\d{1,2}\|(?:\d{2}|\d{4})\|\d{3,4})")
    card_lines = card_pattern.findall(raw_cards)

    if not card_lines:
        return await update.effective_message.reply_text(
            "Invalid format. Please provide at least one card in the format: number|mm|yy|cvv.",
            parse_mode=None
        )
    
    cards_to_check = card_lines
    if len(card_lines) > 10:
        await update.effective_message.reply_text("⚠️ Only 10 cards are allowed. Checking the first 10 now.")
        cards_to_check = card_lines[:10]
    
    total_cards = len(cards_to_check)
    approved_count, declined_count, error_count, checked_count = 0, 0, 0, 0
    
    processing_text = "Processing..."
    processing_msg = await update.effective_message.reply_text(processing_text, parse_mode=None)
    
    start_time = time.time()
    results = []
    
    for i, raw in enumerate(cards_to_check):
        user_data = await get_user(user_id)
        if user_data.get('credits', 0) <= 0:
            results.append("❌ Out of credits.")
            error_count += 1
            break
            
        parts = raw.split("|")
        # Normalize year to 2 digits
        if len(parts[2]) == 4:
            parts[2] = parts[2][-2:]
        cc_normalized = "|".join(parts)

        # Deduct credit
        if not await consume_credit(user_id):
            results.append(f"❌ Failed to deduct credit for card {raw}.")
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
            
            current_time_taken = round(time.time() - start_time, 2)
            current_summary = escape_markdown(
                f"✧ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
                f"✧ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
                f"✧ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
                f"✧ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
                f"✧ 𝐄𝐫𝐫𝐨𝐫𝐬↣{error_count}\n"
                f"✧ 𝐓𝐢𝐦𝐞↣{current_time_taken} 𝐒\n"
                f"\n𝗠𝗮𝘀𝘀 𝗖𝗵�𝗰𝗸\n"
                f"──────── ⸙ ─────────", version=2
            )
            current_results = "\n──────── ⸙ ─────────\n".join(results)
            await processing_msg.edit_text(current_summary + "\n\n" + current_results, parse_mode=ParseMode.MARKDOWN_V2)
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
        current_summary = escape_markdown(
            f"✧ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
            f"✧ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
            f"✧ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
            f"✧ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
            f"✧ 𝐄𝐫𝐫𝐨𝐫𝐬↣{error_count}\n"
            f"✧ 𝐓𝐢𝐦𝐞↣{current_time_taken} 𝐒\n"
            f"\n𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸\n"
            f"──────── ⸙ ─────────", version=2
        )
        current_results_str = "\n──────── ⸙ ─────────\n".join(results)
        await processing_msg.edit_text(current_summary + "\n\n" + current_results_str, parse_mode=ParseMode.MARKDOWN_V2)

    final_time_taken = round(time.time() - start_time, 2)
    final_summary = escape_markdown(
        f"✧ 𝐓𝐨𝐭𝐚𝐥↣{total_cards}\n"
        f"✧ 𝐂𝐡𝐞𝐜𝐤𝐞𝐝↣{checked_count}\n"
        f"✧ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝↣{approved_count}\n"
        f"✧ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝↣{declined_count}\n"
        f"✧ 𝐄𝐫𝐫𝐨𝐫𝐬↣{error_count}\n"
        f"✧ 𝐓𝐢𝐦𝐞↣{final_time_taken} 𝐒"
        f"\n\n𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸\n"
        f"──────── ⸙ ─────────", version=2
    )
    
    final_text = final_summary + "\n\n" + "\n──────── ⸙ ─────────\n".join(results) + "\n──────── ⸙ ─────────"
    await processing_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN_V2)



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
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
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
