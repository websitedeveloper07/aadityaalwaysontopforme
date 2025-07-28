import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# === CONFIGURATION ===
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

BINTABLE_API_KEY = "2504e1938a63e931f65c90cee460c7ef8c418252"
BINTABLE_URL = "https://api.bintable.com/v1"

AUTHORIZED_GROUPS = {-1002675283650}

user_last_command = {}

# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === ERROR HANDLER ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Try to send a message back to the user
    if update.effective_message:
        await update.effective_message.reply_text(
            "An error occurred while processing your request. Please try again later."
        )

# === HELPER FUNCTIONS ===

def escape_markdown_v2(text):
    if text is None:
        return "Unknown"
    text = str(text)
    # List of special characters in MarkdownV2 that need to be escaped
    # See: https://core.telegram.org/bots/api#markdownv2-style
    special_chars = '_*[]()~`>#+-=|{}.!'
    escaped_text = ""
    for char in text:
        if char in special_chars:
            escaped_text += '\\' + char
        else:
            escaped_text += char
    return escaped_text

def get_short_country_name(full_name):
    if not full_name:
        return "Unknown"
    
    name_map = {
        "United States of America": "United States",
        "Russian Federation": "Russia",
        "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
        "Republic of Korea": "South Korea",
        "Islamic Republic of Iran": "Iran",
        "Venezuela (Bolivarian Republic of)": "Venezuela",
        "Viet Nam": "Vietnam",
        "Lao People's Democratic Republic": "Laos",
        "Democratic Republic of the Congo": "DR Congo",
        "Congo (Democratic Republic of the)": "Congo",
        "Tanzania, United Republic of": "Tanzania",
        "Syrian Arab Republic": "Syria",
        "Bolivia (Plurinational State of)": "Bolivia",
        "Brunei Darussalam": "Brunei",
        "Cabo Verde": "Cape Verde",
        "Central African Republic": "Central African Republic",
        "Comoros": "Comoros",
        "Côte d'Ivoire": "Ivory Coast",
        "Democratic People's Republic of Korea": "North Korea",
        "Dominican Republic": "Dominican Republic",
        "Equatorial Guinea": "Equatorial Guinea",
        "Eswatini": "Eswatini",
        "Falkland Islands (Malvinas)": "Falkland Islands",
        "Gambia (the)": "Gambia",
        "Guinea-Bissau": "Guinea-Bissau",
        "Holy See": "Vatican City",
        "Iran (Islamic Republic of)": "Iran",
        "Lao People's Democratic Republic": "Laos",
        "Libya": "Libya",
        "Macedonia (the former Yugoslav Republic of)": "North Macedonia",
        "Micronesia (Federated States of)": "Micronesia",
        "Moldova (Republic of)": "Moldova",
        "Mozambique": "Mozambique",
        "Myanmar": "Myanmar",
        "Niger (the)": "Niger",
        "Palestine, State of": "Palestine",
        "Saint Helena, Ascension and Tristan da Cunha": "Saint Helena",
        "Sao Tome and Principe": "Sao Tome and Principe",
        "Serbia": "Serbia",
        "Slovakia": "Slovakia",
        "Slovenia": "Slovenia",
        "Somalia": "Somalia",
        "South Georgia and the South Sandwich Islands": "South Georgia",
        "South Sudan": "South Sudan",
        "Sudan (the)": "Sudan",
        "Svalbard and Jan Mayen": "Svalbard",
        "Timor-Leste": "Timor-Leste",
        "Togo": "Togo",
        "Tokelau": "Tokelau",
        "Tonga": "Tonga",
        "Trinidad and Tobago": "Trinidad and Tobago",
        "Tunisia": "Tunisia",
        "Turkey": "Turkey",
        "Turkmenistan": "Turkmenistan",
        "Turks and Caicos Islands (the)": "Turks and Caicos",
        "Tuvalu": "Tuvalu",
        "Uganda": "Uganda",
        "Ukraine": "Ukraine",
        "United Arab Emirates (the)": "United Arab Emirates",
        "United States Minor Outlying Islands (the)": "US Outlying Islands",
        "Uruguay": "Uruguay",
        "Uzbekistan": "Uzbekistan",
        "Vanuatu": "Vanuatu",
        "Venezuela (Bolivarian Republic of)": "Venezuela",
        "Wallis and Futuna": "Wallis and Futuna",
        "Western Sahara": "Western Sahara",
        "Yemen": "Yemen",
        "Zambia": "Zambia",
        "Zimbabwe": "Zimbabwe",
    }

    if full_name in name_map:
        return name_map[full_name]

    cleaned_name = re.sub(r'\s*\(.*\)\s*', '', full_name).strip()
    cleaned_name = re.sub(r'\s*of\s+.*$', '', cleaned_name).strip()
    
    words = cleaned_name.split()
    if len(words) > 2 and words[1].lower() in ["republic", "kingdom", "states", "federation"]:
        return " ".join(words[:2])
    elif len(words) > 1 and words[0].lower() == "the":
        return " ".join(words[1:])
    
    return cleaned_name

def luhn_checksum(card_number):
    def digits_of(n): return [int(d) for d in str(n)]
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]

    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d * 2))
    return checksum % 10 == 0

def get_level_emoji(level):
    level_map = {
        "Classic": "💳",
        "Gold": "✨",
        "Platinum": "💎",
        "Infinite": "♾️",
        "Signature": "✍️",
        "Business": "💼",
        "Corporate": "🏢",
        "Prepaid": "🎁",
        "Debit": "💸",
        "Credit": "💰",
        "Standard": "🌟"
    }
    return level_map.get(level, "❓")

def get_vbv_status_display(status):
    # Since VBV bot logic is removed, status will always be N/A
    return f"❓ {escape_markdown_v2(status)}"

async def fetch_bin_info_bintable(bin_number):
    url = f"{BINTABLE_URL}/{bin_number}?api_key={BINTABLE_API_KEY}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("result") == 200 and data.get("data"):
                        return data["data"]
                    else:
                        logger.warning(f"Bintable API reported an error or no data for BIN {bin_number}. Response: {data}")
                        return None
                else:
                    logger.warning(f"Bintable API returned HTTP status {resp.status} for BIN: {bin_number}")
                    return None
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching from Bintable for {bin_number}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred fetching from Bintable for {bin_number}: {e}")
        return None

async def fetch_bin_info_binlist(bin_number):
    url = f"https://lookup.binlist.net/{bin_number}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"Binlist API returned status {resp.status} for BIN: {bin_number}")
                    return None
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching from Binlist for {bin_number}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred fetching from Binlist for {bin_number}: {e}")
        return None

async def fetch_bin_info_bincheckio(bin_number):
    url = f"https://api.bincheck.io/bin/{bin_number}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "ok":
                        return data
                    else:
                        logger.warning(f"Bincheck.io API returned status '{data.get('status')}' for BIN: {bin_number}")
                        return None
                else:
                    logger.warning(f"Bincheck.io API returned HTTP status {resp.status} for BIN: {bin_number}")
                    return None
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching from Bincheck.io for {bin_number}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred fetching from Bincheck.io for {bin_number}: {e}")
        return None

async def get_bin_details(bin_number):
    """
    Attempts to fetch BIN details from multiple APIs with fallback.
    VBV status will always be N/A.
    """
    details = {
        "bank": "Unknown",
        "country_name": "Unknown",
        "country_emoji": "",
        "scheme": "Unknown",
        "card_type": "Unknown",
        "level": "N/A",
        "vbv_status": "N/A" # Always N/A
    }
    
    bintable_data = await fetch_bin_info_bintable(bin_number)
    
    if bintable_data:
        bank_info = bintable_data.get("bank", {})
        country_info = bintable_data.get("country", {})
        card_info = bintable_data.get("card", {})

        details["bank"] = bank_info.get("name", details["bank"])
        details["country_name"] = country_info.get("name", details["country_name"])
        details["country_emoji"] = country_info.get("flag", details["country_emoji"]) 
        details["scheme"] = card_info.get("scheme", details["scheme"]).capitalize()
        details["card_type"] = card_info.get("type", details["card_type"]).capitalize()
        details["level"] = card_info.get("category", details["level"]).capitalize()
    else:
        binlist_data = await fetch_bin_info_binlist(bin_number)
        if binlist_data:
            details["bank"] = binlist_data.get("bank", {}).get("name", details["bank"])
            details["country_name"] = binlist_data.get("country", {}).get("name", details["country_name"])
            details["country_emoji"] = binlist_data.get("country", {}).get("emoji", details["country_emoji"])
            details["scheme"] = binlist_data.get("scheme", details["scheme"]).capitalize()
            details["card_type"] = binlist_data.get("type", details["card_type"]).capitalize()
        else:
            bincheck_data = await fetch_bin_info_bincheckio(bin_number)
            if bincheck_data:
                details["bank"] = bincheck_data.get("bank", {}).get("name", details["bank"])
                details["country_name"] = bincheck_data.get("country", {}).get("name", details["country_name"])
                details["country_emoji"] = bincheck_data.get("country", {}).get("emoji", details["country_emoji"])
                details["scheme"] = bincheck_data.get("brand", details["scheme"]).capitalize()
                details["card_type"] = bincheck_data.get("type", details["card_type"]).capitalize()
                details["level"] = bincheck_data.get("level", details["level"]).capitalize()

    details["country_name"] = get_short_country_name(details["country_name"])
    
    return details

async def enforce_cooldown(user_id):
    now = time.time()
    last_time = user_last_command.get(user_id, 0)
    if now - last_time < 5:
        return False
    user_last_command[user_id] = now
    return True

# === COMMAND HANDLERS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome = f"👋 Hi, welcome {user.full_name}!\n🤖 Bot Status: Active"
    buttons = [
        [InlineKeyboardButton("📜 Commands", callback_data="show_main_commands")],
        [InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")]
    ]
    
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(welcome, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(buttons))

async def show_main_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    commands_text = "📜 *Bot Commands:*\nSelect a command to learn more:"
    buttons = [
        [InlineKeyboardButton("💳 Generate Cards (/gen)", callback_data="cmd_gen")],
        [InlineKeyboardButton("🔍 BIN Info (/bin)", callback_data="cmd_bin")],
        [InlineKeyboardButton("📊 Bot Status (/status)", callback_data="cmd_status")],
        [InlineKeyboardButton("⬅️ Back to Start", callback_data="back_to_start")]
    ]
    
    if query:
        await query.edit_message_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

async def show_command_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    command_name = query.data.replace("cmd_", "")
    
    usage_text = ""
    if command_name == "gen":
        usage_text = (
            "*💳 Generate Cards*\n" +
            "Usage: `/gen [bin]` or `\\.gen [bin]`\n" +
            "Example: `/gen 453957`\n" +
            "Generates 10 credit card numbers based on the provided BIN\\.\\\n" +
            "*Note:* This command works only in authorized groups\\.\n"
        ).strip()
    elif command_name == "bin":
        usage_text = (
            "*🔍 BIN Info*\n" +
            "Usage: `/bin [bin]` or `\\.bin [bin]`\n" +
            "Example: `/bin 518765`\n" +
            "Provides detailed information about a given BIN\\.\\\n" +
            "*Note:* This command works only in authorized groups\\.\n"
        ).strip()
    elif command_name == "status":
        usage_text = (
            "*📊 Bot Status*\n" +
            "Usage: `/status`\n" +
            "Example: `/status`\n" +
            "Displays the bot's current operational status, including user count, RAM/CPU usage, and uptime\\.\\\n" +
            "*Note:* This command works only in authorized groups\\.\n"
        ).strip()
    elif command_name == "au":
        usage_text = (
            "*🔐 Authorize Group*\n" +
            "Usage: `/au [chat_id]`\n" +
            "Example: `/au \\-100123456789`\n" +
            "Authorizes a specific group to use the bot's features\\.\\\n" +
            "*Note:* This command can only be used by the bot owner\\.\n"
        ).strip()
    else:
        usage_text = "Unknown command\\. Please go back and select a valid command\\.\\"

    back_button = [[InlineKeyboardButton("⬅️ Back to Commands", callback_data="show_main_commands")]]
    await query.edit_message_text(usage_text, reply_markup=InlineKeyboardMarkup(back_button), parse_mode=ParseMode.MARKDOWN_V2)

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        button = InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")
        return await update.message.reply_text("Join our official group to use this bot.", reply_markup=InlineKeyboardMarkup([[button]]))

    chat_id = update.effective_chat.id
    if chat_id not in AUTHORIZED_GROUPS:
        return await update.message.reply_text("🚫 This group is not authorized to use the bot.")

    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying.")

    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.message.text:
        command_text = update.message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]

    if not bin_input:
        return await update.message.reply_text("❌ Please provide a 6\\-digit BIN\\. Usage: `/gen [bin]` or `\\.gen [bin]`\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if len(bin_input) < 6:
        return await update.message.reply_text("⚠️ BIN should be at least 6 digits\\.", parse_mode=ParseMode.MARKDOWN_V2)

    bin_details = await get_bin_details(bin_input[:6])

    brand = bin_details["scheme"]
    bank = bin_details["bank"]
    country_name = bin_details['country_name']
    country_emoji = bin_details['country_emoji']
    card_type = bin_details["card_type"]
    
    cards = []
    while len(cards) < 10:
        num = bin_input + ''.join(str(os.urandom(1)[0] % 10) for _ in range(16 - len(bin_input)))
        if not luhn_checksum(num):
            continue
        
        mm = str(os.urandom(1)[0] % 12 + 1).zfill(2)
        yyyy = str(datetime.now().year + os.urandom(1)[0] % 6)
        
        cvv_length = 4 if brand == 'American Express' else 3
        cvv = str(os.urandom(1)[0] % (10**cvv_length)).zfill(cvv_length)
        
        cards.append(f"`{num}|{mm}|{yyyy[-2:]}|{cvv}`")

    cards_list = "\n".join(cards)
    
    escaped_brand = escape_markdown_v2(brand)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country_name = escape_markdown_v2(country_name)
    escaped_country_emoji = escape_markdown_v2(country_emoji)
    escaped_card_type = escape_markdown_v2(card_type)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)
    
    # BIN info block content for /gen, using "=>" and no bolding, with escaped hyphen
    bin_info_block_content = (
        f"BIN\\-LOOKUP\n" # Escaped hyphen
        f"BIN => `{bin_input}`\n"
        f"Country => {escaped_country_name} {escaped_country_emoji}\n"
        f"Type => {escaped_card_type}\n"
        f"Bank => {escaped_bank}"
    )

    user_info_block_content = (
        f"Requested by \\-\\> {escaped_user_full_name}\n"
        f"Bot by \\-\\> Your Friend"
    )

    result = (
        f"Generated 10 Cards 💳\n"
        f"\n"
        f"{cards_list}\n"
        f"\n"
        f"> {bin_info_block_content.replace('\n', '\n> ')}\n"
        f"> \n"
        f"> {user_info_block_content.replace('\n', '\n> ')}"
    )

    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        button = InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")
        return await update.message.reply_text("Join our official group to use this bot.", reply_markup=InlineKeyboardMarkup([[button]]))

    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying.")

    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.message.text:
        command_text = update.message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]

    if not bin_input:
        return await update.message.reply_text("❌ Please provide a 6\\-digit BIN\\. Usage: `/bin [bin]` or `\\.bin [bin]`\\.", parse_mode=ParseMode.MARKDOWN_V2)

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
    
    # Main BIN info box - made narrower for mobile
    bin_info_box = (
        f"╔═══════ BIN INFO ═══════╗\n"
        f"✦ BIN    : `{bin_input}`\n"
        f"✦ Status : {status_display}\n"
        f"✦ Brand  : {escaped_scheme}\n"
        f"✦ Type   : {escaped_card_type}\n"
        f"✦ Level  : {level_emoji} {escaped_level}\n"
        f"✦ Bank   : {escaped_bank}\n"
        f"✦ Country: {escaped_country_name} {escaped_country_emoji}\n"
        f"╚════════════════════════╝"
    )

    # User info in a separate quote box
    user_info_quote_box = (
        f"> Requested by \\-: {escaped_user_full_name}\n"
        f"> Bot by \\-: Your Friend"
    )

    result = f"{bin_info_box}\n\n{user_info_quote_box}"
    
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        return await update.message.reply_text("🔒 This command can only be used in the group.")

    total_users = len(user_last_command)
    
    ram_mb = psutil.virtual_memory().used / (1024 * 1024)
    ram_usage = f"{ram_mb:.0f} MB"
    
    cpu_usage_percent = psutil.cpu_percent()
    escaped_cpu_usage_text = escape_markdown_v2(str(cpu_usage_percent)) + "\\%"
    
    uptime_seconds = int(time.time() - psutil.boot_time())
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    
    uptime_parts = []
    if days > 0:
        uptime_parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours > 0:
        uptime_parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes > 0:
        uptime_parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    
    uptime_string = ", ".join(uptime_parts) if uptime_parts else "less than a minute"

    escaped_total_users = escape_markdown_v2(str(total_users))
    escaped_ram_usage = escape_markdown_v2(ram_usage)
    escaped_uptime_string = escape_markdown_v2(uptime_string)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)

    status_msg = (
        f"> 📊 Bot Status\n"
        f"> 👥 Total Users: {escaped_total_users}\n"
        f"> 🧠 RAM Usage: {escaped_ram_usage}\n"
        f"> 🖥️ CPU Usage: {escaped_cpu_usage_text}\n"
        f"> ⏱️ Uptime: {escaped_uptime_string}\n"
        f"> 🤖 Bot by \\- Your Friend"
    )
    
    await update.message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN_V2)

async def authorize_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this command.")
    if not context.args:
        return await update.message.reply_text("Usage: `/au [chat_id]`\\. Please provide a chat ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
    
    try:
        chat_id_to_authorize = int(context.args[0])
        AUTHORIZED_GROUPS.add(chat_id_to_authorize)
        await update.message.reply_text(f"✅ Group `{chat_id_to_authorize}` is now authorized to use the bot\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await update.message.reply_text("❌ Invalid chat ID\\. Please provide a numeric chat ID\\.", parse_mode=ParseMode.MARKDOWN_V2)

# === MAIN APPLICATION SETUP ===
def main():
    if TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set. Please set it before running the bot.")
        exit(1)
    if OWNER_ID is None:
        logger.error("OWNER_ID environment variable is not set. Please set it before running the bot.")
        exit(1)
    
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("au", authorize_group))

    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.gen\b.*"), gen))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.bin\b.*"), bin_lookup))

    application.add_handler(CallbackQueryHandler(show_main_commands, pattern="^show_main_commands$"))
    application.add_handler(CallbackQueryHandler(show_command_details, pattern="^cmd_"))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_start$"))

    # Add the error handler
    application.add_error_handler(error_handler)

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
