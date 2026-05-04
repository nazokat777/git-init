"""
Instagram Lead Bridge Bot v1.1
Polling rejimi — Railway uchun eng oson
"""

import os
import asyncio
import logging
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ══════════════════════════════════════════
# SOZLAMALAR
# ══════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID  = int(os.environ.get("TELEGRAM_GROUP_ID", "0"))
MANYCHAT_API_TOKEN = os.environ.get("MANYCHAT_API_TOKEN", "")
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "secret")
PORT               = int(os.environ.get("PORT", "8000"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
# XOTIRA
# ══════════════════════════════════════════
lead_map = {}
recent_messages = {}
DUPLICATE_WINDOW = 60

# ══════════════════════════════════════════
# MANYCHAT: DM YUBORISH
# ══════════════════════════════════════════
def send_ig_dm(subscriber_id: str, text: str) -> bool:
    url = "https://api.manychat.com/fb/sending/sendContent"
    headers = {
        "Authorization": f"Bearer {MANYCHAT_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "subscriber_id": subscriber_id,
        "data": {
            "version": "v2",
            "content": {
                "messages": [{"type": "text", "text": text}]
            }
        },
        "message_tag": "ACCOUNT_UPDATE"
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"ManyChat xatosi: {e}")
        return False

# ══════════════════════════════════════════
# TELEGRAM: GURUHGA XABAR YUBORISH
# ══════════════════════════════════════════
async def send_to_group_async(lead: dict) -> int:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    kanal = "Izoh (+)" if lead.get("channel") == "comment" else "Instagram DM"
    ts    = lead.get("ts", datetime.now().strftime("%Y-%m-%d %H:%M"))
    text = (
        f"📩 *Yangi Lead*\n"
        f"─────────────────────────\n"
        f"👤 Foydalanuvchi: @{lead['username']}\n"
        f"📌 Kanal: {kanal}\n"
        f"🕐 Vaqt: {ts}\n"
        f"─────────────────────────\n"
        f"💬 Xabar:\n_{lead['message']}_\n"
        f"─────────────────────────\n"
        f"↩️ Javob berish uchun shu xabarni *REPLY* qiling"
    )
    sent = await bot.send_message(
        chat_id=TELEGRAM_GROUP_ID,
        text=text,
        parse_mode="Markdown"
    )
    await bot.close()
    return sent.message_id

def send_to_group(lead: dict) -> int:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(send_to_group_async(lead))
    finally:
        loop.close()

# ══════════════════════════════════════════
# FLASK: WEBHOOK SERVER
# ══════════════════════════════════════════
app_flask = Flask(__name__)

@app_flask.route("/webhook/manychat", methods=["POST"])
def manychat_webhook():
    token = request.headers.get("X-Secret-Token", "")
    if token != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Bo'sh so'rov"}), 400

    username      = data.get("username", "unknown")
    message       = data.get("message", "")
    subscriber_id = data.get("subscriber_id", "")
    channel       = data.get("channel", "dm")
    ts            = datetime.now().strftime("%Y-%m-%d %H:%M")

    dup_key  = f"{username}:{message}"
    now_unix = datetime.now().timestamp()
    if dup_key in recent_messages:
        if now_unix - recent_messages[dup_key] < DUPLICATE_WINDOW:
            return jsonify({"status": "duplicate_skipped"}), 200
    recent_messages[dup_key] = now_unix

    lead = {
        "username": username, "message": message,
        "subscriber_id": subscriber_id,
        "channel": channel, "ts": ts
    }

    try:
        msg_id = send_to_group(lead)
        lead_map[msg_id] = lead
        logger.info(f"Lead saqlandi → msg_id={msg_id}, @{username}")
    except Exception as e:
        logger.error(f"Guruhga yuborishda xato: {e}")
        return jsonify({"error": str(e)}), 500

    if channel == "comment" and subscriber_id:
        send_ig_dm(subscriber_id, "Salom! Xabaringizni oldik, tez orada bog'lanamiz. 😊")

    return jsonify({"status": "ok", "telegram_message_id": msg_id}), 200

@app_flask.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "leads": len(lead_map)})

# ══════════════════════════════════════════
# TELEGRAM BOT: OPERATOR REPLY (POLLING)
# ══════════════════════════════════════════
async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat_id != TELEGRAM_GROUP_ID:
        return
    if not msg.reply_to_message:
        return

    replied_from = msg.reply_to_message.from_user
    if not (replied_from and replied_from.is_bot):
        return

    lead = lead_map.get(msg.reply_to_message.message_id)
    if not lead:
        await msg.reply_text("⚠️ Lead topilmadi.")
        return

    success = send_ig_dm(lead.get("subscriber_id", ""), msg.text or "")
    if success:
        await msg.reply_text(f"✅ Javob @{lead['username']} ga yetkazildi.")
    else:
        await msg.reply_text(f"❌ @{lead['username']} ga yuborib bo'lmadi.")

def run_bot_polling():
    """Polling rejimi — webhook kerak emas."""
    async def main():
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & filters.REPLY, handle_reply))
        logger.info("Bot polling rejimida ishga tushdi")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # To'xtatmasdan ishlaydi
        await asyncio.Event().wait()

    asyncio.run(main())

# ══════════════════════════════════════════
# ASOSIY
# ══════════════════════════════════════════
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Instagram Lead Bridge Bot ishga tushmoqda...")
    logger.info("=" * 50)

    # Telegram bot — alohida threadda (polling)
    bot_thread = threading.Thread(target=run_bot_polling, daemon=True)
    bot_thread.start()

    # Flask — asosiy threadda
    logger.info(f"Flask port {PORT} da ishga tushdi")
    app_flask.run(host="0.0.0.0", port=PORT, use_reloader=False)
