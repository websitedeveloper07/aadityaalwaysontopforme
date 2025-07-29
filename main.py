import os
import time
import logging
import asyncio
import aiohttp
import re
import psutil
import random
import uuid # Added for idempotency key generation
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest # Import BadRequest for specific error handling

import stripe # Added for Stripe API interaction

# === CONFIGURATION ===
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

BINTABLE_API_KEY = "d1359fe2b305160dd9b9d895a07b4438794ea1f6"
BINTABLE_URL = "https://api.bintable.com/v1"

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY") # Added for Stripe API key

user_last_command = {}

# Initialize Stripe API client
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    # Log a warning if the key is not set, the bot will still run but Stripe checker won't work
    print("STRIPE_SECRET_KEY environment variable is not set. Stripe checker will not function.")
    # logger.warning("STRIPE_SECRET_KEY environment variable is not set. Stripe checker will not function.")

# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === ERROR HANDLER ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Try to send a message back to the user
    if update.effective_message:
        await update.effective_message.reply_text(
            "An error occurred while processing your request\\. Please try again later\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

# === HELPER FUNCTIONS ===
def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2 formatting."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)

def get_short_country_name(full_name: str) -> str:
    """Converts a full country name to a shorter, more common one."""
    country_map = {
        "United States of America": "United States",
        "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
        "Russian Federation": "Russia",
        "Korea, Republic of": "South Korea",
        "Iran, Islamic Republic of": "Iran",
        "Venezuela, Bolivarian Republic of": "Venezuela",
        "Viet Nam": "Vietnam",
        "Bolivia, Plurinational State of": "Bolivia",
        "Congo, The Democratic Republic of the": "DR Congo",
        "Tanzania, United Republic of": "Tanzania",
        "Syrian Arab Republic": "Syria"
    }
    return country_map.get(full_name, full_name)

def luhn_checksum(card_number: str) -> bool:
    """Implements the Luhn algorithm to validate a credit card number."""
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

def get_level_emoji(level: str) -> str:
    """Returns an emoji based on card level."""
    level = level.lower()
    if "gold" in level:
        return "✨"
    elif "platinum" in level:
        return "💎"
    elif "infinite" in level or "world elite" in level:
        return "👑"
    elif "classic" in level:
        return "💳"
    else:
        return "📄"

def get_vbv_status_display(status: str) -> str:
    """Provides a display string for VBV status."""
    # VBV checking logic was removed, always show N/A
    return "❓ N/A"

async def fetch_bin_info_bintable(bin_number: str) -> dict | None:
    """Fetches BIN information from Bintable API."""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {BINTABLE_API_KEY}"}
            async with session.get(f"{BINTABLE_URL}/{bin_number}", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and data.get("status") == "success" and data.get("data"):
                        b = data["data"]
                        return {
                            "scheme": b.get("scheme"),
                            "type": b.get("type"),
                            "level": b.get("level"),
                            "bank_name": b.get("bank", {}).get("name"),
                            "country_name": b.get("country", {}).get("name"),
                            "country_iso": b.get("country", {}).get("iso"),
                            "currency": b.get("country", {}).get("currency"),
                            "website": b.get("bank", {}).get("website"),
                            "phone": b.get("bank", {}).get("phone"),
                            "vbv": "N/A" # Bintable might have it, but for consistency with other sources, keeping N/A
                        }
                elif resp.status == 404:
                    logger.info(f"BIN {bin_number} not found on Bintable.")
                else:
                    logger.warning(f"Bintable API error for BIN {bin_number}: {resp.status} - {await resp.text()}")
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching Bintable info: {e}")
    except Exception as e:
        logger.error(f"Error processing Bintable response: {e}")
    return None

async def fetch_bin_info_binlist(bin_number: str) -> dict | None:
    """Fetches BIN information from Binlist API (fallback)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.binlist.net/v1/{bin_number}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "scheme": data.get("scheme"),
                        "type": data.get("type"),
                        "level": data.get("brand"), # Binlist uses 'brand' for level
                        "bank_name": data.get("bank", {}).get("name"),
                        "country_name": data.get("country", {}).get("name"),
                        "country_iso": data.get("country", {}).get("iso"),
                        "currency": data.get("country", {}).get("currency"),
                        "website": data.get("bank", {}).get("url"),
                        "phone": data.get("bank", {}).get("phone"),
                        "vbv": "N/A"
                    }
                elif resp.status == 404:
                    logger.info(f"BIN {bin_number} not found on Binlist.")
                else:
                    logger.warning(f"Binlist API error for BIN {bin_number}: {resp.status} - {await resp.text()}")
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching Binlist info: {e}")
    except Exception as e:
        logger.error(f"Error processing Binlist response: {e}")
    return None

async def fetch_bin_info_bincheckio(bin_number: str) -> dict | None:
    """Fetches BIN information from Bincheck.io API (fallback)."""
    try:
        async with aiohttp.ClientSession() as session:
            # Note: Bincheck.io might require an API key or have rate limits.
            # Using the free endpoint for demonstration.
            async with session.get(f"https://api.bincheck.io/v2/{bin_number}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and data.get("code") == 200:
                        return {
                            "scheme": data.get("scheme"),
                            "type": data.get("type"),
                            "level": data.get("level"),
                            "bank_name": data.get("bank_name"),
                            "country_name": data.get("country_name"),
                            "country_iso": data.get("country_iso"),
                            "currency": data.get("currency"),
                            "website": data.get("bank_url"),
                            "phone": data.get("bank_phone"),
                            "vbv": "N/A"
                        }
                elif resp.status == 404:
                    logger.info(f"BIN {bin_number} not found on Bincheck.io.")
                else:
                    logger.warning(f"Bincheck.io API error for BIN {bin_number}: {resp.status} - {await resp.text()}")
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching Bincheck.io info: {e}")
    except Exception as e:
        logger.error(f"Error processing Bincheck.io response: {e}")
    return None

async def get_bin_details(bin_number: str) -> dict | None:
    """Attempts to get BIN details from multiple sources."""
    if not bin_number or not bin_number.isdigit() or len(bin_number) < 6:
        return None

    # Try Bintable first
    details = await fetch_bin_info_bintable(bin_number)
    if details:
        return details

    # Fallback to Binlist
    details = await fetch_bin_info_binlist(bin_number)
    if details:
        return details

    # Fallback to Bincheck.io
    details = await fetch_bin_info_bincheckio(bin_number)
    if details:
        return details

    return None

async def enforce_cooldown(user_id: int) -> bool:
    """Enforces a 5-second cooldown per user."""
    current_time = time.time()
    if user_id in user_last_command:
        time_since_last_command = current_time - user_last_command[user_id]
        if time_since_last_command < 5:
            return False
    user_last_command[user_id] = current_time
    return True

async def check_card_with_stripe_live(card_number: str, exp_month: str, exp_year: str, cvc: str) -> dict:
    """
    Attempts a small authorization ($0.50 USD) and immediately refunds it
    to check if a card is live using Stripe.
    """
    if not stripe.api_key:
        return {"status": "error", "message": "Stripe API key not configured. Contact bot owner."}

    # Use a unique ID for idempotency to prevent duplicate charges
    idempotency_key = f"auth_check_{uuid.uuid4()}"

    try:
        # Step 1: Create a PaymentMethod
        # This is primarily for getting the PaymentMethod ID.
        # It performs basic validation but doesn't interact with the bank yet.
        payment_method = await asyncio.to_thread(
            stripe.PaymentMethod.create,
            type="card",
            card={
                "number": card_number,
                "exp_month": exp_month,
                "exp_year": exp_year,
                "cvc": cvc,
            },
            idempotency_key=f"{idempotency_key}_pm" # Separate idempotency for PM creation
        )

        # Step 2: Create a PaymentIntent for a small amount
        # This will attempt to authorize the amount with the bank.
        payment_intent = await asyncio.to_thread(
            stripe.PaymentIntent.create,
            amount=50,  # $0.50 USD (Stripe amounts are in cents)
            currency="usd",
            payment_method=payment_method.id,
            confirm=True, # Automatically confirms the intent
            off_session=True, # Indicates this is happening without customer presence
            metadata={"check_type": "card_auth_validation"},
            idempotency_key=f"{idempotency_key}_pi" # Idempotency for PI creation
        )

        # Step 3: Check PaymentIntent status
        if payment_intent.status == 'succeeded':
            # Card is live and authorized. Now refund immediately.
            try:
                refund = await asyncio.to_thread(
                    stripe.Refund.create,
                    payment_intent=payment_intent.id,
                    idempotency_key=f"{idempotency_key}_refund" # Idempotency for refund
                )
                logger.info(f"Successfully authorized and refunded card: {card_number[:6]}...{card_number[-4:]}")
                return {"status": "success", "message": "Card is LIVE and refunded.", "stripe_status": payment_intent.status, "refund_status": refund.status}
            except stripe.error.StripeError as e:
                logger.error(f"Stripe Refund Error for {card_number[:6]}...{card_number[-4:]}: {e.user_message} (Code: {e.code})")
                # Even if refund fails, the card was likely live.
                return {"status": "success", "message": f"Card is LIVE but refund failed: {escape_markdown_v2(e.user_message)}. Manual refund may be needed.", "stripe_status": payment_intent.status}
        else:
            # PaymentIntent failed or requires further action (e.g., 3D Secure)
            # For a simple checker, anything not 'succeeded' is usually considered dead.
            logger.warning(f"Stripe PaymentIntent status for {card_number[:6]}...{card_number[-4:]}: {payment_intent.status}")
            return {"status": "failed", "message": f"Card is DEAD. Status: {escape_markdown_v2(payment_intent.status)}", "stripe_status": payment_intent.status}

    except stripe.error.CardError as e:
        # A decline or card-related error occurred
        logger.warning(f"Stripe Card Error for {card_number[:6]}...{card_number[-4:]}: {e.user_message} (Code: {e.code})")
        return {"status": "failed", "message": f"Card is DEAD. Reason: {escape_markdown_v2(e.user_message)}", "code": e.code, "stripe_status": e.code}
    except stripe.error.RateLimitError as e:
        logger.error(f"Stripe Rate Limit Error: {e.user_message}")
        return {"status": "error", "message": "Stripe API rate limit exceeded\\. Please try again later\\."}
    except stripe.error.AuthenticationError as e:
        logger.error(f"Stripe Authentication Error: {e.user_message}. Check your API key.")
        return {"status": "error", "message": "Stripe API authentication failed\\. Contact bot owner\\."}
    except stripe.error.StripeError as e:
        # Other Stripe API errors (e.g., network, invalid request)
        logger.error(f"General Stripe API Error for {card_number[:6]}...{card_number[-4:]}: {e.user_message} (Type: {e.error.type})")
        return {"status": "error", "message": f"An error occurred with Stripe: {escape_markdown_v2(e.user_message)}"}
    except Exception as e:
        logger.error(f"Unexpected error during live Stripe check: {e}", exc_info=True)
        return {"status": "error", "message": "An unexpected error occurred during the live check\\."}

# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 Hello, {escape_markdown_v2(user.first_name)}!\n\n"
        "I'm your all\\-in\\-one Card Utility Bot\\.\n"
        "I can generate cards, provide BIN info, and check card status\\.\n\n"
        "Press the 'Commands' button to see what I can do\\."
    )
    keyboard = [
        [InlineKeyboardButton("📚 Commands", callback_data="show_main_commands")],
        [InlineKeyboardButton("📢 Group", url="https://t.me/BlockStormOP")] # Example group link
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

async def show_main_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    commands_text = "📜 *Bot Commands:*\nSelect a command to learn more:"
    buttons = [
        [InlineKeyboardButton("💳 Generate Cards (/gen)", callback_data="cmd_gen")],
        [InlineKeyboardButton("🔍 BIN Info (/bin)", callback_data="cmd_bin")],
        [InlineKeyboardButton("📊 Bot Status (/status)", callback_data="cmd_status")],
        [InlineKeyboardButton("💀 Kill Card (/kill)", callback_data="cmd_kill")],
        [InlineKeyboardButton("✅ Stripe Auth (/chk)", callback_data="cmd_chk")], # Added for Stripe Auth Checker
        [InlineKeyboardButton("⬅️ Back to Start", callback_data="back_to_start")]
    ]

    if query:
        await query.edit_message_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text(commands_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN_V2)

async def show_command_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    command_name = query.data.replace("cmd_", "")
    
    usage_text = ""
    if command_name == "gen":
        usage_text = (
            "*💳 Card Generator*\n" +
            "Usage: `/gen <BIN>` or `\\.gen <BIN>`\n" +
            "Example: `/gen 400000`\n" +
            "Generates 10 credit card numbers based on the provided 6\\-digit BIN\\. " +
            "Includes expiry date \\(MM\\|YY\\) and CVV\\.\n"
        ).strip()
    elif command_name == "bin":
        usage_text = (
            "*🔍 BIN Lookup*\n" +
            "Usage: `/bin <BIN>` or `\\.bin <BIN>`\n" +
            "Example: `/bin 400000`\n" +
            "Provides detailed information about a given Bank Identification Number \\(BIN\\), " +
            "including card scheme, type, level, bank name, and country\\.\n"
        ).strip()
    elif command_name == "status":
        usage_text = (
            "*📊 Bot Status*\n" +
            "Usage: `/status`\n" +
            "Displays the bot's current operational statistics, " +
            "including uptime, RAM usage, and CPU usage\\.\n"
        ).strip()
    elif command_name == "kill":
        usage_text = (
            "*💀 Card Killer \\(Simulation\\)*\n" +
            "Usage: `/kill CC\\|MM\\|YY\\|CVV` or `\\.kill CC\\|MM\\|YY\\|CVV`\n" +
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
        usage_text = "Unknown command\\. Please go back and select a valid command\\.\\"

    back_button = [[InlineKeyboardButton("⬅️ Back to Commands", callback_data="show_main_commands")]]
    await query.edit_message_text(usage_text, reply_markup=InlineKeyboardMarkup(back_button), parse_mode=ParseMode.MARKDOWN_V2)

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if not context.args or len(context.args[0]) < 6:
        return await update.message.reply_text(
            "❌ Please provide a 6\\-digit BIN\\. Usage: `/gen <BIN>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    bin_number = context.args[0][:6]
    if not bin_number.isdigit():
        return await update.message.reply_text(
            "❌ Invalid BIN\\. Please provide a numeric 6\\-digit BIN\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    status_message = await update.message.reply_text(
        f"⚙️ Generating 10 cards for BIN: `{escape_markdown_v2(bin_number)}`\\.\n_This may take a moment\\._",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    bin_details = await get_bin_details(bin_number)

    if not bin_details:
        await status_message.edit_text(
            f"❌ Could not retrieve details for BIN: `{escape_markdown_v2(bin_number)}`\\.\n"
            "Please check the BIN or try again later\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    generated_cards = []
    card_count = 0
    max_attempts_per_card = 100 # To prevent infinite loops for rare BINs
    
    # Determine card length based on scheme
    card_scheme = bin_details.get("scheme", "").lower()
    card_length = 16 # Default for most cards
    if card_scheme == "american express":
        card_length = 15
    elif card_scheme == "diners club":
        card_length = 14

    while card_count < 10:
        attempts = 0
        while attempts < max_attempts_per_card:
            temp_card_number = bin_number + ''.join(random.choices('0123456789', k=card_length - len(bin_number)))
            if luhn_checksum(temp_card_number):
                
                # Generate MM/YY
                current_year = datetime.now().year
                current_month = datetime.now().month
                
                # Random year between current year and +5 years
                exp_year_full = random.randint(current_year, current_year + 5)
                
                # If current year, ensure month is in the future
                if exp_year_full == current_year:
                    exp_month = random.randint(current_month, 12)
                else:
                    exp_month = random.randint(1, 12)
                
                exp_month_str = str(exp_month).zfill(2)
                exp_year_short = str(exp_year_full)[-2:] # Get last two digits

                # Generate CVV (4 for Amex, 3 for others)
                cvv_length = 4 if card_scheme == "american express" else 3
                cvv = ''.join(random.choices('0123456789', k=cvv_length))
                
                generated_cards.append(f"`{temp_card_number}|{exp_month_str}|{exp_year_short}|{cvv}`")
                card_count += 1
                break
            attempts += 1
        if attempts == max_attempts_per_card:
            logger.warning(f"Failed to generate Luhn-valid card for BIN {bin_number} after {max_attempts_per_card} attempts.")
            # Break if too many attempts, to avoid infinite loop
            break 

    if not generated_cards:
        await status_message.edit_text(
            f"⚠️ Could not generate any valid cards for BIN: `{escape_markdown_v2(bin_number)}`\\.\n"
            "This might happen for very specific or invalid BINs\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    card_list_text = "\n".join(generated_cards)

    scheme = escape_markdown_v2(bin_details.get("scheme", "N/A"))
    type_ = escape_markdown_v2(bin_details.get("type", "N/A"))
    level = escape_markdown_v2(bin_details.get("level", "N/A"))
    level_emoji = get_level_emoji(bin_details.get("level", "N/A"))
    bank_name = escape_markdown_v2(bin_details.get("bank_name", "N/A"))
    country_name = escape_markdown_v2(get_short_country_name(bin_details.get("country_name", "N/A")))
    country_iso = escape_markdown_v2(bin_details.get("country_iso", "N/A"))
    website = escape_markdown_v2(bin_details.get("website", "N/A"))
    phone = escape_markdown_v2(bin_details.get("phone", "N/A"))

    response_text = (
        f"✨ *Cards Generated Successfully* ✨\n"
        f"━━━━━━━━━━━━━━\n"
        f"• 𝗕𝗜𝗡             : `{escape_markdown_v2(bin_number)}`\n"
        f"• 𝗖𝗮𝗿𝗱 𝗦𝗰𝗵𝗲𝗺𝗲 : `{scheme}`\n"
        f"• 𝗖𝗮𝗿𝗱 𝗧𝘆𝗽𝗲    : `{type_}`\n"
        f"• 𝗖𝗮𝗿𝗱 𝗟𝗲𝘃𝗲𝗹  : `{level} {level_emoji}`\n"
        f"• 𝗕𝗮𝗻𝗸 𝗡𝗮𝗺𝗲   : `{bank_name}`\n"
        f"• 𝗖𝗼𝘂𝗻𝘁𝗿𝘆       : `{country_name} ({country_iso})`\n"
        f"• 𝗩𝗕𝗩 𝗦𝘁𝗮𝘁𝘂𝘀  : `{get_vbv_status_display('N/A')}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌐 𝗪𝗲𝗯𝘀𝗶𝘁𝗲       : `{website}`\n"
        f"📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁     : `{phone}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"𝗖𝗮𝗿𝗱𝘀 \\(CC\\|MM\\|YY\\|CVV\\):\n"
        f"{card_list_text}\n"
        f"━━━━━━━━━━━━━━\n"
        f"> 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 𝗯𝘆 \\-: {escape_markdown_v2(update.effective_user.full_name)}\n"
        f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎"
    )

    await status_message.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)


async def bin_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if not context.args or len(context.args[0]) < 6:
        return await update.message.reply_text(
            "❌ Please provide a 6\\-digit BIN\\. Usage: `/bin <BIN>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    bin_number = context.args[0][:6]
    if not bin_number.isdigit():
        return await update.message.reply_text(
            "❌ Invalid BIN\\. Please provide a numeric 6\\-digit BIN\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    status_message = await update.message.reply_text(
        f"🔍 Looking up BIN: `{escape_markdown_v2(bin_number)}`\\.\n_This may take a moment\\._",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    bin_details = await get_bin_details(bin_number)

    if not bin_details:
        await status_message.edit_text(
            f"❌ Could not retrieve details for BIN: `{escape_markdown_v2(bin_number)}`\\.\n"
            "Please check the BIN or try again later\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    scheme = escape_markdown_v2(bin_details.get("scheme", "N/A"))
    type_ = escape_markdown_v2(bin_details.get("type", "N/A"))
    level = escape_markdown_v2(bin_details.get("level", "N/A"))
    level_emoji = get_level_emoji(bin_details.get("level", "N/A"))
    bank_name = escape_markdown_v2(bin_details.get("bank_name", "N/A"))
    country_name = escape_markdown_v2(get_short_country_name(bin_details.get("country_name", "N/A")))
    country_iso = escape_markdown_v2(bin_details.get("country_iso", "N/A"))
    website = escape_markdown_v2(bin_details.get("website", "N/A"))
    phone = escape_markdown_v2(bin_details.get("phone", "N/A"))
    
    response_text = (
        f"💳 *BIN Lookup Results* 💳\n"
        f"━━━━━━━━━━━━━━\n"
        f"• 𝗕𝗜𝗡             : `{escape_markdown_v2(bin_number)}`\n"
        f"• 𝗖𝗮𝗿𝗱 𝗦𝗰𝗵𝗲𝗺𝗲 : `{scheme}`\n"
        f"• 𝗖𝗮𝗿𝗱 𝗧𝘆𝗽𝗲    : `{type_}`\n"
        f"• 𝗖𝗮𝗿𝗱 𝗟𝗲𝘃𝗲𝗹  : `{level} {level_emoji}`\n"
        f"• 𝗕𝗮𝗻𝗸 𝗡𝗮𝗺𝗲   : `{bank_name}`\n"
        f"• 𝗖𝗼𝘂𝗻𝘁𝗿𝘆       : `{country_name} ({country_iso})`\n"
        f"• 𝗩𝗕𝗩 𝗦𝘁𝗮𝘁𝘂𝘀  : `{get_vbv_status_display('N/A')}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌐 𝗪𝗲𝗯𝘀𝗶𝘁𝗲       : `{website}`\n"
        f"📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁     : `{phone}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"> 𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆 \\-: {escape_markdown_v2(update.effective_user.full_name)}\n"
        f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎"
    )
    await status_message.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)


async def _execute_kill_process(update: Update, context: ContextTypes.DEFAULT_TYPE, full_card_str: str, initial_message: Update.effective_message):
    """Helper function to simulate card killing with animation."""
    animation_frames = ["⚡", "✨", "🔥"]
    killing_text = "Killing ⚡"
    
    start_time = time.time()
    last_update_time = start_time
    
    # Simulate a longer process with updates
    total_duration = random.randint(30, 78) # Simulate 30 to 78 seconds process
    
    for i in range(total_duration):
        frame = animation_frames[i % len(animation_frames)]
        current_killing_text = f"Killing {frame}"
        
        # Only update every 2 seconds to avoid flooding Telegram API
        if time.time() - last_update_time > 2:
            try:
                await initial_message.edit_text(
                    f"💀 *Card Killer \\(Simulating\\)* 💀\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str)}`\n"
                    f"• 𝗦𝘁𝗮𝘁𝘂𝘀     : {current_killing_text}\n"
                    f"• 𝗧𝗶𝗺𝗲 𝗘𝗹𝗮𝗽𝘀𝗲𝗱: `{escape_markdown_v2(str(timedelta(seconds=int(time.time() - start_time))))}`\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"> 𝗣𝗹𝗲𝗮𝘀𝗲 𝘄𝗮𝗶𝘁\\.\n"
                    f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                last_update_time = time.time()
            except BadRequest as e:
                # Catch "Message is not modified" errors, which means no update is needed
                if "message is not modified" not in str(e).lower():
                    logger.error(f"Error editing message during kill animation: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during kill animation: {e}")
            
        await asyncio.sleep(1) # Wait 1 second per "step"

    end_time = time.time()
    time_taken = end_time - start_time

    # Split card for BIN lookup if possible
    bin_part = full_card_str.split('|')[0][:6] if full_card_str.split('|')[0].isdigit() else None
    
    card_info_text = ""
    if bin_part:
        bin_details = await get_bin_details(bin_part)
        if bin_details:
            card_info_text = (
                f"• 𝗖𝗮𝗿𝗱 𝗕𝗿𝗮𝗻𝗱: `{escape_markdown_v2(bin_details.get('scheme', 'N/A'))}`\n"
                f"• 𝗜𝘀𝘀𝘂𝗲𝗿      : `{escape_markdown_v2(bin_details.get('bank_name', 'N/A'))}`\n"
                f"• 𝗖𝗮𝗿𝗱 𝗟𝗲𝘃𝗲𝗹: `{escape_markdown_v2(bin_details.get('level', 'N/A'))}`\n"
            )
        else:
            card_info_text = "• 𝗖𝗮𝗿𝗱 𝗜𝗻𝗳𝗼 : `N/A (BIN lookup failed)`\n"

    # For Mastercard, add a random success percentage
    success_percentage_text = ""
    if bin_details and bin_details.get("scheme", "").lower() == "mastercard":
        success_percentage = random.randint(68, 100)
        success_percentage_text = f"• 𝗦𝘂𝗰𝗰𝗲𝘀𝘀    : `{success_percentage}%`\n"

    response_text = (
        f"✅ *Card Killed Successfully!* ✅\n"
        f"━━━━━━━━━━━━━━\n"
        f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str)}`\n"
        f"{card_info_text}"
        f"{success_percentage_text}"
        f"━━━━━━━━━━━━━━\n"
        f"> 𝗞𝗶𝗹𝗹𝗲𝗿     : {escape_markdown_v2(update.effective_user.full_name)}\n"
        f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎\n"
        f"> 𝗧𝗶𝗺𝗲 𝗧𝗮𝗸𝗲𝗻: `{escape_markdown_v2(str(timedelta(seconds=int(time_taken))))}`"
    )
    
    try:
        await initial_message.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Error sending final kill message: {e}")
        # Fallback to sending a new message if editing failed
        await update.effective_message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)


async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

    card_details_input = None
    if context.args:
        card_details_input = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        card_details_input = update.message.reply_to_message.text

    if not card_details_input:
        return await update.message.reply_text(
            "❌ Please provide card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) as an argument or reply to a message containing them\\. "
            "Usage: `/kill CC\\|MM\\|YY\\|CVV` or `\\.kill CC\\|MM\\|YYYY\\|CVV`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # Regex to extract CC|MM|YY|CVV or CC|MM|YYYY|CVV
    card_match = re.search(r"(\d{13,19})\s*\|\s*(\d{2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3,4})\s*$", card_details_input)

    if not card_match:
        return await update.message.reply_text(
            "❌ Could not find valid card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) in the provided input\\. "
            "Make sure it's in the format `CC|MM|YY|CVV` or `CC|MM|YYYY|CVV`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    full_card_str = f"{card_match.group(1)}|{card_match.group(2)}|{card_match.group(3)}|{card_match.group(4)}"
    
    initial_message = await update.message.reply_text(
        f"💀 *Card Killer \\(Simulating\\)* 💀\n"
        f"━━━━━━━━━━━━━━\n"
        f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str)}`\n"
        f"• 𝗦𝘁𝗮𝘁𝘂𝘀     : Killing ⚡\n"
        f"• 𝗧𝗶𝗺𝗲 𝗘𝗹𝗮𝗽𝘀𝗲𝗱: `0:00:00`\n"
        f"━━━━━━━━━━━━━━\n"
        f"> 𝗣𝗹𝗲𝗮𝘀𝗲 𝘄𝗮𝗶𝘁\\.\n"
        f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # Run the kill process in the background
    asyncio.create_task(_execute_kill_process(update, context, full_card_str, initial_message))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

    uptime = datetime.now() - context.application.bot_data.get('start_time', datetime.now())
    uptime_str = str(timedelta(seconds=int(uptime.total_seconds())))

    # Get system and process info
    cpu_percent = psutil.cpu_percent(interval=1)
    ram_info = psutil.virtual_memory()
    ram_percent = ram_info.percent
    
    # Calculate process specific RAM usage
    process = psutil.Process(os.getpid())
    process_ram_mb = process.memory_info().rss / (1024 * 1024) # RSS in MB

    total_users = len(user_last_command) # Simple count of users who used a command

    response_text = (
        f"📊 *Bot Status* 📊\n"
        f"━━━━━━━━━━━━━━\n"
        f"• 𝗨𝗽𝘁𝗶𝗺𝗲       : `{escape_markdown_v2(uptime_str)}`\n"
        f"• 𝗖𝗣𝗨 𝗨𝘀𝗮𝗴𝗲   : `{cpu_percent:.1f}%`\n"
        f"• 𝗥𝗔𝗠 𝗨𝘀𝗮𝗴𝗲   : `{ram_percent:.1f}%` \\(Total\\)\n"
        f"• 𝗕𝗼𝘁 𝗥𝗔𝗠    : `{process_ram_mb:.2f} MB`\n"
        f"• 𝗧𝗼𝘁𝗮𝗹 𝗨𝘀𝗲𝗿𝘀: `{total_users}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"> 𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆 \\-: {escape_markdown_v2(update.effective_user.full_name)}\n"
        f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎"
    )
    await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)

async def stripe_auth_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await enforce_cooldown(update.effective_user.id):
        return await update.message.reply_text("⏳ Please wait 5 seconds before retrying\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if not STRIPE_SECRET_KEY:
        return await update.message.reply_text(
            "⚠️ Stripe API key is not configured\\. Please inform the bot owner\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    card_details_input = None
    if context.args:
        card_details_input = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        card_details_input = update.message.reply_to_message.text

    if not card_details_input:
        return await update.message.reply_text(
            "❌ Please provide card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) as an argument or reply to a message containing them\\. "
            "Usage: `/chk CC\\|MM\\|YY\\|CVV` or `\\.chk CC\\|MM\\|YYYY\\|CVV`\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    card_match = re.search(r"(\d{13,19})\s*\|\s*(\d{2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3,4})\s*$", card_details_input)

    if not card_match:
        return await update.message.reply_text(
            "❌ Could not find valid card details \\(CC\\|MM\\|YY\\|CVV or CC\\|MM\\|YYYY\\|CVV\\) in the provided input\\. "
            "Make sure it's in the format `CC|MM|YY|CVV` or `CC|MM|YYYY|CVV`\\.",
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
    checking_message = await update.message.reply_text("⏳ Attempting live card authorization with Stripe...", parse_mode=ParseMode.MARKDOWN_V2)

    result = await check_card_with_stripe_live(cc, mm, yy_full, cvv)

    escaped_user_full_name = escape_markdown_v2(update.effective_user.full_name)
    full_card_str_display = f"{cc}|{mm}|{yy}|{cvv}" # Keep original YY for display

    response_text = ""
    if result["status"] == "success":
        response_text = (
            f"✅ *Card Authenticated Successfully \\(Live Check\\)* ✅\n"
            f"━━━━━━━━━━━━━━\n"
            f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str_display)}`\n"
            f"• 𝗦𝘁𝗮𝘁𝘂𝘀     : LIVE ✅\n"
            f"━━━━━━━━━━━━━━\n"
            f"> 𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆 \\-: {escaped_user_full_name}\n"
            f"> 𝗕𝗼𝘁 𝗯𝘆 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎"
        )
    else:
        error_msg = escape_markdown_v2(result.get("message", "An unknown error occurred."))
        response_text = (
            f"❌ *Stripe Live Authentication Failed!* ❌\n"
            f"━━━━━━━━━━━━━━\n"
            f"• 𝗖𝗮𝗿𝗱 𝗡𝗼\\.  : `{escape_markdown_v2(full_card_str_display)}`\n"
            f"• 𝗦𝘁𝗮𝘁𝘂𝘀     : DEAD ❌\n"
            f"• 𝗥𝗲𝗮𝘀𝗼𝗻     : {error_msg}\n"
            f"━━━━━━━━━━━━━━\n"
            f"> 𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝗲𝗱 𝗯𝘆 \\-: {escaped_user_full_name}\n"
            f"> 𝗕𝒐𝒕 𝒃𝒚 \\-: 𝑩𝒍𝒐𝒄𝒌𝑺𝒕𝒐𝒓𝒎"
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
    """Allows the owner to authorize a specific group."""
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ You are not authorized to use this command\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if not context.args or not context.args[0].isdigit() and not context.args[0].startswith('-100'):
        return await update.message.reply_text(
            "❌ Please provide a valid chat ID \\(numeric\\) to authorize\\. Usage: `/au <chat_id>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    chat_id_to_authorize = int(context.args[0])

    # Here you would add the chat_id_to_authorize to your authorized groups list/database
    # For this example, we'll just acknowledge.
    # In a real bot, you'd store this in a persistent way (e.g., database, file).
    
    # Example: Check if the bot is actually in the group
    try:
        chat = await context.bot.get_chat(chat_id_to_authorize)
        if chat.type in ["group", "supergroup"]:
            await update.message.reply_text(
                f"✅ Group `{chat_id_to_authorize}` \\(`{escape_markdown_v2(chat.title)}`\\) has been authorized successfully\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(f"Group {chat_id_to_authorize} ('{chat.title}') authorized by owner.")
        else:
            await update.message.reply_text(
                f"❌ The provided ID `{chat_id_to_authorize}` is not a group chat\\. Please provide a valid group chat ID\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Could not authorize group `{chat_id_to_authorize}`\\. Error: `{escape_markdown_v2(str(e))}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.error(f"Error authorizing group {chat_id_to_authorize}: {e}")


def main():
    if TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set. Exiting.")
        exit(1)
    
    if OWNER_ID is None:
        logger.warning("OWNER_ID environment variable is not set. Owner-only commands will not function.")

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

    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.gen\b.*\s*.*"), gen))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\.bin\b.*\s*.*"), bin_lookup))
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

if __name__ == '__main__':
    main()
