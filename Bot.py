#!/usr/bin/env python3
"""
IMAGE_BG_REMOVER_by_10x_BOT

Features implemented:
- Uses multiple remove.bg API keys with monthly 50-call limits (round-robin & persisted).
- Coin system: 25 coins on first /start, referral start links give 10 or 15 coins respectively.
- Cost: 5 coins per background removal.
- Requires joining a channel before using. Provides inline buttons for channels and coin-earning links.
- Forwards all user-sent images to a specified group.
- Broadcasts messages received from a specific "source group" to all users.
- VIP-only /statisticsvip command (allowed only for user id 6572397779).
- Commands: /upscale, /help, /feedback, /clone, /promotion, /statistics
- Saves data in a local SQLite DB (persistent): users, api_keys usage, logs.
- Returns PNG (transparent) background-removed image to user.

Usage:
- Edit any configuration constants below if needed.
- Run with: python3 bot.py
- Requirements in requirements.txt.

Author: Generated for the user
"""

import os
import io
import time
import calendar
import sqlite3
import logging
import requests
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    ChatMemberStatus,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)

# -------------------- CONFIG (edit if needed) --------------------
BOT_TOKEN = "8428976485:AAFlV7VjfNdyCS5R-E45dP_3khsZ1Ahb2GE"

# Remove.bg API keys (from user input). We'll store these in DB on first run.
API_KEYS = [
    "Bmtmh8Wf4scqRsa1GYanmCjj",
    "QFh51ZFTAU9ub31zUbZBTKkF",
    "QFh51ZFTAU9ub31zUbZBTKkF",
    "pM3amwZmyjMjX7ZxnomKNSoR",
    "pM3amwZmyjMjX7ZxnomKNSoR",
    "tRgaB7Y9dUjcNMwfBrLUp4YE",
    "c5Nrfmeo2BsqwGhJQVkeD8jS",
    "otsQgv786ywfdmWzRZpAch3J",
    "ddceDMa3T8V79S9kuQ46Jyvy",
    "1yTTcotfLmo2b5NirynoF3wJ",
    "we2EmxtVoJHA7iR4MuqYRbWa",
]

# monthly limit per API (you said 50)
API_MONTHLY_LIMIT = 50

# Coins
COINS_FIRST_START = 25
COINS_REF_1 = 10  # for start param BQADAQAD_goAAqh3GUc_z_5o1L_GeBYE
COINS_REF_2 = 15  # for start param BQADAQAD_goAAqh3GUgjbufrxh33yt
COST_PER_REMOVE = 5

# Required channel to join
REQUIRED_CHANNELS = [
    ("Noob_tube_ff_tg_Channel", "https://t.me/Noob_tube_ff_tg_Channel"),  # display name + url
]

# Links used when user has no coins
EARN_BUTTONS = [
    ("earn 10 coins", "https://cuty.io/2DCHXtq"),
    ("earn 15 coins", "https://cuty.io/Gd1MZS"),
]

# Where to forward all user images
FORWARD_GROUP_ID = -1003190051264  # as integer
FORWARD_GROUP_LINK = "https://t.me/noobTubeFF"

# The "source group" whose messages should be forwarded to all users
BROADCAST_SOURCE_GROUP_ID = -1003158467679
BROADCAST_SOURCE_GROUP_LINK = "https://t.me/+qxTDSZQ4NGVlNTg1"

# Buttons shown after /start
START_BUTTONS = [
    ("feedback", "@NoobTube_FF"),
    ("owner", "@NoobTube_FF"),
    ("add me to a group", "http://t.me/IMAGE_BG_REMOVER_by_10x_BOT?startgroup=start"),
]

# Owner / feedback
OWNER_USERNAME = "@NoobTube_FF"
FEEDBACK_TEXT = f"owner: {OWNER_USERNAME}"

# VIP user id allowed to run /statisticsvip
VIP_USER_ID = 6572397779

# SQLite DB file
DB_FILE = "bg_bot.db"

# Remove.bg API url
REMOVEBG_ENDPOINT = "https://api.remove.bg/v1.0/removebg"

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# -------------------- Database helpers --------------------
def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    # users: store id, coins, first_started (0/1), started_via (token/ref), username, fullname, is_vip
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            fullname TEXT,
            coins INTEGER DEFAULT 0,
            first_started INTEGER DEFAULT 0,
            started_via TEXT DEFAULT NULL,
            is_vip INTEGER DEFAULT 0,
            added_at TEXT
        )
    """
    )
    # api keys usage tracking
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            key_text TEXT PRIMARY KEY,
            month_year TEXT,
            used INTEGER DEFAULT 0
        )
    """
    )
    # logs of operations
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            detail TEXT,
            created_at TEXT
        )
    """
    )
    conn.commit()
    # ensure keys exist
    for k in API_KEYS:
        add_api_key_if_not_exists(conn, k)
    return conn


def add_api_key_if_not_exists(conn: sqlite3.Connection, key: str):
    c = conn.cursor()
    now_my = datetime.utcnow().strftime("%Y-%m")
    c.execute("SELECT key_text, month_year FROM api_keys WHERE key_text = ?", (key,))
    row = c.fetchone()
    if not row:
        c.execute(
            "INSERT INTO api_keys (key_text, month_year, used) VALUES (?, ?, ?)",
            (key, now_my, 0),
        )
        conn.commit()


def reset_api_month_if_needed(conn: sqlite3.Connection):
    """Resets 'used' counters for keys if month rolled."""
    c = conn.cursor()
    now_my = datetime.utcnow().strftime("%Y-%m")
    c.execute("SELECT key_text, month_year, used FROM api_keys")
    rows = c.fetchall()
    for key_text, month_year, used in rows:
        if month_year != now_my:
            c.execute(
                "UPDATE api_keys SET used = 0, month_year = ? WHERE key_text = ?",
                (now_my, key_text),
            )
    conn.commit()


def choose_api_key(conn: sqlite3.Connection) -> Optional[str]:
    """Choose an API key with remaining quota (used < API_MONTHLY_LIMIT)."""
    reset_api_month_if_needed(conn)
    c = conn.cursor()
    c.execute("SELECT key_text, used FROM api_keys ORDER BY used ASC")
    rows = c.fetchall()
    for key_text, used in rows:
        if used < API_MONTHLY_LIMIT:
            return key_text
    return None


def increment_api_usage(conn: sqlite3.Connection, key: str):
    c = conn.cursor()
    c.execute(
        "UPDATE api_keys SET used = used + 1 WHERE key_text = ?",
        (key,),
    )
    conn.commit()


def log_action(conn: sqlite3.Connection, user_id: int, action: str, detail: str = ""):
    c = conn.cursor()
    c.execute(
        "INSERT INTO logs (user_id, action, detail, created_at) VALUES (?, ?, ?, ?)",
        (user_id, action, detail, datetime.utcnow().isoformat()),
    )
    conn.commit()


def get_user(conn: sqlite3.Connection, user_id: int) -> Optional[Dict[str, Any]]:
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, fullname, coins, first_started, started_via, is_vip, added_at FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = c.fetchone()
    if not row:
        return None
    keys = ["user_id", "username", "fullname", "coins", "first_started", "started_via", "is_vip", "added_at"]
    return dict(zip(keys, row))


def ensure_user_exists(conn: sqlite3.Connection, user_id: int, username: str, fullname: str):
    if get_user(conn, user_id) is None:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (user_id, username, fullname, coins, first_started, added_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, fullname, 0, 0, datetime.utcnow().isoformat()),
        )
        conn.commit()


def add_coins(conn: sqlite3.Connection, user_id: int, amount: int, reason: str = ""):
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    log_action(conn, user_id, "add_coins", f"{amount} ({reason})")


def set_first_started(conn: sqlite3.Connection, user_id: int, via: Optional[str], coins_given: int = 0):
    c = conn.cursor()
    c.execute(
        "UPDATE users SET first_started = 1, started_via = ?, coins = coins + ? WHERE user_id = ?",
        (via, coins_given, user_id),
    )
    conn.commit()
    log_action(conn, user_id, "first_start", f"via={via} coins={coins_given}")


def deduct_coins(conn: sqlite3.Connection, user_id: int, amount: int) -> bool:
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        return False
    coins = row[0]
    if coins < amount:
        return False
    c.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    log_action(conn, user_id, "spend_coins", f"-{amount}")
    return True


def count_users(conn: sqlite3.Connection) -> int:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    return c.fetchone()[0]


def get_all_users(conn: sqlite3.Connection):
    c = conn.cursor()
    c.execute("SELECT user_id, username, fullname, coins FROM users ORDER BY user_id DESC")
    return c.fetchall()


# -------------------- Bot logic --------------------

# initialize DB
DB = init_db()


async def force_join_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, Optional[InlineKeyboardMarkup]]:
    """
    Check whether user is member of REQUIRED_CHANNELS.
    Returns (is_member_boolean, keyboard_to_prompt_join_if_not)
    """
    user = update.effective_user
    bot = context.bot
    not_joined = []
    for chan_name, chan_link in REQUIRED_CHANNELS:
        try:
            # get_chat_member requires exact chat username or id. We assume link like https://t.me/ChannelName
            # parse username from link if provided
            # we'll try both the username and the full link
            target = chan_link
            if target.startswith("https://t.me/"):
                target = target.split("https://t.me/")[-1]
            member = await bot.get_chat_member(chat_id=target, user_id=user.id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                not_joined.append((chan_name, chan_link))
        except Exception as e:
            # If get_chat_member fails (private channel or not found), fallback: consider not joined
            logger.info(f"Channel membership check error for {chan_link}: {e}")
            not_joined.append((chan_name, chan_link))

    if not_joined:
        buttons = []
        for name, link in not_joined:
            buttons.append([InlineKeyboardButton(text=f"Join {name}", url=link)])
        # add a refresh check button (user clicks to re-check)
        buttons.append([InlineKeyboardButton(text="I've joined — Check again", callback_data="check_join")])
        kb = InlineKeyboardMarkup(buttons)
        return False, kb
    return True, None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start and referral tokens."""
    user = update.effective_user
    uid = user.id
    username = f"@{user.username}" if user.username else ""
    fullname = user.full_name or ""

    ensure_user_exists(DB, uid, username, fullname)

    # check start payload
    args = context.args or []
    start_payload = args[0] if len(args) >= 1 else None

    userrow = get_user(DB, uid)
    gave_coins = 0

    if userrow and userrow["first_started"] == 0:
        # first time start
        if start_payload is None:
            gave_coins = COINS_FIRST_START
            set_first_started(DB, uid, via=None, coins_given=gave_coins)
        else:
            # match referral payloads (exact strings from user)
            if start_payload == "BQADAQAD_goAAqh3GUc_z_5o1L_GeBYE":
                gave_coins = COINS_REF_1
            elif start_payload == "BQADAQAD_goAAqh3GUgjbufrxh33yt":
                gave_coins = COINS_REF_2
            else:
                gave_coins = COINS_FIRST_START
            set_first_started(DB, uid, via=start_payload, coins_given=gave_coins)

    # Build start keyboard
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=START_BUTTONS[0][0], callback_data="btn_feedback"),
             InlineKeyboardButton(text=START_BUTTONS[1][0], url=f"https://t.me/{START_BUTTONS[1][1].lstrip('@')}")],
            [InlineKeyboardButton(text=START_BUTTONS[2][0], url=START_BUTTONS[2][1])]
        ]
    )

    text_lines = [f"Hi {fullname} 👋"]
    if gave_coins:
        text_lines.append(f"You got {gave_coins} coins on start. Use /help to see how to remove a background.")
    else:
        text_lines.append("Welcome back! Use /help to see how to remove a background.")
    text_lines.append(f"Your current coins: {get_user(DB, uid)['coins']}")
    text = "\n".join(text_lines)
    await update.message.reply_text(text, reply_markup=kb)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline button presses (e.g., check_join, feedback)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "check_join":
        ok, kb = await force_join_check(update, context)
        if ok:
            await query.edit_message_text("Thanks — you are a member. Now send an image to remove background.")
        else:
            await query.edit_message_text("You still haven't joined required channels.", reply_markup=kb)
    elif data == "btn_feedback":
        await query.message.reply_text(FEEDBACK_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Just send a photo — I'll remove the background for 5 coins and return a PNG.")


async def upscale_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("upcoming...")


async def clone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("upcoming...")


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(FEEDBACK_TEXT)


async def promotion_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "no hi no hello only Write your ad with your channel or group link and send it here. 👇\n"
        "@Free_promotion_10x_bot\n"
        "✅English Hindi or Bengali\n🔞Strictly no 18+ content.\n🚫No  spam allowed.\n📢 Free promotion💯"
    )


async def statistics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = count_users(DB)
    await update.message.reply_text(f"Total users: {total}")


async def statistics_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != VIP_USER_ID:
        await update.message.reply_text("You are not authorized for this command.")
        return
    rows = get_all_users(DB)
    lines = ["user_id | username | fullname | coins"]
    for uid, username, fullname, coins in rows:
        lines.append(f"{uid} | {username or ''} | {fullname or ''} | {coins}")
    text = "\n".join(lines) or "No users."
    # if too long, send as file
    if len(text) > 4000:
        bio = io.BytesIO()
        bio.write(text.encode("utf-8"))
        bio.seek(0)
        await update.message.reply_document(document=InputFile(bio, filename="users_stats.txt"))
    else:
        await update.message.reply_text(text)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Main flow for when a user sends a photo (or image). Steps:
    1. Check required channel membership.
    2. Ensure user has enough coins.
    3. Choose an API key with quota.
    4. Download the file, upload to remove.bg, get PNG result.
    5. Send the PNG back to user.
    6. Deduct coins and log; forward original image to FORWARD_GROUP_ID.
    """
    user = update.effective_user
    uid = user.id
    ensure_user_exists(DB, uid, f"@{user.username}" if user.username else "", user.full_name or "")

    ok, join_kb = await force_join_check(update, context)
    if not ok:
        await update.message.reply_text(
            "You must join our telegram channels to use me.",
            reply_markup=join_kb,
        )
        return

    userrow = get_user(DB, uid)
    if userrow["coins"] < COST_PER_REMOVE:
        # send message with earn buttons
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text=t, url=u)] for t, u in EARN_BUTTONS])
        await update.message.reply_text(
            "You don't have enough coins. Click any of the buttons below to earn coins.", reply_markup=keyboard
        )
        return

    # get the best quality photo file (last in PhotoSize list)
    photo = update.message.photo[-1]
    file_obj = await photo.get_file()
    bio = io.BytesIO()
    await file_obj.download_to_memory(out=bio)
    bio.seek(0)

    # choose API key
    api_key = choose_api_key(DB)
    if not api_key:
        await update.message.reply_text("All remove.bg API keys reached monthly limits. Try again next month.")
        return

    # Call remove.bg
    files = {"image_file": ("image.jpg", bio)}
    data = {"size": "auto", "format": "png"}
    headers = {"X-Api-Key": api_key}
    try:
        resp = requests.post(REMOVEBG_ENDPOINT, files=files, data=data, headers=headers, timeout=60)
    except Exception as e:
        logger.exception("remove.bg request failed")
        await update.message.reply_text("Failed to contact remove.bg. Please try again later.")
        return

    if resp.status_code == 200:
        result_bytes = resp.content
        # send the PNG back
        out = io.BytesIO(result_bytes)
        out.name = "no_bg.png"
        out.seek(0)
        await update.message.reply_photo(photo=out, caption="Here is your background-removed image (PNG).")
        # deduct coins & increment API usage & forward original image to group
        deducted = deduct_coins(DB, uid, COST_PER_REMOVE)
        increment_api_usage(DB, api_key)
        log_action(DB, uid, "remove_bg_success", f"used_key={api_key}")
        # forward original image to group (we forward the message)
        try:
            # forward the message that user sent (photo) to the group
            await update.message.forward(chat_id=FORWARD_GROUP_ID)
        except Exception as e:
            logger.info(f"Failed to forward to group {FORWARD_GROUP_ID}: {e}")
    else:
        # parse error message if any
        err_text = resp.text
        logger.error(f"remove.bg error: {resp.status_code} - {err_text}")
        await update.message.reply_text("Failed to remove background: " + str(resp.status_code))


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    When the specific source group sends a message to the bot (e.g., the group posted to bot),
    the bot will forward that message to all users in DB.
    NOTE: This may be heavy. It's the behavior the user requested.
    """
    # Only respond to messages from the specific source group
    if update.effective_chat and update.effective_chat.id == BROADCAST_SOURCE_GROUP_ID:
        # fetch all users
        users = get_all_users(DB)
        for uid, username, fullname, coins in users:
            try:
                # forward this group message to each user
                await update.message.forward(chat_id=uid)
            except Exception as e:
                # if user blocked bot or can't be delivered, ignore
                logger.info(f"Could not forward to {uid}: {e}")
        logger.info("Broadcast from source group forwarded to all users.")
        return


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Use /help.")


# -------------------- Startup --------------------
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("upscale", upscale_command))
    application.add_handler(CommandHandler("clone", clone_command))
    application.add_handler(CommandHandler("feedback", feedback_command))
    application.add_handler(CommandHandler("promotion", promotion_command))
    application.add_handler(CommandHandler("statistics", statistics_command))
    application.add_handler(CommandHandler("statisticsvip", statistics_vip_command))
    # For unknown commands
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Photo handler
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Group message handler to broadcast group -> users
    application.add_handler(
        MessageHandler(
            filters.Chat(BROADCAST_SOURCE_GROUP_ID) & (~filters.COMMAND),
            handle_group_message,
        )
    )

    logger.info("Starting bot...")
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
