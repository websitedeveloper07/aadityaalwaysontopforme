import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil # For status command
from datetime import datetime, timedelta # For status command
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

# API KEY and URL for api.bintable.com
BINTABLE_API_KEY = "2504e1938a63e931f65c90cee460c7ef8c418252"
BINTABLE_URL = "https://api.bintable.com/v1"

# A set to store chat IDs of groups authorized to use the bot's commands.
# The official group chat ID is pre-authorized here.
AUTHORIZED_GROUPS = {-1002675283650} # Your specified official group chat ID

# Dictionary to store the last command execution time for each user,
# used to implement a global cooldown.
user_last_command = {}

# === VBV CHECKER BOT CONFIGURATION ===
VBV_CHECKER_BOT_USERNAME = "lfcchek_bot" # Username without '@' for internal use
VBV_CHECK_CHAT_ID = -1002804744593 # Updated chat ID based on user's confirmation
VBV_CHECK_COMMAND_PREFIX = "/bin"

# === GLOBAL CACHE FOR VBV STATUS ===
# This dictionary will store asyncio.Event objects and VBV status for pending requests.
# Key: bin_number (str)
# Value: {'event': asyncio.Event, 'status': str}
vbv_results_cache = {}

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

def get_short_country_name(full_name):
    """
    Extracts a shorter, more common name from a full country name string.
    Handles common long forms and parenthetical suffixes.
    """
    if not full_name:
        return "Unknown"
    
    # Common mappings for very long or formal names
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

    # Check for direct mapping first
    if full_name in name_map:
        return name_map[full_name]

    # Remove common parenthetical suffixes and "of" phrases
    cleaned_name = re.sub(r'\s*\(.*\)\s*', '', full_name).strip()
    cleaned_name = re.sub(r'\s*of\s+.*$', '', cleaned_name).strip()
    
    # If still long, take the first word or first few words
    words = cleaned_name.split()
    if len(words) > 2 and words[1].lower() in ["republic", "kingdom", "states", "federation"]:
        return " ".join(words[:2]) # e.g., "United States"
    elif len(words) > 1 and words[0].lower() == "the":
        return " ".join(words[1:]) # e.g., "Bahamas" instead of "The Bahamas"
    
    return cleaned_name # Return cleaned name if no specific mapping or further shortening needed

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

def get_level_emoji(level):
    """
    Returns an emoji based on the card level.
    """
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
        "Standard": "🌟" # Added standard
    }
    return level_map.get(level, "❓") # Default to question mark if unknown

def get_vbv_status_display(status):
    """
    Returns formatted VBV status with appropriate emoji.
    """
    if status.lower() == "non-vbv":
        return "✅ NON-VBV"
    elif status.lower() == "vbv":
        return "❌ VBV"
    else:
        return f"❓ {escape_markdown_v2(status)}" # For N/A or Unknown

async def fetch_bin_info_bintable(bin_number):
    """
    Asynchronously fetches BIN information from api.bintable.com.
    """
    url = f"{BINTABLE_URL}/{bin_number}?api_key={BINTABLE_API_KEY}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Corrected check: Bintable API uses "result": 200 for success and wraps data in 'data' key
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
                    logger.warning(f"Binlist API returned status {resp.status} for BIN: {bin_number}")
                    return None
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching from Binlist for {bin_number}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred fetching from Binlist for {bin_number}: {e}")
        return None

async def fetch_bin_info_bincheckio(bin_number):
    """
    Asynchronously fetches BIN information from bincheck.io.
    This is a free API, but may have rate limits or less comprehensive data.
    """
    url = f"https://api.bincheck.io/bin/{bin_number}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # bincheck.io returns a 'status' field. Only proceed if status is 'ok'.
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

async def get_vbv_status_from_external_bot(bin_number, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends a BIN to the external VBV checker bot and waits for its response.
    Uses a global cache and asyncio.Event for synchronization.
    """
    # Initialize the cache entry for this BIN
    vbv_results_cache[bin_number] = {'event': asyncio.Event(), 'status': 'N/A'}

    try:
        # Send the command to the VBV checker bot in the private group, explicitly mentioning its username
        await context.bot.send_message(
            chat_id=VBV_CHECK_CHAT_ID,
            text=f"{VBV_CHECK_COMMAND_PREFIX}@{VBV_CHECKER_BOT_USERNAME} {bin_number}"
        )
        logger.info(f"Sent command to VBV checker bot: {VBV_CHECK_COMMAND_PREFIX}@{VBV_CHECKER_BOT_USERNAME} {bin_number} in chat {VBV_CHECK_CHAT_ID}")

        # Wait for the VBV response handler to set the event (with a timeout)
        try:
            await asyncio.wait_for(vbv_results_cache[bin_number]['event'].wait(), timeout=10) # Wait up to 10 seconds
            return vbv_results_cache[bin_number]['status']
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for VBV status from {VBV_CHECKER_BOT_USERNAME} for BIN: {bin_number}")
            return "N/A (Timeout)"
    except Exception as e:
        logger.error(f"Error sending command to VBV checker bot: {e}")
        return "N/A (Error)"
    finally:
        # Clean up the cache entry after processing or timeout
        if bin_number in vbv_results_cache:
            del vbv_results_cache[bin_number]

async def vbv_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles messages received from the VBV checker bot in the designated private chat.
    Parses the VBV status and updates the global cache.
    """
    # Ensure it's a message and from the correct bot in the correct chat
    if update.message and update.message.from_user and update.message.from_user.username == VBV_CHECKER_BOT_USERNAME:
        if update.message.chat_id == VBV_CHECK_CHAT_ID:
            text = update.message.text
            logger.info(f"Received message from VBV checker bot: {text}")

            # Extract BIN from the VBV checker bot's response (e.g., "🍀 BIN ➜ 486732")
            # Using a more flexible regex for BIN extraction
            bin_match = re.search(r"BIN\s*➜\s*(\d+)", text)
            if not bin_match:
                logger.warning(f"Could not extract BIN from VBV bot response: {text}")
                return # Cannot process without a BIN

            extracted_bin = bin_match.group(1)

            # Parse the VBV status from the response
            # Expected format from image: "🍀 VBV Status ➜ ❌ Vbv ❌" or "🍀 VBV Status ➜ ✅ Non-Vbv ✅"
            status_match = re.search(r"VBV Status ➜ (?:❌|✅)\s*(Vbv|Non-Vbv)\s*(?:❌|✅)", text, re.IGNORECASE)
            
            if extracted_bin in vbv_results_cache:
                if status_match:
                    extracted_status = status_match.group(1).lower()
                    if "non-vbv" in extracted_status:
                        vbv_results_cache[extracted_bin]['status'] = "Non-VBV"
                    elif "vbv" in extracted_status:
                        vbv_results_cache[extracted_bin]['status'] = "VBV"
                    else:
                        vbv_results_cache[extracted_bin]['status'] = "Unknown" # Fallback if regex matches but status is unexpected
                else:
                    vbv_results_cache[extracted_bin]['status'] = "N/A (Parse Error)" # If status not found in response
                
                # Set the event to unblock the waiting command handler
                vbv_results_cache[extracted_bin]['event'].set()
            else:
                logger.info(f"Received VBV status for BIN {extracted_bin} but no pending request found in cache.")

async def get_bin_details(bin_number, context: ContextTypes.DEFAULT_TYPE, fetch_vbv: bool = True):
    """
    Attempts to fetch BIN details from multiple APIs with fallback.
    Also fetches VBV status from external bot if fetch_vbv is True.
    """
    # Initialize with defaults
    details = {
        "bank": "Unknown",
        "country_name": "Unknown",
        "country_emoji": "",
        "scheme": "Unknown",
        "card_type": "Unknown",
        "level": "N/A", # Default for level
        "vbv_status": "N/A" # Default for VBV status
    }
    
    # 1. Try Bintable.com first
    logger.info(f"Attempting BIN lookup with Bintable.com for BIN: {bin_number}")
    bintable_data = await fetch_bin_info_bintable(bin_number)
    
    if bintable_data:
        logger.info(f"Bintable.com processed data for {bin_number}: {bintable_data}") # Log raw data for debugging
        
        # Extracting nested data from bintable_data
        bank_info = bintable_data.get("bank", {})
        country_info = bintable_data.get("country", {})
        card_info = bintable_data.get("card", {})

        details["bank"] = bank_info.get("name", details["bank"])
        details["country_name"] = country_info.get("name", details["country_name"])
        details["country_emoji"] = country_info.get("flag", details["country_emoji"]) 
        details["scheme"] = card_info.get("scheme", details["scheme"]).capitalize()
        details["card_type"] = card_info.get("type", details["card_type"]).capitalize()
        details["level"] = card_info.get("category", details["level"]).capitalize() # 'category' is used for level in Bintable
        
        # If Bintable gives good data, we can proceed.
        if details["bank"] != "Unknown" and details["country_name"] != "Unknown" and details["scheme"] != "Unknown":
            details["country_name"] = get_short_country_name(details["country_name"])
            # Fetch VBV status from external bot ONLY if requested
            if fetch_vbv:
                details["vbv_status"] = await get_vbv_status_from_external_bot(bin_number, context)
            return details
    else:
        logger.info(f"Bintable.com did not return valid data for BIN: {bin_number}. Falling back...")

    # 2. Fallback to Binlist.net
    logger.info(f"Attempting BIN lookup with Binlist.net for BIN: {bin_number}")
    binlist_data = await fetch_bin_info_binlist(bin_number)
    if binlist_data:
        logger.info(f"Binlist.net response for {bin_number}: {binlist_data}")
        details["bank"] = binlist_data.get("bank", {}).get("name", details["bank"])
        details["country_name"] = binlist_data.get("country", {}).get("name", details["country_name"])
        details["country_emoji"] = binlist_data.get("country", {}).get("emoji", details["country_emoji"])
        details["scheme"] = binlist_data.get("scheme", details["scheme"]).capitalize()
        details["card_type"] = binlist_data.get("type", details["card_type"]).capitalize()
        # binlist.net doesn't provide 'level' or VBV status
    else:
        logger.info(f"Binlist.net did not return valid data for BIN: {bin_number}. Falling back...")
    
    # 3. Fallback to Bincheck.io if still missing key info
    if details["bank"] == "Unknown" or details["country_name"] == "Unknown" or details["scheme"] == "Unknown":
        logger.info(f"Attempting BIN lookup with Bincheck.io for BIN: {bin_number}")
        bincheck_data = await fetch_bin_info_bincheckio(bin_number)
        if bincheck_data:
            logger.info(f"Bincheck.io response for {bin_number}: {bincheck_data}")
            details["bank"] = bincheck_data.get("bank", {}).get("name", details["bank"])
            details["country_name"] = bincheck_data.get("country", {}).get("name", details["country_name"])
            details["country_emoji"] = bincheck_data.get("country", {}).get("emoji", details["country_emoji"])
            details["scheme"] = bincheck_data.get("brand", details["scheme"]).capitalize()
            details["card_type"] = bincheck_data.get("type", details["card_type"]).capitalize()
            # bincheck.io might have a "level" field, but it varies. VBV status is not explicitly provided.
            details["level"] = bincheck_data.get("level", details["level"]).capitalize()
        else:
            logger.info(f"Bincheck.io did not return valid data for BIN: {bin_number}.")

    # Shorten country name after getting from all sources
    details["country_name"] = get_short_country_name(details["country_name"])
    
    # Fetch VBV status from external bot ONLY if requested
    if fetch_vbv:
        details["vbv_status"] = await get_vbv_status_from_external_bot(bin_number, context)

    return details

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
        [InlineKeyboardButton("⬅️ Back to Start", callback_data="back_to_start")]
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
    """
    Generates credit card numbers based on a provided BIN.
    This command is restricted to authorized group chats and has a cooldown.
    """
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

    # Get BIN details from multiple sources (do NOT fetch VBV for /gen)
    bin_details = await get_bin_details(bin_input[:6], context, fetch_vbv=False) 

    brand = bin_details["scheme"]
    bank = bin_details["bank"]
    country_name = bin_details['country_name']
    country_emoji = bin_details['country_emoji']
    card_type = bin_details["card_type"] 
    # For /gen, VBV status is always N/A as per request
    vbv_status = "N/A" 
    # For /gen, level is not told as per request, but we need it for card generation logic
    level = bin_details["level"] 
    
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
    
    # Escape dynamic text for MarkdownV2
    escaped_brand = escape_markdown_v2(brand)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country_name = escape_markdown_v2(country_name)
    escaped_country_emoji = escape_markdown_v2(country_emoji)
    escaped_card_type = escape_markdown_v2(card_type)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)

    # Get emojis for status (level emoji is not used for /gen output)
    status_display = get_vbv_status_display(vbv_status)
    
    # Construct the message with precise quote box placement
    result = (
        f"> Generated 10 Cards\n" # Top quote box
        f"\n" # Blank line after top quote box
        f"{cards_list}\n" # Cards list, NOT in quote box
        f"\n" # Blank line between cards and info quote box
        f"╔═══════ BIN INFO ═══════╗\n"
        f"✦ BIN\\s\\s\\s\\s\\s\\s : `{bin_input}`\n"
        f"✦ Status : {status_display}\n"
        f"✦ Brand\\s\\s : {escaped_brand}\n"
        f"✦ Type\\s\\s\\s\\s : {escaped_card_type}\n"
        f"✦ Bank\\s\\s\\s\\s : {escaped_bank}\n"
        f"✦ Country: {escaped_country_name} {escaped_country_emoji}\n"
        f"╚════════════════════════╝\n"
        f"Requested by \\-: {escaped_user_full_name}\n"
        f"Bot by \\-: Your Friend"
    )
    
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Performs a BIN lookup using the external API and displays the information.
    """
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
    
    # Get BIN details from multiple sources (DO fetch VBV for /bin)
    bin_details = await get_bin_details(bin_input, context, fetch_vbv=True) 

    # Extract details, using "Unknown" or "N/A" if not found
    scheme = bin_details["scheme"]
    bank = bin_details["bank"]
    card_type = bin_details["card_type"]
    level = bin_details["level"]
    country_name = bin_details['country_name']
    country_emoji = bin_details['country_emoji']
    vbv_status = bin_details["vbv_status"] # Get VBV status

    # Escape dynamic text for MarkdownV2
    escaped_scheme = escape_markdown_v2(scheme)
    escaped_bank = escape_markdown_v2(bank)
    escaped_country_name = escape_markdown_v2(country_name)
    escaped_country_emoji = escape_markdown_v2(country_emoji)
    escaped_card_type = escape_markdown_v2(card_type)
    escaped_level = escape_markdown_v2(level)
    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)

    # Get emojis for status and level
    status_display = get_vbv_status_display(vbv_status)
    level_emoji = get_level_emoji(escaped_level)

    # Construct the final response message with proper MarkdownV2 formatting
    result = (
        f"╔═══════ BIN INFO ═══════╗\n"
        f"✦ BIN\\s\\s\\s\\s\\s\\s : `{bin_input}`\n"
        f"✦ Status : {status_display}\n"
        f"✦ Brand\\s\\s : {escaped_scheme}\n"
        f"✦ Type\\s\\s\\s\\s : {escaped_card_type}\n"
        f"✦ Level\\s\\s : {level_emoji} {escaped_level}\n"
        f"✦ Bank\\s\\s\\s\\s : {escaped_bank}\n"
        f"✦ Country: {escaped_country_name} {escaped_country_emoji}\n"
        f"╚════════════════════════╝\n"
        f"Requested by \\-: {escaped_user_full_name}\n"
        f"Bot by \\-: Your Friend"
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

    # Construct the entire message within a single quote block
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

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("au", authorize_group))

    # Message Handlers for dot commands
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.gen\b.*"), gen))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.bin\b.*"), bin_lookup))

    # Callback Query Handlers for inline buttons
    application.add_handler(CallbackQueryHandler(show_main_commands, pattern="^show_main_commands$"))
    application.add_handler(CallbackQueryHandler(show_command_details, pattern="^cmd_"))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_start$"))

    # IMPORTANT: Add the VBV response handler BEFORE run_polling
    # This handler specifically listens for messages from the VBV_CHECKER_BOT_USERNAME
    # in the VBV_CHECK_CHAT_ID.
    application.add_handler(MessageHandler(
        filters.Chat(VBV_CHECK_CHAT_ID) & filters.User(username=VBV_CHECKER_BOT_USERNAME) & filters.TEXT,
        vbv_response_handler
    ))

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
