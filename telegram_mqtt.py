
import os
import ssl
import csv
import asyncio
import logging
from datetime import datetime

import paho.mqtt.client as mqtt

from fastapi import FastAPI, Request, HTTPException

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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
# FILE
# =========================================================

REPORT_FILE = "temperature_report.csv"


# =========================================================
# GLOBAL TEMPERATURE
# =========================================================

latest_temperature = None
latest_temperature_time = None


# =========================================================
# CONTINUOUS REPORT
# =========================================================

continuous_tasks = {}


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI()

telegram_app = None


# =========================================================
# CSV INITIALIZATION
# =========================================================

def initialize_report_file():

    if not os.path.exists(REPORT_FILE):

        with open(
            REPORT_FILE,
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

        print("Temperature report file created.")


# =========================================================
# SAVE TEMPERATURE
# =========================================================

def save_temperature(temperature):

    now = datetime.now()

    with open(
        REPORT_FILE,
        "a",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow(
            [
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                f"{temperature:.2f}"
            ]
        )

    print(
        f"Temperature saved: "
        f"{temperature:.2f} C"
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


    if reason_code == 0:

        result = client.subscribe(
            MQTT_TOPIC,
            qos=1
        )

        if result[0] == mqtt.MQTT_ERR_SUCCESS:

            print(
                f"Subscribed: {MQTT_TOPIC}"
            )

        else:

            print(
                f"Subscribe failed: {result[0]}"
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

    print("MQTT disconnected")
    print(f"Reason code: {reason_code}")


# =========================================================
# MQTT MESSAGE
# =========================================================

def on_message(
    client,
    userdata,
    message
):

    global latest_temperature
    global latest_temperature_time

    topic = message.topic

    try:

        payload = message.payload.decode(
            "utf-8"
        ).strip()

    except Exception:

        return


    print("======================================")
    print("MQTT MESSAGE")
    print(f"Topic: {topic}")
    print(f"Message: {payload}")
    print("======================================")


    # -----------------------------------------------------
    # TEMPERATURE
    # -----------------------------------------------------

    if payload.startswith("TEMP:"):

        try:

            temperature_text = payload[
                5:
            ].strip()

            temperature = float(
                temperature_text
            )

            latest_temperature = temperature

            latest_temperature_time = (
                datetime.now()
            )

            print(
                f"Temperature received: "
                f"{temperature:.2f} C"
            )

        except Exception as e:

            print(
                "Temperature parsing error:"
            )

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

def is_allowed(update: Update):

    if update.effective_chat is None:

        return False

    chat_id = str(
        update.effective_chat.id
    )

    if ALLOWED_CHAT_ID == "0":

        return True

    return chat_id == ALLOWED_CHAT_ID


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [

        [
            "🟢 روشن کردن LED",
            "🔴 خاموش کردن LED"
        ],

        [
            "🌡️ دمای فعلی"
        ],

        [
            "📊 گزارش دما"
        ],

        [
            "📡 گزارش مستمر دما"
        ],

        [
            "⛔ توقف گزارش مستمر"
        ],

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
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

    chat_id = update.effective_chat.id

    print("--------------------------------------")
    print(
        f"Telegram Chat ID: {chat_id}"
    )
    print("Command: /start")
    print("--------------------------------------")


    await update.message.reply_text(

        "🤖 ESP32 Control Bot\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",

        reply_markup=main_menu()
    )


# =========================================================
# SEND TEMPERATURE
# =========================================================

async def send_current_temperature(
    update: Update
):

    if latest_temperature is None:

        await update.message.reply_text(

            "❌ هنوز دمایی از ESP32 دریافت نشده است.\n\n"
            "ابتدا مطمئن شوید ESP32 به MQTT متصل است "
            "و دما را ارسال می‌کند.",

            reply_markup=main_menu()
        )

        return


    time_text = ""

    if latest_temperature_time:

        time_text = (
            latest_temperature_time
            .strftime("%Y-%m-%d %H:%M:%S")
        )


    await update.message.reply_text(

        f"🌡️ دمای فعلی ESP32\n\n"
        f"🌡️ {latest_temperature:.2f} °C\n\n"
        f"🕐 آخرین دریافت:\n"
        f"{time_text}",

        reply_markup=main_menu()
    )


# =========================================================
# LED ON
# =========================================================

async def led_on(
    update: Update
):

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

        print("MQTT -> ON")

        await update.message.reply_text(

            "🟢 LED روشن شد",

            reply_markup=main_menu()
        )

    else:

        await update.message.reply_text(
            "❌ ارسال فرمان انجام نشد."
        )


# =========================================================
# LED OFF
# =========================================================

async def led_off(
    update: Update
):

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

        print("MQTT -> OFF")

        await update.message.reply_text(

            "🔴 LED خاموش شد",

            reply_markup=main_menu()
        )

    else:

        await update.message.reply_text(
            "❌ ارسال فرمان انجام نشد."
        )


# =========================================================
# SEND REPORT FILE
# =========================================================

async def send_report(
    update: Update
):

    if not os.path.exists(REPORT_FILE):

        initialize_report_file()


    try:

        with open(
            REPORT_FILE,
            "rb"
        ) as file:

            await update.message.reply_document(

                document=file,

                filename="temperature_report.csv",

                caption=(
                    "📊 گزارش دما\n\n"
                    "📝 اطلاعات ثبت‌شده "
                    "در فایل CSV."
                )
            )


    except Exception as e:

        print(
            "Report sending error:"
        )

        print(e)

        await update.message.reply_text(

            "❌ ارسال فایل گزارش انجام نشد.",

            reply_markup=main_menu()
        )


# =========================================================
# CONTINUOUS TEMPERATURE REPORT
# =========================================================

async def continuous_temperature_report(
    chat_id,
    interval
):

    try:

        while True:

            await asyncio.sleep(
                interval
            )

            if (
                chat_id
                not in continuous_tasks
            ):

                break


            if latest_temperature is None:

                continue


            try:

                await telegram_app.bot.send_message(

                    chat_id=chat_id,

                    text=(
                        "📡 گزارش دما\n\n"
                        f"🌡️ "
                        f"{latest_temperature:.2f} °C\n\n"
                        f"🕐 "
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                )

            except Exception as e:

                print(
                    "Continuous report error:"
                )

                print(e)

                break


    except asyncio.CancelledError:

        pass


# =========================================================
# START CONTINUOUS REPORT
# =========================================================

async def start_continuous_report(
    update: Update
):

    chat_id = update.effective_chat.id


    if chat_id in continuous_tasks:

        await update.message.reply_text(

            "📡 گزارش مستمر دما از قبل فعال است.\n\n"
            "برای توقف آن گزینه "
            "«⛔ توقف گزارش مستمر» را بزنید.",

            reply_markup=main_menu()
        )

        return


    context_data = {
        "waiting_for_interval": True
    }

    # ذخیره حالت انتظار
    context_data_key = f"interval_{chat_id}"

    if not hasattr(
        start_continuous_report,
        "waiting"
    ):

        start_continuous_report.waiting = set()


    start_continuous_report.waiting.add(
        chat_id
    )


    await update.message.reply_text(

        "⏱️ هر چند ثانیه یک بار دما ارسال شود؟\n\n"
        "مثلاً:\n"
        "10\n"
        "30\n"
        "60\n"
        "300\n\n"
        "عدد را بر حسب ثانیه ارسال کنید.",

        reply_markup=ReplyKeyboardRemove()
    )


# =========================================================
# STOP CONTINUOUS REPORT
# =========================================================

async def stop_continuous_report(
    update: Update
):

    chat_id = update.effective_chat.id


    if hasattr(
        start_continuous_report,
        "waiting"
    ):

        start_continuous_report.waiting.discard(
            chat_id
        )


    task = continuous_tasks.pop(
        chat_id,
        None
    )


    if task:

        task.cancel()

        await update.message.reply_text(

            "⛔ گزارش مستمر دما متوقف شد.",

            reply_markup=main_menu()
        )

    else:

        await update.message.reply_text(

            "ℹ️ گزارش مستمر در حال اجرا نیست.",

            reply_markup=main_menu()
        )


# =========================================================
# TEXT MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global continuous_tasks


    if not update.effective_chat:

        return

    if not update.message:

        return


    chat_id = update.effective_chat.id

    text = update.message.text.strip()


    print("--------------------------------------")
    print(
        f"Telegram Chat ID: {chat_id}"
    )
    print(
        f"Message: {text}"
    )
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
    # STOP FIRST
    # -----------------------------------------------------

    if text == "⛔ توقف گزارش مستمر":

        await stop_continuous_report(
            update
        )

        return


    # -----------------------------------------------------
    # INTERVAL INPUT
    # -----------------------------------------------------

    if (
        hasattr(
            start_continuous_report,
            "waiting"
        )
        and chat_id
        in start_continuous_report.waiting
    ):

        try:

            interval = float(text)

            if interval < 1:

                raise ValueError


            start_continuous_report.waiting.discard(
                chat_id
            )


            continuous_tasks[
                chat_id
            ] = asyncio.create_task(

                continuous_temperature_report(
                    chat_id,
                    interval
                )
            )


            await update.message.reply_text(

                "✅ گزارش مستمر فعال شد.\n\n"
                f"⏱️ فاصله ارسال: {interval:g} ثانیه\n\n"
                "برای توقف، گزینه "
                "«⛔ توقف گزارش مستمر» را بزنید.",

                reply_markup=main_menu()
            )

            return


        except ValueError:

            await update.message.reply_text(

                "❌ لطفاً فقط یک عدد معتبر وارد کنید.\n\n"
                "مثلاً:\n"
                "10\n"
                "30\n"
                "60",

            )

            return


    # -----------------------------------------------------
    # LED ON
    # -----------------------------------------------------

    if text in (
        "🟢 روشن کردن LED",
        "led on"
    ):

        await led_on(update)

        return


    # -----------------------------------------------------
    # LED OFF
    # -----------------------------------------------------

    if text in (
        "🔴 خاموش کردن LED",
        "led off"
    ):

        await led_off(update)

        return


    # -----------------------------------------------------
    # CURRENT TEMPERATURE
    # -----------------------------------------------------

    if text in (
        "🌡️ دمای فعلی",
        "دریافت دما",
        "temperature",
        "temp"
    ):

        await send_current_temperature(
            update
        )

        return


    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    if text in (
        "📊 گزارش دما",
        "گزارش دما",
        "report"
    ):

        await send_report(update)

        return


    # -----------------------------------------------------
    # CONTINUOUS REPORT
    # -----------------------------------------------------

    if text in (
        "📡 گزارش مستمر دما",
        "گزارش مستمر دما"
    ):

        await start_continuous_report(
            update
        )

        return


    # -----------------------------------------------------
    # UNKNOWN
    # -----------------------------------------------------

    await update.message.reply_text(

        "❓ گزینه مورد نظر شناخته نشد.\n\n"
        "لطفاً از منوی پایین انتخاب کنید.",

        reply_markup=main_menu()
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
    print("     TELEGRAM ESP32 RENDER BOT")
    print("======================================")


    # -----------------------------------------------------
    # REPORT FILE
    # -----------------------------------------------------

    initialize_report_file()


    # -----------------------------------------------------
    # MQTT
    # -----------------------------------------------------

    connect_mqtt()


    # -----------------------------------------------------
    # TELEGRAM
    # -----------------------------------------------------

    telegram_app = (

        Application.builder()

        .token(TELEGRAM_BOT_TOKEN)

        .updater(None)

        .build()
    )


    # -----------------------------------------------------
    # HANDLERS
    # -----------------------------------------------------

    telegram_app.add_handler(

        CommandHandler(
            "start",
            start_command
        )
    )


    telegram_app.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            handle_message
        )
    )


    # -----------------------------------------------------
    # INITIALIZE
    # -----------------------------------------------------

    await telegram_app.initialize()

    await telegram_app.start()


    # -----------------------------------------------------
    # WEBHOOK
    # -----------------------------------------------------

    webhook_url = (
        RENDER_URL
        + "/telegram"
    )


    print("")
    print(
        "Setting Telegram webhook..."
    )

    print(webhook_url)


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


    # توقف گزارش‌ها

    for task in continuous_tasks.values():

        task.cancel()


    continuous_tasks.clear()


    # Telegram

    if telegram_app:

        await telegram_app.stop()

        await telegram_app.shutdown()


    # MQTT

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

