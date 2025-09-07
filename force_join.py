from functools import wraps
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# --- Configuration ---
GROUP_ID = "@bosssdkkk"        # Group username (bot must be admin)
CHANNEL_ID = "@abtkalinux"     # Channel username (bot must be admin)
FORCE_JOIN_IMAGE = "https://i.postimg.cc/hjNQNyP1/1ea64ac8-ad6a-42f2-89b1-3de4a0d8e447.png"


# --- Helper: Check if user joined ---
async def is_user_joined(bot, user_id: int) -> bool:
    """Check if user has joined both group and channel."""
    try:
        group_status = await bot.get_chat_member(GROUP_ID, user_id)
        channel_status = await bot.get_chat_member(CHANNEL_ID, user_id)

        if group_status.status in [ChatMember.LEFT, ChatMember.KICKED]:
            return False
        if channel_status.status in [ChatMember.LEFT, ChatMember.KICKED]:
            return False
        return True
    except Exception:
        return False


# --- Force Join Decorator ---
def force_join(func):
    """Decorator to enforce group/channel join before using a command."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id

        # ✅ Allow /start always without blocking
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

            if update.message:
                await update.message.reply_photo(
                    photo=FORCE_JOIN_IMAGE,
                    caption=(
                        "❌ You must join our group and channel to use this bot.\n\n"
                        f"👉 Group: {GROUP_ID}\n"
                        f"👉 Channel: {CHANNEL_ID}\n\n"
                        "➡️ After joining, press ✅ I have joined."
                    ),
                    reply_markup=reply_markup
                )
            elif update.callback_query:
                await update.callback_query.message.reply_photo(
                    photo=FORCE_JOIN_IMAGE,
                    caption=(
                        "❌ You must join our group and channel to use this bot.\n\n"
                        f"👉 Group: {GROUP_ID}\n"
                        f"👉 Channel: {CHANNEL_ID}\n\n"
                        "➡️ After joining, press ✅ I have joined."
                    ),
                    reply_markup=reply_markup
                )
            return

        # ✅ User already joined → proceed with command
        return await func(update, context, *args, **kwargs)
    return wrapper


# --- Callback for "✅ I have joined" button ---
async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-check membership when user clicks 'I have joined'."""
    query = update.callback_query
    user_id = query.from_user.id

    joined = await is_user_joined(context.bot, user_id)

    if joined:
        await query.answer("✅ You have joined, now you can use the bot!", show_alert=True)
        await query.edit_message_caption("🎉 Welcome! You can now use the bot commands.")
    else:
        await query.answer("❌ You still need to join both group and channel.", show_alert=True)


# --- Register Callback in main.py ---
def register_force_join(application):
    """Call this in main.py to register the callback for ✅ I have joined button."""
    application.add_handler(CallbackQueryHandler(check_joined_callback, pattern="check_joined"))
