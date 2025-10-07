#!/usr/bin/env python3
# bot.py - IMAGE_BG_REMOVER_by_10x_BOT (async, PTB v20+)
import asyncio
import os
import sqlite3
from datetime import datetime
from typing import Optional, Tuple, List
import httpx

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile)
from telegram.ext import (Application, CommandHandler, MessageHandler, filters, ContextTypes)

# ---------------------
# CONFIG (replace or use ENV)
# ---------------------
# You provided these — it's safer to set them as environment variables.
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8428976485:AAFlV7VjfNdyCS5R-E45dP_3khsZ1Ahb2GE"

# remove.bg-like API keys (rotate among them). Provided by user:
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

# Monthly limit per key:
KEY_MONTHLY_LIMIT = 50

# Channel / group IDs and links (as requested)
REQUIRE_JOIN_CHANNELS = [
    {"id": "@Noob_tube_ff_tg_Channel", "link": "https://t.me/Noob_tube_ff_tg_Channel"}
]
FORWARD_GROUP_CHAT_ID = int(os.environ.get("FORWARD_GROUP_ID") or -1003190051264)  # -1003190051264
BROADCAST_FROM_GROUP_ID = int(os.environ.get("BROADCAST_FROM_GROUP_ID") or -1003158467679)  # -1003158467679

# VIP user allowed for /statisticsvip
VIP_USER_ID = int(os.environ.get("VIP_USER_ID") or 6572397779)

COINS_PER_REMOVE = 5
INITIAL_FIRST_START_COINS = 25
REF_LINK_COINS = {
    # payload -> coins
    "BQADAQAD_goAAqh3GUc_z_5o1L_GeBYE": 10,
    "BQADAQAD_goAAqh3GUgjbufrxh33yt": 15,
}

# Earn buttons when coins < required
EARN_BUTTONS = [
    ("earn 10 coins", "https://cuty.io/2DCHXtq"),
    ("earn 15 coins", "https://cuty.io/Gd1MZS"),
]

# After start buttons:
AFTER_START_BUTTONS = [
    ("feedback", "@NoobTube_FF"),
    ("owner", "@NoobTube_FF"),
    ("add me to a group", "http://t.me/IMAGE_BG_REMOVER_by_10x_BOT?startgroup=start"),
]

# remove.bg endpoint (example)
REMOVE_BG_ENDPOINT = "https://api.remove.bg/v1.0/removebg"

# ---------------------
# DB Setup (sqlite)
# ---------------------
DB_PATH = os.environ.get("DB_PATH") or "data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        coins INTEGER DEFAULT 0,
        started INTEGER DEFAULT 0, -- 0 = never started, 1 = started
        joined INTEGER DEFAULT 0
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS api_usage (
        api_key TEXT PRIMARY KEY,
        month TEXT,
        used INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

def db_get_user(user_id: int) -> Optional[Tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, coins, started FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def db_add_or_update_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if db_get_user(user_id) is None:
        c.execute("INSERT INTO users (user_id, username, first_name, coins, started) VALUES (?, ?, ?, 0, 0)",
                  (user_id, username, first_name))
    else:
        c.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                  (username, first_name, user_id))
    conn.commit()
    conn.close()

def db_set_started_and_add_coins(user_id: int, coins_to_add: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT coins, started FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO users (user_id, coins, started) VALUES (?, ?, 1)", (user_id, coins_to_add))
    else:
        coins, started = row
        if started == 0:
            c.execute("UPDATE users SET coins = coins + ?, started=1 WHERE user_id=?", (coins_to_add, user_id))
        else:
            # do not add again if already started
            pass
    conn.commit()
    conn.close()

def db_modify_coins(user_id: int, delta: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row is None:
        # create user with 0 then modify
        c.execute("INSERT INTO users (user_id, coins, started) VALUES (?, ?, 0)", (user_id, 0))
        current = 0
    else:
        current = row[0]
    new = max(0, current + delta)
    c.execute("UPDATE users SET coins=? WHERE user_id=?", (new, user_id))
    conn.commit()
    conn.close()
    return new

def db_get_all_users() -> List[Tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, coins FROM users")
    rows = c.fetchall()
    conn.close()
    return rows

# API usage tracking functions
def db_get_or_create_api_key_entry(api_key: str):
    now_month = datetime.utcnow().strftime("%Y-%m")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT api_key, month, used FROM api_usage WHERE api_key=?", (api_key,))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO api_usage (api_key, month, used) VALUES (?, ?, 0)", (api_key, now_month))
        conn.commit()
        conn.close()
        return (api_key, now_month, 0)
    else:
        api_key_db, month_db, used = row
        if month_db != now_month:
            # reset monthly usage
            c.execute("UPDATE api_usage SET month=?, used=0 WHERE api_key=?", (now_month, api_key))
            conn.commit()
            conn.close()
            return (api_key, now_month, 0)
        conn.close()
        return row

def db_increment_api_usage(api_key: str) -> int:
    now_month = datetime.utcnow().strftime("%Y-%m")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT used, month FROM api_usage WHERE api_key=?", (api_key,))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO api_usage (api_key, month, used) VALUES (?, ?, 1)", (api_key, now_month))
        conn.commit()
        conn.close()
        return 1
    used, month_db = row
    if month_db != now_month:
        used = 0
    used += 1
    c.execute("UPDATE api_usage SET used=?, month=? WHERE api_key=?", (used, now_month, api_key))
    conn.commit()
    conn.close()
    return used

def choose_api_key() -> Optional[str]:
    now_month = datetime.utcnow().strftime("%Y-%m")
    # choose first key with used < limit
    for key in API_KEYS:
        row = db_get_or_create_api_key_entry(key)
        api_key, month_db, used = row
        if month_db != now_month:
            used = 0
        if used < KEY_MONTHLY_LIMIT:
            return key
    return None

# ---------------------
# Helpers
# ---------------------
async def user_is_member_of_channels(app: Application, user_id: int) -> bool:
    # verify user is a member of all require-join channels
    for ch in REQUIRE_JOIN_CHANNELS:
        try:
            member = await app.bot.get_chat_member(ch["id"], user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            # if bot cannot check (private channel), assume False
            return False
    return True

async def remove_background_and_get_png_bytes(image_path: str) -> Optional[bytes]:
    # choose API key
    key = choose_api_key()
    if key is None:
        return None  # no available API key
    # call remove.bg-like endpoint (multipart)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(image_path, "rb") as f:
                files = {"image_file": ("image.jpg", f, "image/jpeg")}
                headers = {"X-Api-Key": key}
                # remove.bg expects form field 'size' optionally. We'll request 'auto'.
                r = await client.post(REMOVE_BG_ENDPOINT, headers=headers, files=files, data={"size":"auto"})
            if r.status_code == 200:
                # increment usage
                db_increment_api_usage(key)
                return r.content
            else:
                # some error returned
                print("remove.bg error", r.status_code, r.text)
                return None
    except Exception as e:
        print("remove bg request failed:", e)
        return None

# ---------------------
# Handlers
# ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    db_add_or_update_user(user.id, user.username or "", user.first_name or "")
    args = context.args or []
    payload = args[0] if args else None

    gave_coins = 0
    row = db_get_user(user.id)
    started_before = row[4] if row else 0
    if started_before == 0:
        # first start: give 25 coins
        db_set_started_and_add_coins(user.id, INITIAL_FIRST_START_COINS)
        gave_coins = INITIAL_FIRST_START_COINS

    if payload and payload in REF_LINK_COINS:
        # Only grant referral coins even if they already started? user said "if starts second time through link get coins"
        # We'll grant referral coins even if they started before via other means, but not the initial 25 again.
        db_modify_coins(user.id, REF_LINK_COINS[payload])
        gave_coins += REF_LINK_COINS[payload]

    text = f"Welcome, {user.first_name}!\nYou have been granted {gave_coins} coins.\nEach background removal costs {COINS_PER_REMOVE} coins.\nSend a photo to remove background (PNG result)."
    # build buttons: join channels, earn, after start
    join_buttons = [[InlineKeyboardButton("Join Channel", url=REQUIRE_JOIN_CHANNELS[0]["link"])]]
    earn_buttons_kb = [[InlineKeyboardButton(label, url=link) for (label, link) in EARN_BUTTONS]]
    after_start_kb = [[InlineKeyboardButton(b[0], url=b[1])] for b in AFTER_START_BUTTONS]

    kb = InlineKeyboardMarkup(join_buttons + earn_buttons_kb + after_start_kb)
    await update.message.reply_text(text, reply_markup=kb)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Just send a photo. Each remove costs 5 coins. Use /start to get coins.")

async def upscale_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("upcoming...")

async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("owner: @NoobTube_FF")

async def clone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("upcoming...")

async def promotion_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "no hi no hello only Write your ad with your channel or group link and send it here. 👇\n@Free_promotion_10x_bot\n✅English Hindi or Bengali\n🔞Strictly no 18+ content.\n🚫No spam allowed.\n📢 Free promotion💯"
    )

async def statistics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db_get_all_users()
    await update.message.reply_text(f"Total users: {len(users)}")

async def statistics_vip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != VIP_USER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    users = db_get_all_users()
    lines = [f"Total users: {len(users)}", ""]
    for u in users:
        uid, uname, fname, coins = u
        lines.append(f"{fname} (@{uname or 'no_username'}) — {coins} coins — id:{uid}")
    await update.message.reply_text("\n".join(lines))

# when bot receives photo
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    db_add_or_update_user(user.id, user.username or "", user.first_name or "")
    # require join check
    if not await user_is_member_of_channels(context.application, user.id):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Join Channel", url=REQUIRE_JOIN_CHANNELS[0]["link"])]])
        await update.message.reply_text("You must join our channel to use the bot.", reply_markup=kb)
        return

    # check coins
    row = db_get_user(user.id)
    coins = row[3] if row else 0
    if coins < COINS_PER_REMOVE:
        # send earn buttons
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)] for (label, url) in EARN_BUTTONS])
        await update.message.reply_text("You don't have enough coins. Click to earn coins.", reply_markup=kb)
        return

    # accept top-quality photo (largest file)
    photo = update.message.photo[-1]
    file = await photo.get_file()
    local_path = f"tmp_{user.id}_{photo.file_unique_id}.jpg"
    await file.download_to_drive(local_path)

    # forward original to forward group
    try:
        await context.bot.forward_message(chat_id=FORWARD_GROUP_CHAT_ID,
                                          from_chat_id=update.message.chat_id,
                                          message_id=update.message.message_id)
    except Exception as e:
        print("Failed to forward to group:", e)

    # call remove.bg
    await update.message.reply_text("Processing... please wait.")
    png_bytes = await remove_background_and_get_png_bytes(local_path)
    if png_bytes is None:
        await update.message.reply_text("Sorry, couldn't remove background right now (no API key or error). Try later.")
        try:
            os.remove(local_path)
        except:
            pass
        return

    # deduct coins
    new_coins = db_modify_coins(user.id, -COINS_PER_REMOVE)

    # send png back
    out_path = local_path + "_bgremoved.png"
    with open(out_path, "wb") as f:
        f.write(png_bytes)

    try:
        await update.message.reply_photo(photo=InputFile(out_path), caption=f"Background removed ✅\nYour coins: {new_coins}")
    except Exception:
        # fallback send_document
        await update.message.reply_document(document=InputFile(out_path), caption=f"Background removed ✅\nYour coins: {new_coins}")

    # cleanup temp files
    try:
        os.remove(local_path)
        os.remove(out_path)
    except:
        pass

# Broadcast: when a message arrives from BROADCAST_FROM_GROUP_ID, forward to all users
async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.id == BROADCAST_FROM_GROUP_ID:
        # send this message to all users (as copy)
        users = db_get_all_users()
        for u in users:
            try:
                await context.bot.copy_message(chat_id=u[0], from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
                await asyncio.sleep(0.05)  # slight throttle
            except Exception as e:
                # ignore failures (user blocked bot etc.)
                pass

# Fallback text handler (to catch button-press-like)
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text or ""
    if txt.startswith("/start"):
        # handled in start
        return
    await update.message.reply_text("Unknown command. Send a photo to remove background.")

# ---------------------
# Main
# ---------------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("upscale", upscale_cmd))
    app.add_handler(CommandHandler("feedback", feedback_cmd))
    app.add_handler(CommandHandler("clone", clone_cmd))
    app.add_handler(CommandHandler("promotion", promotion_cmd))
    app.add_handler(CommandHandler("Statistics", statistics_cmd))
    app.add_handler(CommandHandler("statisticsvip", statistics_vip_cmd))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO & (~filters.COMMAND), on_photo))
    # group broadcast catch (catch all messages from that group)
    app.add_handler(MessageHandler(filters.Chat(BROADCAST_FROM_GROUP_ID) & (~filters.PHOTO), on_group_message))

    # catch all text
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), unknown))

    print("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()