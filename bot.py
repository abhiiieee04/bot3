import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.error import TelegramError
from database import Database
from datetime import datetime

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Conversation states ──────────────────────────────────────────────────────
AWAIT_FOLDER_NAME, AWAIT_COUPON_CODE, AWAIT_COUPON_DESC, AWAIT_COUPON_FOLDER = range(4)

# ── Config from env ──────────────────────────────────────────────────────────
BOT_TOKEN          = os.environ["BOT_TOKEN"]
CHANNEL_ID         = os.environ["CHANNEL_ID"]        # numeric ID: -100xxxxxxxxx
GROUP_ID           = os.environ["GROUP_ID"]           # numeric ID: -100xxxxxxxxx
CHANNEL_INVITE     = os.environ["CHANNEL_INVITE"]     # https://t.me/+xxxx  (private invite link)
GROUP_INVITE       = os.environ["GROUP_INVITE"]       # https://t.me/+xxxx  (private invite link)
DATABASE_URL       = os.environ["DATABASE_URL"]

db = Database(DATABASE_URL)


# ════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════════════

async def is_admin(bot, user_id: int) -> bool:
    """True if user is admin in either the channel or the group."""
    for chat_id in [CHANNEL_ID, GROUP_ID]:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ("administrator", "creator"):
                return True
        except TelegramError:
            pass
    return False


async def is_member(bot, user_id: int) -> bool:
    """True if user is a member of BOTH the channel and the group."""
    for chat_id in [CHANNEL_ID, GROUP_ID]:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except TelegramError:
            return False
    return True


def membership_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_INVITE)],
        [InlineKeyboardButton("💬 Join Group",   url=GROUP_INVITE)],
        [InlineKeyboardButton("✅ I've Joined – Check Again", callback_data="check_membership")],
    ])


def main_menu_keyboard(is_adm: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🗂  Browse Coupons", callback_data="browse")],
    ]
    if is_adm:
        rows += [
            [InlineKeyboardButton("➕ Add Coupon",    callback_data="add_coupon"),
             InlineKeyboardButton("📁 New Folder",    callback_data="add_folder")],
            [InlineKeyboardButton("🗑  Delete Coupon", callback_data="delete_coupon"),
             InlineKeyboardButton("🗂  Delete Folder", callback_data="delete_folder")],
        ]
    return InlineKeyboardMarkup(rows)


# ════════════════════════════════════════════════════════════════════════════
#  /start
# ════════════════════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    adm  = await is_admin(ctx.bot, user.id)
    mem  = adm or await is_member(ctx.bot, user.id)

    if not mem:
        await update.message.reply_text(
            "👋 Welcome!\n\n"
            "To access exclusive coupon codes you must join our channel and group first.",
            reply_markup=membership_keyboard(),
        )
        return

    await update.message.reply_text(
        f"👋 Hey {user.first_name}!\n\n"
        "Welcome to the 🎟 *Coupon Bot*.\n"
        "Browse folders to reveal exclusive discount codes!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(adm),
    )


# ════════════════════════════════════════════════════════════════════════════
#  MEMBERSHIP CHECK (callback)
# ════════════════════════════════════════════════════════════════════════════

async def check_membership_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    adm  = await is_admin(ctx.bot, user.id)
    mem  = adm or await is_member(ctx.bot, user.id)

    if not mem:
        await query.edit_message_text(
            "❌ You still haven't joined both.\nPlease join and try again.",
            reply_markup=membership_keyboard(),
        )
        return

    await query.edit_message_text(
        f"✅ Access granted, {user.first_name}!\n\nWelcome to the Coupon Bot 🎉",
        reply_markup=main_menu_keyboard(adm),
    )


# ════════════════════════════════════════════════════════════════════════════
#  BROWSE — folder list → coupons in folder
# ════════════════════════════════════════════════════════════════════════════

async def browse_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    adm  = await is_admin(ctx.bot, user.id)
    mem  = adm or await is_member(ctx.bot, user.id)

    if not mem:
        await query.edit_message_text(
            "❌ You must join first!", reply_markup=membership_keyboard()
        )
        return

    folders = db.get_folders()
    if not folders:
        await query.edit_message_text(
            "📭 No coupon folders yet. Check back soon!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
            ),
        )
        return

    buttons = [
        [InlineKeyboardButton(
            f"📁 {f['name']}  ({f['coupon_count']} codes)  •  {f['created_at'].strftime('%d %b %Y')}",
            callback_data=f"folder_{f['id']}"
        )]
        for f in folders
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])
    await query.edit_message_text(
        "🗂 *Choose a folder to browse:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def folder_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split("_")[1])
    folder    = db.get_folder(folder_id)
    coupons   = db.get_coupons(folder_id)

    if not coupons:
        text = f"📭 No coupons in *{folder['name']}* yet."
    else:
        lines = [f"🎟 *Coupons in {folder['name']}:*\n"]
        for c in coupons:
            desc = f"  _{c['description']}_" if c["description"] else ""
            lines.append(f"• `{c['code']}`{desc}")
        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Folders", callback_data="browse")]]
        ),
    )


# ════════════════════════════════════════════════════════════════════════════
#  MAIN MENU (back button)
# ════════════════════════════════════════════════════════════════════════════

async def main_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    adm = await is_admin(ctx.bot, query.from_user.id)
    await query.edit_message_text(
        "🏠 *Main Menu*", parse_mode="Markdown",
        reply_markup=main_menu_keyboard(adm),
    )


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — ADD FOLDER (conversation)
# ════════════════════════════════════════════════════════════════════════════

async def add_folder_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(ctx.bot, query.from_user.id):
        await query.answer("❌ Admins only.", show_alert=True)
        return ConversationHandler.END

    await query.edit_message_text("📁 Enter the *folder name* (e.g. `Nike June 2025`):",
                                  parse_mode="Markdown")
    return AWAIT_FOLDER_NAME


async def recv_folder_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("⚠️ Name can't be empty. Try again:")
        return AWAIT_FOLDER_NAME

    folder_id = db.create_folder(name)
    adm = await is_admin(ctx.bot, update.effective_user.id)
    await update.message.reply_text(
        f"✅ Folder *{name}* created!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(adm),
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — ADD COUPON (conversation)
# ════════════════════════════════════════════════════════════════════════════

async def add_coupon_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(ctx.bot, query.from_user.id):
        await query.answer("❌ Admins only.", show_alert=True)
        return ConversationHandler.END

    folders = db.get_folders()
    if not folders:
        await query.edit_message_text(
            "⚠️ No folders exist yet. Create a folder first!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📁 New Folder", callback_data="add_folder"),
                  InlineKeyboardButton("⬅️ Back",       callback_data="main_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(f"📁 {f['name']}", callback_data=f"pick_folder_{f['id']}")]
        for f in folders
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="main_menu")])
    await query.edit_message_text(
        "📁 *Pick a folder* for the new coupon:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return AWAIT_COUPON_FOLDER


async def pick_folder_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split("_")[2])
    ctx.user_data["coupon_folder_id"] = folder_id
    folder = db.get_folder(folder_id)
    ctx.user_data["coupon_folder_name"] = folder["name"]
    await query.edit_message_text(
        f"✏️ Adding coupon to *{folder['name']}*.\n\nSend me the *coupon code*:",
        parse_mode="Markdown",
    )
    return AWAIT_COUPON_CODE


async def recv_coupon_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["coupon_code"] = update.message.text.strip()
    await update.message.reply_text(
        "📝 Optional: send a *description* for this coupon (or /skip):",
        parse_mode="Markdown",
    )
    return AWAIT_COUPON_DESC


async def recv_coupon_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip() if update.message.text != "/skip" else ""
    folder_id = ctx.user_data["coupon_folder_id"]
    code      = ctx.user_data["coupon_code"]
    db.add_coupon(folder_id, code, desc)
    adm = await is_admin(ctx.bot, update.effective_user.id)
    await update.message.reply_text(
        f"✅ Coupon `{code}` added to *{ctx.user_data['coupon_folder_name']}*!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(adm),
    )
    return ConversationHandler.END


async def skip_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await recv_coupon_desc(update, ctx)


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — DELETE COUPON
# ════════════════════════════════════════════════════════════════════════════

async def delete_coupon_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(ctx.bot, query.from_user.id):
        await query.answer("❌ Admins only.", show_alert=True)
        return

    coupons = db.get_all_coupons()
    if not coupons:
        await query.edit_message_text(
            "📭 No coupons to delete.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
            ),
        )
        return

    buttons = [
        [InlineKeyboardButton(
            f"🗑 {c['code']}  ({c['folder_name']})",
            callback_data=f"delcoupon_{c['id']}"
        )]
        for c in coupons
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])
    await query.edit_message_text(
        "🗑 *Select coupon to delete:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def confirm_delete_coupon_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    coupon_id = int(query.data.split("_")[1])
    coupon    = db.get_coupon(coupon_id)
    db.delete_coupon(coupon_id)
    adm = await is_admin(ctx.bot, query.from_user.id)
    await query.edit_message_text(
        f"✅ Coupon `{coupon['code']}` deleted.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(adm),
    )


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — DELETE FOLDER
# ════════════════════════════════════════════════════════════════════════════

async def delete_folder_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(ctx.bot, query.from_user.id):
        await query.answer("❌ Admins only.", show_alert=True)
        return

    folders = db.get_folders()
    if not folders:
        await query.edit_message_text(
            "📭 No folders to delete.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
            ),
        )
        return

    buttons = [
        [InlineKeyboardButton(
            f"🗑 {f['name']}  ({f['coupon_count']} codes)",
            callback_data=f"delfolder_{f['id']}"
        )]
        for f in folders
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])
    await query.edit_message_text(
        "🗑 *Select folder to delete* (all coupons inside will be deleted too):*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def confirm_delete_folder_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split("_")[1])
    folder    = db.get_folder(folder_id)
    db.delete_folder(folder_id)
    adm = await is_admin(ctx.bot, query.from_user.id)
    await query.edit_message_text(
        f"✅ Folder *{folder['name']}* and all its coupons deleted.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(adm),
    )


# ════════════════════════════════════════════════════════════════════════════
#  CANCEL (conversation fallback)
# ════════════════════════════════════════════════════════════════════════════

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    adm = await is_admin(ctx.bot, update.effective_user.id)
    await update.message.reply_text(
        "❌ Action cancelled.",
        reply_markup=main_menu_keyboard(adm),
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  APP ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

def main():
    db.init()

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Add Folder conversation ──────────────────────────────────────────────
    folder_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_folder_cb, pattern="^add_folder$")],
        states={AWAIT_FOLDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_folder_name)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── Add Coupon conversation ──────────────────────────────────────────────
    coupon_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_coupon_cb, pattern="^add_coupon$")],
        states={
            AWAIT_COUPON_FOLDER: [CallbackQueryHandler(pick_folder_cb, pattern=r"^pick_folder_\d+$")],
            AWAIT_COUPON_CODE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_coupon_code)],
            AWAIT_COUPON_DESC:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_coupon_desc),
                CommandHandler("skip", skip_desc),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── Handlers ─────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(folder_conv)
    app.add_handler(coupon_conv)
    app.add_handler(CallbackQueryHandler(check_membership_cb,      pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(main_menu_cb,             pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(browse_cb,                pattern="^browse$"))
    app.add_handler(CallbackQueryHandler(folder_cb,                pattern=r"^folder_\d+$"))
    app.add_handler(CallbackQueryHandler(delete_coupon_cb,         pattern="^delete_coupon$"))
    app.add_handler(CallbackQueryHandler(confirm_delete_coupon_cb, pattern=r"^delcoupon_\d+$"))
    app.add_handler(CallbackQueryHandler(delete_folder_cb,         pattern="^delete_folder$"))
    app.add_handler(CallbackQueryHandler(confirm_delete_folder_cb, pattern=r"^delfolder_\d+$"))

    logger.info("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
