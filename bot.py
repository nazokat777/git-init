"""
╔══════════════════════════════════════════════════════════════════╗
║         INSTAGRAM LEAD BRIDGE BOT — v1.0                        ║
║         Barcha narsa bitta faylda: kod + sozlamalar + qo'llanma  ║
╚══════════════════════════════════════════════════════════════════╝

ISHLATISH:
  1. pip install python-telegram-bot flask requests python-dotenv
  2. Quyidagi SOZLAMALAR bo'limini to'ldiring
  3. python bot_all_in_one.py

STACK: Python 3.10+ | python-telegram-bot 21.x | Flask | Requests
"""

# ══════════════════════════════════════════════════════════════════
#  O'RNATISH QO'LLANMASI (BOSQICHMA-BOSQICH)
# ══════════════════════════════════════════════════════════════════
#
#  1-QADAM: TELEGRAM BOT YARATISH
#  ────────────────────────────────
#  → Telegramda @BotFather ga yozing
#  → /newbot → nom bering → username bering
#  → Token nusxalang → TELEGRAM_BOT_TOKEN ga qo'ying
#
#  2-QADAM: TELEGRAM GURUH SOZLASH
#  ────────────────────────────────
#  → Yangi guruh yarating: "Lumnaara Leads"
#  → Botni guruhga admin qilib qo'shing
#  → Guruh ID olish: @userinfobot ga guruhni forward qiling
#  → ID ni TELEGRAM_GROUP_ID ga kiriting (manfiy son: -1001234567890)
#
#  3-QADAM: MANYCHAT SOZLASH
#  ────────────────────────────────
#  → manychat.com → Instagram akkauntni ulang
#  → Settings > API → token oling → MANYCHAT_API_TOKEN ga qo'ying
#  → Flow Builder → Yangi flow:
#      Trigger: "Comment contains +"
#      Action: Webhook POST → https://sizserver.com/webhook/manychat
#      Headers: X-Secret-Token: (WEBHOOK_SECRET qiymati)
#      Body JSON:
#        {
#          "username":      "{{first name}}",
#          "message":       "{{last comment}}",
#          "subscriber_id": "{{subscriber id}}",
#          "channel":       "comment"
#        }
#  → DM uchun alohida flow (bir xil, faqat "channel": "dm")
#
#  4-QADAM: SERVERGA DEPLOY (Railway — bepul)
#  ────────────────────────────────
#  → railway.app → New Project → GitHub repo ulang
#  → Environment Variables qo'ying (quyidagi SOZLAMALAR)
#  → Deploy → URL oling → SERVER_URL ga kiriting
#
#  5-QADAM: TEST (terminal)
#  ────────────────────────────────
#  curl -X POST https://sizserver.com/webhook/manychat \
#    -H "Content-Type: application/json" \
#    -H "X-Secret-Token: WEBHOOK_SECRET_qiymatingiz" \
#    -d '{"username":"test","message":"Narx?","subscriber_id":"123","channel":"dm"}'
#
# ══════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════
#  SOZLAMALAR — SHU YERNI TO'LDIRING
# ══════════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN  = "8762418382:AAEg1zlIyFBSTOm7HUXgBRzTazWUCLUjZMk"       # BotFather dan
TELEGRAM_GROUP_ID   = -1003943264155                # Guruh ID (manfiy son!)
MANYCHAT_API_TOKEN  = "4842073:0c410c55cb1523e43eb9513dda8d1cf5"        # ManyChat > Settings > API
WEBHOOK_SECRET      = "lumnaara3" # Istalgan murakkab so'z
SERVER_URL          = "https://sizning-server.com"   # Railway/Render manzili
PORT                = 8000                           # Flask port

# ══════════════════════════════════════════════════════════════════
#  KUTUBXONALAR
# ══════════════════════════════════════════════════════════════════

import os
import asyncio
import logging
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  XOTIRA (In-Memory — restart qilsa tozalanadi)
#  Doimiy saqlash uchun SQLite yoki Redis ga almashtiring
# ══════════════════════════════════════════════════════════════════

# { telegram_message_id: lead_dict }
lead_map: dict = {}

# Duplicate filter: { "username:xabar": unix_timestamp }
recent_messages: dict = {}
DUPLICATE_WINDOW_SEC = 60  # bir xil xabar 60 soniyada 1 marta o'tadi


# ══════════════════════════════════════════════════════════════════
#  MANYCHAT: INSTAGRAM DM YUBORISH
# ══════════════════════════════════════════════════════════════════

def send_ig_dm(subscriber_id: str, text: str) -> bool:
    """
    ManyChat API orqali leadga Instagram DM yuboradi.
    subscriber_id — ManyChat {{subscriber id}} o'zgaruvchisi.
    """
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
        logger.info(f"DM yuborildi → subscriber_id={subscriber_id}")
        return True
    except Exception as e:
        logger.error(f"ManyChat xatosi: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
#  TELEGRAM: GURUHGA FORMATLANGAN XABAR YUBORISH
# ══════════════════════════════════════════════════════════════════

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_to_group(lead: dict) -> int:
    """
    Telegram guruhga SRS formatida lead xabarini yuboradi.
    Qaytadi: yuborilgan xabarning message_id si.
    """
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
    return sent.message_id


# ══════════════════════════════════════════════════════════════════
#  FLASK: MANYCHAT WEBHOOK SERVER
# ══════════════════════════════════════════════════════════════════

app_flask = Flask(__name__)

@app_flask.route("/webhook/manychat", methods=["POST"])
def manychat_webhook():
    """
    ManyChat bu endpoint ga POST yuboradi.
    Har bir Instagram lead (DM yoki Izoh+) shu yerga keladi.
    """
    # 1. Secret token xavfsizlik tekshiruvi
    token = request.headers.get("X-Secret-Token", "")
    if token != WEBHOOK_SECRET:
        logger.warning("Webhook: noto'g'ri secret token")
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Bo'sh so'rov"}), 400

    username      = data.get("username", "unknown")
    message       = data.get("message", "")
    subscriber_id = data.get("subscriber_id", "")
    channel       = data.get("channel", "dm")   # "comment" yoki "dm"
    ts            = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 2. Duplicate filter
    dup_key  = f"{username}:{message}"
    now_unix = datetime.now().timestamp()
    if dup_key in recent_messages:
        if now_unix - recent_messages[dup_key] < DUPLICATE_WINDOW_SEC:
            logger.info(f"Duplicate bloklandi: @{username}")
            return jsonify({"status": "duplicate_skipped"}), 200
    recent_messages[dup_key] = now_unix

    lead = {
        "username":      username,
        "message":       message,
        "subscriber_id": subscriber_id,
        "channel":       channel,
        "ts":            ts,
        "replied":       False
    }

    # 3. Telegram guruhga yuborish (async → sync ko'prik)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        msg_id = loop.run_until_complete(send_to_group(lead))
    finally:
        loop.close()

    # 4. lead_map ga saqlash
    lead_map[msg_id] = lead
    logger.info(f"Lead saqlandi → msg_id={msg_id}, @{username}, kanal={channel}")

    # 5. Izoh (+) bo'lsa — darhol avtomatik DM
    if channel == "comment" and subscriber_id:
        send_ig_dm(
            subscriber_id,
            "Salom! 👋 Xabaringizni oldik, tez orada bog'lanamiz."
        )

    return jsonify({"status": "ok", "telegram_message_id": msg_id}), 200


@app_flask.route("/health", methods=["GET"])
def health():
    """Server ishlayotganini tekshirish uchun (Railway monitoring)."""
    return jsonify({
        "status": "ok",
        "leads_in_memory": len(lead_map),
        "uptime": "running"
    })


# ══════════════════════════════════════════════════════════════════
#  TELEGRAM BOT: OPERATOR REPLY → INSTAGRAM DM
# ══════════════════════════════════════════════════════════════════

async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Operator Telegram guruhda bot xabariga Reply qilganda ishga tushadi.
    Javobni ManyChat orqali leadning Instagram DM iga yetkazadi.
    """
    msg = update.message
    if not msg:
        return

    # Faqat belgilangan guruhdan
    if msg.chat_id != TELEGRAM_GROUP_ID:
        return

    # Reply bo'lmasa — ignore
    if not msg.reply_to_message:
        return

    replied_msg_id = msg.reply_to_message.message_id
    operator_text  = msg.text or ""

    # Bot o'z xabarlariga qilingan Reply larni ushlab oladi
    replied_from = msg.reply_to_message.from_user
    if not (replied_from and replied_from.is_bot):
        return  # Boshqa guruh xabarlariga Reply — ignore

    # Lead topish
    lead = lead_map.get(replied_msg_id)
    if not lead:
        await msg.reply_text("⚠️ Bu lead ma'lumotlari topilmadi (restart bo'lgandir).")
        return

    subscriber_id = lead.get("subscriber_id", "")
    username      = lead.get("username", "?")

    if not subscriber_id:
        await msg.reply_text(f"⚠️ @{username} uchun subscriber_id topilmadi.")
        return

    # ManyChat orqali Instagram DM yuborish
    success = send_ig_dm(subscriber_id, operator_text)

    if success:
        lead["replied"] = True
        await msg.reply_text(f"✅ Javob @{username} ga yetkazildi.")
        logger.info(f"Operator javob yubordi → @{username}")
    else:
        await msg.reply_text(
            f"❌ @{username} ga yuborib bo'lmadi.\n"
            f"Sabab: lead DM ni o'chirgan yoki akkaunt o'chirilgan."
        )


# ══════════════════════════════════════════════════════════════════
#  ASOSIY ISHGA TUSHIRISH
# ══════════════════════════════════════════════════════════════════

def run_flask():
    """Flask webhook server — alohida threadda ishlaydi."""
    logger.info(f"Flask webhook server port {PORT} da ishga tushdi")
    app_flask.run(host="0.0.0.0", port=PORT, use_reloader=False)


def run_telegram_bot():
    """Telegram bot — webhook rejimida ishlaydi."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Faqat Reply xabarlarni ushlab oladi
    application.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY, handle_reply)
    )

    webhook_path = f"/telegram/{TELEGRAM_BOT_TOKEN}"
    logger.info(f"Telegram bot webhook: {SERVER_URL}{webhook_path}")

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT + 1,
        url_path=webhook_path,
        webhook_url=f"{SERVER_URL}{webhook_path}"
    )


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  Instagram Lead Bridge Bot ishga tushmoqda...")
    logger.info(f"  Guruh ID : {TELEGRAM_GROUP_ID}")
    logger.info(f"  Server   : {SERVER_URL}")
    logger.info("=" * 60)

    # Flask alohida threadda
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Telegram bot asosiy threadda
    run_telegram_bot()