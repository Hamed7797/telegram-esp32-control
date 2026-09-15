import os
import ssl
import logging
import time

import paho.mqtt.client as mqtt

from fastapi import FastAPI, Request, HTTPException

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
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

TELEGRAM_BOT_TOKEN = (
    "8814366440:AAH_KHZ2jkce9AyIISaKq0OJ9Wk2oY6aRXU"
)

# فعلاً 0 یعنی همه کاربران مجاز هستند.
# بعداً می‌توانی Chat ID خودت را اینجا قرار بدهی.
ALLOWED_CHAT_ID = "0"


# =========================================================
# HIVEMQ
# =========================================================

MQTT_HOST = (
    "c8f63357997a47a8b37f0495aac24c7d.s1.eu.hivemq.cloud"
)

MQTT_PORT = 8883

MQTT_USERNAME = "hamed_esp32"
MQTT_PASSWORD = "Ha00102030meD@"


# =========================================================
# MQTT TOPIC
# =========================================================

# همان Topic قبلی
MQTT_TOPIC = "hamed/esp32/led"


# =========================================================
# RENDER
# =========================================================

RENDER_URL = (
    "https://telegram-esp32-control.onrender.com"
)

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)

WEBHOOK_SECRET = "HamedESP32_2026_X9"


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI()

telegram_app = None


# =========================================================
# TEMPERATURE DATA
# =========================================================

latest_temperature = None

last_temperature_time = 0


# =========================================================
# TEMPERATURE TIMEOUT
# =========================================================

# اگر بیشتر از 30 ثانیه از آخرین دما گذشته باشد
# اطلاعات را قدیمی در نظر می‌گیریم.

TEMPERATURE_TIMEOUT = 30


# =========================================================
# TELEGRAM KEYBOARD
# =========================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [
            KeyboardButton("🟢 LED ON"),
            KeyboardButton("🔴 LED OFF"),
        ],
        [
            KeyboardButton("🌡 دمای فعلی"),
        ],
        [
            KeyboardButton("📊 وضعیت سیستم"),
        ],
    ],
    resize_keyboard=True,
    is_persistent=True,
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


    # =====================================================
    # Subscribe
    # =====================================================

    result = client.subscribe(
        MQTT_TOPIC,
        qos=1
    )


    if result[0] == mqtt.MQTT_ERR_SUCCESS:

        print(
            "Subscribed successfully:"
        )

        print(
            MQTT_TOPIC
        )

    else:

        print(
            "MQTT subscribe failed:"
        )

        print(
            result
        )


# =========================================================
# MQTT DISCONNECT
# =========================================================

def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties
):

    print(
        "MQTT disconnected"
    )

    print(
        f"Reason code: {reason_code}"
    )


# =========================================================
# MQTT MESSAGE
# =========================================================

def on_message(
    client,
    userdata,
    msg
):

    global latest_temperature
    global last_temperature_time


    try:

        message = (
            msg.payload
            .decode("utf-8")
            .strip()
        )

    except Exception as e:

        print(
            "MQTT decode error:"
        )

        print(e)

        return


    print("--------------------------------------")

    print(
        f"MQTT Topic: {msg.topic}"
    )

    print(
        f"MQTT Message: {message}"
    )

    print("--------------------------------------")


    # =====================================================
    # TEMPERATURE
    # =====================================================

    if message.startswith("TEMP:"):

        try:

            temperature_text = (
                message[5:]
            )

            temperature = float(
                temperature_text
            )

            latest_temperature = (
                temperature
            )

            last_temperature_time = (
                time.time()
            )

            print(
                f"Temperature received: "
                f"{temperature:.2f} C"
            )

        except ValueError:

            print(
                "Invalid temperature message:"
            )

            print(
                message
            )

        return


    # =====================================================
    # OTHER MQTT MESSAGES
    # =====================================================

    print(
        "MQTT message is not temperature."
    )


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

mqtt_client.on_message = on_message


# =========================================================
# CONNECT MQTT
# =========================================================

def connect_mqtt():

    print(
        "Connecting to HiveMQ..."
    )


    try:

        mqtt_client.connect(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=60
        )

        mqtt_client.loop_start()

        print(
            "MQTT connection started."
        )


    except Exception as e:

        print(
            "MQTT CONNECTION ERROR:"
        )

        print(e)


# =========================================================
# SECURITY
# =========================================================

def is_allowed(
    update: Update
) -> bool:

    if update.effective_chat is None:

        return False


    chat_id = str(
        update.effective_chat.id
    )


    if ALLOWED_CHAT_ID == "0":

        return True


    return (
        chat_id == ALLOWED_CHAT_ID
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


    chat_id = (
        update.effective_chat.id
    )


    print("--------------------------------------")

    print(
        f"Telegram Chat ID: {chat_id}"
    )

    print(
        "Command: /start"
    )

    print("--------------------------------------")


    await update.message.reply_text(
        "🤖 ESP32 Control Bot\n\n"
        "لطفاً یک گزینه را انتخاب کنید:",
        reply_markup=MAIN_KEYBOARD
    )


# =========================================================
# BUTTON MENU
# =========================================================

async def show_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎛 کنترل ESP32\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=MAIN_KEYBOARD
    )


# =========================================================
# SEND LED COMMAND
# =========================================================

async def send_led_command(
    update: Update,
    command: str,
    text: str
):

    if not mqtt_client.is_connected():

        await update.message.reply_text(
            "❌ اتصال MQTT برقرار نیست.",
            reply_markup=MAIN_KEYBOARD
        )

        return


    result = mqtt_client.publish(
        MQTT_TOPIC,
        command,
        qos=1
    )


    if result.rc == mqtt.MQTT_ERR_SUCCESS:

        if command == "ON":

            await update.message.reply_text(
                "🟢 LED روشن شد",
                reply_markup=MAIN_KEYBOARD
            )

            print(
                "MQTT -> ON"
            )

        else:

            await update.message.reply_text(
                "🔴 LED خاموش شد",
                reply_markup=MAIN_KEYBOARD
            )

            print(
                "MQTT -> OFF"
            )

    else:

        print(
            "MQTT publish failed:"
        )

        print(
            result.rc
        )

        await update.message.reply_text(
            "❌ ارسال فرمان انجام نشد.",
            reply_markup=MAIN_KEYBOARD
        )


# =========================================================
# SHOW TEMPERATURE
# =========================================================

async def show_temperature(
    update: Update
):

    # =====================================================
    # No temperature received yet
    # =====================================================

    if latest_temperature is None:

        await update.message.reply_text(
            "🌡 دمای فعلی\n\n"
            "❌ هنوز دمایی از ESP32 دریافت نشده است.\n\n"
            "لطفاً چند ثانیه صبر کنید و دوباره امتحان کنید.",
            reply_markup=MAIN_KEYBOARD
        )

        return


    # =====================================================
    # Temperature age
    # =====================================================

    age = (
        time.time()
        - last_temperature_time
    )


    # =====================================================
    # Old temperature
    # =====================================================

    if age > TEMPERATURE_TIMEOUT:

        await update.message.reply_text(
            "🌡 دمای فعلی\n\n"
            f"آخرین دمای دریافت‌شده:\n"
            f"🌡 {latest_temperature:.2f} °C\n\n"
            f"⚠️ این اطلاعات {int(age)} ثانیه قبل دریافت شده است.\n"
            "ممکن است ESP32 در حال حاضر متصل نباشد.",
            reply_markup=MAIN_KEYBOARD
        )

        return


    # =====================================================
    # Current temperature
    # =====================================================

    await update.message.reply_text(
        "🌡 دمای فعلی\n\n"
        f"🌡 {latest_temperature:.2f} °C\n\n"
        f"🟢 سنسور DS18B20 فعال است\n"
        f"📡 آخرین دریافت: {int(age)} ثانیه قبل",
        reply_markup=MAIN_KEYBOARD
    )


# =========================================================
# SYSTEM STATUS
# =========================================================

async def show_status(
    update: Update
):

    # =====================================================
    # MQTT
    # =====================================================

    if mqtt_client.is_connected():

        mqtt_status = "🟢 Connected"

    else:

        mqtt_status = "🔴 Disconnected"


    # =====================================================
    # Temperature
    # =====================================================

    if latest_temperature is None:

        temperature_status = (
            "❌ No data"
        )

    else:

        age = (
            time.time()
            - last_temperature_time
        )


        if age <= TEMPERATURE_TIMEOUT:

            temperature_status = (
                f"🟢 {latest_temperature:.2f} °C"
            )

        else:

            temperature_status = (
                f"🟡 {latest_temperature:.2f} °C "
                f"(old data)"
            )


    # =====================================================
    # Telegram response
    # =====================================================

    await update.message.reply_text(

        "📊 وضعیت سیستم\n\n"

        f"MQTT: {mqtt_status}\n"

        f"🌡 دما: {temperature_status}\n"

        f"📡 Topic:\n"
        f"{MQTT_TOPIC}\n\n"

        "ESP32 + DS18B20\n"
        "GPIO 23: Temperature\n"
        "GPIO 2: LED",

        reply_markup=MAIN_KEYBOARD
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


    chat_id = (
        update.effective_chat.id
    )


    text = (
        update.message.text
        .strip()
        .lower()
    )


    print("--------------------------------------")

    print(
        f"Telegram Chat ID: {chat_id}"
    )

    print(
        f"Message: {text}"
    )

    print("--------------------------------------")


    # =====================================================
    # SECURITY
    # =====================================================

    if not is_allowed(update):

        print(
            "Unauthorized Telegram user."
        )

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return


    # =====================================================
    # LED ON
    # =====================================================

    if text in (
        "🟢 led on",
        "led on"
    ):

        await send_led_command(
            update,
            "ON",
            text
        )

        return


    # =====================================================
    # LED OFF
    # =====================================================

    if text in (
        "🔴 led off",
        "led off"
    ):

        await send_led_command(
            update,
            "OFF",
            text
        )

        return


    # =====================================================
    # TEMPERATURE
    # =====================================================

    if text in (
        "🌡 دمای فعلی",
        "دمای فعلی",
        "temperature"
    ):

        await show_temperature(
            update
        )

        return


    # =====================================================
    # STATUS
    # =====================================================

    if text in (
        "📊 وضعیت سیستم",
        "وضعیت سیستم",
        "status"
    ):

        await show_status(
            update
        )

        return


    # =====================================================
    # MENU
    # =====================================================

    if text in (
        "menu",
        "منو"
    ):

        await show_menu(
            update,
            context
        )

        return


    # =====================================================
    # UNKNOWN
    # =====================================================

    await update.message.reply_text(

        "❓ دستور نامعتبر است.\n\n"
        "لطفاً یکی از گزینه‌های منو را انتخاب کنید.",

        reply_markup=MAIN_KEYBOARD
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

    received_secret = (
        request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )
    )


    if received_secret != WEBHOOK_SECRET:

        print(
            "Invalid webhook secret."
        )

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

        print(
            "Webhook error:"
        )

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

    print(
        "     TELEGRAM ESP32 RENDER BOT"
    )

    print("======================================")


    # =====================================================
    # MQTT
    # =====================================================

    connect_mqtt()


    # =====================================================
    # Telegram Application
    # =====================================================

    telegram_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .updater(None)
        .build()
    )


    # =====================================================
    # Telegram Handlers
    # =====================================================

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


    # =====================================================
    # Initialize
    # =====================================================

    await telegram_app.initialize()

    await telegram_app.start()


    # =====================================================
    # Set Webhook
    # =====================================================

    webhook_url = (
        RENDER_URL
        + "/telegram"
    )


    print("")

    print(
        "Setting Telegram webhook..."
    )

    print(
        webhook_url
    )


    await telegram_app.bot.set_webhook(

        url=webhook_url,

        secret_token=WEBHOOK_SECRET,

        allowed_updates=Update.ALL_TYPES
    )


    print("")

    print(
        "Telegram webhook configured."
    )

    print(
        "Bot is ready."
    )

    print("")


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown_event():

    print(
        "Stopping bot..."
    )


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
