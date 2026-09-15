import os
import ssl
import asyncio
import logging
import csv
from datetime import datetime

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

TELEGRAM_BOT_TOKEN = (
    "8814366440:AAH_KHZ2jkce9AyIISaKq0OJ9Wk2oY6aRXU"
)

# فعلاً 0 یعنی همه کاربران مجاز هستند
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

# فعلاً همان Topic فعلی
# بعداً می‌توانیم دما را به Topic جدا منتقل کنیم.
MQTT_TOPIC = "hamed/esp32/led"


# =========================================================
# RENDER
# =========================================================

RENDER_URL = "https://telegram-esp32-control.onrender.com"

PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_SECRET = "HamedESP32_2026_X9"


# =========================================================
# TEMPERATURE LOGGER
# =========================================================

TEMPERATURE_FILE = "temperature_log.csv"

# هر چند ثانیه یک بار ذخیره شود
LOG_INTERVAL = 60

# آخرین دمای دریافت شده از ESP32
last_temperature = None

# زمان آخرین دریافت دما
last_temperature_time = None

# وضعیت Logger
logger_running = True


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI()

telegram_app = None


# =========================================================
# TELEGRAM KEYBOARD
# =========================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🟢 LED ON", "🔴 LED OFF"],
        ["🌡 دریافت دما"],
        ["📊 گزارش دما"],
        ["📄 دریافت فایل گزارش"],
        ["ℹ️ وضعیت"],
    ],
    resize_keyboard=True,
)


# =========================================================
# CREATE CSV FILE
# =========================================================

def create_temperature_file():

    if not os.path.exists(TEMPERATURE_FILE):

        with open(
            TEMPERATURE_FILE,
            "w",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.writer(file)

            writer.writerow(
                [
                    "Date",
                    "Time",
                    "Temperature_C"
                ]
            )

        print("Temperature log file created.")


# =========================================================
# SAVE TEMPERATURE
# =========================================================

def save_temperature():

    global last_temperature

    if last_temperature is None:

        print("No temperature available for logging.")

        return

    now = datetime.now()

    with open(
        TEMPERATURE_FILE,
        "a",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow(
            [
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                f"{last_temperature:.2f}"
            ]
        )

    print(
        f"Temperature logged: "
        f"{last_temperature:.2f} C"
    )


# =========================================================
# TEMPERATURE LOGGER TASK
# =========================================================

async def temperature_logger():

    print("Temperature logger started.")

    while True:

        try:

            await asyncio.sleep(LOG_INTERVAL)

            save_temperature()

        except asyncio.CancelledError:

            print("Temperature logger stopped.")

            break

        except Exception as e:

            print("Temperature logger error:")
            print(e)


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
# MQTT MESSAGE
# =========================================================

def on_message(
    client,
    userdata,
    msg
):

    global last_temperature
    global last_temperature_time

    try:

        payload = msg.payload.decode(
            "utf-8",
            errors="ignore"
        ).strip()

        print("======================================")
        print("MQTT MESSAGE")
        print(f"Topic: {msg.topic}")
        print(f"Message: {payload}")
        print("======================================")

        # ---------------------------------------------
        # Temperature message
        # ---------------------------------------------

        if payload.startswith("TEMP:"):

            value = payload.replace(
                "TEMP:",
                "",
                1
            ).strip()

            temperature = float(value)

            last_temperature = temperature

            last_temperature_time = datetime.now()

            print(
                f"Temperature received: "
                f"{temperature:.2f} C"
            )

    except Exception as e:

        print("MQTT message error:")
        print(e)


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

    print("Connecting to HiveMQ...")

    try:

        mqtt_client.connect(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=60
        )

        mqtt_client.loop_start()

        # دریافت پیام‌های LED و Temperature
        mqtt_client.subscribe(
            MQTT_TOPIC,
            qos=1
        )

        print(
            f"Subscribed: {MQTT_TOPIC}"
        )

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
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    print("--------------------------------------")
    print(f"Telegram Chat ID: {chat_id}")
    print("Command: /start")
    print("--------------------------------------")

    await update.message.reply_text(
        "🤖 ESP32 Control Bot\n\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=MAIN_KEYBOARD
    )


# =========================================================
# SEND TEMPERATURE
# =========================================================

async def send_temperature(
    update: Update
):

    if last_temperature is None:

        await update.message.reply_text(
            "❌ هنوز دمایی از ESP32 دریافت نشده است."
        )

        return

    if last_temperature_time:

        time_text = last_temperature_time.strftime(
            "%H:%M:%S"
        )

    else:

        time_text = "-"

    await update.message.reply_text(
        "🌡 دمای فعلی ESP32\n\n"
        f"🌡 Temperature: {last_temperature:.2f} °C\n"
        f"🕐 آخرین دریافت: {time_text}"
    )


# =========================================================
# SEND TEMPERATURE FILE
# =========================================================

async def send_temperature_file(
    update: Update
):

    create_temperature_file()

    try:

        if not os.path.exists(TEMPERATURE_FILE):

            await update.message.reply_text(
                "❌ فایل گزارش پیدا نشد."
            )

            return

        file_size = os.path.getsize(
            TEMPERATURE_FILE
        )

        if file_size <= 0:

            await update.message.reply_text(
                "❌ فایل گزارش خالی است."
            )

            return

        await update.message.reply_document(
            document=TEMPERATURE_FILE,
            caption=(
                "📊 گزارش دمای ESP32\n\n"
                "ثبت دما هر ۶۰ ثانیه"
            )
        )

        print("Temperature report sent.")

    except Exception as e:

        print("File sending error:")
        print(e)

        await update.message.reply_text(
            "❌ ارسال فایل گزارش انجام نشد."
        )


# =========================================================
# HANDLE MESSAGE
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


    # =====================================================
    # SECURITY
    # =====================================================

    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return


    # =====================================================
    # LED ON
    # =====================================================

    if text in ["🟢 led on", "led on"]:

        if not mqtt_client.is_connected():

            await update.message.reply_text(
                "❌ اتصال MQTT برقرار نیست."
            )

            return

        result = mqtt_client.publish(
            MQTT_TOPIC,
            "ON",
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            await update.message.reply_text(
                "🟢 LED روشن شد",
                reply_markup=MAIN_KEYBOARD
            )

        else:

            await update.message.reply_text(
                "❌ ارسال فرمان انجام نشد."
            )

        return


    # =====================================================
    # LED OFF
    # =====================================================

    if text in ["🔴 led off", "led off"]:

        if not mqtt_client.is_connected():

            await update.message.reply_text(
                "❌ اتصال MQTT برقرار نیست."
            )

            return

        result = mqtt_client.publish(
            MQTT_TOPIC,
            "OFF",
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            await update.message.reply_text(
                "🔴 LED خاموش شد",
                reply_markup=MAIN_KEYBOARD
            )

        else:

            await update.message.reply_text(
                "❌ ارسال فرمان انجام نشد."
            )

        return


    # =====================================================
    # GET TEMPERATURE
    # =====================================================

    if text in [
        "🌡 دریافت دما",
        "دریافت دما"
    ]:

        await send_temperature(
            update
        )

        return


    # =====================================================
    # TEMPERATURE REPORT
    # =====================================================

    if text in [
        "📊 گزارش دما",
        "گزارش دما"
    ]:

        await update.message.reply_text(
            "📊 گزارش دما فعال است.\n\n"
            "دما هر ۶۰ ثانیه در فایل CSV ذخیره می‌شود.\n\n"
            "برای دریافت فایل، گزینه زیر را بزنید:\n"
            "📄 دریافت فایل گزارش",
            reply_markup=MAIN_KEYBOARD
        )

        return


    # =====================================================
    # SEND FILE
    # =====================================================

    if text in [
        "📄 دریافت فایل گزارش",
        "دریافت فایل گزارش"
    ]:

        await send_temperature_file(
            update
        )

        return


    # =====================================================
    # STATUS
    # =====================================================

    if text in [
        "ℹ️ وضعیت",
        "وضعیت",
        "status"
    ]:

        mqtt_state = (
            "Connected"
            if mqtt_client.is_connected()
            else "Disconnected"
        )

        if last_temperature is None:

            temp_text = "دریافت نشده"

        else:

            temp_text = (
                f"{last_temperature:.2f} °C"
            )

        await update.message.reply_text(
            "🤖 ESP32 Control\n\n"
            f"📡 MQTT: {mqtt_state}\n"
            f"🌡 Temperature: {temp_text}\n"
            f"📝 Log interval: {LOG_INTERVAL} seconds",
            reply_markup=MAIN_KEYBOARD
        )

        return


    # =====================================================
    # INVALID
    # =====================================================

    await update.message.reply_text(
        "❓ گزینه نامعتبر است.\n\n"
        "از منوی زیر استفاده کنید:",
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
    # Create temperature file
    # -----------------------------------------------------

    create_temperature_file()

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
    # Initialize Telegram
    # -----------------------------------------------------

    await telegram_app.initialize()

    await telegram_app.start()

    # -----------------------------------------------------
    # Start temperature logger
    # -----------------------------------------------------

    asyncio.create_task(
        temperature_logger()
    )

    # -----------------------------------------------------
    # Telegram Webhook
    # -----------------------------------------------------

    webhook_url = (
        RENDER_URL +
        "/telegram"
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
# START
# =========================================================

if __name__ == "__main__":

    uvicorn.run(
        "telegram_mqtt:app",
        host="0.0.0.0",
        port=PORT
    )
