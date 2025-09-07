from functools import wraps
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Configuration ---
GROUP_ID = -1003021757536   # numeric group ID (used only for membership check)
GROUP_USERNAME = "Cardxchktesting"  # used for join button
CHANNEL_USERNAME = "AXCMRX"         # used for join button (optional)
FORCE_JOIN_IMAGE = "https://i.postimg.cc/hjNQNyP1/1ea64ac8-ad6a-42f2-89b1-3de4a0d8e447.png"

logger = logging.getLogger("force_join")
logger.setLevel(logging.INFO)

# --- Helper: Safe membership check ---
async def safe_get_member(bot, chat_id: int, user_id: int):
    """Safely check if a user is in a group, handles API errors."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        logger.info(f"[DEBUG] User {user_id} in {chat_id}: {member.status}")
        return member.status
    except Exception as e:
        logger.warning(f"[SAFE CHECK] Failed to get member {user_id} in {chat_id}: {e}")
        return None

async def is_user_joined(bot, user_id: int) -> bool:
    """Check if user has joined the group only."""
    valid_statuses = ["member", "administrator", "creator"]
    group_status = await safe_get_member(bot, GROUP_ID, user_id)

    if group_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in group ({group_status})")
        return False

    logger.info(f"User {user_id} is in group ✅")
    return True

# --- Force Join Decorator ---
def force_join(func):
    """Decorator to enforce group join before using a command."""
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

            caption_text = "❌ To use the bot please join below 👇"

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
        await query.answer("✅ You have joined the group, now you can use the bot!", show_alert=True)
        await query.edit_message_caption("🎉 Welcome! You can now use the bot commands.")
    else:
        await query.answer("❌ You still need to join the group.", show_alert=True)
        logger.info(f"User {user_id} clicked 'I have joined' but is still not in the group.")
