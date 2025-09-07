from functools import wraps
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Configuration ---
# ⚠️ If either group/channel is private, replace with numeric chat_id (like -100xxxxxxxxxx)
GROUP_ID = "@Cardxchktesting"   # or numeric ID
CHANNEL_ID = "@AXCMRX"          # or numeric ID
FORCE_JOIN_IMAGE = "https://i.postimg.cc/hjNQNyP1/1ea64ac8-ad6a-42f2-89b1-3de4a0d8e447.png"

logger = logging.getLogger(__name__)

# --- Helper: Check if user joined ---
async def is_user_joined(bot, user_id: int) -> bool:
    """Check if user has joined both group and channel."""
    try:
        group_status = await bot.get_chat_member(GROUP_ID, user_id)
        channel_status = await bot.get_chat_member(CHANNEL_ID, user_id)

        valid_statuses = ["member", "administrator", "creator"]

        if group_status.status not in valid_statuses:
            logger.info(f"User {user_id} is NOT in group ({group_status.status})")
            return False
        if channel_status.status not in valid_statuses:
            logger.info(f"User {user_id} is NOT in channel ({channel_status.status})")
            return False

        logger.info(f"User {user_id} is in both group and channel ✅")
        return True

    except Exception as e:
        logger.warning(f"Error checking user {user_id} membership: {e}")
        return False

# --- Force Join Decorator ---
def force_join(func):
    """Decorator to enforce group/channel join before using a command."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id

        # ✅ Allow /start always
        if update.message and update.message.text.startswith("/start"):
            return await func(update, context, *args, **kwargs)

        # 🔍 Check membership
        joined = await is_user_joined(context.bot, user_id)
        if not joined:
            keyboard = [
                [InlineKeyboardButton("📢 Join Group", url=f"https://t.me/{GROUP_ID.lstrip('@')}")],
                [InlineKeyboardButton("📡 Join Channel", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],
                [InlineKeyboardButton("✅ I have joined", callback_data="check_joined")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            caption_text = (
                "❌ You must join our group and channel to use this bot.\n\n"
                f"👉 Group: {GROUP_ID}\n"
                f"👉 Channel: {CHANNEL_ID}\n\n"
                "➡️ After joining, press ✅ I have joined."
            )

            if update.message:
                await update.message.reply_photo(
                    photo=FORCE_JOIN_IMAGE,
                    caption=caption_text,
                    reply_markup=reply_markup
                )
            elif update.callback_query:
                await update.callback_query.message.reply_photo(
                    photo=FORCE_JOIN_IMAGE,
                    caption=caption_text,
                    reply_markup=reply_markup
                )
            return  # Stop command execution until joined

        # ✅ User already joined → proceed with command
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
        await query.answer("✅ You have joined, now you can use the bot!", show_alert=True)
        await query.edit_message_caption("🎉 Welcome! You can now use the bot commands.")
    else:
        await query.answer("❌ You still need to join both group and channel.", show_alert=True)
