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
DEFAULT_FREE_CREDITS = 50  # A non-expiring credit pool for free users

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

    welcome_message = (
        f"╭━━━[ 𝙒𝙀𝙇𝘾𝙊𝙈𝙀 𝙏𝙊 𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝓵𝓽ₓ ]━━━⬣\n"
        f"┣ ❏ 𝐈𝐃        ➳ `{user.id}`\n"
        f"┣ ❏ 𝐔𝐬𝐞𝐫𝐧𝐚𝐦𝐞  ➳ `@{escape_markdown(user.username or 'N/A', version=2)}`\n"
        f"┣ ❏ 𝐃𝐚𝐭𝐞      ➳ `{today}`\n"
        f"┣ ❏ 𝐓𝐢𝐦𝐞      ➳ `{now}`\n"
        f"┣ ❏ 𝐂𝐫𝐞𝐝𝐢𝐭𝐬   ➳ `{credits}`\n"
        f"┣ ❏ 𝐏𝐥𝐚𝐧      ➳ `{escape_markdown(plan, version=2)}`\n"
        f"╰━━━━━━━━━━━━━━━━━━━━⬣\n\n"
        f"_Use the buttons below to get started_"
    )

    keyboard = [
        [
            InlineKeyboardButton("💀 Killers", callback_data="killers_menu"),
            InlineKeyboardButton("🛠 Tools", callback_data="tools_menu")
        ],
        [
            InlineKeyboardButton("🧾 Plans", callback_data="plans_menu"),
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
        "┣ ❏ `/kill <cc|mm|yy|cvv>` \\-  kill a card\n"
        "┣ ❏ `/fk <country>` \\- Generate fake identity info\n"
        "┣ ❏ `/fl <dump>` \\- Extracts cards from dumps\n"
        "┣ ❏ `/status` \\- Bot system status info\n"
        "┣ ❏ `/credits` \\- Check your remaining credits\n"
        "┣ ❏ `/plans` \\- Check available subscription plans\n"
        "┣ ❏ `/info` \\- Shows your user info\n"
        "╰━━━━━━━━━━━━━━━━━━⬣"
    )
    await update.effective_message.reply_text(help_message, parse_mode=ParseMode.MARKDOWN_V2)

async def show_killers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the detailed Killer menu."""
    query = update.callback_query
    await query.answer()
    killer_message = (
        "╭━━━〔 𝐊𝟏𝐋𝐋𝐄𝐑 𝗚𝗔𝗧𝗘𝗦 – 𝓒𝓪𝓻d𝓥𝓪𝒖𝒍𝒕𝑿 〕━━━╮\n"
        "│ 🛠 Status: 𝘼𝙘𝙩𝙞𝙫𝙚 ✅\n"
        "│ 👑 Owner: @enough69s\n"
        "│ ⚙️ Mode: 𝙆𝟭𝙇𝙇𝙀𝙍 𝙀𝙉𝙂𝙄𝙉𝙀\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "🔹 𝗩𝗜𝗦𝗔 𝗢𝗡𝗟𝗬 𝗚𝗔𝗧𝗘\n"
        "┗ 📛 Name: `Standard K1LL`\n"
        "┗ 💬 Command: `/kill cc|mm|yy|cvv`\n"
        "┗ 🧾 Format: `CC\\|MM\\|YY\\|CVV`\n"
        "┗ 🟢 Status: `Online`\n"
        "┗ 📅 Updated: `03 Aug 2025`\n"
        "┗ 🕐 Avg Time: `45s`\n"
        "┗ 💉 Health: `95%`\n"
        "┗ 📝 Note: Only for Visa\n\n"
        "🔸 𝗠𝗔𝗦𝗧𝗘𝗥 𝗚𝗔𝗧𝗘\n"
        "┗ 📛 Name: `Advanced K1LL`\n"
        "┗ 💬 Command: `/kmc cc|mm|yy|cvv`\n"
        "┗ 🧾 Format: `CC\\|MM\\|YY\\|CVV`\n"
        "┗ ❌ Status: `Offline`\n"
        "┗ 📅 Updated: `06 Aug 2025`\n"
        "┗ 🕐 Avg Time: `65s`\n"
        "┗ 💉 Health: `20%`\n"
        "┗ 📝 Note: Only MasterCard supported\n\n"
        "📊 Total Gates: `2`"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        killer_message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def show_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the list of tools and their status."""
    query = update.callback_query
    await query.answer()
    tools_message = (
        "*✦ All Commands ✦*\n"
        "All commands are live, `Online`, and have `100%` health\\.\n"
        "For MasterCard and Visa, different messages will be shown for prepaid bins\\.\n\n"
        "• `/gen <BIN>` \\- Generates 10 cards\n"
        "• `/fk <country>` \\- Generates fake info\n"
        "• `/fl <dump>` \\- Extracts cards from dumps\n"
        "• `/credits` \\- Shows your credits\n"
        "• `/bin <BIN>` \\- Performs BIN lookup\n"
        "• `/status` \\- Checks bot health\n"
        "• `/info` \\- Shows your info\n"
        "• `/plans` \\- Shows subscription plans"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(tools_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

async def show_plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the detailed bot plans."""
    query = update.callback_query
    if query:
        await query.answer()
    plans_message = (
        "📦 *𝓒𝓪𝓻d𝓥𝓪𝒖𝒍𝒕𝑿 Subscription Plans*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔹 *Starter Plan*\n"
        "• Access: `Full Access`\n"
        "• Duration: `7 Days`\n"
        "• Credits: `300`\n"
        "• Price: `₹219`\n\n"
        "🥈 *Premium Plan*\n"
        "• Access: `Full Access`\n"
        "• Duration: `30 Days`\n"
        "• Credits: `1000`\n"
        "• Price: `₹349`\n\n"
        "🥇 *Plus Plan*\n"
        "• Access: `Full Access \\+ MasterCard Killer`\n"
        "• Duration: `60 Days`\n"
        "• Credits: `2000`\n"
        "• Price: `₹639`\n\n"
        "👑 *Custom Plan*\n"
        "• Access: `Everything \\+ Private Queue \\+ Dedicated Support`\n"
        "• Duration: `Custom`\n"
        "• Credits: `Based on Request`\n"
        "• Price: DM @enough69s\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📝 *Note:*\n"
        "• Credits do *not* expire\n"
        "• After expiry, plan access will be locked unless renewed\n"
        "• 🚫 No refunds \\| 🔒 Plans are non\\-transferable\n\n"
        "✅ *Full Access includes:*\n"
        "Private use of Visa/MasterCard killer and advanced tools only available to paid users\n\n"
        "🛒 *To subscribe or redeem a key:*\n"
        "Contact → @enough69s"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(
            plans_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    elif query:
        await query.edit_message_text(
            plans_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main callback handler for all inline keyboard buttons."""
    query = update.callback_query
    await query.answer()
    if query.data == "killers_menu":
        await show_killers_menu(update, context)
    elif query.data == "tools_menu":
        await show_tools_menu(update, context)
    elif query.data == "plans_menu":
        await show_plans_menu(update, context)
    elif query.data == "back_to_start":
        await start(update, context)

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the user's detailed information."""
    if not await check_authorization(update, context):
        return
    user = update.effective_user
    user_data = await get_user(user.id)

    info_message = (
        f"╭━━━[ 𝙐𝙎𝙀𝙍 𝙄𝙉𝙁𝙊 – 𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝓵𝓽ₓ ⚡ ]━━━⬣\n"
        f"┣ ❏ 𝐅𝐢𝐫𝐬𝐭 𝐍𝐚𝐦𝐞     ➳ `{user.first_name or 'N/A'}`\n"
        f"┣ ❏ 𝐈𝐃             ➳ `{user.id}`\n"
        f"┣ ❏ 𝐔𝐬𝐞𝐫𝐧𝐚𝐦𝐞       ➳ `@{escape_markdown(user.username or 'N/A', version=2)}`\n"
        f"┣ ❏ 𝐒𝐭𝐚𝐭𝐮𝐬         ➳ `{user_data.get('status', 'N/A')}`\n"
        f"┣ ❏ 𝐂𝐫𝐞𝐝𝐢𝐭𝐬        ➳ `{user_data.get('credits', 0)}`\n"
        f"┣ ❏ 𝐏𝐥𝐚𝐧           ➳ `{escape_markdown(user_data.get('plan', 'N/A'), version=2)}`\n"
        f"┣ ❏ 𝐏𝐥𝐚𝐧 𝐄𝐱𝐩𝐢𝐫𝐲    ➳ `{user_data.get('plan_expiry', 'N/A')}`\n"
        f"┣ ❏ 𝐊𝐞𝐲𝐬 𝐑𝐞𝐝𝐞𝐞𝐦𝐞𝐝  ➳ `{user_data.get('keys_redeemed', 0)}`\n"
        f"┣ ❏ 𝐑𝐞𝐠𝐢𝐬𝐭𝐞𝐫𝐞𝐝 𝐀𝐭  ➳ `{user_data.get('registered_at', 'N/A')}`\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.message.reply_text(info_message, parse_mode=ParseMode.MARKDOWN_V2)

async def kill_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /kill command for Visa cards."""
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

    if not context.args or len(context.args) != 1:
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: `/kill CC|MM|YY|CVV`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    full_card_str = context.args[0]
    parts = full_card_str.split('|')
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return await update.effective_message.reply_text(
            "❌ Invalid card format\\. Use `CC|MM|YY|CVV`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    card_number = parts[0]
    bin_number = card_number[:6]
    bin_details = await get_bin_details(bin_number)
    scheme = bin_details.get("scheme", "N/A").lower()
    card_type = bin_details.get("type", "N/A").lower()

    if "mastercard" in scheme:
        return await update.effective_message.reply_text(
            "❌ 𝙊𝙣𝙡𝙮 𝙑𝙞𝙨𝙖 𝙘𝙖𝙧𝙙𝙨 𝙖𝙧𝙚 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙛𝙤𝙧 𝙩𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if "amex" in scheme or "american express" in scheme:
        return await update.effective_message.reply_text(
            "❌ 𝙊𝙣𝙡𝙮 𝙑𝙞𝙨𝙖 𝙘𝙖𝙧𝙙𝙨 𝙖𝙧𝙚 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙛𝙤𝙧 𝙩𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if "prepaid" in card_type:
        return await update.effective_message.reply_text(
            "🚫 𝙏𝙝𝙞𝙨 𝙘𝙖𝙧𝙙 𝙞𝙨 𝙖 𝙥𝙧𝙚𝙥𝙖𝙞𝙙 𝙩𝙮𝙥𝙚 𝙖𝙣𝙙 𝙣𝙤𝙩 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙩𝙤 𝙠𝙞𝙡𝙡 💳\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    initial_message = await update.effective_message.reply_text(
        "🔪 Kɪʟʟɪɴɢ\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    asyncio.create_task(_execute_kill_process(update, context, full_card_str, initial_message, bin_details))


async def kmc_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /kmc command for MasterCard only."""
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

    if not context.args or len(context.args) != 1:
        return await update.effective_message.reply_text(
            "❌ Invalid format\\. Usage: /kmc CC|MM|YY|CVV",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    full_card_str = context.args[0]
    parts = full_card_str.split('|')
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return await update.effective_message.reply_text(
            "❌ Invalid card format\\. Use CC|MM|YY|CVV",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    card_number = parts[0]
    bin_number = card_number[:6]
    bin_details = await get_bin_details(bin_number)
    scheme = bin_details.get("scheme", "N/A").lower()
    card_type = bin_details.get("type", "N/A").lower()

    if "visa" in scheme:
        return await update.effective_message.reply_text(
            "❌ 𝙊𝙣𝙡𝙮 𝙈𝙖𝙨𝙩𝙚𝙧𝘾𝙖𝙧𝙙 𝙘𝙖𝙧𝙙𝙨 𝙖𝙧𝙚 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙛𝙤𝙧 𝙩𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if "amex" in scheme or "american express" in scheme:
        return await update.effective_message.reply_text(
            "❌ 𝙊𝙣𝙡𝙮 𝙈𝙖𝙨𝙩𝙚𝙧𝘾𝙖𝙧𝙙 𝙘𝙖𝙧𝙙𝙨 𝙖𝙧𝙚 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙛𝙤𝙧 𝙩𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if "prepaid" in card_type:
        return await update.effective_message.reply_text(
            "🚫 𝙏𝙝𝙞𝙨 𝙘𝙖𝙧𝙙 𝙞𝙨 𝙖 𝙥𝙧𝙚𝙥𝙖𝙞𝙙 𝙩𝙮𝙥𝙚 𝙖𝙣𝙙 𝙣𝙤𝙩 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙩𝙤 𝙠𝙞𝙡𝙡 💳\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    initial_message = await update.effective_message.reply_text(
        "🔪 Kɪʟʟɪɴɢ\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    asyncio.create_task(_execute_kill_process(update, context, full_card_str, initial_message, bin_details))



async def _execute_kill_process(update: Update, context: ContextTypes.DEFAULT_TYPE, full_card_str: str, initial_message, bin_details):
    """
    Handles the long-running kill animation and final message.
    Modified to use the requested animation frames.
    """
    start_time = time.time()
    kill_time = random.uniform(40, 87)
    animation_frames = [
        "▱▱▱▱▱▱▱▱▱▱ 0%",
        "█▱▱▱▱▱▱▱▱▱ 10%",
        "██▱▱▱▱▱▱▱▱ 20%",
        "███▱▱▱▱▱▱▱ 30%",
        "████▱▱▱▱▱▱ 40%",
        "█████▱▱▱▱▱ 50%",
        "██████▱▱▱▱ 60%",
        "███████▱▱▱ 70%",
        "████████▱▱ 80%",
        "█████████▱ 90%",
        "██████████ 100%"
    ]
    frame_interval = kill_time / len(animation_frames)
    elapsed_animation_time = 0
    frame_index = 0
    while elapsed_animation_time < kill_time:
        current_frame = animation_frames[frame_index % len(animation_frames)]
        escaped_frame = escape_markdown_v2(current_frame)
        try:
            await initial_message.edit_text(f"🔪 Kɪʟʟɪɴɢ\\.\\.\\.\n```{escaped_frame}```", parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.debug("Message not modified.")
            elif "Flood control exceeded" in str(e):
                logger.warning(f"Flood control hit during animation for {full_card_str}: {e}")
            else:
                logger.warning(f"Failed to edit message during animation (BadRequest): {e}")
        sleep_duration = min(frame_interval, kill_time - elapsed_animation_time)
        if sleep_duration <= 0:
            break
        await asyncio.sleep(sleep_duration)
        elapsed_animation_time = time.time() - start_time
        frame_index += 1
    final_frame = animation_frames[-1]
    escaped_final_frame = escape_markdown_v2(final_frame)
    try:
        await initial_message.edit_text(f"🔪 Kɪʟʟɪɴɢ\\.\\.\\.\n```{escaped_final_frame}```", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.warning(f"Failed to edit message to final frame: {e}")
    
    time_taken = round(time.time() - start_time)
    bank_name = escape_markdown_v2(bin_details["bank"])
    level = escape_markdown_v2(bin_details["level"])
    level_emoji = get_level_emoji(bin_details["level"])
    brand = escape_markdown_v2(bin_details["scheme"])
    header_title = "⚡Cᴀʀd Kɪʟʟeᴅ Sᴜᴄᴄᴇssꜰᴜʟʟʏ"

    if bin_details["scheme"].lower() == 'mastercard':
        percentage = random.randint(68, 100)
        header_title = f"⚡Cᴀʀd Kɪʟʟeᴅ Sᴜᴄᴄᴇssꜰᴜʟʟʏ \\- {percentage}\\%"

    final_message_text_formatted = (
        f"╭━━━[ {header_title} ]━━━⬣\n"
        f"┣ ❏ 𝐂𝐚𝐫𝐝 𝐍𝐮𝐦𝐛𝐞𝐫     ➳ `{escape_markdown_v2(full_card_str)}`\n"
        f"┣ ❏ 𝐁𝐫𝐚𝐧𝐝           ➳ `{brand}`\n"
        f"┣ ❏ 𝐈𝐬𝐬𝐮𝐞𝐫          ➳ `{bank_name}`\n"
        f"┣ ❏ 𝐋𝐞𝐯𝐞𝐥           ➳ `{level_emoji} {level}`\n"
        f"┣ ❏ 𝐊𝐢𝐥𝐥𝐞𝐫          ➳ `𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝒍𝒕𝑿`\n"
        f"┣ ❏ 𝐁𝐨𝐭 𝐛𝐲          ➳ `『𝗥ᴏᴄ𝗸ʏ』`\n"
        f"┣ ❏ 𝐓𝐢𝐦𝐞 𝐓𝐚𝐤𝐞𝐧      ➳ `{escape_markdown_v2(f'{time_taken:.0f} seconds')}`\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━⬣"
    )

    await initial_message.edit_text(
        final_message_text_formatted,
        parse_mode=ParseMode.MARKDOWN_V2
    )


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
        f"┣ ❏ *𝐁𝐨𝐭 𝐛𝐲*       ➳ 『𝗥ᴏᴄ𝗸ʏ』\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    final_message = f"{bin_info_box}\n\n{user_info_box}"

    await update.effective_message.reply_text(
        final_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )




async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /credits command, showing user info and credits."""
    if not await check_authorization(update, context):
        return

    user = update.effective_user
    user_data = await get_user(user.id)
    credits = user_data.get('credits', 0)
    plan = user_data.get('plan', 'N/A')

    # Escape for MarkdownV2
    escaped_username = escape_markdown_v2(user.username or 'N/A')
    escaped_user_id = escape_markdown_v2(str(user.id))
    escaped_plan = escape_markdown_v2(plan)
    escaped_credits = escape_markdown_v2(str(credits))

    credit_message = (
        f"╭━━━[ 💳 𝐂𝐑𝐄𝐃𝐈𝐓 𝐈𝐍𝐅𝐎 💳 ]━━━⬣\n"
        f"┣ ❏ 𝐔𝐬𝐞𝐫𝐧𝐚𝐦𝐞   ➳ `@{escaped_username}`\n"
        f"┣ ❏ 𝐔𝐬𝐞𝐫 𝐈𝐃    ➳ `{escaped_user_id}`\n"
        f"┣ ❏ 𝐏𝐥𝐚𝐧       ➳ `{escaped_plan}`\n"
        f"┣ ❏ 𝐂𝐫𝐞𝐝𝐢𝐭𝐬    ➳ `{escaped_credits}`\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.effective_message.reply_text(credit_message, parse_mode=ParseMode.MARKDOWN_V2)


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

async def fl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts all cards from any dump or text."""
    if not await check_authorization(update, context):
        return

    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    if user_data['credits'] <= 0:
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not context.args:
        return await update.effective_message.reply_text(
            "❌ Please provide a dump or text to extract cards from\\. Usage: `/fl <dump or text>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if not await consume_credit(user_id):
        return await update.effective_message.reply_text(
            "❌ You have no credits left\\. Please get a subscription to use this command\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    dump = " ".join(context.args)
    cards_found = re.findall(r'\d{13,16}(?:\|\d{2}\|\d{2}(?:\|\d{3,4})?)?', dump)
    count = len(cards_found)

    extracted_cards_text = "\n".join([f"`{escape_markdown_v2(card)}`" for card in cards_found])
    if not cards_found:
        extracted_cards_text = "_No cards found in the provided text\\._"

    escaped_user = escape_markdown_v2(update.effective_user.full_name)

    msg = (
        f"╭━━━ [ 💳 𝘊𝘢𝘳𝘥 𝘓𝘪𝘴𝘵 𝘌𝘹𝘵𝘳𝘢𝘤𝘵𝘦𝘥 ] ━━━⬣\n"
        f"┣ ❏ Total Cards ➳ `{count}`\n"
        f"┣ ❏ Requested by ➳ `{escaped_user}`\n"
        f"┣ ❏ Bot by ➳ 『𝗥ᴏᴄ𝗸ʏ』\n"
        f"╰━━━━━━━━━━━━━━━━━━━━⬣\n\n"
        f"{extracted_cards_text}"
    )

    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


import psutil

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks and reports on bot system status."""
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
    total_memory = memory_info.total / (1024 ** 2)  # in MB
    used_memory = memory_info.used / (1024 ** 2)    # in MB
    memory_percent = memory_info.percent

    status_message = (
        "╭━━━ 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬 ━━━━⬣\n"
        f"┣ ❏ 𝖢𝖯𝖴 𝖴𝗌𝖺𝗀𝖾 ➳ `{cpu_usage}%`\n"
        f"┣ ❏ 𝖱𝖠𝖬 𝖴𝗌𝖺𝗀𝖾 ➳ `{memory_percent}%`\n"
        f"┣ ❏ 𝖳𝗈𝗍𝖺𝗅 𝖱𝖠𝖬 ➳ `{total_memory:.2f} MB`\n"
        f"┣ ❏ 𝖴𝗌𝖾𝖽 𝖱𝖠𝖬  ➳ `{used_memory:.2f} MB`\n"
        f"╰━━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.effective_message.reply_text(status_message, parse_mode=ParseMode.MARKDOWN_V2)


# === OWNER-ONLY COMMANDS ===
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Function to escape MarkdownV2 special characters
def escape_markdown_v2(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows all admin commands, authorized groups, and users."""

    admin_commands_list = (
        "• `/give_starter <user_id>`: Give 7\\-day Starter Plan\n"
        "• `/give_premium <user_id>`: Give 30\\-day Premium Plan\n"
        "• `/give_plus <user_id>`: Give 60\\-day Plus Plan\n"
        "• `/give_custom <user_id>`: Give Custom Plan\n"
        "• `/take_plan <user_id>`: Remove plan & private access\n"
        "• `/au <chat_id>`: Authorize a group\n"
        "• `/rauth <user_id>`: Remove private user auth\n"
        "• `/gen_codes`: Generate 10 Starter Plan codes\n"
    )

    authorized_groups_list = (
        "\n".join([f"• `{escape_markdown_v2(str(chat_id))}`" for chat_id in AUTHORIZED_CHATS])
        if AUTHORIZED_CHATS else "No groups authorized."
    )

    authorized_users_list = []
    for user_id in AUTHORIZED_PRIVATE_USERS:
        user_data = USER_DATA_DB.get(user_id)
        if user_data:
            uid = escape_markdown_v2(str(user_id))
            plan = escape_markdown_v2(user_data.get("plan", "N/A"))
            authorized_users_list.append(f"• ID: `{uid}` | Plan: `{plan}`")
    authorized_users_list_str = (
        "\n".join(authorized_users_list) if authorized_users_list else "No private users authorized."
    )

    admin_dashboard_message = (
        "╭━━━━━『 𝐀𝐃𝐌𝐈𝐍 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃 』━━━━━╮\n"
        "┣ 🤖 *Owner Commands:*\n"
        f"╰─\\> {admin_commands_list}"
        "╭━━━『 𝐀𝐮𝐭𝐡𝐨𝐫𝐢𝐳𝐞𝐝 𝐆𝐫𝐨𝐮𝐩𝐬 』━━━╮\n"
        f"╰─\\> {escape_markdown_v2(authorized_groups_list)}\n"
        "╭━━━『 𝐀𝐮𝐭𝐡𝐨𝐫𝐢𝐳𝐞𝐝 𝐔𝐬𝐞𝐫𝐬 \\(Private\\) 』━━━╮\n"
        f"╰─\\> {escape_markdown_v2(authorized_users_list_str)}"
    )

    await update.effective_message.reply_text(admin_dashboard_message, parse_mode=ParseMode.MARKDOWN_V2)

from datetime import datetime, timedelta

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


async def give_starter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")
    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text("❌ Invalid format\\. Usage: `/give_starter [user_id]`", parse_mode=ParseMode.MARKDOWN_V2)
    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Starter Plan', 300, 7)
    await update.effective_message.reply_text(f"✅ Starter Plan activated for user `{user_id}`\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def give_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")
    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text("❌ Invalid format\\. Usage: `/give_premium [user_id]`", parse_mode=ParseMode.MARKDOWN_V2)
    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Premium Plan', 1000, 30)
    await update.effective_message.reply_text(f"✅ Premium Plan activated for user `{user_id}`\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def give_plus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")
    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text("❌ Invalid format\\. Usage: `/give_plus [user_id]`", parse_mode=ParseMode.MARKDOWN_V2)
    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Plus Plan', 2000, 60)
    await update.effective_message.reply_text(f"✅ Plus Plan activated for user `{user_id}`\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def give_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command.")
    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text("❌ Invalid format\\. Usage: `/give_custom [user_id]`", parse_mode=ParseMode.MARKDOWN_V2)
    user_id = int(context.args[0])
    await _update_user_plan(user_id, 'Custom Plan', 3000)
    await update.effective_message.reply_text(f"✅ Custom Plan activated for user `{user_id}` with 3000 credits\\.", parse_mode=ParseMode.MARKDOWN_V2)

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
    application.add_handler(CommandHandler("kill", kill_card))
    application.add_handler(CommandHandler("kmc", kmc_kill))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("fk", fk_command))
    application.add_handler(CommandHandler("fl", fl_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("plans", show_plans_menu))
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
