
import os
import ssl
import logging

import paho.mqtt.client as mqtt

from fastapi import FastAPI, Request, HTTPException

from telegram import (
    Update,
    ReplyKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import uvicorn


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = "8814366440:AAH_KHZ2jkce9AyIISaKq0OJ9Wk2oY6aRXU"

# فعلاً 0 یعنی همه کاربران مجاز هستند
# بعداً Chat ID خودت را اینجا قرار بده
ALLOWED_CHAT_ID = "0"


# =========================================================
# HIVEMQ
# =========================================================

MQTT_HOST = "c8f63357997a47a8b37f0495aac24c7d.s1.eu.hivemq.cloud"
MQTT_PORT = 8883

MQTT_USERNAME = "hamed_esp32"
MQTT_PASSWORD = "Ha00102030meD@"

MQTT_TOPIC_LED = "hamed/esp32/led"


# =========================================================
# RENDER
# =========================================================

RENDER_URL = "https://telegram-esp32-control.onrender.com"

PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_SECRET = "HamedESP32_2026_X9"


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI()

telegram_app = None


# =========================================================
# REPLY KEYBOARD
# =========================================================

def create_main_keyboard():

    keyboard = [
        ["🟢 LED ON", "🔴 LED OFF"],
        ["📊 STATUS"]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )


# =========================================================
# MQTT CALLBACK
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
# MQTT CONNECT
# =========================================================

def connect_mqtt():

    print("Connecting to HiveMQ...")

    try:

        mqtt_client.connect(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=60
        )

        mqtt_client.loop_start()

        print("MQTT connection started.")

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

    if ALLOWED_CHAT_ID == "0":
        return True

    return chat_id == ALLOWED_CHAT_ID


# =========================================================
# SEND LED COMMAND
# =========================================================

async def send_led_command(
    update: Update,
    command: str
):

    if not update.message:
        return

    if not mqtt_client.is_connected():

        await update.message.reply_text(
            "❌ اتصال MQTT برقرار نیست.",
            reply_markup=create_main_keyboard()
        )

        return


    result = mqtt_client.publish(
        MQTT_TOPIC_LED,
        command,
        qos=1
    )


    if result.rc != mqtt.MQTT_ERR_SUCCESS:

        print(
            "MQTT publish failed:",
            result.rc
        )

        await update.message.reply_text(
            "❌ ارسال فرمان انجام نشد.",
            reply_markup=create_main_keyboard()
        )

        return


    # -----------------------------------------------------
    # ON
    # -----------------------------------------------------

    if command == "ON":

        print("MQTT -> ON")

        await update.message.reply_text(
            "🟢 LED روشن شد",
            reply_markup=create_main_keyboard()
        )


    # -----------------------------------------------------
    # OFF
    # -----------------------------------------------------

    elif command == "OFF":

        print("MQTT -> OFF")

        await update.message.reply_text(
            "🔴 LED خاموش شد",
            reply_markup=create_main_keyboard()
        )


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    if not update.message:
        return

    chat_id = update.effective_chat.id

    print("--------------------------------------")
    print(f"Telegram Chat ID: {chat_id}")
    print("Command: /start")
    print("--------------------------------------")


    # -----------------------------------------------------
    # SECURITY
    # -----------------------------------------------------

    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return


    # -----------------------------------------------------
    # MAIN MENU
    # -----------------------------------------------------

    await update.message.reply_text(
        "🤖 ESP32 Control Bot\n\n"
        "لطفاً یک گزینه را انتخاب کنید:",
        reply_markup=create_main_keyboard()
    )


# =========================================================
# /LED_ON
# =========================================================

async def led_on_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_allowed(update):

        if update.message:
            await update.message.reply_text(
                "⛔ شما اجازه کنترل این دستگاه را ندارید."
            )

        return


    await send_led_command(
        update,
        "ON"
    )


# =========================================================
# /LED_OFF
# =========================================================

async def led_off_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_allowed(update):

        if update.message:
            await update.message.reply_text(
                "⛔ شما اجازه کنترل این دستگاه را ندارید."
            )

        return


    await send_led_command(
        update,
        "OFF"
    )


# =========================================================
# /STATUS
# =========================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return


    mqtt_state = (
        "🟢 Connected"
        if mqtt_client.is_connected()
        else "🔴 Disconnected"
    )


    await update.message.reply_text(
        "🤖 ESP32 Control\n\n"
        f"MQTT: {mqtt_state}\n"
        f"Topic: {MQTT_TOPIC_LED}",
        reply_markup=create_main_keyboard()
    )


# =========================================================
# TEXT MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    if not update.message:
        return


    chat_id = update.effective_chat.id

    text = update.message.text.strip().lower()


    print("--------------------------------------")
    print(f"Telegram Chat ID: {chat_id}")
    print(f"Message: {text}")
    print("--------------------------------------")


    # -----------------------------------------------------
    # SECURITY
    # -----------------------------------------------------

    if not is_allowed(update):

        print("Unauthorized Telegram user.")

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return


    # -----------------------------------------------------
    # LED ON
    # -----------------------------------------------------

    if text == "led on" or text == "🟢 led on":

        await send_led_command(
            update,
            "ON"
        )

        return


    # -----------------------------------------------------
    # LED OFF
    # -----------------------------------------------------

    if text == "led off" or text == "🔴 led off":

        await send_led_command(
            update,
            "OFF"
        )

        return


    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if text == "status" or text == "📊 status":

        mqtt_state = (
            "🟢 Connected"
            if mqtt_client.is_connected()
            else "🔴 Disconnected"
        )


        await update.message.reply_text(
            "🤖 ESP32 Control\n\n"
            f"MQTT: {mqtt_state}\n"
            f"Topic: {MQTT_TOPIC_LED}",
            reply_markup=create_main_keyboard()
        )

        return


    # -----------------------------------------------------
    # UNKNOWN COMMAND
    # -----------------------------------------------------

    await update.message.reply_text(
        "❓ دستور نامعتبر است.\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید.",
        reply_markup=create_main_keyboard()
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/")
async def root():

    return {
        "status": "online",
        "service": "Telegram ESP32 Bot"
    }


@app.get("/health")
async def health():

    return {
        "status": "ok"
    }


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

@app.post("/telegram")
async def telegram_webhook(
    request: Request
):

    received_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )


    if received_secret != WEBHOOK_SECRET:

        print("Invalid webhook secret.")

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )


    try:

        data = await request.json()


        update = Update.de_json(
            data,
            telegram_app.bot
        )


        await telegram_app.update_queue.put(
            update
        )


        return {
            "ok": True
        }


    except Exception as e:

        print("Webhook error:")
        print(e)

        raise HTTPException(
            status_code=500,
            detail="Webhook error"
        )


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup_event():

    global telegram_app


    print("")
    print("======================================")
    print("     TELEGRAM ESP32 RENDER BOT")
    print("======================================")


    # -----------------------------------------------------
    # MQTT
    # -----------------------------------------------------

    connect_mqtt()


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
    # COMMAND HANDLERS
    # -----------------------------------------------------

    telegram_app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )


    telegram_app.add_handler(
        CommandHandler(
            "led_on",
            led_on_command
        )
    )


    telegram_app.add_handler(
        CommandHandler(
            "led_off",
            led_off_command
        )
    )


    telegram_app.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )


    # -----------------------------------------------------
    # TEXT HANDLER
    # -----------------------------------------------------

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )


    # -----------------------------------------------------
    # Initialize Telegram
    # -----------------------------------------------------

    await telegram_app.initialize()

    await telegram_app.start()


    # -----------------------------------------------------
    # Set Telegram Webhook
    # -----------------------------------------------------

    webhook_url = RENDER_URL + "/telegram"


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
    print("Bot is ready.")
    print("")


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown_event():

    print("Stopping bot...")


    if telegram_app:

        await telegram_app.stop()
        await telegram_app.shutdown()


    mqtt_client.loop_stop()
    mqtt_client.disconnect()


# =========================================================
# LOCAL START
# =========================================================

if __name__ == "__main__":

    uvicorn.run(
        "telegram_mqtt:app",
        host="0.0.0.0",
        port=PORT
    )
