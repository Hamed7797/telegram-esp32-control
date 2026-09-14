
import os
import ssl
import asyncio
import logging

import paho.mqtt.client as mqtt

from flask import Flask, request, Response
from asgiref.wsgi import WsgiToAsgi
import uvicorn

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID", "0")

MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))

MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

MQTT_TOPIC_LED = os.getenv(
    "MQTT_TOPIC_LED",
    "hamed/esp32/led"
)

# Render automatically provides this
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

# Render automatically provides PORT
PORT = int(os.getenv("PORT", "10000"))

# Optional webhook secret
WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "telegram_esp32_secret"
)

# =========================================================
# CHECK CONFIGURATION
# =========================================================

required_variables = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "MQTT_HOST": MQTT_HOST,
    "MQTT_USERNAME": MQTT_USERNAME,
    "MQTT_PASSWORD": MQTT_PASSWORD,
}

missing = [
    name
    for name, value in required_variables.items()
    if not value
]

if missing:
    raise RuntimeError(
        "Missing environment variables: "
        + ", ".join(missing)
    )

if not RENDER_EXTERNAL_URL:
    raise RuntimeError(
        "RENDER_EXTERNAL_URL is not available."
    )

# =========================================================
# MQTT CALLBACKS
# =========================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties
):
    print("======================================")
    print("MQTT STATUS")
    print("Connected to HiveMQ")
    print(f"Reason code: {reason_code}")
    print("======================================")


def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties
):
    print("MQTT disconnected")
    print(f"Reason code: {reason_code}")


# =========================================================
# MQTT CLIENT
# =========================================================

mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="Telegram_ESP32_Render"
)

mqtt_client.username_pw_set(
    MQTT_USERNAME,
    MQTT_PASSWORD
)

mqtt_client.tls_set(
    cert_reqs=ssl.CERT_REQUIRED,
    tls_version=ssl.PROTOCOL_TLS_CLIENT
)

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect


# =========================================================
# CONNECT MQTT
# =========================================================

print("Connecting to HiveMQ...")

try:
    mqtt_client.connect(
        MQTT_HOST,
        MQTT_PORT,
        keepalive=60
    )

    mqtt_client.loop_start()

except Exception as e:
    print("MQTT CONNECTION ERROR:")
    print(e)


# =========================================================
# SECURITY
# =========================================================

def is_allowed(update: Update) -> bool:

    if update.effective_chat is None:
        return False

    chat_id = str(update.effective_chat.id)

    # فقط برای تست اولیه
    if ALLOWED_CHAT_ID == "0":
        return True

    return chat_id == ALLOWED_CHAT_ID


# =========================================================
# /start
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    print(f"Telegram Chat ID: {chat_id}")

    await update.message.reply_text(
        "🤖 ESP32 Control Bot\n\n"
        "دستورهای قابل استفاده:\n\n"
        "led on\n"
        "led off\n"
        "status"
    )


# =========================================================
# TEXT MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id

    text = update.message.text.strip().lower()

    print("--------------------------------------")
    print(f"Telegram Chat ID: {chat_id}")
    print(f"Message: {text}")
    print("--------------------------------------")

    # -----------------------------------------------------
    # Security
    # -----------------------------------------------------

    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return

    # -----------------------------------------------------
    # LED ON
    # -----------------------------------------------------

    if text == "led on":

        result = mqtt_client.publish(
            MQTT_TOPIC_LED,
            "ON",
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            print("MQTT -> ON")

            await update.message.reply_text(
                "🟢 LED روشن شد"
            )

        else:

            print(
                "MQTT publish failed:",
                result.rc
            )

            await update.message.reply_text(
                "❌ ارسال فرمان MQTT انجام نشد."
            )

    # -----------------------------------------------------
    # LED OFF
    # -----------------------------------------------------

    elif text == "led off":

        result = mqtt_client.publish(
            MQTT_TOPIC_LED,
            "OFF",
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            print("MQTT -> OFF")

            await update.message.reply_text(
                "🔴 LED خاموش شد"
            )

        else:

            print(
                "MQTT publish failed:",
                result.rc
            )

            await update.message.reply_text(
                "❌ ارسال فرمان MQTT انجام نشد."
            )

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    elif text == "status":

        try:

            mqtt_status = (
                "connected"
                if mqtt_client.is_connected()
                else "disconnected"
            )

            await update.message.reply_text(
                f"🤖 ESP32 Control\n\n"
                f"MQTT: {mqtt_status}\n"
                f"Topic: {MQTT_TOPIC_LED}"
            )

        except Exception:

            await update.message.reply_text(
                "⚠️ دریافت وضعیت انجام نشد."
            )

    # -----------------------------------------------------
    # INVALID COMMAND
    # -----------------------------------------------------

    else:

        await update.message.reply_text(
            "❓ دستور نامعتبر است.\n\n"
            "دستورهای مجاز:\n"
            "led on\n"
            "led off\n"
            "status"
        )


# =========================================================
# FLASK APP
# =========================================================

flask_app = Flask(__name__)


# =========================================================
# HEALTH CHECK
# =========================================================

@flask_app.get("/")
def home():

    return Response(
        "Telegram ESP32 Bot is running.",
        status=200,
        mimetype="text/plain"
    )


@flask_app.get("/health")
def health():

    return Response(
        "OK",
        status=200,
        mimetype="text/plain"
    )


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

telegram_app = None


@flask_app.post("/telegram")
async def telegram_webhook():

    # امنیت Webhook
    received_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if received_secret != WEBHOOK_SECRET:

        return Response(
            "Unauthorized",
            status=401
        )

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return Response(
                "Bad Request",
                status=400
            )

        update = Update.de_json(
            data=data,
            bot=telegram_app.bot
        )

        await telegram_app.update_queue.put(
            update
        )

        return Response(
            "OK",
            status=200
        )

    except Exception as e:

        print("Webhook processing error:")
        print(e)

        return Response(
            "Error",
            status=500
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    global telegram_app

    print("")
    print("======================================")
    print("   TELEGRAM ESP32 RENDER BOT")
    print("======================================")

    # -----------------------------------------------------
    # Telegram Application
    # -----------------------------------------------------

    telegram_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .updater(None)
        .build()
    )

    # -----------------------------------------------------
    # Handlers
    # -----------------------------------------------------

    telegram_app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    # -----------------------------------------------------
    # Initialize
    # -----------------------------------------------------

    await telegram_app.initialize()

    await telegram_app.start()

    # -----------------------------------------------------
    # Webhook URL
    # -----------------------------------------------------

    webhook_url = (
        RENDER_EXTERNAL_URL
        + "/telegram"
    )

    print("")
    print("Setting Telegram webhook...")
    print(webhook_url)

    await telegram_app.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES
    )

    print("")
    print("Telegram webhook configured.")
    print("Render URL:")
    print(RENDER_EXTERNAL_URL)
    print("")
    print("Bot is ready.")
    print("")


    # -----------------------------------------------------
    # Run Flask through Uvicorn
    # -----------------------------------------------------

    asgi_app = WsgiToAsgi(
        flask_app
    )

    config = uvicorn.Config(
        asgi_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )

    server = uvicorn.Server(config)

    try:

        await server.serve()

    finally:

        await telegram_app.stop()
        await telegram_app.shutdown()

        mqtt_client.loop_stop()
        mqtt_client.disconnect()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print("Bot stopped.")

