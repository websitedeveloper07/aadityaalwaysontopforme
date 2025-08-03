import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest
from faker import Faker
import pytz

# === CONFIGURATION ===
# IMPORTANT: Set these as environment variables before running your bot:
# export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
# export OWNER_ID="YOUR_TELEGRAM_USER_ID" # Your personal Telegram User ID (numeric)
# export BINTABLE_API_KEY="YOUR_BINTABLE_API_KEY" # Get this from Bintable.com
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None
BINTABLE_API_KEY = os.getenv("BINTABLE_API_KEY")
BINTABLE_URL = "https://api.bintable.com/v1"

# --- New Configuration ---
AUTHORIZATION_CONTACT = "@enough69s"
OFFICIAL_GROUP_LINK = "https://t.me/+gtvJT4SoimBjYjQ1"
DAILY_KILL_CREDIT_LIMIT = 50

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
# 4. Replace `USER_DATA_DB` and `USER_CREDITS` with calls to these database functions.
#
# --- GLOBAL STATE (In-Memory) ---
user_last_command = {}
AUTHORIZED_CHATS = set()
AUTHORIZED_PRIVATE_USERS = set()
USER_CREDITS = {}
USER_DATA_DB = {
    OWNER_ID: {
        'credits': 9999,
        'plan': 'Owner',
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
    """Fetches user data from the in-memory 'database'. This needs to be replaced."""
    if user_id not in USER_DATA_DB:
        USER_DATA_DB[user_id] = {
            'credits': 50,
            'plan': 'Free',
            'status': 'Free',
            'plan_expiry': 'N/A',
            'keys_redeemed': 0,
            'registered_at': datetime.now().strftime('%d-%m-%Y')
        }
    return USER_DATA_DB.get(user_id)

def get_user_credits(user_id):
    now = datetime.now()
    if user_id not in USER_CREDITS:
        USER_CREDITS[user_id] = {'credits': DAILY_KILL_CREDIT_LIMIT, 'last_credit_reset': now}
    else:
        last_reset_date = USER_CREDITS[user_id]['last_credit_reset'].date()
        if now.date() > last_reset_date:
            USER_CREDITS[user_id]['credits'] = DAILY_KILL_CREDIT_LIMIT
            USER_CREDITS[user_id]['last_credit_reset'] = now
    return USER_CREDITS[user_id]['credits']

def consume_credit(user_id):
    get_user_credits(user_id)
    if USER_CREDITS[user_id]['credits'] > 0:
        USER_CREDITS[user_id]['credits'] -= 1
        return True
    return False

def add_credits_to_user(user_id, amount):
    get_user_credits(user_id)
    USER_CREDITS[user_id]['credits'] += amount
    return USER_CREDITS[user_id]['credits']

async def get_bin_details(bin_number):
    bin_data = {
        "scheme": "N/A", "type": "N/A", "level": "N/A",
        "bank": "N/A", "country_name": "N/A", "country_emoji": "",
        "vbv_status": None, "card_type": "N/A"
    }
    async with aiohttp.ClientSession() as session:
        if BINTABLE_API_KEY:
            try:
                bintable_url = f"{BINTABLE_URL}/{bin_number}?api_key={BINTABLE_API_KEY}"
                async with session.get(bintable_url, timeout=7) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and data.get("result") == 200:
                            response_data = data.get("data", {})
                            card_info = response_data.get("card", {})
                            country_info = response_data.get("country", {})
                            bank_info = response_data.get("bank", {})
                            bin_data["scheme"] = card_info.get("scheme", "N/A").upper()
                            bin_data["type"] = card_info.get("type", "N/A").title()
                            bin_data["card_type"] = card_info.get("category", card_info.get("type", "N/A")).title()
                            bin_data["level"] = card_info.get("level", "N/A").title()
                            bin_data["bank"] = bank_info.get("name", "N/A").title()
                            bin_data["country_name"] = country_info.get("name", "N/A")
                            bin_data["country_emoji"] = country_info.get("emoji", "")
                            return bin_data
            except aiohttp.ClientError as e:
                logger.warning(f"Bintable API call failed for {bin_number}: {e}")
            except Exception as e:
                logger.warning(f"Error processing Bintable response for {bin_number}: {e}")
        try:
            binlist_url = f"https://lookup.binlist.net/{bin_number}"
            async with session.get(binlist_url, timeout=7) as response:
                if response.status == 200:
                    data = await response.json()
                    if data:
                        bin_data["scheme"] = data.get("scheme", "N/A").upper()
                        bin_data["type"] = data.get("type", "N/A").title()
                        bin_data["card_type"] = data.get("type", "N/A").title()
                        bin_data["level"] = data.get("brand", "N/A").title()
                        bin_data["bank"] = data.get("bank", {}).get("name", "N/A").title()
                        bin_data["country_name"] = data.get("country", {}).get("name", "N/A")
                        bin_data["country_emoji"] = data.get("country", {}).get("emoji", "")
                        return bin_data
        except aiohttp.ClientError as e:
            logger.warning(f"Binlist API call failed for {bin_number}: {e}")
        except Exception as e:
            logger.warning(f"Error processing Binlist response for {bin_number}: {e}")
        try:
            bincheck_url = f"https://api.bincheck.io/v2/{bin_number}"
            async with session.get(bincheck_url, timeout=7) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and data.get("success"):
                        bin_data["scheme"] = data.get("scheme", "N/A").upper()
                        bin_data["type"] = data.get("type", "N/A").title()
                        bin_data["card_type"] = data.get("type", "N/A").title()
                        bin_data["level"] = data.get("level", "N/A").title()
                        bin_data["bank"] = data.get("bank", {}).get("name", "N/A").title()
                        bin_data["country_name"] = data.get("country", {}).get("name", "N/A")
                        bin_data["country_emoji"] = data.get("country", {}).get("emoji", "")
                        return bin_data
        except aiohttp.ClientError as e:
            logger.warning(f"Bincheck.io API call failed for {bin_number}: {e}")
        except Exception as e:
            logger.warning(f"Error processing Bincheck.io response for {bin_number}: {e}")
    logger.warning(f"Failed to get BIN details for {bin_number} from all sources.")
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

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE, is_group_only: bool = False) -> bool:
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    chat_id = update.effective_chat.id
    if user_id == OWNER_ID:
        return True
    if is_group_only:
        if chat_type != 'group' and chat_type != 'supergroup':
            await update.effective_message.reply_text("🚫 This command can only be used in authorized group chats\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return False
        if chat_id not in AUTHORIZED_CHATS:
            await update.effective_message.reply_text(f"🚫 This group chat is not authorized to use this bot\\. Please contact {AUTHORIZATION_CONTACT} to get approved\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return False
        return True
    if chat_type == 'private':
        if user_id in AUTHORIZED_PRIVATE_USERS:
            return True
        else:
            keyboard = [[InlineKeyboardButton("Official Group", url=OFFICIAL_GROUP_LINK)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            escaped_link = escape_markdown_v2(OFFICIAL_GROUP_LINK)
            await update.effective_message.reply_text(f"🚫 You are not approved to use bot in private\\. Get the subscription at cheap from {AUTHORIZATION_CONTACT} to use or else use for free in our official group\\.", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
            return False
    elif chat_type == 'group' or chat_type == 'supergroup':
        if chat_id in AUTHORIZED_CHATS:
            return True
        else:
            await update.effective_message.reply_text(f"🚫 This group chat is not authorized to use this bot\\. Please contact {AUTHORIZATION_CONTACT} to get approved\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return False
    return False

# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command, displaying user info and main menu."""
    user = update.effective_user
    indian_timezone = pytz.timezone('Asia/Kolkata')
    now = datetime.now(indian_timezone).strftime('%I:%M %p')
    today = datetime.now(indian_timezone).strftime('%d-%m-%Y')
    user_data = get_user_from_db(user.id)
    credits = user_data.get('credits', 0)
    plan = user_data.get('plan', 'Free')
    welcome_message = (
        f"👋 *Welcome to 𝓒𝓪𝓻d𝓥𝓪𝓾𝒍𝒕𝑿* ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{user.id}`\n"
        f"👤 Username: `@{user.username or 'N/A'}`\n"
        f"📅 Date: `{today}`\n"
        f"🕒 Time: `{now}`\n"
        f"💳 Credits: `{credits}`\n"
        f"📋 Plan: `{plan}`\n\n"
        f"Use the buttons below to get started 👇"
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
    if update.message:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Error editing message: {e}")
                await context.bot.send_message(chat_id=query.message.chat_id, text=welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

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
        "╰━━━━━━━━━━━━━━━━━━⬣"
    )
    await update.effective_message.reply_text(help_message, parse_mode=ParseMode.MARKDOWN_V2)

async def show_killers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the detailed Killer menu."""
    query = update.callback_query
    await query.answer()
    killer_message = (
        "╭━━━〔 𝐊𝟏𝐋𝐋𝐄𝐑 𝐂𝐄𝐍𝐓𝐄𝐑 – 𝓒𝓪𝓻d𝓥𝓪𝒖𝒍𝒕𝑿 〕━━━╮\n"
        "│ 🛠 Status: `Active`\n"
        "│ 👑 Owner: `@enough69s`\n"
        "│ ⚙️ Mode: `K1LLER Engine`\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "🔹 𝗩𝗜𝗦𝗔 𝗢𝗡𝗟𝗬 𝗚𝗔𝗧𝗘\n"
        "┗ 📛 Name: `Standard K1LL`\n"
        "┗ 💬 Command: `/kill cc|mm|yy|cvv`\n"
        "┗ 🧾 Format: `CC\\|MM\\|YY\\|CVV`\n"
        "┗ 🟢 Status: `Online`\n"
        "┗ 📅 Updated: `03 Aug 2025`\n"
        "┗ 🕐 Avg Time: `45s`\n"
        "┗ 💉 Health: `100%`\n"
        "┗ 📝 Note: Ideal for Visa\\-only replacement shops\n\n"
        "🔸 𝗩𝗜𝗦𝗔 \\+ 𝗠𝗔𝗦𝗧𝗘𝗥 𝗚𝗔𝗧𝗘\n"
        "┗ 📛 Name: `Advanced K1LL`\n"
        "┗ 💬 Command: `/kmc cc|mm|yy|cvv`\n"
        "┗ 🧾 Format: `CC\\|MM\\|YY\\|CVV`\n"
        "┗ 🟢 Status: `Online`\n"
        "┗ 📅 Updated: `03 Aug 2025`\n"
        "┗ 🕐 Avg Time: `65s`\n"
        "┗ 💉 Health: `90%`\n"
        "┗ 📝 Note: Visa \\+ Master supported \\| High kill rate\n\n"
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
        "• `/gen <BIN>` - Generates 10 cards\n"
        "• `/fk <country>` - Generates fake info\n"
        "• `/fl <dump>` - Extracts cards from dumps\n"
        "• `/credits` - Shows your credits\n"
        "• `/bin <BIN>` - Performs BIN lookup\n"
        "• `/status` - Checks bot health\n"
        "• `/info` - Shows your info"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(tools_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

async def show_plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the detailed bot plans."""
    query = update.callback_query
    await query.answer()
    plans_message = (
        "📦 *𝓒𝓪𝓻d𝓥𝓪𝓾𝒍𝒕𝑿 Subscription Plans*\n"
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
        "• Price: `DM @enough69s`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📝 *Note:*\n"
        "• Credits do *not* expire\n"
        "• After expiry, plan access will be locked unless renewed\n"
        "• 🚫 No refunds \\| 🔒 Plans are non\\-transferable\n\n"
        "✅ *Full Access includes:*\n"
        "Private use of Visa/MasterCard killer and advanced tools only available to paid users\n\n"
        "🛒 *To subscribe or redeem a key:*\n"
        "Contact → `@enough69s`"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
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
    user_data = get_user_from_db(user.id)
    info_message = (
        "🔍 Your Info on 𝓒𝓪𝓻d𝓥𝓪𝓾𝒍𝒕𝑿 ⚡\n"
        "━━━━━━━━━━━━━━\n"
        f"👤 First Name: ㅤ`{user.first_name or 'N/A'}`\n"
        f"🆔 ID: `{user.id}`\n"
        f"📛 Username: `@{user.username or 'N/A'}`\n\n"
        f"📋 Status: `{user_data.get('status', 'N/A')}`\n"
        f"💳 Credit: `{user_data.get('credits', 0)}`\n"
        f"💼 Plan: `{user_data.get('plan', 'N/A')}`\n"
        f"📅 Plan Expiry: `{user_data.get('plan_expiry', 'N/A')}`\n"
        f"🔑 Keys Redeemed: `{user_data.get('keys_redeemed', 0)}`\n"
        f"🗓 Registered At: `{user_data.get('registered_at', 'N/A')}`\n"
    )
    await update.message.reply_text(info_message, parse_mode=ParseMode.MARKDOWN_V2)

async def kill_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /kill command for Visa cards."""
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return
    user_id = update.effective_user.id
    if not context.args or len(context.args) != 1:
        await update.effective_message.reply_text("❌ Invalid format\\. Usage: `/kill CC|MM|YY|CVV`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    full_card_str = context.args[0]
    parts = full_card_str.split('|')
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        await update.effective_message.reply_text("❌ Invalid card format\\. Use `CC|MM|YY|CVV`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    card_number = parts[0]
    bin_number = card_number[:6]
    bin_details = await get_bin_details(bin_number)
    scheme = bin_details.get("scheme", "N/A").lower()
    card_type = bin_details.get("type", "N/A").lower()
    if "mastercard" in scheme:
        await update.effective_message.reply_text("❌ Only Visa cards are allowed for this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    if "prepaid" in card_type:
        await update.effective_message.reply_text("❌ Prepaid bins are not allowed to be killed with this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    if not consume_credit(user_id):
        credits = get_user_credits(user_id)
        await update.effective_message.reply_text(f"❌ You have no credits left\\. Current credits: `{credits}`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    initial_message = await update.effective_message.reply_text("🔪 Kɪʟʟɪɴɢ\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    asyncio.create_task(_execute_kill_process(update, context, full_card_str, initial_message, bin_details))

async def kmc_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /kmc command for Visa and MasterCard."""
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return
    user_id = update.effective_user.id
    if not context.args or len(context.args) != 1:
        await update.effective_message.reply_text("❌ Invalid format\\. Usage: `/kmc CC|MM|YY|CVV`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    full_card_str = context.args[0]
    parts = full_card_str.split('|')
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        await update.effective_message.reply_text("❌ Invalid card format\\. Use `CC|MM|YY|CVV`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    card_number = parts[0]
    bin_number = card_number[:6]
    bin_details = await get_bin_details(bin_number)
    scheme = bin_details.get("scheme", "N/A").lower()
    card_type = bin_details.get("type", "N/A").lower()
    if "visa" in scheme:
        await update.effective_message.reply_text("❌ Only MasterCard cards are allowed for this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    if "prepaid" in card_type:
        await update.effective_message.reply_text("❌ Prepaid bins are not allowed to be killed with this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    if not consume_credit(user_id):
        credits = get_user_credits(user_id)
        await update.effective_message.reply_text(f"❌ You have no credits left\\. Current credits: `{credits}`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    initial_message = await update.effective_message.reply_text("🔪 Kɪʟʟɪɴɢ\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
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
        f"╭───\\[ {header_title} \\]──╮\n"
        f"├💳 Cᴀʀᴅ : `{escape_markdown_v2(full_card_str)}`\n"
        f"├⌛ Tɪᴍᴇ : `{time_taken}s`\n"
        f"├💳 Bʀᴀɴᴅ: `{brand}`\n"
        f"├🏛️ Bᴀɴᴋ : `{bank_name}`\n"
        f"├👑 Lᴇᴠᴇʟ: `{level_emoji} {level}`\n"
        f"├🌍 Cᴏᴜɴᴛʀʏ: `{escape_markdown_v2(bin_details['country_name'])} {bin_details['country_emoji']}`\n"
        f"╰───────────\\[ ✅ Live \\]──╯"
    )
    await initial_message.edit_text(final_message_text_formatted, parse_mode=ParseMode.MARKDOWN_V2)

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates cards from a given BIN."""
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return
    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.effective_message and update.effective_message.text:
        command_text = update.effective_message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]
    if not bin_input or not bin_input.isdigit():
        return await update.effective_message.reply_text("❌ Please provide a valid numerical BIN\\. Usage: `/gen [bin]` or `\\.gen [bin]`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    bin_prefix = bin_input[:6]
    bin_details = await get_bin_details(bin_prefix)
    brand = bin_details["scheme"]
    bank = bin_details["bank"]
    country_name = bin_details['country_name']
    country_emoji = bin_details['country_emoji']
    card_type = bin_details["card_type"]
    cards = []
    while len(cards) < 10:
        num_len = 16
        if brand.lower() == 'american express':
            num_len = 15
        elif brand.lower() == 'diners club':
            num_len = 14
        num_suffix_len = num_len - len(bin_input)
        if num_suffix_len < 0:
            num = bin_input[:num_len]
        else:
            num = bin_input + ''.join(str(random.randint(0, 9)) for _ in range(num_suffix_len))
        if not luhn_checksum(num):
            continue
        mm = str(random.randint(1, 12)).zfill(2)
        yyyy = str(datetime.now().year + random.randint(1, 5))
        cvv_length = 4 if brand.lower() == 'american express' else 3
        cvv = str(random.randint(0, (10**cvv_length) - 1)).zfill(cvv_length)
        cards.append(f"`{num}|{mm}|{yyyy[-2:]}|{cvv}`")
    cards_list = "\n".join(cards)
    
    escaped_brand = escape_markdown_v2(brand)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country_name = escape_markdown_v2(country_name)
    escaped_country_emoji = escape_markdown_v2(country_emoji)
    escaped_card_type = escape_markdown_v2(card_type)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)

    # BIN info block content for /gen, using ">>" as separator and escaped hyphen
    bin_info_block_content = (
        f"✦ BIN\\-LOOKUP\n"
        f"✦ BIN : `{escape_markdown_v2(bin_input)}`\n"
        f"✦ Country : {escaped_country_name} {escaped_country_emoji}\n"
        f"✦ Type : {escaped_card_type}\n"
        f"✦ Bank : {escaped_bank}"
    )

    user_info_block_content = (
        f"Requested by : {escaped_user_full_name}\n"
        f"Bot by : 🔮 𝓖𝓸𝓼𝓽𝓑𝓲𝓽 𝖃𝖃𝖃 👁️"
    )

    result = (
        f"> Generated 10 Cards 💳\n"
        f"\n"
        f"{cards_list}\n"
        f"\n"
        f"> {bin_info_block_content.replace('\n', '\n> ')}\n"
        f"> \n"
        f"> {user_info_block_content.replace('\n', '\n> ')}"
    )

    await update.effective_message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Performs a BIN lookup."""
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return
    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.effective_message and update.effective_message.text:
        command_text = update.effective_message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]
    if not bin_input:
        return await update.effective_message.reply_text("❌ Please provide a 6\\-digit BIN\\. Usage: `/bin [bin]` or `\\.bin [bin]`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    bin_input = bin_input[:6]
    bin_details = await get_bin_details(bin_input)
    scheme = bin_details["scheme"]
    bank = bin_details["bank"]
    card_type = bin_details["card_type"]
    level = bin_details["level"]
    country_name = bin_details['country_name']
    country_emoji = bin_details['country_emoji']
    vbv_status = bin_details["vbv_status"]
    escaped_scheme = escape_markdown_v2(scheme)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country_name = escape_markdown_v2(country_name)
    escaped_country_emoji = escape_markdown_v2(country_emoji)
    escaped_card_type = escape_markdown_v2(card_type)
    escaped_level = escape_markdown_v2(level)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)
    level_emoji = get_level_emoji(escaped_level)
    status_display = get_vbv_status_display(vbv_status)
    bin_info_box = (
        f"╔═══════ BIN INFO ═══════╗\n"
        f"✦ BIN    : `{escape_markdown_v2(bin_input)}`\n"
        f"✦ Status : {status_display}\n"
        f"✦ Brand  : {escaped_scheme}\n"
        f"✦ Type   : {escaped_card_type}\n"
        f"✦ Level  : {level_emoji} {escaped_level}\n"
        f"✦ Bank   : {escaped_bank}\n"
        f"✦ Country: {escaped_country_name} {escaped_country_emoji}\n"
        f"╚════════════════════════╝"
    )
    user_info_quote_box = (
        f"> Requested by \\-: {escaped_user_full_name}\n"
        f"> Bot by \\-: 🔮 𝓖𝓸𝓼𝓽𝓑𝓲𝓽 𝖃𝖃𝖃 👁️"
    )
    result = f"{bin_info_box}\n\n{user_info_quote_box}"
    await update.effective_message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /credits command."""
    if not await check_authorization(update, context):
        return
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)
    await update.effective_message.reply_text(f"💳 Your remaining credits for the `kill` command is: `{credits}`", parse_mode=ParseMode.MARKDOWN_V2)

async def fk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates fake identity info."""
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return
    country_code = 'en_US'
    if context.args:
        country_code = context.args[0]
    try:
        fake_info = Faker(country_code)
    except Exception:
        fake_info = Faker('en_US')
    name = escape_markdown_v2(fake_info.name())
    dob = escape_markdown_v2(fake_info.date_of_birth().strftime('%Y-%m-%d'))
    ssn = escape_markdown_v2(fake_info.ssn())
    email = escape_markdown_v2(fake_info.email())
    username = escape_markdown_v2(fake_info.user_name())
    phone = escape_markdown_v2(fake_info.phone_number())
    job = escape_markdown_v2(fake_info.job())
    company = escape_markdown_v2(fake_info.company())
    street = escape_markdown_v2(fake_info.street_address())
    address2 = escape_markdown_v2(fake_info.secondary_address())
    city = escape_markdown_v2(fake_info.city())
    state = escape_markdown_v2(fake_info.state())
    zip_code = escape_markdown_v2(fake_info.zipcode())
    country = escape_markdown_v2(fake_info.country())
    ip = escape_markdown_v2(fake_info.ipv4_public())
    ua = escape_markdown_v2(fake_info.user_agent())
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

async def fl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts all cards from any dump or text."""
    if not await check_authorization(update, context):
        return
    if not context.args:
        return await update.effective_message.reply_text("❌ Please provide a dump or text to extract cards from\\. Usage: `/fl <dump or text>`", parse_mode=ParseMode.MARKDOWN_V2)
    
    dump = " ".join(context.args)
    cards_found = re.findall(r'\d{13,16}(?:\|\d{2}\|\d{2}(?:\|\d{3,4})?)?', dump)
    count = len(cards_found)
    
    extracted_cards_text = "\n".join([f"`{card}`" for card in cards_found])
    if not extracted_cards_text:
        extracted_cards_text = "No cards found in the provided text."

    escaped_user = escape_markdown_v2(update.effective_user.full_name)
    msg = (
        f"╭━━━ [ 💳 𝘊𝘢𝘳𝘥 𝘓𝘪𝘴𝘵 𝘌𝘹𝘵𝘳𝘢𝘤𝘵𝘦𝘥 ] ━━━⬣\n"
        f"┣ ❏ Total Cards ➳ `{count}`\n"
        f"┣ ❏ Requested by ➳ `{escaped_user}`\n"
        f"┣ ❏ Bot by ➳ 🔮 𝓖𝓸𝓼𝓽𝓑𝓲𝓽 𝖃𝖃𝖃 👁️\n"
        f"╰━━━━━━━━━━━━━━━━━━━━⬣\n\n"
        f"{extracted_cards_text}"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks and reports on bot system status."""
    if not await check_authorization(update, context):
        return
    cpu_usage = psutil.cpu_percent(interval=1)
    memory_info = psutil.virtual_memory()
    total_memory = memory_info.total
    used_memory = memory_info.used
    memory_percent = memory_info.percent
    status_message = (
        "╭━━━ 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬 ━━━━⬣\n"
        f"┣ ❏ 𝖢𝖯𝖴 𝖴𝗌𝖺𝗀𝖾 ➳ `{cpu_usage}%`\n"
        f"┣ ❏ 𝖱𝖠𝖬 𝖴𝗌𝖺𝗀𝖾 ➳ `{memory_percent}%`\n"
        f"┣ ❏ 𝖳𝗈𝗍𝖺𝗅 𝖱𝖠𝖬 ➳ `{total_memory / (1024 ** 2):.2f} MB`\n"
        f"┣ ❏ 𝖴𝗌𝖾𝖽 𝖱𝖠𝖬  ➳ `{used_memory / (1024 ** 2):.2f} MB`\n"
        f"╰━━━━━━━━━━━━━━━━━━━⬣"
    )
    await update.effective_message.reply_text(status_message, parse_mode=ParseMode.MARKDOWN_V2)

# === REGISTERING COMMANDS AND HANDLERS ===
def main():
    """Starts the bot."""
    if not TOKEN:
        logger.error("BOT_TOKEN is not set. Please set the BOT_TOKEN environment variable.")
        exit(1)
    application = ApplicationBuilder().token(TOKEN).build()
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
    application.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Bot started and is polling for updates...")
    application.run_polling()

if __name__ == '__main__':
    main()
