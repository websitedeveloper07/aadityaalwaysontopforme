import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil
import random
import uuid # Added for idempotency key generation
import stripe # Make sure stripe library is imported
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest # Import BadRequest for specific error handling

# === CONFIGURATION ===
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

BINTABLE_API_KEY = "d1359fe2b305160dd9b9d895a07b4438794ea1f6"
BINTABLE_URL = "https://api.bintable.com/v1"

user_last_command = {}

# Initialize Stripe API client
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logging.warning("STRIPE_SECRET_KEY environment variable is not set. Stripe checker will not function.")

# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Helper to escape MarkdownV2 special characters
def escape_markdown_v2(text: str) -> str:
    # Escape all characters that have special meaning in MarkdownV2
    special_chars = r'_*[]()~`>#+-=|{}.!\\' # Added '\' itself to be escaped
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

# === ERROR HANDLER ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Try to send a message back to the user
    if update.effective_message:
        error_message_text = "An error occurred while processing your request. Please try again later."
        try:
            await update.effective_message.reply_text(
                escape_markdown_v2(error_message_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except BadRequest:
            # Fallback to plain text if MarkdownV2 still fails
            await update.effective_message.reply_text(error_message_text)

# === COMMANDS AND FUNCTIONS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_message = (
        f"Hey {escape_markdown_v2(user.first_name)} 👋\n\n"
        f"I'm a Credit Card Checker Bot that can help you with CC related tasks\.\n"
        f"You can use me to Gen, Check, Bin Lookup & Authorize stripe cards with my advanced API\.\n\n"
        f"Press the button below to see my commands\."
    )
    keyboard = [[InlineKeyboardButton("Commands", callback_data="show_main_commands")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(
            welcome_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        await update.message.reply_text(
            welcome_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def show_main_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    commands_message = escape_markdown_v2(
        "Here are my main commands:\n\n"
        "• /gen \- Generate credit cards\n"
        "• /bin \- Lookup BIN information\n"
        "• /kill \- Simulate card checking \(for fun\)\n"
        "• /chk \- Stripe Live Auth Checker\n"
        "• /status \- Check bot status\n"
        "• /au \- Authorize group to use bot\n\n"
        "Click on a command for more details\."
    )

    keyboard = [
        [InlineKeyboardButton("💳 /gen", callback_data="cmd_gen")],
        [InlineKeyboardButton("🔍 /bin", callback_data="cmd_bin")],
        [InlineKeyboardButton("🔪 /kill", callback_data="cmd_kill")],
        [InlineKeyboardButton("✅ /chk", callback_data="cmd_chk")],
        [InlineKeyboardButton("📊 /status", callback_data="cmd_status")],
        [InlineKeyboardButton("🔐 /au", callback_data="cmd_au")],
        [InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        commands_message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def show_command_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    command = query.data.replace("cmd_", "/")

    details = {
        "/gen": "Usage: `/gen BIN|MM|YY|CVV`\nExample: `/gen 400000|12|25|123`",
        "/bin": "Usage: `/bin BIN`\nExample: `/bin 400000`",
        "/kill": "Usage: `/kill CC|MM|YY|CVV`\nExample: `/kill 4000000000000000|12|25|123`",
        "/chk": "Usage: `/chk PaymentMethodID`\nExample: `/chk pm_1Lg824K...`\n\n*Note*: This performs a live $0.50 authorization which is immediately refunded. Use with Stripe test keys for testing. For real cards, ensure you are using PaymentMethod IDs obtained via client-side tokenization.",
        "/status": "Usage: `/status`\nShows the current status and resource usage of the bot.",
        "/au": "Usage: `/au <group_id>`\nAuthorize a group to use the bot. Only for bot owner.",
    }

    message_text = escape_markdown_v2(details.get(command, "Details not found."))

    keyboard = [[InlineKeyboardButton("🔙 Back to Commands", callback_data="show_main_commands")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_text = update.message.text
    header_title = "𝘾𝙧𝙚𝙙𝙞𝙩 𝘾𝙖𝙧𝙙 𝙂𝙚𝙣𝙚𝙧𝙖𝙩𝙤𝙧"

    # Define a custom cooldown for this specific command (e.g., 2 seconds)
    cooldown_seconds = 2
    if chat_id in user_last_command and (time.time() - user_last_command[chat_id] < cooldown_seconds):
        remaining_time = int(cooldown_seconds - (time.time() - user_last_command[chat_id]))
        await update.message.reply_text(f"Please wait {remaining_time} seconds before using this command again.")
        return
    user_last_command[chat_id] = time.time()

    parts = re.search(r'^(?:/|\.)gen\s+(\d{6})(?:\|(\d{1,2}))?(?:\|(\d{2,4}))?(?:\|(\d{3,4}))?$', message_text)

    if not parts:
        await update.message.reply_text(
            escape_markdown_v2("Usage: `/gen BIN|MM|YY|CVV` or reply to a message.\nExample: `/gen 400000|12|25|123`"),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    bin_prefix = parts.group(1)
    month = parts.group(2)
    year = parts.group(3)
    cvv_length = int(parts.group(4)) if parts.group(4) else None

    if year and len(year) == 2:
        year = "20" + year if int(year) < 50 else "19" + year # Simple heuristic for 2-digit years
    elif year and len(year) == 3: # Handle 3-digit year like '024' -> 2024
        year = "20" + year if int(year) < 100 else year # Assuming 2000s
    elif year and len(year) == 4:
        pass # Already 4 digits
    else:
        year = str(random.randint(2025, 2030)) # Default if not provided

    if month:
        month = month.zfill(2) # Pad with leading zero if needed
    else:
        month = str(random.randint(1, 12)).zfill(2) # Default if not provided

    if not cvv_length:
        # Determine CVV length based on BIN, rudimentary check
        if bin_prefix.startswith('34') or bin_prefix.startswith('37'): # AMEX
            cvv_length = 4
        else:
            cvv_length = 3

    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    generated_card = generate_credit_card(bin_prefix, month, year)
    generated_cvv = ''.join(random.choices('0123456789', k=cvv_length))

    reply_message = (
        f"*{escape_markdown_v2(header_title)}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"• *𝗖𝗖* \: `{escape_markdown_v2(generated_card)}`\n"
        f"• *𝗘𝘅𝗽* \: `{escape_markdown_v2(month)}/{escape_markdown_v2(year)}`\n"
        f"• *𝗖𝗩𝗩* \: `{escape_markdown_v2(generated_cvv)}`\n"
        f"━━━━━━━━━━━━━━\n"
        f" *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n"
        f" *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎"
    )
    await update.message.reply_text(reply_message, parse_mode=ParseMode.MARKDOWN_V2)

def generate_credit_card(bin_prefix, month, year):
    length = 16
    cc_number = bin_prefix
    while len(cc_number) < length - 1:
        cc_number += str(random.randint(0, 9))

    # Calculate Luhn checksum
    checksum = luhn_checksum(cc_number)
    cc_number += str(checksum)
    return cc_number

def luhn_checksum(card_number):
    digits = [int(d) for d in card_number]
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    total = sum(digits)
    return (10 - (total % 10)) % 10

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_text = update.message.text
    header_title = "𝗕𝗜𝗡 𝗟𝗼𝗼𝗸𝘂𝗽 𝗥𝗲𝘀𝘂𝗹𝘁"

    # Define a custom cooldown for this specific command (e.g., 3 seconds)
    cooldown_seconds = 3
    if chat_id in user_last_command and (time.time() - user_last_command[chat_id] < cooldown_seconds):
        remaining_time = int(cooldown_seconds - (time.time() - user_last_command[chat_id]))
        await update.message.reply_text(f"Please wait {remaining_time} seconds before using this command again.")
        return
    user_last_command[chat_id] = time.time()

    bin_match = re.search(r'^(?:/|\.)bin\s+(\d{6})$', message_text)

    if not bin_match:
        await update.message.reply_text(
            escape_markdown_v2("Usage: `/bin BIN` or reply to a message.\nExample: `/bin 400000`"),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    bin_code = bin_match.group(1)

    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": BINTABLE_API_KEY}
            async with session.get(f"{BINTABLE_URL}/{bin_code}", headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

        if data.get("success"):
            bin_info = data.get("data", {})
            bank = bin_info.get("bank", {}).get("name", "N/A")
            country_name = bin_info.get("country", {}).get("name", "N/A")
            country_flag = bin_info.get("country", {}).get("emoji", "")
            card_type = bin_info.get("card", {}).get("type", "N/A")
            card_brand = bin_info.get("card", {}).get("brand", "N/A")
            card_level = bin_info.get("card", {}).get("level", "N/A")

            reply_message = (
                f"*{escape_markdown_v2(header_title)}*\n"
                f"━━━━━━━━━━━━━━\n"
                f"• *𝗕𝗜𝗡* \: `{escape_markdown_v2(bin_code)}`\n"
                f"• *𝗕𝗮𝗻𝗸* \: `{escape_markdown_v2(bank)}`\n"
                f"• *𝗖𝗼𝘂𝗻𝘁𝗿𝘆* \: `{escape_markdown_v2(country_name)} {escape_markdown_v2(country_flag)}`\n"
                f"• *𝗧𝘆𝗽𝗲* \: `{escape_markdown_v2(card_type)}`\n"
                f"• *𝗕𝗿𝗮𝗻𝗱* \: `{escape_markdown_v2(card_brand)}`\n"
                f"• *𝗟𝗲𝘃𝗲𝗹* \: `{escape_markdown_v2(card_level)}`\n"
                f"━━━━━━━━━━━━━━\n"
                f" *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n"
                f" *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝗺"
            )
        else:
            reason = data.get("message", "No info found for this BIN.")
            reply_message = (
                f"*{escape_markdown_v2(header_title)}*\n"
                f"━━━━━━━━━━━━━━\n"
                f"• *𝗕𝗜𝗡* \: `{escape_markdown_v2(bin_code)}`\n"
                f"• *𝗦𝘁𝗮𝘁𝘂𝘀* \: `DEAD`\n"
                f"• *𝗥𝗲𝗮𝘀𝗼𝗻* \: {escape_markdown_v2(reason)}\n"
                f"━━━━━━━━━━━━━━\n"
                f" *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n"
                f" *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝗺"
            )
    except aiohttp.ClientResponseError as e:
        logger.error(f"BIN lookup API error: {e}", exc_info=True)
        status_text = "ERROR"
        reason_text = f"API error: {e.status} {e.message}"
        reply_message = (
            f"*{escape_markdown_v2(header_title)}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"• *𝗕𝗜𝗡* \: `{escape_markdown_v2(bin_code)}`\n"
            f"• *𝗦𝘁𝗮𝘁𝘂𝘀* \: `{escape_markdown_v2(status_text)}`\n"
            f"• *𝗥𝗲𝗮𝘀𝗼𝗻* \: {escape_markdown_v2(reason_text)}\n"
            f"━━━━━━━━━━━━━━\n"
            f" *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n"
            f" *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎"
        )
    except Exception as e:
        logger.error(f"Error during BIN lookup: {e}", exc_info=True)
        status_text = "ERROR"
        reason_text = "An unexpected error occurred during BIN lookup."
        reply_message = (
            f"*{escape_markdown_v2(header_title)}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"• *𝗕𝗜𝗡* \: `{escape_markdown_v2(bin_code)}`\n"
            f"• *𝗦𝘁𝗮𝘁𝘂𝘀* \: `{escape_markdown_v2(status_text)}`\n"
            f"• *𝗥𝗲𝗮𝘀𝗼𝗻* \: {escape_markdown_v2(reason_text)}\n"
            f"━━━━━━━━━━━━━━\n"
            f" *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n"
            f" *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝒌𝑺𝒕𝒐𝒓𝒎"
        )
    await update.message.reply_text(reply_message, parse_mode=ParseMode.MARKDOWN_V2)


async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_text = update.message.text
    header_title = "𝗖𝗖 𝗖𝗵𝗲𝗰𝗸𝗲𝗿"

    cooldown_seconds = 5
    if chat_id in user_last_command and (time.time() - user_last_command[chat_id] < cooldown_seconds):
        remaining_time = int(cooldown_seconds - (time.time() - user_last_command[chat_id]))
        await update.message.reply_text(f"Please wait {remaining_time} seconds before using this command again.")
        return
    user_last_command[chat_id] = time.time()

    card_info_match = re.search(r'^(?:/|\.)kill\s+(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$', message_text)

    if not card_info_match:
        await update.message.reply_text(
            escape_markdown_v2("Usage: `/kill CC|MM|YY|CVV`\nExample: `/kill 4000000000000000|12|25|123`"),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    cc_number = card_info_match.group(1)
    exp_month = card_info_match.group(2)
    exp_year = card_info_match.group(3)
    cvv = card_info_match.group(4)
    bin_code = cc_number[:6]

    loading_message = await update.message.reply_text(escape_markdown_v2("Checking... Please wait ⏳"), parse_mode=ParseMode.MARKDOWN_V2)
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": BINTABLE_API_KEY}
            async with session.get(f"{BINTABLE_URL}/{bin_code}", headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

        status = "UNKNOWN"
        reason = "N/A"
        bin_info_str = "BIN Info: N/A"

        if data.get("success"):
            bin_info = data.get("data", {})
            card_brand = bin_info.get("card", {}).get("brand", "N/A")
            card_type = bin_info.get("card", {}).get("type", "N/A")
            country_name = bin_info.get("country", {}).get("name", "N/A")
            country_flag = bin_info.get("country", {}).get("emoji", "")
            bank_name = bin_info.get("bank", {}).get("name", "N/A")
            bin_info_str = (
                f"𝗕𝗿𝗮𝗻𝗱: `{escape_markdown_v2(card_brand)}`\n"
                f"𝗧𝘆𝗽𝗲: `{escape_markdown_v2(card_type)}`\n"
                f"𝗖𝗼𝘂𝗻𝘁𝗿𝘆: `{escape_markdown_v2(country_name)} {escape_markdown_v2(country_flag)}`\n"
                f"𝗕𝗮𝗻𝗸: `{escape_markdown_v2(bank_name)}`"
            )

            # Simulate card status
            if random.random() < 0.7: # 70% chance of being live
                status = "LIVE"
                reason = "Card is live."
            else:
                status = "DEAD"
                reason = "Card declined."
        else:
            status = "DEAD"
            reason = "BIN info not found."

        reply_message = (
            f"*{escape_markdown_v2(header_title)}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"• *𝗖𝗖* \: `{escape_markdown_v2(cc_number)}`\n"
            f"• *𝗘𝘅𝗽* \: `{escape_markdown_v2(exp_month)}/{escape_markdown_v2(exp_year)}`\n"
            f"• *𝗖𝗩𝗩* \: `{escape_markdown_v2(cvv)}`\n"
            f"• *𝗦𝘁𝗮𝘁𝘂𝘀* \: *{escape_markdown_v2(status)}*\n"
            f"• *𝗥𝗲𝗮𝘀𝗼𝗻* \: {escape_markdown_v2(reason)}\n"
            f"━━━━━━━━━━━━━━\n"
            f"{escape_markdown_v2(bin_info_str)}\n"
            f"━━━━━━━━━━━━━━\n"
            f" *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n"
            f" *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎"
        )
        await loading_message.edit_text(reply_message, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error(f"Error during kill command: {e}", exc_info=True)
        error_text = escape_markdown_v2(f"An error occurred: {str(e)}")
        await loading_message.edit_text(f"*{escape_markdown_v2(header_title)}*\n━━━━━━━━━━━━━━\n• *𝗦𝘁𝗮𝘁𝘂𝘀* \: `ERROR`\n• *𝗥𝗲𝗮𝘀𝗼𝗻* \: {error_text}\n━━━━━━━━━━━━━━\n *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝒌𝑺𝒕𝒐𝒓𝒎", parse_mode=ParseMode.MARKDOWN_V2)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    header_title = "📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘂𝘀"

    cooldown_seconds = 10
    if chat_id in user_last_command and (time.time() - user_last_command[chat_id] < cooldown_seconds):
        remaining_time = int(cooldown_seconds - (time.time() - user_last_command[chat_id]))
        await update.message.reply_text(f"Please wait {remaining_time} seconds before using this command again.")
        return
    user_last_command[chat_id] = time.time()

    # Get CPU usage
    cpu_percent = psutil.cpu_percent(interval=1)
    # Get RAM usage
    ram = psutil.virtual_memory()
    ram_percent = ram.percent
    ram_used = round(ram.used / (1024 ** 3), 2)
    ram_total = round(ram.total / (1024 ** 3), 2)

    # Get uptime
    boot_time_timestamp = psutil.boot_time()
    boot_time_datetime = datetime.fromtimestamp(boot_time_timestamp)
    current_time = datetime.now()
    uptime = current_time - boot_time_datetime
    # Format uptime nicely
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    seconds = uptime.seconds % 60
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"


    status_message = (
        f"*{escape_markdown_v2(header_title)}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"• *𝗖𝗣𝗨* \: `{escape_markdown_v2(str(cpu_percent))}%`\n"
        f"• *𝗥𝗔𝗠* \: `{escape_markdown_v2(str(ram_used))}GB / {escape_markdown_v2(str(ram_total))}GB ({escape_markdown_v2(str(ram_percent))}%)`\n"
        f"• *𝗨𝗽𝘁𝗶𝗺𝗲* \: `{escape_markdown_v2(uptime_str)}`\n"
        f"━━━━━━━━━━━━━━\n"
        f" *𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆* \-: 『{escape_markdown_v2(update.effective_user.first_name)}』\n"
        f" *𝗕𝒐𝒕 𝒃𝒚* \-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝗺"
    )
    await update.message.reply_text(status_message, parse_mode=ParseMode.MARKDOWN_V2)


async def authorize_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(escape_markdown_v2("You are not the owner of this bot."), parse_mode=ParseMode.MARKDOWN_V2)
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(escape_markdown_v2("Usage: `/au <group_id>`"), parse_mode=ParseMode.MARKDOWN_V2)
        return

    group_id = int(context.args[0])
    # In a real application, you would save this group_id to a database or file
    # For this example, we'll just acknowledge it.
    await update.message.reply_text(escape_markdown_v2(f"Group `{group_id}` has been authorized\. \(Authorization not persisted in this example\)"), parse_mode=ParseMode.MARKDOWN_V2)


# === MAIN APPLICATION SETUP ===
def main():
    if not TOKEN:
        logger.error("BOT_TOKEN environment variable is not set. Exiting.")
        exit(1)
    if OWNER_ID is None:
        logger.warning("OWNER_ID environment variable is not set. /au command will not be restricted to an owner.")

    application = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("kill", kill, filters=filters.ChatType.PRIVATE | filters.ChatType.GROUPS))
    application.add_handler(CommandHandler("chk", stripe_auth_check, filters=filters.ChatType.PRIVATE | filters.ChatType.GROUPS)) # Added Stripe command
    application.add_handler(CommandHandler("au", authorize_group))


    # Message handlers for dot commands
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.gen\b.*"), gen))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.bin\b.*"), bin_lookup))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.kill\b.*") & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS), kill))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.chk\b.*") & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS), stripe_auth_check)) # Added Stripe message handler

    # Callback query handlers for inline keyboard buttons
    application.add_handler(CallbackQueryHandler(show_main_commands, pattern="^show_main_commands$"))
    application.add_handler(CallbackQueryHandler(show_command_details, pattern="^cmd_"))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_start$"))

    # Add the error handler
    application.add_handler(application.add_error_handler(error_handler))


    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
