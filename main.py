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

def _escape_markdown_v2_text(text: str) -> str:
    """
    Escapes characters that have special meaning in MarkdownV2.
    This is crucial for dynamic text that might contain these characters.
    """
    # List of characters that need to be escaped in MarkdownV2
    # This list covers all characters that can be problematic.
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    
    # Use a regular expression to find and escape each special character
    # `re.sub` replaces occurrences of characters in `escape_chars` with their escaped version.
    # The `|` creates an OR condition for the regex, and `\` escapes the character itself.
    # Example: `r'([_*\[\]()~`>#+\-=|{}.!])'` will match any of these characters literally.
    # The `r''` prefix makes it a raw string, which is good for regex patterns.
    # The `\` before each special char in `escape_chars` in the regex pattern is to
    # treat them as literal characters for the regex engine itself.
    # The `\` in the replacement string `\\` is to ensure a literal backslash is inserted.
    
    # The pattern needs to be built carefully to escape the regex special characters themselves
    # before they are used in the regex to match the Markdown special characters.
    import re
    
    # Escape characters that are special in regex itself
    regex_special_chars = r'[\^$.|?*+(){}\[\]]'
    escaped_for_regex = ''.join([f'\\{c}' if c in regex_special_chars else c for c in escape_chars])
    
    # Create the final regex pattern to match MarkdownV2 special characters
    pattern = f"([{re.escape(escape_chars)}])"
    
    # Replace matched characters with their escaped version
    return re.sub(pattern, r'\\\1', text)


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
    Asynchronously fetches BIN (Bank Identification Number) information
    from the binlist.net API. This function makes an HTTP GET request.
    """
    url = f"https://lookup.binlist.net/{bin_number}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"BIN API returned status {resp.status} for BIN: {bin_number}")
                    return None
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching BIN info for {bin_number}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred fetching BIN info for {bin_number}: {e}")
        return None

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
        # Removed "Authorize Group" from this menu as it's owner-only and primarily for groups.
        # It's still accessible via the /au command for the owner.
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
    # Check if the command is used in a group or supergroup
    if update.effective_chat.type not in ["group", "supergroup"]:
        button = InlineKeyboardMarkup([[InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")]])
        return await update.message.reply_text("Join our official group to use this bot.", reply_markup=button)

    chat_id = update.effective_chat.id
    # Check if the current group is authorized to use the bot
    if chat_id not in AUTHORIZED_GROUPS:
        return await update.message.reply_text("🚫 This group is not authorized to use the bot.")

    # Enforce cooldown to prevent command spamming
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying.")

    bin_input = None
    # Robust argument parsing for both /command [bin] and .command [bin]
    if context.args: # For /gen [bin]
        bin_input = context.args[0]
    elif update.message.text: # For .gen [bin]
        # Split the message to get the part after the command (.gen)
        command_text = update.message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]

    if not bin_input:
        return await update.message.reply_text("❌ Please provide a 6\\-digit BIN\\. Usage: `/gen [bin]` or `\\.gen [bin]`\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if len(bin_input) < 6:
        return await update.message.reply_text("⚠️ BIN should be at least 6 digits\\.", parse_mode=ParseMode.MARKDOWN_V2)

    # Fetch BIN data from the external API
    bin_data = await fetch_bin_info(bin_input[:6]) or {}
    bank = bin_data.get("bank", {}).get("name", "Unknown")
    country_name = bin_data.get("country", {}).get("name", "Unknown")
    country_emoji = bin_data.get("country", {}).get("emoji", '')
    brand = bin_data.get("scheme", "Unknown").capitalize()

    # Escape dynamic text for MarkdownV2
    escaped_brand = _escape_markdown_v2_text(brand)
    escaped_bank = _escape_markdown_v2_text(bank)
    escaped_country = _escape_markdown_v2_text(f"{country_name} {country_emoji}".strip())
    escaped_user_full_name = _escape_markdown_v2_text(update.effective_user.full_name)
    
    cards = []
    # Generate 10 unique, Luhn-valid card numbers
    while len(cards) < 10:
        # Construct a 16-digit number starting with the BIN and random digits
        num = bin_input + ''.join(str(os.urandom(1)[0] % 10) for _ in range(16 - len(bin_input)))
        if not luhn_checksum(num): # Validate using Luhn algorithm
            continue
        
        # Generate random month (01-12) and year (current year + up to 5 years)
        mm = str(os.urandom(1)[0] % 12 + 1).zfill(2)
        yyyy = str(datetime.now().year + os.urandom(1)[0] % 6)
        
        # Generate CVV (3 digits for most cards, 4 for American Express)
        cvv_length = 4 if brand == 'American Express' else 3
        cvv = str(os.urandom(1)[0] % (10**cvv_length)).zfill(cvv_length)
        
        cards.append(f"`{num}|{mm}|{yyyy[-2:]}|{cvv}`") # Format each card in monospace

    cards_list = "\n".join(cards) # Join all cards with newlines
    
    # Construct the final response message with proper MarkdownV2 formatting
    # Only card numbers and BIN are in monospace
    result = (
        f"Generated 10 Cards\n\n" # Header with a line space
        f"{cards_list}\n\n" # List of cards
        f"> *💳 Brand*: {escaped_brand}\n"
        f"> *🏦 Bank*: {escaped_bank}\n"
        f"> *🌍 Country*: {escaped_country}\n"
        f"> *🧾 BIN*: `{bin_input}`\n"
        f"> *🙋 Requested by \\-*: {escaped_user_full_name}\n" # Escaped hyphen, and now escaped username
        f"> *🤖 Bot by \\-*: Your Friend" # Escaped hyphen
    )
    
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Performs a BIN lookup using the external API and displays the information.
    This command is restricted to authorized group chats and has a cooldown.
    """
    if update.effective_chat.type not in ["group", "supergroup"]:
        button = InlineKeyboardMarkup([[InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")]])
        return await update.message.reply_text("Join our official group to use this bot.", reply_markup=button)

    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying.")

    bin_input = None
    # Robust argument parsing for both /command [bin] and .command [bin]
    if context.args: # For /bin [bin]
        bin_input = context.args[0]
    elif update.message.text: # For .bin [bin]
        # Split the message to get the part after the command (.bin)
        command_text = update.message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]

    if not bin_input:
        return await update.message.reply_text("❌ Please provide a 6\\-digit BIN\\. Usage: `/bin [bin]` or `\\.bin [bin]`\\.", parse_mode=ParseMode.MARKDOWN_V2)

    bin_input = bin_input[:6] # Take only the first 6 digits for BIN lookup
    data = await fetch_bin_info(bin_input)
    if not data:
        return await update.message.reply_text("❌ BIN not found in database or an error occurred\\.", parse_mode=ParseMode.MARKDOWN_V2)

    # Extract relevant information from the API response
    bank = data.get("bank", {}).get("name", "Unknown")
    country_name = data.get("country", {}).get("name", "Unknown")
    country_emoji = data.get("country", {}).get("emoji", '')
    scheme = data.get("scheme", "Unknown").capitalize()
    card_type = data.get("type", "Unknown").capitalize() # e.g., debit, credit
    level = data.get("brand", "Unknown") # Using 'brand' from binlist.net as 'level'

    # Escape dynamic text for MarkdownV2
    escaped_scheme = _escape_markdown_v2_text(scheme)
    escaped_bank = _escape_markdown_v2_text(bank)
    escaped_country = _escape_markdown_v2_text(f"{country_name} {country_emoji}".strip())
    escaped_card_type = _escape_markdown_v2_text(card_type)
    escaped_level = _escape_markdown_v2_text(level)
    escaped_user_full_name = _escape_markdown_v2_text(update.effective_user.full_name)

    # Construct the final response message with proper MarkdownV2 formatting
    # Only the BIN number is in monospace, as requested
    result = (
        f"╔══════════════════════╗\n"
        f"║ 💳 \\*\\*𝐁𝐈𝐍 𝐈𝐍𝐅𝐎𝐑𝐌𝐀𝐓𝐈𝐎𝐍\\*\\* ║\n" # Escaped asterisks for bold within ASCII art
        f"╚══════════════════════╝\n"
        f"**💳 Brand**: {escaped_scheme}\n"
        f"**🏦 Bank**: {escaped_bank}\n"
        f"**🌐 Type**: {escaped_card_type}\n"
        f"**💠 Level**: {escaped_level}\n"
        f"**🌎 Country**: {escaped_country}\n"
        f"**🧾 Bin**: `{bin_input}`\n" # Only this line has monospace backticks
        f"🙋 Requested by \\- {escaped_user_full_name}\n" # Escaped hyphen, and now fully escaped username
        f"🤖 Bot by \\- Your Friend" # Escaped hyphen
    )
    
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays the bot's current operational status (users, RAM, CPU, uptime).
    This command is restricted to group chats.
    """
    if update.effective_chat.type not in ["group", "supergroup"]:
        return await update.message.reply_text("🔒 This command can only be used in the group.")

    total_users = len(user_last_command) # Simple count of users who have used a command
    
    # Calculate RAM usage in MB
    ram_mb = psutil.virtual_memory().used / (1024 * 1024)
    ram_usage = f"{ram_mb:.0f} MB"
    
    # Get CPU usage percentage and escape the '%' character
    cpu_usage_percent = psutil.cpu_percent()
    cpu_usage_text = f"{cpu_usage_percent}\\%"
    
    # Calculate bot uptime in hours and minutes
    uptime_seconds = int(time.time() - psutil.boot_time())
    uptime_delta = timedelta(seconds=uptime_seconds)
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_string = f"{hours} hours {minutes} minutes"

    # Escape the user's full name for MarkdownV2
    escaped_user_full_name = _escape_markdown_v2_text(update.effective_user.full_name)

    # Construct the final response message with proper MarkdownV2 formatting, with no monospace.
    status_msg = (
        f"> 📊 Bot Status\n"
        f"> 👥 Total Users: {total_users}\n"
        f"> 🧠 RAM Usage: {ram_usage}\n"
        f"> 🖥️ CPU Usage: {cpu_usage_text}\n"
        f"> ⏱️ Uptime: {uptime_string}\n"
        f"> 🤖 Bot by \\- Your Friend" # Escaped hyphen
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
        # Escaping the dot at the end of the sentence for MarkdownV2
        await update.message.reply_text(f"✅ Group `{chat_id_to_authorize}` is now authorized to use the bot\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await update.message.reply_text("❌ Invalid chat ID\\. Please provide a numeric chat ID\\.", parse_mode=ParseMode.MARKDOWN_V2)

# === MAIN APPLICATION SETUP ===
def main():
    """
    Main function to build and run the Telegram bot application.
    Initializes the bot, registers all command and callback handlers, and starts polling for updates.
    """
    # Validate environment variables before starting the bot
    if TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set. Please set it before running the bot.")
        exit(1)
    if OWNER_ID is None:
        logger.error("OWNER_ID environment variable is not set. Please set it before running the bot.")
        exit(1)
    
    # Build the Telegram Application
    application = ApplicationBuilder().token(TOKEN).build()

    # Register Command Handlers for '/' commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("au", authorize_group))

    # Register Message Handlers for '.' commands using regex
    # The `^` ensures the dot command is at the beginning of the message.
    # `filters.Regex(r"^\.gen\b.*")` matches messages starting with ".gen" followed by a word boundary.
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.gen\b.*"), gen))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.bin\b.*"), bin_lookup))

    # Register Callback Query Handlers for inline buttons
    application.add_handler(CallbackQueryHandler(show_main_commands, pattern="^show_main_commands$"))
    application.add_handler(CallbackQueryHandler(show_command_details, pattern="^cmd_"))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_start$")) # Handler for the new back button

    logger.info("Bot started polling...")
    # Start polling for updates from Telegram
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
