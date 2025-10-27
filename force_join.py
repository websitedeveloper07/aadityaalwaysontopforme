from functools import wraps
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Configuration ---
GROUP_ID = -1003204998888     # numeric group ID (required)
GROUP_USERNAME = "+bCOqK048pxIwZjM1"     # for join button (@username only)

CHANNEL_ID = -1003119905313    # numeric channel ID (required)
CHANNEL_USERNAME = "regretingnow"  # for join button (no '+' sign)

# ✅ Updated permanent image link from ImgBB
FORCE_JOIN_IMAGE = "https://i.ibb.co/YFDvs5fr/6190727515442629298.jpg"

logger = logging.getLogger("force_join")
logger.setLevel(logging.INFO)


# --- Helper: Safe membership check ---
async def safe_get_member(bot, chat_id, user_id: int):
    """Safely check if a user is in a group/channel, handles API errors."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        logger.info(f"[DEBUG] User {user_id} in {chat_id}: {member.status}")
        return member.status
    except Exception as e:
        logger.warning(f"[SAFE CHECK] Failed to get member {user_id} in {chat_id}: {e}")
        return None


async def is_user_joined(bot, user_id: int) -> bool:
    """Check if user has joined BOTH group and channel."""
    valid_statuses = ["member", "administrator", "creator"]

    # --- Check group ---
    group_status = await safe_get_member(bot, GROUP_ID, user_id)
    if group_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in group ({group_status})")
        return False

    # --- Check channel ---
    channel_status = await safe_get_member(bot, CHANNEL_ID, user_id)
    if channel_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in channel ({channel_status})")
        return False

    logger.info(f"User {user_id} is in group & channel ✅")
    return True


# --- Force Join Decorator ---
def force_join(func):
    """Decorator to enforce group + channel join before using a command."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id

        # Always allow /start
        if update.message and update.message.text.startswith("/start"):
            return await func(update, context, *args, **kwargs)

        # Check membership
        joined = await is_user_joined(context.bot, user_id)
        if not joined:
            keyboard = [
                [InlineKeyboardButton("📢 Join Group", url=f"https://t.me/{GROUP_USERNAME}")],
                [InlineKeyboardButton("📡 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}")],
                [InlineKeyboardButton("✅ I have joined", callback_data="check_joined")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            caption_text = "❌ 𝗨𝗻𝗹𝗼𝗰𝗸 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗼 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗯𝘆 𝗷𝗼𝗶𝗻𝗶𝗻𝗴 𝗼𝘂𝗿 𝗰𝗵𝗮𝗻𝗻𝗲𝗹 𝗮𝗻𝗱 𝗴𝗿𝗼𝘂𝗽 𝘁𝗼𝗱𝗮𝘆!👇"

            target = update.message or update.callback_query.message
            await target.reply_photo(
                photo=FORCE_JOIN_IMAGE,
                caption=caption_text,
                reply_markup=reply_markup
            )
            return  # Stop execution

        # User already joined → proceed
        return await func(update, context, *args, **kwargs)

    return wrapper


# --- Callback for "✅ I have joined" button ---
async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-check membership when user clicks 'I have joined'."""
    query = update.callback_query
    user_id = query.from_user.id

    logger.info(f"Callback triggered by user {user_id}")

    joined = await is_user_joined(context.bot, user_id)

    if joined:
        await query.answer("✅ 𝗬𝗼𝘂 𝗵𝗮𝘃𝗲 𝗷𝗼𝗶𝗻𝗲𝗱, 𝗮𝗰𝗰𝗲𝘀𝘀 𝗴𝗿𝗮𝗻𝘁𝗲𝗱! 𝗡𝗼𝘄 𝘆𝗼𝘂 𝗰𝗮𝗻 𝘂𝘀𝗲 𝘁𝗵𝗲 𝗯𝗼𝘁 ✅", show_alert=True)
        await query.edit_message_caption("✨ 𝗪𝗲𝗹𝗰𝗼𝗺𝗲! 𝗕𝗼𝘁 𝗰𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗿𝗲 𝗻𝗼𝘄 𝗮𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲 𝗳𝗼𝗿 𝘆𝗼𝘂 𝗶𝗻 𝗽𝗿𝗶𝘃𝗮𝘁𝗲 𝗰𝗵𝗮𝘁𝘀 𝗮𝗻𝗱 𝗴𝗿𝗼𝘂𝗽𝘀.")
    else:
        await query.answer("❌ 𝗔𝗰𝗰𝗲𝘀𝘀 𝗱𝗲𝗻𝗶𝗲𝗱 – 𝘆𝗼𝘂 𝘀𝘁𝗶𝗹𝗹 𝗻𝗲𝗲𝗱 𝘁𝗼 𝗷𝗼𝗶𝗻!", show_alert=True)
        logger.info(f"User {user_id} clicked 'I have joined' but is still missing membership.")
