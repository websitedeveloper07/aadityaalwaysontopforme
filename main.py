import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil
import random
import uuid # Added for idempotency key generation, if you're adding Stripe checker back
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

# Initialize Stripe API client (if you're adding it back)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if STRIPE_SECRET_KEY:
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY environment variable is not set. Stripe checker will not function.")


# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === ERROR HANDLER ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Try to send a message back to the user
    if update.effective_message:
        # Ensure the error message itself is MarkdownV2 escaped
        error_message_text = escape_markdown_v2("An error occurred while processing your request. Please try again later.")
        await update.effective_message.reply_text(
            error_message_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )

# === HELPER FUNCTIONS ===

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2 formatting."""
    if text is None:
        return "Unknown"
    text = str(text)
    # List of special characters in MarkdownV2 that need to be escaped, including '\'
    # The official Telegram documentation for MarkdownV2 lists:
    # _ * [ ] ( ) ~ ` > # + - = | { } . ! \
    special_chars = r'_*[]()~`>#+-=|{}.!\\' # Added backslash to the list
    # Use a regex to find any of these special characters and prepend a backslash
    return re.sub(r'([%s])' % re.escape(special_chars), r'\\\1', text)

def get_short_country_name(full_name: str) -> str:
    # ... (rest of your get_short_country_name function, no changes needed here)
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
    return f"❓ {escape_markdown_v2(status)}" # Ensured status itself is escaped

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

# Add Stripe checker if you plan to re-introduce it
async def check_card_with_stripe_live(card_number: str, exp_month: str, exp_year: str, cvc: str) -> dict:
    """
    Attempts a small authorization ($0.50 USD) and immediately refunds it
    to check if a card is live using Stripe.
    """
    if not STRIPE_SECRET_KEY:
        return {"status": "error", "message": "Stripe API key not configured. Contact bot owner."}

    # Use a unique ID for idempotency to prevent duplicate charges
    idempotency_key = f"auth_check_{uuid.uuid4()}"

    try:
        # Step 1: Create a PaymentMethod
        payment_method = await asyncio.to_thread(
            stripe.PaymentMethod.create,
            type="card",
            card={
                "number": card_number,
                "exp_month": exp_month,
                "exp_year": exp_year,
                "cvc": cvc,
            },
            idempotency_key=f"{idempotency_key}_pm"
        )

        # Step 2: Create a PaymentIntent for a small amount
        payment_intent = await asyncio.to_thread(
            stripe.PaymentIntent.create,
            amount=50,  # $0.50 USD
            currency="usd",
            payment_method=payment_method.id,
            confirm=True,
            off_session=True,
            metadata={"check_type": "card_auth_validation"},
            idempotency_key=f"{idempotency_key}_pi"
        )

        if payment_intent.status == 'succeeded':
            try:
                refund = await asyncio.to_thread(
                    stripe.Refund.create,
                    payment_intent=payment_intent.id,
                    idempotency_key=f"{idempotency_key}_refund"
                )
                logger.info(f"Successfully authorized and refunded card: {card_number[:6]}...{card_number[-4:]}")
                return {"status": "success", "message": "Card is LIVE and refunded.", "stripe_status": payment_intent.status, "refund_status": refund.status}
            except stripe.error.StripeError as e:
                logger.error(f"Stripe Refund Error for {card_number[:6]}...{card_number[-4:]}: {e.user_message} (Code: {e.code})")
                return {"status": "success", "message": f"Card is LIVE but refund failed: {escape_markdown_v2(e.user_message)}. Manual refund may be needed.", "stripe_status": payment_intent.status}
        else:
            logger.warning(f"Stripe PaymentIntent status for {card_number[:6]}...{card_number[-4:]}: {payment_intent.status}")
            return {"status": "failed", "message": f"Card is DEAD. Status: {escape_markdown_v2(payment_intent.status)}", "stripe_status": payment_intent.status}

    except stripe.error.CardError as e:
        logger.warning(f"Stripe Card Error for {card_number[:6]}...{card_number[-4:]}: {e.user_message} (Code: {e.code})")
        return {"status": "failed", "message": f"Card is DEAD. Reason: {escape_markdown_v2(e.user_message)}", "code": e.code, "stripe_status": e.code}
    except stripe.error.RateLimitError as e:
        logger.error(f"Stripe Rate Limit Error: {e.user_message}")
        return {"status": "error", "message": escape_markdown_v2("Stripe API rate limit exceeded. Please try again later.")}
    except stripe.error.AuthenticationError as e:
        logger.error(f"Stripe Authentication Error: {e.user_message}. Check your API key.")
        return {"status": "error", "message": escape_markdown_v2("Stripe API authentication failed. Contact bot owner.")}
    except stripe.error.StripeError as e:
        logger.error(f"General Stripe API Error for {card_number[:6]}...{card_number[-4:]}: {e.user_message} (Type: {e.error.type})")
        return {"status": "error", "message": f"An error occurred with Stripe: {escape_markdown_v2(e.user_message)}"}
    except Exception as e:
        logger.error(f"Unexpected error during live Stripe check: {e}", exc_info=True)
        return {"status": "error", "message": escape_markdown_v2("An unexpected error occurred during the live check.")}

# === COMMAND HANDLERS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Ensure all parts of the message are escaped if they might contain special characters
    welcome = f"👋 Hi, welcome {escape_markdown_v2(user.full_name)}!\n🤖 Bot Status: Active" # Escaped !
    buttons = [
        [InlineKeyboardButton("📜 Commands", callback_data="show_main_commands")],
        [InlineKeyboardButton("👥 Group", url="https://t.me/+8a9R0pRERuE2YWFh")]
    ]
    
    query = update.callback_query
    if query:
        await query.answer()
        # Ensure parse_mode is consistently MARKDOWN_V2 for edit_message_text
        await query.edit_message_text(welcome, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        # Ensure parse_mode is consistently MARKDOWN_V2 for reply_text
        await update.message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN_V2)

async def show_main_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    commands_text = "*📜 Bot Commands:*\nSelect a command to learn more:" # Escaped :
    buttons = [
        [InlineKeyboardButton("💳 Generate Cards (/gen)", callback_data="cmd_gen")],
        [InlineKeyboardButton("🔍 BIN Info (/bin)", callback_data="cmd_bin")],
        [InlineKeyboardButton("📊 Bot Status (/status)", callback_data="cmd_status")],
        [InlineKeyboardButton("💀 Kill Card (/kill)", callback_data="cmd_kill")],
        [InlineKeyboardButton("✅ Stripe Auth (/chk)", callback_data="cmd_chk")], # Re-added for Stripe Checker
        [InlineKeyboardButton("⬅️ Back to Start", callback_data="back_to_start")]
    ]
    
    if query:
        # Changed parse_mode to MARKDOWN_V2 as per bot's consistent usage
        await query.edit_message_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        # Changed parse_mode to MARKDOWN_V2 as per bot's consistent usage
        await update.message.reply_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN_V2)


async def show_command_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    command_name = query.data.replace("cmd_", "")
    
    usage_text = ""
    if command_name == "gen":
        usage_text = (
            "*💳 Card Generator*\n" + # Updated title
            "Usage: `/gen <BIN>` or `\\.gen <BIN>`\n" + # Consistent usage example
            "Example: `/gen 400000`\n" +
            "Generates 10 credit card numbers based on the provided 6\\-digit BIN\\. " + # Corrected punctuation
            "Includes expiry date \\(MM\\|YY\\) and CVV\\.\n" # Corrected punctuation
        ).strip()
    elif command_name == "bin":
        usage_text = (
            "*🔍 BIN Lookup*\n" + # Updated title
            "Usage: `/bin <BIN>` or `\\.bin <BIN>`\n" + # Consistent usage example
            "Example: `/bin 400000`\n" +
            "Provides detailed information about a given Bank Identification Number \\(BIN\\), " +
            "including card scheme, type, level, bank name, and country\\.\n"
        ).strip()
    elif command_name == "status":
        usage_text = (
            "*📊 Bot Status*\n" + # Updated title
            "Usage: `/status`\n" +
            "Displays the bot's current operational statistics, " +
            "including uptime, RAM usage, and CPU usage\\.\n"
        ).strip()
    elif command_name == "kill":
        usage_text = (
            "*💀 Card Killer \\(Simulation\\)*\n" + # Updated title
            "Usage: `/kill CC\\|MM\\|YY\\|CVV` or `\\.kill CC\\|MM\\|YYYY\\|CVV`\n" +
            "Alternatively, reply to a message containing card details with `/kill` or `\\.kill`\\.\n" +
            "Example: `/kill 4000001234567890\\|12\\|25\\|123`\n" +
            "Simulates a card 'killing' process with an animation\\. " +
            "This is a fun simulation and does not actually affect the card\\.\n"
        ).strip()
    elif command_name == "chk": # Added this new block
        usage_text = (
            "*💳 Stripe Live Auth Checker*\n" +
            "Usage: `/chk CC\\|MM\\|YY\\|CVV` or `\\.chk CC\\|MM\\|YYYY\\|CVV`\n" +
            "Alternatively, reply to a message with card details using `/chk` or `\\.chk`\\.\n" +
            "Example: `/chk 4242424242424242\\|12\\|25\\|123`\n" +
            "This command attempts to perform a small authorization \\(e\\.g\\., $0\\.50\\) " +
            "and immediately refunds it using Stripe's API to check if the card is live and can be charged\\.\n" +
            "*Note:* This is a *live* check and will appear on the cardholder's statement as a small authorization followed by a refund\\.\n"
        ).strip()
    elif command_name == "au":
        usage_text = (
            "*🔐 Authorize Group \\(Owner Only\\)*\n" +
            "Usage: `/au <chat_id>`\n" +
            "Example: `/au \\-1001234567890`\n" +
            "Allows the bot owner to authorize a specific group for bot usage\\. " +
            "This command is restricted to the bot owner only\\.\n"
        ).strip()
    else:
        usage_text = "Unknown command\\. Please go back and select a valid command\\.\\" # Escaped . and !

    back_button = [[InlineKeyboardButton("⬅️ Back to Commands", callback_data="show_main_commands")]]
    await query.edit_message_text(usage_text, reply_markup=InlineKeyboardMarkup(back_button), parse_mode=ParseMode.MARKDOWN_V2)

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

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

    if not bin_details: # Added check for bin_details
        return await update.message.reply_text(f"❌ Could not retrieve details for BIN: `{escape_markdown_v2(bin_input)}`\\.\\nPlease check the BIN or try again later\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped . and !


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
        f"✦ BIN\\-LOOKUP\n" # Escaped -
        f"✦ BIN : `{escape_markdown_v2(bin_input)}`\n"
        f"✦ Country : {escaped_country_name} {escaped_country_emoji}\n"
        f"✦ Type : {escaped_card_type}\n"
        f"✦ Bank : {escaped_bank}"
    )

    user_info_block_content = (
        f"Requested by : {escaped_user_full_name}\n"
        f"Bot by : 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎"
    )

    result = (
        f"> Generated 10 Cards 💳\n" # Escaped !
        f"\n"
        f"{cards_list}\n"
        f"\n"
        f"> {bin_info_block_content.replace('\n', '\n> ')}\n" # Replace to add "> " to each line
        f"> \n"
        f"> {user_info_block_content.replace('\n', '\n> ')}" # Replace to add "> " to each line
    )

    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

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
        f"╔═══════ BIN INFO ═══════╗\n" # No change, decorative characters are fine
        f"✦ BIN    : `{escape_markdown_v2(bin_input)}`\n"
        f"✦ Status : {status_display}\n"
        f"✦ Brand  : {escaped_scheme}\n"
        f"✦ Type   : {escaped_card_type}\n"
        f"✦ Level  : {level_emoji} {escaped_level}\n"
        f"✦ Bank   : {escaped_bank}\n"
        f"✦ Country: {escaped_country_name} {escaped_country_emoji}\n"
        f"╚════════════════════════╝" # No change, decorative characters are fine
    )

    # User info in a separate quote box
    user_info_quote_box = (
        f"> Requested by \\-: {escaped_user_full_name}\n" # Escaped -
        f"> Bot by \\-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎" # Escaped -
    )

    result = f"{bin_info_box}\n\n{user_info_quote_box}"
    
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

async def _execute_kill_process(update: Update, context: ContextTypes.DEFAULT_TYPE, full_card_str: str, initial_message):
    """
    Handles the long-running kill animation and final message.
    This function is designed to be run as a separate asyncio task.
    """
    time_taken = 0 # Initialize time_taken

    # Simulate delay: 30 seconds to 1.3 minutes (78 seconds)
    kill_time = random.uniform(30, 78) 
    start_time = time.time()

    # Animation frames for "Killing..." using ⚡ emoji
    animation_states = [
        "Kɪʟʟɪɴɢ ⚡",
        "Kɪʟʟɪɴɢ ⚡⚡",
        "Kɪʟʟɪɴɢ ⚡⚡⚡",
        "Kɪʟʟɪɴɢ ⚡⚡",
        "Kɪʟʟɪɴɢ ⚡"
    ]
    frame_interval = 4.0 # seconds per frame update (Increased to reduce API calls)

    elapsed_animation_time = 0
    frame_index = 0

    while elapsed_animation_time < kill_time:
        current_frame = animation_states[frame_index % len(animation_states)]
        # Edit the initial message to show the animation
        try:
            await initial_message.edit_text(
                f"Card No\\.: `{escape_markdown_v2(full_card_str)}`\n" # Escaped .
                f"🔪 {current_frame}"
            , parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            # This specific error means content is identical, so we just log and continue.
            # Or if it's a flood control error, we still continue after the sleep.
            if "Message is not modified" in str(e) or "Flood control exceeded" in str(e):
                logger.debug(f"Message not modified or flood control hit during animation: {e}")
            else:
                # Other BadRequest errors might be critical, so log but DO NOT BREAK.
                # We need the sleep to continue to ensure the full kill_time is met.
                logger.warning(f"Failed to edit message during animation (BadRequest, non-modified): {e}")
        except Exception as e:
            logger.warning(f"Failed to edit message during animation (General Error): {e}")
            # For any other unexpected error, log but DO NOT BREAK.
            # We need the sleep to continue to ensure the full kill_time is met.
        
        # Calculate remaining time for sleep to ensure total kill_time is met
        sleep_duration = min(frame_interval, kill_time - elapsed_animation_time)
        if sleep_duration <= 0:
            break # No more time left to sleep
        await asyncio.sleep(sleep_duration)
        
        elapsed_animation_time = time.time() - start_time
        frame_index += 1

    # Calculate actual time taken after the loop finishes
    time_taken = round(time.time() - start_time)

    # Get BIN details for stylish info
    cc_part = full_card_str.split('|')[0]
    bin_number = cc_part[:6]
    bin_details = await get_bin_details(bin_number)

    # Escape dynamic parts for MarkdownV2, careful with emojis
    bank_name = escape_markdown_v2(bin_details.get("bank", "Unknown")) # Use .get with default
    level = escape_markdown_v2(bin_details.get("level", "N/A")) # Use .get with default
    level_emoji = get_level_emoji(bin_details.get("level", "N/A")) # Emoji doesn't need escaping
    brand = escape_markdown_v2(bin_details.get("scheme", "Unknown")) # Use .get with default

    # Determine header based on card scheme
    header_title = "⚡Cᴀʀᴅ Kɪʟʟᴇᴅ Sᴜᴄᴄᴇssꜰᴜʟʟʏ" # Escaped ! later
    if bin_details["scheme"].lower() == 'mastercard':
        # Generate random percentage > 67%
        percentage = random.randint(68, 100) 
        header_title = f"⚡Cᴀʀᴅ Kɪʟʟᴇᴅ Sᴜᴄᴄᴇssꜰᴜʟʟʏ \\- {percentage}\\%" # Escaping - and % for MarkdownV2

    # Construct the final message using a single f-string for easy modification
    # Manual padding for visual alignment of colons
    final_message_text_formatted = (
        f"╭───[ {header_title} ]───╮\n"
        f"\n"
        f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str)}`\n" # Escaped .
        f"• 𝗕𝗿𝗮𝗻𝗱        : `{brand}`\n"
        f"• 𝗜𝘀𝘀𝘂𝗲𝗿       : `{bank_name}`\n"
        f"• 𝗟𝗲𝘃𝗲𝗹        : `{level_emoji} {level}`\n"
        f"• 𝗞𝗶𝗹𝗹𝗲𝗿       :  𝓒𝓪𝓻𝓭𝗩𝗮𝘂𝗹𝘁𝑿\n" # No change, special characters outside MDV2 context
        f"• 𝗕𝒐𝒕 𝒃𝒚      :  𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎\n" # No change, special characters outside MDV2 context
        f"• 𝗧𝗶𝗺𝗲 𝗧𝗮𝗸𝗲𝗻  : {escape_markdown_v2(f'{time_taken:.0f} seconds')}\n"
        f"\n"
        f"╰────────────────────╯" # No change, decorative characters are fine
    )

    await initial_message.edit_text(final_message_text_formatted, parse_mode=ParseMode.MARKDOWN_V2)


async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    card_details_input = None

    # 1. Try to get card details from command arguments
    if context.args:
        card_details_input = " ".join(context.args)
        logger.debug(f"Kill command: Card details from args: '{card_details_input}'")
    # 2. If no arguments, try to get from message text for .kill command
    elif update.message.text and (update.message.text.lower().startswith(".kill ") or update.message.text.lower().startswith("/kill ")):
        # Extract content after the command word
        parts = update.message.text.split(maxsplit=1)
        if len(parts) > 1:
            card_details_input = parts[1].strip()
        logger.debug(f"Kill command: Card details from message text: '{card_details_input}'")
    # 3. Fallback to replied message if no direct arguments
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        card_details_input = update.message.reply_to_message.text
        logger.debug(f"Kill command: Card details from replied message: '{card_details_input}'")

    if not card_details_input:
        logger.info("Kill command: No card details found in arguments or replied message.")
        return await update.message.reply_text(
            "❌ Please provide card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) as an argument or reply to a message containing them\\. " # Escaped .
            "Usage: `/kill CC\\|MM\\|YY\\|CVV` or `\\.kill CC\\|MM\\|YYYY\\|CVV`\\.", # Escaped .
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Regex to find card details in `CC|MM|YY|CVV` or `CC|MM|YYYY|CVV` format.
    # Added \s* around | to tolerate spaces, and \s*$ to tolerate trailing spaces.
    card_match = re.search(r"(\d{13,19})\s*\|\s*(\d{2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3,4})\s*$", card_details_input)
    logger.debug(f"Kill command: Regex match result: {card_match}")

    if not card_match:
        logger.info(f"Kill command: Regex failed to match for input: '{card_details_input}'")
        return await update.message.reply_text(
            "❌ Could not find valid card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) in the provided input\\. " # Escaped .
            "Make sure it's in the format `CC|MM|YY|CVV` or `CC|MM|YYYY|CVV`\\.", # Escaped .
            parse_mode=ParseMode.MARKDOWN_V2
        )

    cc = card_match.group(1)
    mm = card_match.group(2)
    yy = card_match.group(3) # Keep the original year format (YY or YYYY) for display
    cvv = card_match.group(4)
    
    full_card_str = f"{cc}|{mm}|{yy}|{cvv}"
    
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

    # Send the initial message and store it to edit later
    initial_message = await update.message.reply_text(
        f"Card No\\.: `{escape_markdown_v2(full_card_str)}`\n" # Escaped .
        f"🔪Kɪʟʟɪɴɢ ⚡" # Initial message without emojis for animation
    , parse_mode=ParseMode.MARKDOWN_V2)

    # Create a separate task for the long-running kill process
    asyncio.create_task(_execute_kill_process(update, context, full_card_str, initial_message))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = len(user_last_command)
    
    ram_mb = psutil.virtual_memory().used / (1024 * 1024)
    ram_usage = f"{ram_mb:.0f} MB"
    
    cpu_usage_percent = psutil.cpu_percent()
    escaped_cpu_usage_text = escape_markdown_v2(str(cpu_usage_percent)) + "\\%" # Ensure % is escaped
    
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
        f"> 🤖 Bot by \\- 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎" # Escaped -
    )
    
    await update.message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN_V2)


async def stripe_auth_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if not STRIPE_SECRET_KEY:
        return await update.message.reply_text(
            "⚠️ Stripe API key is not configured\\. Please inform the bot owner\\.", # Escaped .
            parse_mode=ParseMode.MARKDOWN_V2
        )

    card_details_input = None
    if context.args:
        card_details_input = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        card_details_input = update.message.reply_to_message.text

    if not card_details_input:
        return await update.message.reply_text(
            "❌ Please provide card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) as an argument or reply to a message containing them\\. " # Escaped .
            "Usage: `/chk CC\\|MM\\|YY\\|CVV` or `\\.chk CC\\|MM\\|YYYY\\|CVV`\\.", # Escaped .
            parse_mode=ParseMode.MARKDOWN_V2
        )

    card_match = re.search(r"(\d{13,19})\s*\|\s*(\d{2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3,4})\s*$", card_details_input)

    if not card_match:
        return await update.message.reply_text(
            "❌ Could not find valid card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) in the provided input\\. " # Escaped .
            "Make sure it's in the format `CC\\|MM\\|YY\\|CVV` or `CC\\|MM\\|YYYY\\|CVV`\\.", # Escaped .
            parse_mode=ParseMode.MARKDOWN_V2
        )

    cc = card_match.group(1)
    mm = card_match.group(2)
    yy = card_match.group(3)
    cvv = card_match.group(4)

    # Convert YY to YYYY if necessary
    if len(yy) == 2:
        current_century = (datetime.now().year // 100) * 100
        full_year = current_century + int(yy)
        # Adjust for year 2000 problem if YY is in the past, assume it means 20XX
        if full_year < datetime.now().year - 10: 
            full_year += 100
        # Adjust if YY means 19XX, assume 20XX
        elif full_year > datetime.now().year + 20: 
            full_year -= 100
        yy_full = str(full_year)
    else:
        yy_full = yy

    # Initial message while checking
    checking_message = await update.message.reply_text(escape_markdown_v2("⏳ Attempting live card authorization with Stripe..."), parse_mode=ParseMode.MARKDOWN_V2) # Escaped ...

    result = await check_card_with_stripe_live(cc, mm, yy_full, cvv)

    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)
    full_card_str_display = f"{cc}|{mm}|{yy}|{cvv}" # Keep original YY for display

    response_text = ""
    if result["status"] == "success":
        response_text = (
            f"✅ *Card Authenticated Successfully \\(Live Check\\)* ✅\n" # Escaped !
            f"━━━━━━━━━━━━━━\n"
            f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str_display)}`\n" # Escaped .
            f"• 𝗦𝘁𝗮𝘁𝘂𝘀     : LIVE ✅\n"
            f"━━━━━━━━━━━━━━\n"
            f"> 𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆 \\-: {escaped_user_full_name}\n" # Escaped -
            f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝒎" # Escaped -
        )
    else:
        error_msg = escape_markdown_v2(result.get("message", "An unknown error occurred.")) # Ensure message is always escaped
        response_text = (
            f"❌ *Stripe Live Authentication Failed\\!* ❌\n" # Escaped !
            f"━━━━━━━━━━━━━━\n"
            f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str_display)}`\n" # Escaped .
            f"• 𝗦𝘁𝗮𝘁𝘂𝘀     : DEAD ❌\n"
            f"• 𝗥𝗲𝗮𝘀𝗼𝗻     : {error_msg}\n"
            f"━━━━━━━━━━━━━━\n"
            f"> 𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆 \\-: {escaped_user_full_name}\n" # Escaped -
            f"> 𝗕𝒐𝒕 𝒃𝒚 \\-: 𝑩𝒍𝗼𝗰𝗸𝑺𝒕𝒐𝒓𝗺" # Escaped -
        )
    
    try:
        await checking_message.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info("Stripe check message not modified.")
        else:
            logger.error(f"Error editing stripe check message: {e}")
            await update.effective_message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Unexpected error sending final stripe check message: {e}")
        await update.effective_message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)


async def authorize_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this command\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped .
    if not context.args:
        return await update.message.reply_text("Usage: `/au [chat_id]`\\. Please provide a chat ID\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped .
    
    try:
        chat_id_to_authorize = int(context.args[0])
        # In a real bot, you would store this chat_id in a persistent storage (database/file)
        # and then check against it for future command access.
        # For demonstration, we'll just acknowledge the authorization.
        await update.message.reply_text(f"✅ Group `{chat_id_to_authorize}` is now authorized to use the bot\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped .
    except ValueError:
        await update.message.reply_text("❌ Invalid chat ID\\. Please provide a numeric chat ID\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped .

# === MAIN APPLICATION SETUP ===
def main():
    if TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set. Please set it before running the bot.")
        exit(1)
    if OWNER_ID is None:
        logger.warning("OWNER_ID environment variable is not set. Please set it before running the bot. Owner-only commands will not function.")
    
    application = ApplicationBuilder().token(TOKEN).build()

    # Store start time for uptime calculation
    application.bot_data['start_time'] = datetime.now()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("bin", bin_lookup))
    application.add_handler(CommandHandler("status", status))
    # Explicitly add filters for private and group chats for kill command
    application.add_handler(CommandHandler("kill", kill, filters=filters.ChatType.PRIVATE | filters.ChatType.GROUPS))
    application.add_handler(CommandHandler("chk", stripe_auth_check, filters=filters.ChatType.PRIVATE | filters.ChatType.GROUPS)) # Added Stripe command

    application.add_handler(CommandHandler("au", authorize_group))

    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.gen\b.*"), gen))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.bin\b.*"), bin_lookup))
    # Explicitly add filters for private and group chats for .kill message handler
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.kill\b.*") & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS), kill))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.chk\b.*") & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS), stripe_auth_check)) # Added Stripe message handler

    application.add_handler(CallbackQueryHandler(show_main_commands, pattern="^show_main_commands$"))
    application.add_handler(CallbackQueryHandler(show_command_details, pattern="^cmd_"))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_start$"))

    # Add the error handler
    application.add_error_handler(error_handler)

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
