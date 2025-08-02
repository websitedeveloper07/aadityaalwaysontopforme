import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest

# === CONFIGURATION ===
# IMPORTANT: Set these as environment variables before running your bot:
# export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
# export OWNER_ID="YOUR_TELEGRAM_USER_ID" # Your personal Telegram User ID (numeric)
# export BINTABLE_API_KEY="YOUR_BINTABLE_API_KEY" # Get this from Bintable.com
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

BINTABLE_API_KEY = os.getenv("BINTABLE_API_KEY") # Read directly from environment variable
BINTABLE_URL = "https://api.bintable.com/v1"

# --- New Configuration ---
AUTHORIZATION_CONTACT = "@enough69s"
OFFICIAL_GROUP_LINK = "https://t.me/+gtvJT4SoimBjYjQ1" # Replace with your actual official group link
DAILY_KILL_CREDIT_LIMIT = 50

# === GLOBAL STATE ===
user_last_command = {}
# These sets/dict are in-memory and will reset on bot restart.
# For persistence, consider using a simple JSON file or a database.
AUTHORIZED_CHATS = set() # Stores chat_id of authorized groups
AUTHORIZED_PRIVATE_USERS = set() # Stores user_ids of authorized private users
USER_CREDITS = {} # user_id -> {'credits': int, 'last_credit_reset': datetime}

# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === HELPER FUNCTIONS ===

def escape_markdown_v2(text: str) -> str:
    """Escapes markdown v2 special characters."""
    # List of special characters in MarkdownV2 that need to be escaped
    # _ * [ ] ( ) ~ ` > # + - = | { } . !
    
    # Escape characters that are always special
    escaped_text = re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", text)
    
    # Correct common double escaping issue with backslashes
    return escaped_text.replace('\\\\\\\\', '\\\\\\')

def get_short_country_name(full_name):
    name_map = {
        "United States": "USA", "United Kingdom": "UK", "Canada": "CA",
        "Australia": "AU", "Germany": "DE", "France": "FR",
        "India": "IN", "Brazil": "BR", "Mexico": "MX",
        "Argentina": "AR", "South Africa": "ZA", "Japan": "JP",
        "China": "CN", "Russia": "RU", "Italy": "IT",
        "Spain": "ES", "Netherlands": "NL", "Belgium": "BE",
        "Sweden": "SE", "Norway": "NO", "Denmark": "DK",
        "Finland": "FI", "Ireland": "IE", "Switzerland": "CH",
        "Austria": "AT", "Portugal": "PT", "Greece": "GR",
        "Turkey": "TR", "Poland": "PL", "Egypt": "EG",
        "Saudi Arabia": "SA", "United Arab Emirates": "AE", "New Zealand": "NZ",
        "Singapore": "SG", "Malaysia": "MY", "Indonesia": "ID",
        "Philippines": "PH", "Thailand": "TH", "Vietnam": "VN",
        "South Korea": "KR", "Nigeria": "NG", "Kenya": "KE",
        "Colombia": "CO", "Chile": "CL", "Peru": "PE",
        "Venezuela": "VE", "Pakistan": "PK", "Bangladesh": "BD",
        "Ukraine": "UA", "Kazakhstan": "KZ", "Romania": "RO",
        "Czech Republic": "CZ", "Hungary": "HU", "Slovakia": "SK",
        "Croatia": "HR", "Serbia": "RS", "Bulgaria": "BG",
        "Lithuania": "LT", "Latvia": "LV", "Estonia": "EE",
        "Israel": "IL", "Egypt": "EG", "Morocco": "MA",
        "Algeria": "DZ", "Tunisia": "TN", "Kuwait": "KW",
        "Qatar": "QA", "Bahrain": "BH", "Oman": "OM",
        "Jordan": "JO", "Lebanon": "LB", "Syria": "SY",
        "Iraq": "IQ", "Iran": "IR", "Afghanistan": "AF",
        "Nepal": "NP", "Sri Lanka": "LK", "Myanmar": "MM",
        "Cambodia": "KH", "Laos": "LA", "Mongolia": "MN",
        "Uzbekistan": "UZ", "Azerbaijan": "AZ", "Georgia": "GE",
        "Armenia": "AM", "Moldova": "MD", "Belarus": "BY",
        "Bosnia and Herzegovina": "BA", "Albania": "AL", "North Macedonia": "MK",
        "Kosovo": "XK", "Cyprus": "CY", "Malta": "MT",
        "Iceland": "IS", "Luxembourg": "LU", "Monaco": "MC",
        "Andorra": "AD", "San Marino": "SM", "Liechtenstein": "LI",
        "Vatican City": "VA", "Greenland": "GL", "Fiji": "FJ",
        "Papua New Guinea": "PG", "Solomon Islands": "SB", "Vanuatu": "VU",
        "New Caledonia": "NC", "French Polynesia": "PF", "Samoa": "WS",
        "Tonga": "TO", "Tuvalu": "TV", "Kiribati": "KI",
        "Nauru": "NR", "Marshall Islands": "MH", "Micronesia": "FM",
        "Palau": "PW", "East Timor": "TL", "Brunei": "BN",
        "Bhutan": "BT", "Maldives": "MV", "Seychelles": "SC",
        "Mauritius": "MU", "Comoros": "KM", "Madagascar": "MG",
        "Mozambique": "MZ", "Angola": "AO", "Zambia": "ZM",
        "Zimbabwe": "ZW", "Botswana": "BW", "Namibia": "NA",
        "Lesotho": "LS", "Eswatini": "SZ", "Congo (Brazzaville)": "CG",
        "Congo (Kinshasa)": "CD", "Gabon": "GA", "Equatorial Guinea": "GQ",
        "Cameroon": "CM", "Central African Republic": "CF", "Chad": "TD",
        "Niger": "NE", "Burkina Faso": "BF", "Mali": "ML",
        "Mauritania": "MR", "Senegal": "SN", "Gambia": "GM",
        "Guinea-Bissau": "GW", "Guinea": "GN", "Sierra Leone": "SL",
        "Liberia": "LR", "Ivory Coast": "CI", "Ghana": "GH",
        "Togo": "TG", "Benin": "BJ", "Nigeria": "NG",
        "Ethiopia": "ET", "Eritrea": "ER", "Djibouti": "DJ",
        "Somalia": "SO", "South Sudan": "SS", "Sudan": "SD",
        "Uganda": "UG", "Rwanda": "RW", "Burundi": "BI",
        "Tanzania": "TZ", "Malawi": "MW", "Djibouti": "DJ",
        "Zimbabwe": "ZW", "Eritrea": "ER", "Angola": "AO",
        "Cape Verde": "CV", "Sao Tome and Principe": "ST", "Dominican Republic": "DO",
        "Haiti": "HT", "Jamaica": "JM", "Cuba": "CU",
        "Bahamas": "BS", "Barbados": "BB", "Trinidad and Tobago": "TT",
        "Guyana": "GY", "Suriname": "SR", "French Guiana": "GF",
        "Belize": "BZ", "Guatemala": "GT", "Honduras": "HN",
        "El Salvador": "SV", "Nicaragua": "NI", "Costa Rica": "CR",
        "Panama": "PA", "Ecuador": "EC", "Bolivia": "BO",
        "Paraguay": "PY", "Uruguay": "UY", "Aruba": "AW",
        "Curaçao": "CW", "Sint Maarten": "SX", "Cayman Islands": "KY",
        "Bermuda": "BM", "Turks and Caicos Islands": "TC", "British Virgin Islands": "VG",
        "US Virgin Islands": "VI", "Guam": "GU", "Northern Mariana Islands": "MP",
        "American Samoa": "AS", "Puerto Rico": "PR"
    }
    return name_map.get(full_name, full_name)


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
    return "💡" # Default emoji

def get_vbv_status_display(status):
    # This function is here for completeness based on the original script,
    # but the VBV status is always "N/A" as per current logic.
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

async def get_bin_details(bin_number):
    # Initialize bin_data with default N/A values
    bin_data = {
        "scheme": "N/A", "type": "N/A", "level": "N/A",
        "bank": "N/A", "country_name": "N/A", "country_emoji": "",
        "vbv_status": None,
        "card_type": "N/A" # This will hold 'category' from Bintable, or 'type' from others
    }

    async with aiohttp.ClientSession() as session:
        # --- Attempt to get details from Bintable first ---
        if BINTABLE_API_KEY:
            try:
                bintable_url = f"{BINTABLE_URL}/{bin_number}?api_key={BINTABLE_API_KEY}"
                logger.info(f"Attempting Bintable lookup for BIN: {bin_number}")
                async with session.get(bintable_url, timeout=7) as response: # Increased timeout slightly
                    response_text = await response.text()
                    logger.info(f"Bintable response status for {bin_number}: {response.status}")
                    logger.info(f"Bintable raw response for {bin_number}: {response_text}")

                    if response.status == 200:
                        data = await response.json()
                        # Correctly check for Bintable's success indicators
                        if data and data.get("result") == 200 and data.get("message") == "SUCCESS":
                            # Correctly access the nested 'data' dictionary first
                            response_data = data.get("data", {})
                            card_info = response_data.get("card", {})
                            country_info = response_data.get("country", {})
                            bank_info = response_data.get("bank", {})

                            # Populate bin_data with Bintable details
                            bin_data["scheme"] = card_info.get("scheme", "N/A").upper()
                            bin_data["type"] = card_info.get("type", "N/A").title()
                            # Use 'category' for 'card_type' if available, otherwise fallback to 'type'
                            bin_data["card_type"] = card_info.get("category", card_info.get("type", "N/A")).title()
                            bin_data["level"] = card_info.get("level", "N/A").title()
                            bin_data["bank"] = bank_info.get("name", "N/A").title()
                            bin_data["country_name"] = country_info.get("name", "N/A")
                            bin_data["country_emoji"] = country_info.get("emoji", "")
                            
                            logger.info(f"Successfully retrieved BIN details from Bintable for {bin_number}: {bin_data}")
                            return bin_data # Return immediately if Bintable was successful
                        else:
                            logger.warning(f"Bintable API returned non-success indicators for {bin_number}. Data: {data}")
                    else:
                        logger.warning(f"Bintable API returned non-200 status {response.status} for {bin_number}.")
            except aiohttp.ClientError as e:
                logger.warning(f"Bintable API call failed (ClientError) for {bin_number}: {e}")
            except Exception as e:
                logger.warning(f"Error processing Bintable response (General Error) for {bin_number}: {e}")
        else:
            logger.info("BINTABLE_API_KEY not set. Skipping Bintable lookup.")

        # --- Fallback to Binlist if Bintable failed or didn't provide useful data ---
        logger.info(f"Falling back to Binlist lookup for BIN: {bin_number}")
        try:
            binlist_url = f"https://lookup.binlist.net/{bin_number}"
            async with session.get(binlist_url, timeout=7) as response: # Increased timeout slightly
                response_text = await response.text()
                logger.info(f"Binlist response status for {bin_number}: {response.status}")
                logger.info(f"Binlist raw response for {bin_number}: {response_text}")

                if response.status == 200:
                    data = await response.json()
                    if data:
                        # Populate bin_data with Binlist details
                        bin_data["scheme"] = data.get("scheme", "N/A").upper()
                        bin_data["type"] = data.get("type", "N/A").title()
                        bin_data["card_type"] = data.get("type", "N/A").title() # Binlist doesn't have 'category', so use 'type'
                        bin_data["level"] = data.get("brand", "N/A").title() # Binlist has 'brand' for level-like info
                        bin_data["bank"] = data.get("bank", {}).get("name", "N/A").title()
                        bin_data["country_name"] = data.get("country", {}).get("name", "N/A")
                        bin_data["country_emoji"] = data.get("country", {}).get("emoji", "")
                        
                        logger.info(f"Successfully retrieved BIN details from Binlist for {bin_number}: {bin_data}")
                        return bin_data # Return immediately if Binlist was successful
                    else:
                        logger.warning(f"Binlist API returned no data for {bin_number}.")
                else:
                    logger.warning(f"Binlist API returned non-200 status {response.status} for {bin_number}.")
        except aiohttp.ClientError as e:
            logger.warning(f"Binlist API call failed (ClientError) for {bin_number}: {e}")
        except Exception as e:
            logger.warning(f"Error processing Binlist response (General Error) for {bin_number}: {e}")

        # --- Fallback to Bincheck.io if both Bintable and Binlist failed ---
        logger.info(f"Falling back to Bincheck.io lookup for BIN: {bin_number}")
        try:
            bincheck_url = f"https://api.bincheck.io/v2/{bin_number}"
            async with session.get(bincheck_url, timeout=7) as response: # Increased timeout slightly
                response_text = await response.text()
                logger.info(f"Bincheck.io response status for {bin_number}: {response.status}")
                logger.info(f"Bincheck.io raw response for {bin_number}: {response_text}")

                if response.status == 200:
                    data = await response.json()
                    if data and data.get("success"): # Bincheck.io uses 'success' boolean
                        # Populate bin_data with Bincheck.io details
                        bin_data["scheme"] = data.get("scheme", "N/A").upper()
                        bin_data["type"] = data.get("type", "N/A").title()
                        bin_data["card_type"] = data.get("type", "N/A").title() # Bincheck.io doesn't have 'category', so use 'type'
                        bin_data["level"] = data.get("level", "N/A").title()
                        bin_data["bank"] = data.get("bank", {}).get("name", "N/A").title()
                        bin_data["country_name"] = data.get("country", {}).get("name", "N/A")
                        bin_data["country_emoji"] = data.get("country", {}).get("emoji", "")
                        
                        logger.info(f"Successfully retrieved BIN details from Bincheck.io for {bin_number}: {bin_data}")
                        return bin_data # Return immediately if Bincheck.io was successful
                    else:
                        logger.warning(f"Bincheck.io API returned success=false or no data for {bin_number}. Data: {data}")
                else:
                    logger.warning(f"Bincheck.io API returned non-200 status {response.status} for {bin_number}.")
        except aiohttp.ClientError as e:
            logger.warning(f"Bincheck.io API call failed (ClientError) for {bin_number}: {e}")
        except Exception as e:
            logger.warning(f"Error processing Bincheck.io response (General Error) for {bin_number}: {e}")

    # If all APIs fail or return no data, return the initially set default N/A values
    logger.warning(f"Failed to get BIN details for {bin_number} from all sources. Returning default N/A data.")
    return bin_data

async def enforce_cooldown(user_id: int, update: Update) -> bool:
    """Enforces a 5-second cooldown per user and sends a warning message."""
    current_time = time.time()
    last_command_time = user_last_command.get(user_id, 0)

    if current_time - last_command_time < 5:
        await update.effective_message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return False
    user_last_command[user_id] = current_time
    return True

# --- New Helper Functions ---
def get_user_credits(user_id):
    now = datetime.now()
    if user_id not in USER_CREDITS:
        USER_CREDITS[user_id] = {'credits': DAILY_KILL_CREDIT_LIMIT, 'last_credit_reset': now}
    else:
        # Check if it's a new day since last reset (based on date only)
        last_reset_date = USER_CREDITS[user_id]['last_credit_reset'].date()
        if now.date() > last_reset_date:
            USER_CREDITS[user_id]['credits'] = DAILY_KILL_CREDIT_LIMIT
            USER_CREDITS[user_id]['last_credit_reset'] = now
    return USER_CREDITS[user_id]['credits']

def consume_credit(user_id):
    get_user_credits(user_id) # Ensure credits are up-to-date
    if USER_CREDITS[user_id]['credits'] > 0:
        USER_CREDITS[user_id]['credits'] -= 1
        return True
    return False

def add_credits_to_user(user_id, amount):
    get_user_credits(user_id) # Ensure credits are up-to-date
    USER_CREDITS[user_id]['credits'] += amount
    # Optionally, update last_credit_reset to now to prevent immediate re-fill if you want this to be a "manual override"
    # USER_CREDITS[user_id]['last_credit_reset'] = datetime.now()
    return USER_CREDITS[user_id]['credits']

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE, is_group_only: bool = False) -> bool:
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    chat_id = update.effective_chat.id # Get chat_id for group check

    # Owner can use bot everywhere
    if user_id == OWNER_ID:
        return True

    # If the command is group-only, check that first
    if is_group_only:
        if chat_type != 'group' and chat_type != 'supergroup':
            await update.effective_message.reply_text(
                "🚫 This command can only be used in authorized group chats\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return False
        # And then check if the group itself is authorized
        if chat_id not in AUTHORIZED_CHATS:
            await update.effective_message.reply_text(
                f"🚫 This group chat is not authorized to use this bot\\. Please contact {AUTHORIZATION_CONTACT} to get approved\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return False
        return True # If it's a group-only command and passed group authorization

    # Check for private chat restrictions (for commands not explicitly group-only)
    if chat_type == 'private':
        if user_id in AUTHORIZED_PRIVATE_USERS:
            return True
        else:
            keyboard = [[InlineKeyboardButton("Official Group", url=OFFICIAL_GROUP_LINK)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text( # Use effective_message for consistency
                f"🚫 You are not approved to use bot in private\\. Get the subscription at cheap from {AUTHORIZATION_CONTACT} to use or else use for free in our official group\\.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return False

    # Check for group chat restrictions (for commands not explicitly group-only)
    elif chat_type == 'group' or chat_type == 'supergroup':
        if chat_id in AUTHORIZED_CHATS:
            return True
        else:
            await update.effective_message.reply_text( # Use effective_message for consistency
                f"🚫 This group chat is not authorized to use this bot\\. Please contact {AUTHORIZATION_CONTACT} to get approved\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return False
    return False # Should not reach here


# === COMMAND HANDLERS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # No cooldown for start command
    user_full_name = escape_markdown_v2(update.effective_user.full_name)
    welcome_message = (
        f"Hey {user_full_name} 👋\\! Welcome to *𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝒍𝒕𝑿* ⚡\\.\n\n"
        f"I'm your all\\-in\\-one bot for ⚙️ *Card Tools* & 💀 *Live Killing* \\!\n"
        f"Use me to generate cards, check BINs, and powerful cc killer — fast and smart ✅\\.\n\n"
        f"Hit the button below to explore all my commands and get started 👇"
    )

    keyboard = [
        [InlineKeyboardButton("Commands", callback_data="show_main_commands")],
        [InlineKeyboardButton("Our Official Group", url=OFFICIAL_GROUP_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Handle both direct /start command and "back to start" callback
    if update.message: # Direct command
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    elif update.callback_query: # From inline button
        query = update.callback_query
        await query.answer()
        # Check if the message can be edited, otherwise send new message
        try:
            await query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.debug("Message not modified when trying to edit start message.")
            else:
                logger.warning(f"Could not edit message for 'back to start', sending new one: {e}")
                # Fallback to sending a new message if edit fails
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=welcome_message,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
    else: # Fallback for any other unexpected update type if needed
        logger.warning(f"Start command called without message or callback_query: {update}")
        # If no effective message or callback query, do nothing or log further.


async def show_main_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💳 Generate Cards", callback_data="cmd_gen")],
        [InlineKeyboardButton("🔍 BIN Lookup", callback_data="cmd_bin")],
        [InlineKeyboardButton("🔪 Kill Card", callback_data="cmd_kill")],
        [InlineKeyboardButton("👤 Fake Info", callback_data="cmd_fk")],
        [InlineKeyboardButton("🧠 Payment Scanner", callback_data="cmd_gate")],
        [InlineKeyboardButton("📤 Dump Extractor", callback_data="cmd_fl")],  # ✅ New /fl command
        [InlineKeyboardButton("📊 Bot Status", callback_data="cmd_status")],
        [InlineKeyboardButton("ℹ️ My Credits", callback_data="cmd_credits")],
        [InlineKeyboardButton("❔ Help", callback_data="cmd_help")],
        [InlineKeyboardButton("🔙 Back to Start", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(commands_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
)

async def show_command_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    command_name = query.data.replace("cmd_", "")

    details = {
        "gen": (
            "*/gen \\<BIN\\>*\n"
            "Generate 10 random credit cards \\(CC\\|MM\\|YY\\|CVV\\) based on a 6\\-digit BIN\\.\n"
            "Example: `/gen 400000`"
        ),
        "bin": (
            "*/bin \\<BIN\\>*\n"
            "Look up detailed information for a 6\\-digit BIN \\(Bank, Country, Type, Scheme\\, Level\\, VBV Status\\)\\.\n"
            "Example: `/bin 400000`"
        ),
        "kill": (
            f"*/kill CC\\|MM\\|YY\\|CVV*\n"
            f"Performs real\\-time card killing\\. Fast, direct, and effective ☠️\\.\n"
            f"You have `{get_user_credits(update.effective_user.id)}` credits\\.\n"
            f"Example: `/kill 4000000000000000|12|25|123`"
        ),
        "fk": (
            "*/fk \\<country\\>*\n"
            "Generates random fake personal info: name, address, email, IP, phone number, and card\\.\n"
            "Example: `/fk usa`"
        ),
        "gate": (
            "*/gate \\<url\\>*\n"
            "Scans a website deeply for payment gateways like Stripe, PayPal, UPI, Klarna, etc\\.\n"
            "Example: `/gate https://example.com`"
        ),
        "fl": (
            "*/fl \\<dump or reply\\>*\n"
            "Extracts all valid card formats \\(CC\\|MM\\|YY\\|CVV\\) from messages or dumps\\.\n"
            "Supports reply or inline usage\\.\n"
            "Example: `/fl 4242424242424242|12|25|123`"
        ),
        "status": (
            "*/status*\n"
            "Check bot health \\(RAM, CPU, Uptime, Total Users\\)\\."
        ),
        "credits": (
            "*/credits*\n"
            "Shows your remaining credits \\(only 50 total unless subscribed\\)\\."
        ),
        "help": (
            "*/help*\n"
            "Show full command list and features of the bot\\."
        )
    }

    text = details.get(command_name, "Details not found\\.")
    keyboard = [[InlineKeyboardButton("🔙 Back to Commands", callback_data="show_main_commands")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)



async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update): # Pass update to cooldown
        return 

    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.effective_message and update.effective_message.text: # Use effective_message
        command_text = update.effective_message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = command_text[1]

    if not bin_input:
        return await update.effective_message.reply_text("❌ Please provide a 6\\-digit BIN\\. Usage: `/gen [bin]` or `\\.gen [bin]`\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if len(bin_input) < 6:
        return await update.effective_message.reply_text("⚠️ BIN should be at least 6 digits\\.", parse_mode=ParseMode.MARKDOWN_V2)

    bin_details = await get_bin_details(bin_input[:6])

    brand = bin_details["scheme"]
    bank = bin_details["bank"]
    country_name = bin_details['country_name']
    country_emoji = bin_details['country_emoji']
    card_type = bin_details["card_type"]

    cards = []
    while len(cards) < 10:
        # Determine card number length based on brand, default to 16
        num_len = 16
        if brand.lower() == 'american express':
            num_len = 15
        elif brand.lower() == 'diners club':
            num_len = 14

        num_suffix_len = num_len - len(bin_input)
        if num_suffix_len < 0:
            num = bin_input[:num_len] # Truncate BIN if it's too long for the card type
        else:
            num = bin_input + ''.join(str(random.randint(0, 9)) for _ in range(num_suffix_len))

        if not luhn_checksum(num):
            continue

        # Generate MM (01-12)
        mm = str(random.randint(1, 12)).zfill(2)
        # Generate YYYY (current year + 1 to 5 years)
        yyyy = str(datetime.now().year + random.randint(1, 5))

        # CVV length logic: 4 for Amex, 3 for others
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
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update): # Pass update to cooldown
        return 

    bin_input = None
    if context.args:
        bin_input = context.args[0]
    elif update.effective_message and update.effective_message.text: # Use effective_message
        command_text = update.effective_message.text.split(maxsplit=1)
        if len(command_text) > 1:
            bin_input = parts[1]

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

    # Main BIN info box - made narrower for mobile
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

    # User info in a separate quote box
    user_info_quote_box = (
        f"> Requested by \\-: {escaped_user_full_name}\n"
        f"> Bot by \\-: 🔮 𝓖𝓸𝓼𝓽𝓑𝓲𝓽 𝖃𝖃𝖃 👁️"
    )

    result = f"{bin_info_box}\n\n{user_info_quote_box}"

    await update.effective_message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def _execute_kill_process(update: Update, context: ContextTypes.DEFAULT_TYPE, full_card_str: str, initial_message, bin_details):
    """
    Handles the long-running kill animation and final message.
    This function is designed to be run as a separate asyncio task.
    It now receives bin_details directly.
    """
    time_taken = 0 # Initialize time_taken

    # Simulate delay: 30 seconds to 1.3 minutes (78 seconds)
    kill_time = random.uniform(30, 78)
    start_time = time.time()

    # Animation frames for "Killing..." using progress bar
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
    frame_interval = kill_time / len(animation_frames) # seconds per frame update

    elapsed_animation_time = 0
    frame_index = 0

    while elapsed_animation_time < kill_time:
        current_frame = animation_frames[frame_index % len(animation_frames)]
        
        # FIX: Escape the current animation frame text
        escaped_frame = escape_markdown_v2(current_frame)
        
        # Edit the initial message to show the animation
        try:
            # FIX: Escape the dots in "Killing..." and remove quote box
            await initial_message.edit_text(
                f"🔪 Kɪʟʟɪɴɢ\\.\\.\\.\n"
                f"```{escaped_frame}```"
            , parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.debug("Message not modified when trying to edit animation.")
            elif "Flood control exceeded" in str(e):
                logger.warning(f"Flood control hit during animation for {full_card_str}: {e}")
            else:
                logger.warning(f"Failed to edit message during animation (BadRequest): {e}")

        # Calculate remaining time for sleep
        sleep_duration = min(frame_interval, kill_time - elapsed_animation_time)
        if sleep_duration <= 0:
            break
        await asyncio.sleep(sleep_duration)

        elapsed_animation_time = time.time() - start_time
        frame_index += 1

    # Final frame to ensure it always reaches 100%
    final_frame = animation_frames[-1]
    # FIX: Escape the final animation frame text
    escaped_final_frame = escape_markdown_v2(final_frame)
    try:
        # FIX: Escape the dots in "Killing..." and remove quote box
        await initial_message.edit_text(
            f"🔪 Kɪʟʟɪɴɢ\\.\\.\\.\n"
            f"```{escaped_final_frame}```"
        , parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.warning(f"Failed to edit message to final frame: {e}")

    # Calculate actual time taken after the loop finishes
    time_taken = round(time.time() - start_time)

    # Use bin_details passed directly
    bank_name = escape_markdown_v2(bin_details["bank"])
    level = escape_markdown_v2(bin_details["level"])
    level_emoji = get_level_emoji(bin_details["level"]) # Emoji doesn't need escaping
    brand = escape_markdown_v2(bin_details["scheme"])

    # Determine header based on card scheme
    header_title = "⚡Cᴀʀd Kɪʟʟᴇd Sᴜᴄᴄᴇssꜰᴜʟʟʏ"
    if bin_details["scheme"].lower() == 'mastercard':
        # Generate random percentage > 67%
        percentage = random.randint(68, 100)
        # Escaping % is important for markdown
        header_title = f"⚡Cᴀʀd Kɪʟʟᴇd Sᴜᴄᴄᴇssꜰᴜʟʟʏ \\- {percentage}\\%" 

    # Construct the final message using a single f-string for easy modification
    # Manual padding for visual alignment of colons
    final_message_text_formatted = (
        f"╭───\\[ {header_title} \\]───╮\n" # FIX: Escaped the closing bracket ']'
        f"\n"
        f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str)}`\n"
        f"• 𝗕𝗿𝗮𝗻𝗱        : `{brand}`\n"
        f"• 𝗜𝘀𝘀𝘂𝗲𝗿       : `{bank_name}`\n"
        f"• 𝗟𝗲𝘃𝗲𝗹        : `{level_emoji} {level}`\n"
        f"• 𝗞𝗶𝗹𝗹𝗲𝗿       :  𝓒𝓪𝓻𝓭𝓥𝓪𝓾𝒍𝒕𝑿\n"
        f"• 𝗕𝒐𝒕 𝒃𝒚      :  🔮 𝓖𝓸𝓼𝓽𝓑𝓲𝒕 𝖃𝖃𝖃 👁️\n"
        f"• 𝗧𝗶𝗺𝗲 𝗧𝗮𝗸𝗲𝗻  : {escape_markdown_v2(f'{time_taken:.0f} seconds')}\n"
        f"\n"
        f"╰────────────────────╯"
    )
    # The hyphens in the header and footer are non-special characters and don't need escaping,
    # but the brackets do, which I have added.

    await initial_message.edit_text(final_message_text_formatted, parse_mode=ParseMode.MARKDOWN_V2)


async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    # Owner bypasses all checks
    if user_id != OWNER_ID:
        # For group chats, if not authorized, return
        if (chat_type == 'group' or chat_type == 'supergroup') and update.effective_chat.id not in AUTHORIZED_CHATS:
            await update.effective_message.reply_text( # Use effective_message
                f"🚫 This group chat is not authorized to use this bot\\. Please contact {AUTHORIZATION_CONTACT} to get approved\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return
        # For private chats, if not authorized, return
        if chat_type == 'private' and user_id not in AUTHORIZED_PRIVATE_USERS:
            keyboard = [[InlineKeyboardButton("Official Group", url=OFFICIAL_GROUP_LINK)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text( # Use effective_message
                f"🚫 You are not approved to use bot in private\\. Get the subscription at cheap from {AUTHORIZATION_CONTACT} to use or else use for free in our official group\\.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

    # Credit check for /kill command (only if not owner)
    if user_id != OWNER_ID:
        remaining_credits = get_user_credits(user_id)
        if remaining_credits <= 0:
            await update.effective_message.reply_text( # Use effective_message
                f"❌ You have no credits left for the kill command today\\. Your daily credits will reset soon\\. Use other commands for free in our official group, or contact {AUTHORIZATION_CONTACT} for more credits\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return
        
    if not await enforce_cooldown(user_id, update): # Pass update to cooldown
        return 

    card_details_input = None

    # 1. Try to get card details from command arguments
    if context.args:
        card_details_input = " ".join(context.args)
        logger.debug(f"Kill command: Card details from args: '{card_details_input}')")
    # 2. If no arguments, try to get from message text for .kill command
    elif update.effective_message and (update.effective_message.text.lower().startswith(".kill ") or update.effective_message.text.lower().startswith("/kill ")):
        # Extract content after the command word
        parts = update.effective_message.text.split(maxsplit=1)
        if len(parts) > 1:
            card_details_input = parts[1].strip()
        logger.debug(f"Kill command: Card details from message text: '{card_details_input}'")
    # 3. Fallback to replied message if no direct arguments
    elif update.effective_message and update.effective_message.reply_to_message and update.effective_message.reply_to_message.text:
        card_details_input = update.effective_message.reply_to_message.text
        logger.debug(f"Kill command: Card details from replied message: '{card_details_input}'")

    if not card_details_input:
        logger.info("Kill command: No card details found in arguments or replied message.")
        return await update.effective_message.reply_text( # Use effective_message
            "❌ Please provide card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) as an argument or reply to a message containing them\\. "
            "Usage: `/kill CC\\|MM\\|YY\\|CVV` or `\\.kill CC\\|MM\\|YYYY\\|CVV`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Regex to find card details in `CC|MM|YY|CVV` or `CC|MM|YYYY|CVV` format.
    # Added \s* around | to tolerate spaces, and \s*$ to tolerate trailing spaces.
    card_match = re.search(r"(\d{13,19})\s*\|\s*(\d{2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3,4})\s*$", card_details_input)
    logger.debug(f"Kill command: Regex match result: {card_match}")

    if not card_match:
        logger.info(f"Kill command: Regex failed to match for input: '{card_details_input}'")
        return await update.effective_message.reply_text( # Use effective_message
            "❌ Could not find valid card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) in the provided input\\. "
            "Make sure it's in the format `CC|MM|YY|CVV` or `MM/YY/CVV`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    cc = card_match.group(1)
    mm = card_match.group(2)
    yy = card_match.group(3) # Keep the original year format (YY or YYYY) for display
    cvv = card_match.group(4)

    full_card_str = f"{cc}|{mm}|{yy}|{cvv}"

    # --- Moved logic for Prepaid and Amex checks here ---
    bin_number = cc[:6]
    bin_details = await get_bin_details(bin_number)

    if bin_details["card_type"].lower() == "prepaid":
        return await update.effective_message.reply_text(
            f"🚫 𝙋𝙧𝙚𝙥𝙖𝙞𝙙 𝘽𝙄𝙉s 𝙖𝙧𝙚 𝙣𝙤𝙩 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙩𝙤 𝙠𝙞𝙡𝙡 💳\\. Bin: `{escape_markdown_v2(bin_number)}` 💳 𝙞𝙨 𝙖 𝙥𝙧𝙚𝙥𝙖𝙞𝙙 𝙩𝙮𝙥𝙚\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    elif bin_details["scheme"].lower() == "american express":
        return await update.effective_message.reply_text(
            f"🚫 𝘼𝙈𝙀𝙓 𝙘𝙖𝙧𝙙𝙨 𝙖𝙧𝙚 𝙣𝙤𝙩 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙩𝙤 𝙠𝙞𝙡𝙡 💳\\. Bin: `{escape_markdown_v2(bin_number)}` 💳 𝙞𝙨 𝙖𝙣 𝘼𝙢𝙚𝙧𝙞𝙘𝙖𝙣 𝙀𝙭𝙥𝙧𝙚𝙨𝙨 𝙩𝙮𝙥𝙚\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    # --- End of moved logic ---

    # Consume credit after all validations pass and before starting the process
    if user_id != OWNER_ID:
        consume_credit(user_id)
        remaining_credits_after_use = get_user_credits(user_id) # Get updated credits
        await update.effective_message.reply_text(f"💳 Card received\\. Your remaining credits: `{remaining_credits_after_use}`\\.", parse_mode=ParseMode.MARKDOWN_V2)


    # Send the initial message and store it to edit later
    initial_message = await update.effective_message.reply_text( # Use effective_message
        f"🔪Kɪʟʟɪɴɢ ⚡" # Initial message without quote box
    , parse_mode=ParseMode.MARKDOWN_V2)

    # Create a separate task for the long-running kill process, passing bin_details
    asyncio.create_task(_execute_kill_process(update, context, full_card_str, initial_message, bin_details))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update): # Pass update to cooldown
        return 

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
        f"> 🤖 Bot by \\- 🔮 𝓖𝓸𝓼𝓽𝓑𝓲𝓽 𝖃𝖃𝖃 👁️"
    )

    await update.effective_message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN_V2)

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if get_user_credits(user_id) <= 0:
        await update.message.reply_text(
            "🚫 You have no remaining credits\\. Please subscribe to continue using this bot\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    user_full_name = escape_markdown_v2(update.effective_user.full_name)
    remaining_credits = get_user_credits(user_id)

    credits_msg = (
        f"╭━━━ *𝘊𝘳𝘦𝘥𝘪𝘵𝘴 𝘚𝘵𝘢𝘵𝘶𝘴* ━━━⬣\n"
        f"┣ ❏ *Username* ➳ `{user_full_name}`\n"
        f"┣ ❏ *Credits* ➳ `{remaining_credits}` / `50`\n"
        f"┣ ❏ *Plan* ➳ `Free`\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.message.reply_text(credits_msg, parse_mode=ParseMode.MARKDOWN_V2)

async def fl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return

    # Step 1: Get the input text from message or reply
    text = None
    if context.args:
        text = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    else:
        await update.message.reply_text("❌ Please reply to a message or provide dump with card format like `cc|mm|yy|cvv`.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Step 2: Extract all card patterns
    pattern = r'(\d{13,19})\s*\|\s*(\d{2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3,4})'
    matches = re.findall(pattern, text)

    if not matches:
        await update.message.reply_text("⚠️ No card data found in the provided input\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Step 3: Format the cards
    formatted_cards = []
    seen = set()
    for cc, mm, yy, cvv in matches:
        card = f"{cc}|{mm}|{yy}|{cvv}"
        if card not in seen:
            formatted_cards.append(f"`{card}`")
            seen.add(card)

    # Step 4: Build the final message
    count = len(formatted_cards)
    cards_str = "\n".join(formatted_cards)
    escaped_user = escape_markdown_v2(update.effective_user.full_name)

    msg = (
        f"╭━━━ [ 💳 𝘊𝘢𝘳𝘥 𝘓𝘪𝘴𝘵 𝘌𝘹𝘵𝘳𝘢𝘤𝘵𝘦𝘥 ] ━━━⬣\n"
        f"┣ ❏ Total Cards ➳ `{count}`\n"
        f"┣ ❏ Requested by ➳ `{escaped_user}`\n"
        f"┣ ❏ Bot by ➳ 🔮 𝓖𝓸𝓼𝓽𝓑𝓲𝓽 𝖃𝖃𝖃 👁️\n"
        f"╰━━━━━━━━━━━━━━━━━━━━⬣\n\n"
        f"{cards_str}"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)






from faker import Faker
import random
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

def escape_markdown_v2(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)

# Country to Locale Mapping
country_locale_map = {
    "usa": "en_US", "us": "en_US", "united states": "en_US",
    "uk": "en_GB", "united kingdom": "en_GB",
    "india": "en_IN", "in": "en_IN", "bharat": "en_IN",
    "canada": "en_CA", "australia": "en_AU",
    "germany": "de_DE", "france": "fr_FR",
    "spain": "es_ES", "italy": "it_IT"
}

async def fk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_authorization(update, context):
        return
    if not await enforce_cooldown(update.effective_user.id, update):
        return

    # Get country input
    args = context.args
    country_input = " ".join(args).strip().lower() if args else "usa"
    locale = country_locale_map.get(country_input, "en_US")

    # Create faker instance with specific locale
    fake = Faker(locale)

    # Generate all values using locale-specific faker
    name = escape_markdown_v2(fake.name())
    dob = escape_markdown_v2(fake.date_of_birth(minimum_age=18, maximum_age=50).strftime("%d/%m/%Y"))
    ssn = escape_markdown_v2(fake.ssn()) if hasattr(fake, "ssn") else escape_markdown_v2(fake.bban())
    email = escape_markdown_v2(fake.email())
    username = escape_markdown_v2(fake.user_name())
    phone = escape_markdown_v2(fake.phone_number())
    job = escape_markdown_v2(fake.job())
    company = escape_markdown_v2(fake.company())
    street = escape_markdown_v2(fake.street_address())
    address2 = escape_markdown_v2(fake.secondary_address()) if hasattr(fake, "secondary_address") else "Apt. 102"
    city = escape_markdown_v2(fake.city())
    state = escape_markdown_v2(fake.state())
    zip_code = escape_markdown_v2(fake.postcode())
    country = escape_markdown_v2(fake.current_country()) if hasattr(fake, "current_country") else escape_markdown_v2(country_input.upper())
    ip = escape_markdown_v2(fake.ipv4())
    ua = escape_markdown_v2(fake.user_agent())
    msg = (
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

    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)

import httpx
import re
import asyncio
from datetime import datetime, timedelta
from telegram import Update, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# === GLOBAL STATE ===
# Cooldown tracker
user_cooldowns = {}
COOLDOWN_SECONDS = 5

# MarkdownV2 escaper
def escape_markdown_v2(text: str) -> str:
    """
    Escapes special characters for MarkdownV2 formatting.
    This implementation is more robust and escapes characters individually.
    """
    special_chars = r'_*[]()~`>#+-=|{}.!\\'
    return ''.join([f'\\{char}' if char in special_chars else char for char in text])

# Payment gateway signatures with more specific JS/API patterns
GATEWAY_SIGNATURES = {
    # --- Major Global Gateways ---
    "Stripe": [
        r'\b(stripe\.com/v1|pk_live_|pk_test_|stripe-checkout|stripe\.js)\b',
        r'\b(data-stripe|stripe-key|stripe-session-id)\b',
        r'\b(js\.stripe\.com|checkout\.stripe\.com)\b',
        r'\b(api\.stripe\.com/v1)\b',
        r'\b(Stripe\.(?P<method>createToken|confirmCardPayment|redirectToCheckout))\b' # Added more JS method calls
    ],
    "PayPal": [
        r'\b(paypal\.com/cgi-bin/webscr|paypalobjects\.com|data-paypal-button|paypal-checkout|pp_btn_pay)\b',
        r'\b(www\.paypal\.com/sdk/js|paypal\.me)\b',
        r'\b(paypal-braintree-client|paypal-rest-sdk)\b' # Added more SDKs
    ],
    "Braintree": [
        r'\b(braintreepayments\.com|braintree\.js|braintree-web|client-token)\b',
        r'\b(assets\.braintreegateway\.com)\b',
        r'\b(paypal\.checkout\.braintree|braintree\.dropin)\b',
        r'\b(braintree\.setup)\b'
    ],
    "Adyen": [
        r'\b(adyen\.com|adyen/checkout\.min\.js|data-adyen-payment-method|adyen\.checkout\.api)\b',
        r'\b(checkout\.adyen\.com|components\.adyen\.com|api\.adyen\.com|AdyenCheckout)\b',
        r'\b(adyen-payment-form|adyen\.init\.checkout)\b' # Added specific Adyen-related checkout/form patterns
    ],
    "Authorize.net": [
        r'\b(authorize\.net/v1|accept\.authorize\.net|data-anet-payment-form)\b',
        r'\b(secure2\.authorize\.net|anet\.js)\b'
    ],
    "Square": [
        r'\b(squareup\.com/js/payment\.js|square\.com|square-web-sdk)\b',
        r'\b(connect\.squareup\.com|api\.squareup\.com)\b'
    ],
    "Worldpay": [
        r'\b(worldpay\.com|worldpay-js|secure\.worldpay\.com)\b'
    ],
    "2Checkout": [
        r'\b(2checkout\.com|2co\.com|tco\.com)\b',
        r'\b(checkout\.2co\.com)\b'
    ],
    "Klarna": [
        r'\b(klarna\.com|klarna-payments|data-klarna)\b',
        r'\b(cdn\.klarnacdn\.com)\b'
    ],
    "Afterpay": [
        r'\b(afterpay\.com|afterpay-payments)\b',
        r'\b(static\.afterpay\.com)\b'
    ],
    "Revolut": [
        r'\b(revolut\.com|revolut-payments)\b',
        r'\b(assets\.revolut\.com|api\.revolut\.com)\b'
    ],
    "Checkout.com": [
        r'\b(checkout\.com|checkout-js|frames\.js)\b',
        r'\b(api\.checkout\.com)\b'
    ],
    "FastSpring": [
        r'\b(fastspring\.com|fsc\.com)\b',
        r'\b(checkout\.fastspring\.com)\b'
    ],
    "BlueSnap": [
        r'\b(bluesnap\.com|bluesnap\.js)\b',
        r'\b(checkout\.bluesnap\.com)\b'
    ],
    "Global Payments": [
        r'\b(globalpay\.com|api\.globalpay\.com)\b',
        r'\b(hpp\.globalpay\.com)\b'
    ],
    "Cybersource": [
        r'\b(cybersource\.com|cybersource-api)\b',
        r'\b(flex\.cybersource\.com)\b'
    ],
    "Payoneer": [
        r'\b(payoneer\.com|payoneer\.checkout)\b'
    ],
    "Mollie": [
        r'\b(mollie\.com|mollie\.js|api\.mollie\.com)\b'
    ],
    "Plaid": [
        r'\b(plaid\.com|plaidlink\.js)\b'
    ],
    "GoCardless": [
        r'\b(gocardless\.com|gocardless-js)\b',
        r'\b(pay\.gocardless\.com)\b'
    ],
    "DLocal": [
        r'\b(dlocal\.com|dlocal-api)\b',
        r'\b(checkout\.dlocal\.com)\b'
    ],
    "Payfort": [
        r'\b(payfort\.com|fort\.js)\b'
    ],
    "WePay": [
        r'\b(wepay\.com|wepay\.js)\b'
    ],
    "Paddle": [
        r'\b(paddle\.com|paddle\.js)\b',
        r'\b(cdn\.paddle\.com)\b'
    ],
    "Paysafe": [ # Added Paysafe
        r'\b(paysafe\.com|paysafe-api)\b',
        r'\b(checkout\.paysafe\.com)\b'
    ],
    
    # --- Indian/Asian Market ---
    "Razorpay": [
        r'\b(razorpay\.com/checkout|checkout\.razorpay\.com|api\.razorpay\.com)\b',
        r'\b(data-key|rzp_live|rzp_test|razorpay_order_id|razorpay_payment_id|razorpay_signature|RazorpayCheckout)\b',
        r'\b(checkout\.js)\b'
    ],
    "Juspay (Swiggy/Others)": [
        r'\b(juspay\.in|hyperupi\.com|juspay-sdk)\b',
        r'\b(Swiggy UPI|Zomato UPI)\b',
        r'\b(juspaysdk)\b'
    ],
    "PayU": [
        r'\b(payu\.in|payu\.com|payumoney\.com)\b',
        r'\b(payment-page\.payu\.in|secure\.payu\.in)\b', # Added secure URL
        r'\b(payulatam\.com|payu\.pl)\b' # Added regional variations
    ],
    "Paytm": [
        r'\b(paytm\.com|paytm-payments|paytmpayments\.com|paytm-wallet|paytm\.in)\b',
        r'\b(securegw\.paytm\.in|pg\.paytm\.in)\b'
    ],
    "PhonePe": [
        r'\b(phonepe\.com|phonepe-checkout|phonepe-payments)\b',
        r'\b(api\.phonepe\.com)\b'
    ],
    "UPI": [
        r'\b(upi:\/\/pay|vpa|upi\-pin)\b'
    ],
    "Paystack": [
        r'\b(paystack\.co|paystack\.js)\b',
        r'\b(js\.paystack\.co|api\.paystack\.co)\b'
    ],
    "Zomato Pay": [
        r'\b(zomato-pay|zomatopay|zomatopayments)\b',
        r'\b(api\.zomato\.com/v1/payment)\b'
    ],
    "Instamojo": [
        r'\b(instamojo\.com|instamojo-js)\b'
    ],
    "CCAvenue": [
        r'\b(ccavenue\.com|ccavenue-api)\b',
        r'\b(secure\.ccavenue\.com)\b'
    ],
    "Paytabs": [
        r'\b(paytabs\.com|paytabs\.js)\b'
    ],
    "Easebuzz": [
        r'\b(easebuzz\.in|easebuzz-api)\b'
    ],
    "UnionPay": [ # Added UnionPay
        r'\b(unionpay\.com|unionpayinternational\.com|upay\.com)\b',
        r'\b(cloudpay\.unionpay\.com)\b',
        r'\b(China UnionPay)\b'
    ],
    "WeChat Pay": [ # Added WeChat Pay
        r'\b(wechatpay\.com|pay\.weixin\.qq\.com)\b',
        r'\b(wx-jsapi)\b'
    ],
    "Alipay": [ # Added Alipay
        r'\b(alipay\.com|alipay-payments)\b',
        r'\b(qr\.alipay\.com|openapi\.alipay\.com)\b'
    ],
    
    # --- Other Gateways ---
    "NMI": [
        r'\b(secure\.nmi\.com|nmi-token)\b'
    ],
    "Eway": [
        r'\b(eway\.com\.au|eway-rapid-api|ewaygateway\.com)\b'
    ],
    "Paysera": [
        r'\b(paysera\.com|paysera_api)\b'
    ],
    "PagSeguro": [
        r'\b(pagseguro\.uol\.com\.br)\b'
    ],
    "Amazon Pay": [
        r'\b(pay\.amazon\.com|amazon-pay-button)\b',
        r'\b(amazon-checkout-sdk|amazon-payment-services)\b',
        r'\b(https://payments\.amazon\.com)\b',
        r'\b(amazon\.co\.uk/gp/buy/sp/widget/)\b'
    ],
    "Google Pay / GPay": [
        r'\b(googlepay\.com|gpay)\b'
    ],
    "Trustly": [
        r'\b(trustly\.com|trustly-api|trustly\.js)\b'
    ],

    # --- In-built eCommerce Systems ---
    "Shopify Payments": [
        r'\b(cdn\.shopify\.com|data-shop-id|shopify\.com/payments)\b',
        r'\b(shopify\.checkout|checkout\.shopify\.com)\b'
    ],
    "WooCommerce": [
        r'\b(woocommerce\.com|wc-ajax=checkout)\b',
        r'\b(wp-json/wc/v3)\b'
    ],
    "Magento": [
        r'\b(magento\.com|data-magento-init)\b',
        r'\b(checkout\.magento\.com)\b'
    ],
    "BigCommerce": [
        r'\b(bigcommerce\.com|bc-checkout)\b',
        r'\b(store-.+\.mybigcommerce\.com)\b'
    ],
    "PrestaShop": [
        r'\b(prestashop\.com|prestashop-checkout)\b'
    ],
    "OpenCart": [
        r'\b(opencart\.com|index\.php\?route=checkout)\b'
    ],
    "Big Cartel": [
        r'\b(bigcartel\.com)\b'
    ],
    "Ecwid": [
        r'\b(ecwid\.com|ecwid-store)\b'
    ],
    
    # --- Generic Payment Indicators ---
    "Generic Payment System": [
        r'\b(checkout|payment|paynow|pay|secure-payment|buy-now|purchase|billing|donations|add-to-cart)\b',
        r'\b(payment-form|payment-gateway-button|payment-gateway-field|cc-form|credit-card|debit-card|card-number|card-expiry|card-cvv|cvv|cvc|card-holder-name|expiry-date|payment-api|payment-widget|payment-method)\b',
        r'/(checkout|payment|purchase|pay|cart|billing)\b',
        r'(src="payment\.js"|/api/payment|/api/checkout|/api/secure-payment)',
        r'\b(data-payment-type)\b'
    ]
}

async def gate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyzes a website for payment gateways and edits the message."""
    user_id = update.effective_user.id

    # Enforce per-user cooldown
    now = datetime.now()
    if user_id in user_cooldowns and now < user_cooldowns[user_id]:
        return
    user_cooldowns[user_id] = now + timedelta(seconds=COOLDOWN_SECONDS)

    # Input validation
    if not context.args:
        await update.message.reply_text("🚫 Usage: `/gate <url>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url

    # Inform user and get the message object to edit later
    sent_message = None
    try:
        sent_message = await update.message.reply_text("🔍 *Fetching\\, please wait\\.\\.\\.*", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        # If we can't even send the initial message, log it and stop.
        print(f"Failed to send initial message: {e}")
        return

    # Fetch the page
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            html = response.text.lower()
            status = response.status_code
    except Exception as e:
        error_message = (
            f"╭━━━ 𝗘𝗿𝗿𝗼𝗿 ━━━━⬣\n"
            f"┣ ❏ 𝗠𝗲𝘀𝘀𝗮𝗴𝗲 ➳ `{escape_markdown_v2(str(e))}`\n"
            f"╰━━━━━━━━━━━━━━━━━━⬣"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=sent_message.chat_id,
                message_id=sent_message.message_id,
                text=error_message,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            # Fallback to sending a new message if editing fails
            await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Deep gateway detection
    found_gateways = set()
    for gateway, signatures in GATEWAY_SIGNATURES.items():
        if any(re.search(sig, html, re.I) for sig in signatures):
            found_gateways.add(gateway)

    # Captcha detection
    captcha = "ReCaptcha" if "recaptcha" in html else ("hCaptcha" if "hcaptcha" in html else "N/A")
    
    # Other checks
    cloudflare = "Yes" if "cloudflare" in html or "cf-ray" in response.headers else "N/A"
    security = "HTTPS" if url.startswith("https://") else "No HTTPS"
    cvv = "Yes" if re.search(r'cvv|cvc', html, re.I) else "N/A"
    
    # Build response
    output = (
        f"╭━━━ 𝗟𝗼𝗼𝗸𝘂𝗽 𝗥𝗲𝘀𝘂𝗹𝘁 ━━━━⬣\n"
        f"┣ ❏ 𝗦𝗶𝘁𝗲 ➳ `{escape_markdown_v2(url)}`\n"
        f"┣ ❏ 𝗣𝗮𝘆𝗺𝗲𝗻𝘁 𝗚𝗮𝘁eways ➳ `{escape_markdown_v2(', '.join(sorted(list(found_gateways))) if found_gateways else 'N/A')}`\n"
        f"┣ ❏ 𝗖𝗮𝗽𝘁𝗰𝗵𝗮 ➳ `{escape_markdown_v2(captcha)}`\n"
        f"┣ ❏ 𝗖𝗹𝗼𝘂𝗱𝗳𝗹𝗮𝗿𝗲 ➳ `{escape_markdown_v2(cloudflare)}`\n"
        f"┣ ❏ 𝗦𝗲𝗰𝘂𝗿𝗶𝘁𝘆 ➳ `{escape_markdown_v2(security)}`\n"
        f"┣ ❏ 𝗖𝗩𝗩/𝗖𝗩𝗖 ➳ `{escape_markdown_v2(cvv)}`\n"
        f"┣ ❏ 𝗦𝘁𝗮𝘁𝘂𝘀 ➳ `{escape_markdown_v2(str(status))}`\n"
        f"╰━━━━━━━━━━━━━━━━━━⬣"
    )

    # Edit the original message with the final result
    try:
        await context.bot.edit_message_text(
            chat_id=sent_message.chat_id,
            message_id=sent_message.message_id,
            text=output,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception:
        # Fallback to sending a new message if editing fails
        await update.message.reply_text(output, parse_mode=ParseMode.MARKDOWN_V2)


# --- New /help command ---
from telegram.constants import ParseMode

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_authorization(update, context, is_group_only=True):
        return

    if not await enforce_cooldown(update.effective_user.id, update):
        return

    help_message = (
        "╭━━━[ 🤖 *Help Menu* ]━━━⬣\n"
        "┣ ❏ `/start` \\- Welcome message\n"
        "┣ ❏ `/help` \\- Shows this help message\n"
        "┣ ❏ `/gen <bin>` \\- Generate cards from BIN\n"
        "┣ ❏ `/bin <bin>` \\- BIN lookup \\(bank, country, type\\)\n"
        "┣ ❏ `/kill <cc|mm|yy|cvv>` \\-  kill a card\n"
        "┣ ❏ `/fk <country>` \\- Generate fake identity info\n"
        "┣ ❏ `/gate <url>` \\- Check payment gateways on a website\n"
        "┣ ❏ `/status` \\- Bot system status info\n"
        "┣ ❏ `/credits` \\- Check your remaining credits\n"
        "╰━━━━━━━━━━━━━━━━━━⬣"
    )

    await update.message.reply_text(help_message, parse_mode=ParseMode.MARKDOWN_V2)



async def authorize_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if not context.args:
        return await update.effective_message.reply_text("Usage: `/au [chat_id]`\\. Please provide a chat ID\\.", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        chat_id_to_authorize = int(context.args[0])
        AUTHORIZED_CHATS.add(chat_id_to_authorize)
        chat_info = await context.bot.get_chat(chat_id_to_authorize)
        chat_title = escape_markdown_v2(chat_info.title if chat_info.title else f"Unnamed Group {chat_id_to_authorize}")
        await update.effective_message.reply_text(f"✅ Group `{chat_title}` \\(`{chat_id_to_authorize}`\\) is now authorized to use the bot\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid chat ID\\. Please provide a numeric chat ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error authorizing group: {escape_markdown_v2(str(e))}\\. Make sure bot is in the group\\.", parse_mode=ParseMode.MARKDOWN_V2)


async def authorize_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if not context.args:
        return await update.effective_message.reply_text("Usage: `/auth [user_id]`\\. Please provide a user ID\\.", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        user_id_to_authorize = int(context.args[0])
        AUTHORIZED_PRIVATE_USERS.add(user_id_to_authorize)
        user_info = await context.bot.get_chat(user_id_to_authorize)
        user_full_name = escape_markdown_v2(user_info.full_name)
        await update.effective_message.reply_text(f"✅ User `{user_full_name}` \\(`{user_id_to_authorize}`\\) is now authorized to use the bot in private chat\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid user ID\\. Please provide a numeric user ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error authorizing user: {escape_markdown_v2(str(e))}\\. Make sure bot has interacted with user before\\.", parse_mode=ParseMode.MARKDOWN_V2)


async def remove_authorize_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if not context.args:
        return await update.effective_message.reply_text("Usage: `/rauth [user_id]`\\. Please provide a user ID to unapprove\\.", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        user_id_to_unauthorize = int(context.args[0])
        if user_id_to_unauthorize in AUTHORIZED_PRIVATE_USERS:
            AUTHORIZED_PRIVATE_USERS.remove(user_id_to_unauthorize)
            # Also remove them from USER_CREDITS to reset their state
            if user_id_to_unauthorize in USER_CREDITS:
                del USER_CREDITS[user_id_to_unauthorize]
            
            user_info = await context.bot.get_chat(user_id_to_unauthorize)
            user_full_name = escape_markdown_v2(user_info.full_name)
            await update.effective_message.reply_text(
                f"❌ User `{user_full_name}` \\(`{user_id_to_unauthorize}`\\) has been unapproved from using the bot in private chat and their credits reset\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await update.effective_message.reply_text(
                f"⚠️ User `{user_id_to_unauthorize}` was not found in the authorized private users list\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid user ID\\. Please provide a numeric user ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ Error unapproving user: {escape_markdown_v2(str(e))}\\. Make sure bot has interacted with user before\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


async def add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command\\.", parse_mode=ParseMode.MARKDOWN_V2)
    
    if len(context.args) != 2:
        return await update.effective_message.reply_text("Usage: `/ar [amount] [user_id]`\\. Example: `/ar 50 123456789`", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        amount = int(context.args[0])
        target_user_id = int(context.args[1])
        
        if amount <= 0:
            return await update.effective_message.reply_text("❌ Amount must be a positive number\\.", parse_mode=ParseMode.MARKDOWN_V2)

        new_credits = add_credits_to_user(target_user_id, amount)
        target_user_info = await context.bot.get_chat(target_user_id)
        target_user_full_name = escape_markdown_v2(target_user_info.full_name)
        await update.effective_message.reply_text(
            f"✅ Added `{amount}` credits to user `{target_user_full_name}` \\(`{target_user_id}`\\)\\. Total credits for user: `{new_credits}`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid amount or user ID\\. Please provide numeric values\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ Error adding credits: {escape_markdown_v2(str(e))}\\. Make sure bot has interacted with user before\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.effective_message.reply_text("🚫 You are not authorized to use this command\\.", parse_mode=ParseMode.MARKDOWN_V2)

    # --- Authorized Groups ---
    authorized_groups_list = []
    for chat_id in AUTHORIZED_CHATS:
        try:
            chat = await context.bot.get_chat(chat_id)
            group_name = escape_markdown_v2(chat.title)
            authorized_groups_list.append(f"    • {group_name} \\(`{chat_id}`\\)")
        except Exception:
            authorized_groups_list.append(f"    • Unknown Group \\(`{chat_id}`\\) \\(Bot might not be in the group\\)")
    authorized_groups_str = "\n".join(authorized_groups_list) if authorized_groups_list else "    _None_"

    # --- Authorized Private Users ---
    authorized_private_users_list = []
    for user_id in AUTHORIZED_PRIVATE_USERS:
        try:
            user = await context.bot.get_chat(user_id) # get_chat can also get user info
            user_full_name = escape_markdown_v2(user.full_name)
            authorized_private_users_list.append(f"    • {user_full_name} \\(`{user_id}`\\)")
        except Exception:
            authorized_private_users_list.append(f"    • Unknown User \\(`{user_id}`\\) \\(Bot might not have interacted with user\\)")
    authorized_private_users_str = "\n".join(authorized_private_users_list) if authorized_private_users_list else "    _None_"

    admin_info_msg = (
        f"👑 *Admin Panel Overview* 👑\n"
        f"──────────────\n"
        f"📚 *Authorized Groups:*\n"
        f"{authorized_groups_str}\n"
        f"\n"
        f"👥 *Authorized Private Users:*\n"
        f"{authorized_private_users_str}\n"
        f"──────────────\n"
        f"Use `/au \\<chat\\_id\\>` to authorize a group\\.\n"
        f"Use `/auth \\<user\\_id\\>` to authorize a private user\\.\n"
        f"Use `/ar \\<amount\\> \\<user\\_id\\>` to add credits\\.\n"
        f"Use `/rauth \\<user\\_id\\>` to unapprove a private user\\."
    )
    await update.effective_message.reply_text(admin_info_msg, parse_mode=ParseMode.MARKDOWN_V2)


async def handle_unauthorized_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This handler acts as a catch-all for commands or messages from unauthorized sources
    # that are NOT already explicitly handled and blocked by the check_authorization in specific handlers.
    
    if update.effective_user.id == OWNER_ID:
        # Owner is always authorized, so we don't send authorization messages for them.
        # If the command is not recognized, it will simply do nothing.
        return

    # If the bot receives a message (which might be a command) and it's not from an owner,
    # and the effective_message is available, proceed with authorization check.
    if update.effective_message:
        chat_type = update.effective_chat.type
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        # Skip explicit messages to owner if it's already caught by owner_id check
        # This part ensures that if a non-owner tries a command, they get the correct message.
        # Note: Commands that have their own `check_authorization` call at the beginning
        # will handle their own unauthorized responses first. This catches general unhandled commands.
        if chat_type == 'private' and user_id not in AUTHORIZED_PRIVATE_USERS:
            # For private users not authorized, show specific message and group button
            keyboard = [[InlineKeyboardButton("Official Group", url=OFFICIAL_GROUP_LINK)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                f"🚫 You are not approved to use bot in private\\. Get the subscription at cheap from {AUTHORIZATION_CONTACT} to use or else use for free in our official group\\.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return
        elif (chat_type == 'group' or chat_type == 'supergroup') and chat_id not in AUTHORIZED_CHATS:
            # For unauthorized groups, show specific message
            await update.effective_message.reply_text(
                f"🚫 This group chat is not authorized to use this bot\\. Please contact {AUTHORIZATION_CONTACT} to get approved\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return
    # If the user/chat is authorized, or effective_message is not available (e.g., channel post),
    # this handler does nothing, allowing other handlers or the default Telegram behavior.


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    try:
        # Try to send a generic error message to the user if a message context is available
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "An unexpected error occurred\\. Please try again or contact support\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except Exception as e:
        logger.error(f"Failed to send error message to user in error_handler: {e}")

# === MAIN FUNCTION ===
def main():
    if TOKEN is None:
        logger.error("TOKEN is not set.")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # Start command (always accessible and needs to handle callback queries)
    application.add_handler(CommandHandler("start", start))

    # Commands that require authorization (check_authorization is inside each handler)
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("credits", credits_command))
    application.add_handler(CommandHandler("fl", fl_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\.fl\s'), fl_command))
    application.add_handler(CommandHandler("fk", fk_command)) # Corrected function name
    application.add_handler(CommandHandler("gate", gate_command))
    application.add_handler(CommandHandler("help", help_command, filters=filters.ChatType.GROUPS)) # /help only in groups

    # Dot-prefixed versions
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.gen\b.*"), gen))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.bin\b.*"), bin_lookup))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.kill\b.*") & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS), kill))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.credits\b.*"), credits_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.fk\b.*"), fk_command)) # Corrected function name
    application.add_handler(CommandHandler("help", help_command))

    # Kill command in both private & groups
    application.add_handler(CommandHandler("kill", kill, filters=filters.ChatType.PRIVATE | filters.ChatType.GROUPS))

    # Owner-only commands
    application.add_handler(CommandHandler("au", authorize_group)) # Authorize Group
    application.add_handler(CommandHandler("auth", authorize_user)) # Authorize Private User
    application.add_handler(CommandHandler("ar", add_credits)) # Add Credits to User
    application.add_handler(CommandHandler("admin", admin_command)) # Admin Dashboard
    application.add_handler(CommandHandler("rauth", remove_authorize_user)) # Remove Authorized User

    # Callback query handlers for inline keyboard buttons
    application.add_handler(CallbackQueryHandler(show_main_commands, pattern="^show_main_commands$"))
    application.add_handler(CallbackQueryHandler(show_command_details, pattern="^cmd_"))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_start$")) # Re-direct to start handler

    # Fallback handler for unhandled commands
    application.add_handler(MessageHandler(
        filters.TEXT & filters.COMMAND, # Only messages that are slash commands
        handle_unauthorized_commands,
        block=False # Do not block other handlers
    ))

    # Global error handler
    application.add_error_handler(error_handler)

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
