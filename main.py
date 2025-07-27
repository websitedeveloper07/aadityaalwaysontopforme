import os
import time
import logging
import asyncio
import aiohttp
import psutil
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# === CONFIGURATION ===
# Load bot token and owner ID from environment variables for security.
# IMPORTANT: Set these environment variables before running the bot.
# Example for Linux/macOS:
# export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
# export OWNER_ID="YOUR_TELEGRAM_USER_ID"
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

# A set to store chat IDs of groups authorized to use the bot's commands.
# The official group chat ID is pre-authorized here.
AUTHORIZED_GROUPS = {-1002675283650} # Your specified official group chat ID

# Dictionary to store the last command execution time for each user,
# used to implement a global cooldown.
user_last_command = {}

# === LOGGING SETUP ===
# Configure basic logging to output informational messages to the console.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === HELPER FUNCTIONS ===

def escape_markdown_v2(text):
    """
    Helper function to escape special characters for MarkdownV2.
    This is crucial for dynamic content that might contain Markdown special characters.
    """
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

def luhn_checksum(card_number):
    """
    Validates a credit card number using the Luhn algorithm (Mod 10 algorithm).
    This algorithm is commonly used to validate credit card numbers and other
    identification numbers.
    """
    def digits_of(n): return [int(d) for d in str(n)]
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]  # Digits at odd positions from the right (1st, 3rd, etc.)
    even_digits = digits[-2::-2] # Digits at even positions from the right (2nd, 4th, etc.)

    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d * 2)) # Double even digits and sum their individual digits
    return checksum % 10 == 0 # Returns True if checksum is a multiple of 10, False otherwise.

async def fetch_bin_info(bin_number):
    """
    Asynchronously fetches basic BIN information from the free binlist.net API.
    """
    url = f"https://lookup.binlist.net/{bin_number}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"BIN API returned status {resp.status} for BIN: {bin_number}")
                    return None # Return None on non-200 status
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching BIN info for {bin_number}: {e}")
        return None # Return None on network error
    except Exception as e:
        logger.error(f"An unexpected error occurred fetching BIN info for {bin_number}: {e}")
        return None # Return None on any other unexpected error

async def fetch_bin_level_info(bin_number):
    """
    Asynchronously fetches detailed BIN information, including card level, from a
    more comprehensive (paid) API.
    
    NOTE: This is a placeholder function. To get real card levels (Gold, Platinum, etc.),
    you MUST replace this with an actual API call to a service that provides this data
    (e.g., Bincodes.com, Stripe's BIN API if you have a payment gateway setup, etc.).
    These services usually require an API key and may have usage limits.
    """
    # Example placeholder for a real API call:
    # api_key = "YOUR_API_KEY_HERE"
    # url = f"https://api.example.com/bin_lookup?bin={bin_number}&api_key={api_key}"
    # try:
    #     async with aiohttp.ClientSession() as session:
    #         async with session.get(url) as resp:
    #             if resp.status == 200:
    #                 data = await resp.json()
    #                 # Assuming the real API returns something like:
    #                 # {"bin": "...", "card_category": "GOLD", "card_type": "CREDIT", ...}
    #                 return {"card_category": data.get("card_category", "Unknown")}
    #             else:
    #                 logger.warning(f"Level API returned status {resp.status} for BIN: {bin_number}")
    #                 return {"card_category": "N/A (API Error)"}
    # except aiohttp.ClientError as e:
    #     logger.error(f"Network error fetching BIN level info for {bin_number}: {e}")
    #     return {"card_category": "N/A (Network Error)"}
    # except Exception as e:
    #     logger.error(f"An unexpected error occurred fetching BIN level info for {bin_number}: {e}")
    #     return {"card_category": "N/A (Internal Error)"}

    # For now, return a placeholder indicating real API is needed
    return {"card_category": "N/A (Requires external API)"}

async def enforce_cooldown(user_id):
    """
    Enforces a 5-second cooldown period between commands for each individual user.
    This prevents users from spamming commands rapidly.
    Returns True if the command can proceed (cooldown has passed), False otherwise.
    """
    now = time.time()
    last_time = user_last_command.get(user_id, 0)
    if now - last_time < 5: # If less than 5 seconds have passed since last command
        return False
    user_last_command[user_id] = now # Update last command time
    return True

# === COMMAND HANDLERS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command and the 'back_to_start' callback.
    Sends/edits to the initial welcome message with bot status and inline buttons.
    """
    user = update.effective_user
    welcome = f"👋 Hi, welcome {user.full_name}!\n🤖 Bot Status: Active"
    buttons = [
        [InlineKeyboardButton("📜 Commands", callback_data="show_main_commands")],
        [InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")] # Your group link
    ]
    
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(welcome, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(buttons))


async def show_main_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays a list of available commands as inline buttons.
    This function is called when the 'Commands' button is pressed.
    It's designed for interactive use in private chats.
    """
    query = update.callback_query
    if query:
        await query.answer()

    commands_text = "📜 *Bot Commands:*\nSelect a command to learn more:"
    buttons = [
        [InlineKeyboardButton("💳 Generate Cards (/gen)", callback_data="cmd_gen")],
        [InlineKeyboardButton("🔍 BIN Info (/bin)", callback_data="cmd_bin")],
        [InlineKeyboardButton("📊 Bot Status (/status)", callback_data="cmd_status")],
        [InlineKeyboardButton("⬅️ Back to Start", callback_data="back_to_start")] # Added back button
    ]
    
    if query:
        # Using ParseMode.MARKDOWN for this menu as it's less strict and doesn't require escaping for most characters
        await query.edit_message_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

async def show_command_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays detailed usage information for a specific command.
    Triggered by inline buttons for individual commands (e.g., 'cmd_gen').
    Includes a 'Back' button to return to the main command list.
    """
    query = update.callback_query
    await query.answer()

    command_name = query.data.replace("cmd_", "")
    
    usage_text = ""
    if command_name == "gen":
        usage_text = """*💳 Generate Cards*
Usage: `/gen [bin]` or `\\.gen [bin]`
Example: `/gen 453957`
Generates 10 credit card numbers based on the provided BIN\\.\\
*Note:* This command works only in authorized groups\\.\\
"""
    elif command_name == "bin":
        usage_text = """*🔍 BIN Info*
Usage: `/bin [bin]` or `\\.bin [bin]`
Example: `/bin 518765`
Provides detailed information about a given BIN\\.\\
*Note:* This command works only in authorized groups\\.\\
"""
    elif command_name == "status":
        usage_text = """*📊 Bot Status*
Usage: `/status`
Displays the bot's current operational status, including user count, RAM/CPU usage, and uptime\\.\\
*Note:* This command works only in authorized groups\\.\\
"""
    elif command_name == "au":
        usage_text = """*🔐 Authorize Group*
Usage: `/au [chat_id]`
Example: `/au \-100123456789`
Authorizes a specific group to use the bot's features\\.\\
*Note:* This command can only be used by the bot owner\\.\\
"""
    else:
        usage_text = "Unknown command\\. Please go back and select a valid command\\.\\"

    back_button = [[InlineKeyboardButton("⬅️ Back to Commands", callback_data="show_main_commands")]]
    await query.edit_message_text(usage_text, reply_markup=InlineKeyboardMarkup(back_button), parse_mode=ParseMode.MARKDOWN_V2)

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Generates credit card numbers based on a provided BIN.
    This command is restricted to authorized group chats and has a cooldown.
    """
    if update.effective_chat.type not in ["group", "supergroup"]:
        button = InlineKeyboardMarkup([[InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")]])
        return await update.message.reply_text("Join our official group to use this bot.", reply_markup=button)

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

    bin_data = await fetch_bin_info(bin_input[:6])
    level_data = await fetch_bin_level_info(bin_input[:6]) # Fetch level info

    if not bin_data:
        return await update.message.reply_text("❌ Could not retrieve BIN information\\. Please try again later or check the BIN\\.", parse_mode=ParseMode.MARKDOWN_V2)

    bank = bin_data.get("bank", {}).get("name", "Unknown")
    country_name = bin_data.get("country", {}).get("name", "Unknown")
    country_emoji = bin_data.get("country", {}).get("emoji", '')
    brand = bin_data.get("scheme", "Unknown").capitalize()
    level = level_data.get("card_category", "N/A").capitalize() # Get level from level_data

    # Escape dynamic text for MarkdownV2
    escaped_brand = escape_markdown_v2(brand)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country = escape_markdown_v2(f"{country_name} {country_emoji}".strip())
    escaped_level = escape_markdown_v2(level)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)
    
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
    
    result = (
        f"Generated 10 Cards\n\n"
        f"{cards_list}\n\n"
        f"> *💳 Brand*: {escaped_brand}\n"
        f"> *🏦 Bank*: {escaped_bank}\n"
        f"> *🌍 Country*: {escaped_country}\n"
        f"> *💠 Level*: {escaped_level}\n" # Included Level
        f"> *🧾 BIN*: `{bin_input}`\n"
        f"> *🙋 Requested by \\-*: {escaped_user_full_name}\n"
        f"> *🤖 Bot by \\-*: Your Friend"
    )
    
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Performs a BIN lookup using the external API and displays the information.
    """
    if update.effective_chat.type not in ["group", "supergroup"]:
        button = InlineKeyboardMarkup([[InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")]])
        return await update.message.reply_text("Join our official group to use this bot.", reply_markup=button)

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
    
    bin_data = await fetch_bin_info(bin_input)
    level_data = await fetch_bin_level_info(bin_input) # Fetch level info

    if not bin_data:
        return await update.message.reply_text("❌ Could not retrieve BIN information\\. Please try again later or check the BIN\\.", parse_mode=ParseMode.MARKDOWN_V2)

    bank = bin_data.get("bank", {}).get("name", "Unknown")
    country_name = bin_data.get("country", {}).get("name", "Unknown")
    country_emoji = bin_data.get("country", {}).get("emoji", '')
    scheme = bin_data.get("scheme", "Unknown").capitalize()
    card_type = bin_data.get("type", "Unknown").capitalize()
    level = level_data.get("card_category", "N/A").capitalize() # Get level from level_data

    # Escape dynamic text for MarkdownV2
    escaped_scheme = escape_markdown_v2(scheme)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country = escape_markdown_v2(f"{country_name} {country_emoji}".strip())
    escaped_card_type = escape_markdown_v2(card_type)
    escaped_level = escape_markdown_v2(level)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)

    # Construct the final response message with proper MarkdownV2 formatting
    result = (
        f"╔══════════════════════╗\n"
        f"║ 💳 \\*\\*𝐁𝐈𝐍 𝐈𝐍𝐅𝐎𝐑𝐌𝐀𝐓𝐈𝐎𝐍\\*\\* ║\n"
        f"╚══════════════════════╝\n"
        f"* **Brand**: {escaped_scheme}\n"
        f"* **Bank**: {escaped_bank}\n"
        f"* **Type**: {escaped_card_type}\n"
        f"* **Level**: {escaped_level}\n" # Included Level with bullet
        f"* **Country**: {escaped_country}\n"
        f"* **Bin**: `{bin_input}`\n"
        f"Requested by \\- {escaped_user_full_name}\n"
        f"Bot by \\- Your Friend"
    )
    
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays the bot's current operational status (users, RAM, CPU, uptime).
    """
    if update.effective_chat.type not in ["group", "supergroup"]:
        return await update.message.reply_text("🔒 This command can only be used in the group.")

    total_users = len(user_last_command)
    
    ram_mb = psutil.virtual_memory().used / (1024 * 1024)
    ram_usage = f"{ram_mb:.0f} MB"
    
    cpu_usage_percent = psutil.cpu_percent()
    escaped_cpu_usage_text = escape_markdown_v2(str(cpu_usage_percent)) + "\\%"
    
    uptime_seconds = int(time.time() - psutil.boot_time())
    uptime_delta = timedelta(seconds=uptime_seconds)
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_string = f"{hours} hours {minutes} minutes"

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
    """
    Authorizes a specific group to use the bot's features.
    This command is restricted to the bot owner.
    """
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
    """
    Main function to build and run the Telegram bot application.
    """
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

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
