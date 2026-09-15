import os
import ssl
import csv
import asyncio
import logging
import time
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

MQTT_HOST = "c8f63357997a47a8b37f0495aac24c7d.s1.eu.hivemq.cloud"
MQTT_PORT = 8883

MQTT_USERNAME = "hamed_esp32"
MQTT_PASSWORD = "Ha00102030meD@"

# همان Topic قبلی
MQTT_TOPIC = "hamed/esp32/led"


# =========================================================
# RENDER
# =========================================================

RENDER_URL = "https://telegram-esp32-control.onrender.com"

PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_SECRET = "HamedESP32_2026_X9"


# =========================================================
# TEMPERATURE LOG
# =========================================================

REPORT_FILE = "temperature_report.csv"

# ذخیره آخرین دمای موجود هر 60 ثانیه
SAVE_INTERVAL = 60


# =========================================================
# GLOBAL TEMPERATURE
# =========================================================

latest_temperature = None
latest_temperature_time = None


# =========================================================
# REPORT TASKS
# =========================================================

continuous_tasks = {}
waiting_for_interval = set()

temperature_logger_task = None


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI()

telegram_app = None


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [
        [
            "🟢 روشن کردن LED",
            "🔴 خاموش کردن LED",
        ],
        [
            "🌡️ دمای فعلی",
        ],
        [
            "📊 گزارش دما",
        ],
        [
            "📡 گزارش مستمر دما",
        ],
        [
            "⛔ توقف گزارش مستمر",
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


# =========================================================
# CREATE REPORT FILE
# =========================================================

def initialize_report_file():

    try:

        if not os.path.exists(REPORT_FILE):

            with open(
                REPORT_FILE,
                "w",
                newline="",
                encoding="utf-8",
            ) as file:

                writer = csv.writer(file)

                writer.writerow(
                    [
                        "Date",
                        "Time",
                        "Temperature_C",
                    ]
                )

            print("Temperature report file created.")

    except Exception as e:

        print("Could not create report file:")
        print(e)


# =========================================================
# SAVE TEMPERATURE
# =========================================================

def save_temperature():

    if latest_temperature is None:

        print(
            "No temperature available. "
            "Nothing will be saved."
        )

        return

    try:

        now = datetime.now()

        with open(
            REPORT_FILE,
            "a",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.writer(file)

            writer.writerow(
                [
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    f"{latest_temperature:.2f}",
                ]
            )

        print(
            f"Temperature saved: "
            f"{latest_temperature:.2f} C"
        )

    except Exception as e:

        print("Temperature save error:")
        print(e)


# =========================================================
# AUTOMATIC LOGGER
# =========================================================

async def temperature_logger():

    print("======================================")
    print("Temperature Logger")
    print("======================================")
    print("Save interval: 60 seconds")
    print("Logger: ACTIVE")
    print("======================================")

    while True:

        try:

            await asyncio.sleep(SAVE_INTERVAL)

            save_temperature()

        except asyncio.CancelledError:

            print("Temperature logger stopped.")
            break

        except Exception as e:

            print("Temperature logger error:")
            print(e)


# =========================================================
# MQTT ON CONNECT
# =========================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties,
):

    print()
    print("======================================")
    print("MQTT STATUS")
    print("Connected to HiveMQ")
    print(f"Reason code: {reason_code}")
    print("======================================")


    if reason_code == 0:

        result = client.subscribe(
            MQTT_TOPIC,
            qos=1,
        )

        if result[0] == mqtt.MQTT_ERR_SUCCESS:

            print(
                f"Subscribed: {MQTT_TOPIC}"
            )

        else:

            print(
                f"Subscribe failed: {result}"
            )


# =========================================================
# MQTT ON DISCONNECT
# =========================================================

def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties,
):

    print()
    print("MQTT disconnected")
    print(
        f"Reason code: {reason_code}"
    )


# =========================================================
# MQTT MESSAGE
# =========================================================

def on_message(
    client,
    userdata,
    message,
):

    global latest_temperature
    global latest_temperature_time

    try:

        payload = (
            message.payload
            .decode("utf-8")
            .strip()
        )

    except Exception as e:

        print("MQTT decode error:")
        print(e)

        return


    print()
    print("======================================")
    print("MQTT MESSAGE")
    print(f"Topic: {message.topic}")
    print(f"Message: {payload}")
    print("======================================")


    # -----------------------------------------------------
    # TEMPERATURE
    # -----------------------------------------------------

    if payload.startswith("TEMP:"):

        try:

            temperature_text = payload[5:].strip()

            temperature = float(
                temperature_text
            )

            latest_temperature = temperature

            latest_temperature_time = datetime.now()

            print(
                f"Temperature received: "
                f"{temperature:.2f} C"
            )

        except ValueError:

            print(
                "Invalid temperature message:"
            )

            print(payload)


# =========================================================
# MQTT CLIENT
# =========================================================

mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="Telegram_ESP32_Render",
)

mqtt_client.username_pw_set(
    MQTT_USERNAME,
    MQTT_PASSWORD,
)

mqtt_client.tls_set(
    cert_reqs=ssl.CERT_REQUIRED,
    tls_version=ssl.PROTOCOL_TLS_CLIENT,
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
            keepalive=60,
        )

        mqtt_client.loop_start()

        print("MQTT connection started.")

    except Exception as e:

        print("MQTT CONNECTION ERROR:")
        print(e)


# =========================================================
# SECURITY
# =========================================================

def is_allowed(
    update: Update,
):

    if update.effective_chat is None:

        return False

    chat_id = str(
        update.effective_chat.id
    )

    if ALLOWED_CHAT_ID == "0":

        return True

    return chat_id == ALLOWED_CHAT_ID


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_chat:
        return

    if not update.message:
        return


    chat_id = update.effective_chat.id

    print(
        f"Telegram Chat ID: {chat_id}"
    )


    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه استفاده از ربات را ندارید."
        )

        return


    await update.message.reply_text(

        "🤖 ESP32 Control Bot\n\n"
        "لطفاً یک گزینه را انتخاب کنید:",

        reply_markup=main_menu(),
    )


# =========================================================
# LED ON
# =========================================================

async def led_on(
    update: Update,
):

    if not mqtt_client.is_connected():

        await update.message.reply_text(
            "❌ اتصال MQTT برقرار نیست.",
            reply_markup=main_menu(),
        )

        return


    result = mqtt_client.publish(
        MQTT_TOPIC,
        "ON",
        qos=1,
    )


    if result.rc == mqtt.MQTT_ERR_SUCCESS:

        print("MQTT -> ON")

        await update.message.reply_text(

            "🟢 LED روشن شد",

            reply_markup=main_menu(),
        )

    else:

        await update.message.reply_text(

            "❌ ارسال فرمان انجام نشد.",

            reply_markup=main_menu(),
        )


# =========================================================
# LED OFF
# =========================================================

async def led_off(
    update: Update,
):

    if not mqtt_client.is_connected():

        await update.message.reply_text(
            "❌ اتصال MQTT برقرار نیست.",
            reply_markup=main_menu(),
        )

        return


    result = mqtt_client.publish(
        MQTT_TOPIC,
        "OFF",
        qos=1,
    )


    if result.rc == mqtt.MQTT_ERR_SUCCESS:

        print("MQTT -> OFF")

        await update.message.reply_text(

            "🔴 LED خاموش شد",

            reply_markup=main_menu(),
        )

    else:

        await update.message.reply_text(

            "❌ ارسال فرمان انجام نشد.",

            reply_markup=main_menu(),
        )


# =========================================================
# SHOW CURRENT TEMPERATURE
# =========================================================

async def show_current_temperature(
    update: Update,
):

    if latest_temperature is None:

        await update.message.reply_text(

            "❌ هنوز دمایی از ESP32 دریافت نشده است.",

            reply_markup=main_menu(),
        )

        return


    if latest_temperature_time:

        time_text = (
            latest_temperature_time
            .strftime("%Y-%m-%d %H:%M:%S")
        )

    else:

        time_text = "نامشخص"


    await update.message.reply_text(

        "🌡️ دمای فعلی ESP32\n\n"
        f"🌡️ {latest_temperature:.2f} °C\n\n"
        f"🕐 آخرین دریافت:\n"
        f"{time_text}",

        reply_markup=main_menu(),
    )


# =========================================================
# SEND REPORT FILE
# =========================================================

async def send_report(
    update: Update,
):

    initialize_report_file()


    try:

        if not os.path.exists(REPORT_FILE):

            await update.message.reply_text(

                "❌ فایل گزارش وجود ندارد.",

                reply_markup=main_menu(),
            )

            return


        file_size = os.path.getsize(
            REPORT_FILE
        )


        if file_size <= 50:

            await update.message.reply_text(

                "⚠️ فایل گزارش هنوز رکوردی ندارد.\n\n"
                "ابتدا باید حداقل یک دمای معتبر "
                "از ESP32 دریافت شود و سپس اولین "
                "رکورد ذخیره شود.",

                reply_markup=main_menu(),
            )

            return


        with open(
            REPORT_FILE,
            "rb"
        ) as file:

            await update.message.reply_document(

                document=file,

                filename="temperature_report.csv",

                caption=(
                    "📊 گزارش دما\n\n"
                    "📝 ثبت خودکار هر ۶۰ ثانیه"
                ),
            )


        await update.message.reply_text(

            "✅ فایل گزارش ارسال شد.",

            reply_markup=main_menu(),
        )


    except Exception as e:

        print("Report sending error:")
        print(e)


        await update.message.reply_text(

            "❌ ارسال فایل گزارش انجام نشد.",

            reply_markup=main_menu(),
        )


# =========================================================
# CONTINUOUS TEMPERATURE REPORT
# =========================================================

async def continuous_temperature_report(
    chat_id: int,
    interval: float,
):

    print()
    print(
        "======================================"
    )
    print(
        "Continuous Temperature Report"
    )
    print(
        f"Chat ID: {chat_id}"
    )
    print(
        f"Interval: {interval} seconds"
    )
    print(
        "======================================"
    )


    try:

        while True:

            # ---------------------------------------------
            # صبر تا نوبت گزارش
            # ---------------------------------------------

            await asyncio.sleep(
                interval
            )


            # ---------------------------------------------
            # اگر گزارش متوقف شده
            # ---------------------------------------------

            if chat_id not in continuous_tasks:

                break


            # ---------------------------------------------
            # دما وجود ندارد
            # ---------------------------------------------

            if latest_temperature is None:

                await telegram_app.bot.send_message(

                    chat_id=chat_id,

                    text=(
                        "⚠️ هنوز دمایی از ESP32 "
                        "دریافت نشده است."
                    ),
                )

                continue


            # ---------------------------------------------
            # ارسال دما
            # ---------------------------------------------

            now = datetime.now()

            await telegram_app.bot.send_message(

                chat_id=chat_id,

                text=(
                    "📡 گزارش مستمر دما\n\n"

                    f"🌡️ دما: "
                    f"{latest_temperature:.2f} °C\n\n"

                    f"🕐 زمان: "
                    f"{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

                    f"⏱️ فاصله گزارش: "
                    f"{interval:g} ثانیه"
                ),
            )


    except asyncio.CancelledError:

        print(
            f"Continuous report stopped: "
            f"{chat_id}"
        )


    except Exception as e:

        print(
            "Continuous report error:"
        )

        print(e)


    finally:

        continuous_tasks.pop(
            chat_id,
            None
        )


# =========================================================
# START CONTINUOUS REPORT
# =========================================================

async def start_continuous_report(
    update: Update,
):

    chat_id = update.effective_chat.id


    if chat_id in continuous_tasks:

        await update.message.reply_text(

            "📡 گزارش مستمر دما از قبل فعال است.",

            reply_markup=main_menu(),
        )

        return


    waiting_for_interval.add(
        chat_id
    )


    await update.message.reply_text(

        "📡 گزارش مستمر دما\n\n"

        "⏱️ هر چند ثانیه یک بار "
        "گزارش ارسال شود؟\n\n"

        "مثلاً:\n"
        "5\n"
        "10\n"
        "30\n"
        "60\n\n"

        "فقط عدد را وارد کنید.",

        reply_markup=ReplyKeyboardRemove(),
    )


# =========================================================
# STOP CONTINUOUS REPORT
# =========================================================

async def stop_continuous_report(
    update: Update,
):

    chat_id = update.effective_chat.id


    waiting_for_interval.discard(
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

            reply_markup=main_menu(),
        )

    else:

        await update.message.reply_text(

            "ℹ️ گزارش مستمر دما فعال نیست.",

            reply_markup=main_menu(),
        )


# =========================================================
# STATUS
# =========================================================

async def show_status(
    update: Update,
):

    mqtt_status = (
        "🟢 Connected"
        if mqtt_client.is_connected()
        else "🔴 Disconnected"
    )


    if latest_temperature is None:

        temperature_text = (
            "❌ دریافت نشده"
        )

    else:

        temperature_text = (
            f"{latest_temperature:.2f} °C"
        )


    report_status = (
        "🟢 فعال"
        if continuous_tasks
        else "🔴 غیرفعال"
    )


    await update.message.reply_text(

        "📊 وضعیت سیستم\n\n"

        f"📡 MQTT: {mqtt_status}\n"

        f"🌡️ دما: {temperature_text}\n"

        f"📡 گزارش مستمر: {report_status}\n\n"

        f"Topic:\n"
        f"{MQTT_TOPIC}\n\n"

        "GPIO2: LED\n"
        "GPIO23: DS18B20",

        reply_markup=main_menu(),
    )


# =========================================================
# TEXT MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_chat:
        return

    if not update.message:
        return


    chat_id = update.effective_chat.id

    text = update.message.text.strip()


    print()
    print("--------------------------------------")
    print(
        f"Telegram Chat ID: {chat_id}"
    )
    print(
        f"Message: {text}"
    )
    print(
        "--------------------------------------"
    )


    # =====================================================
    # SECURITY
    # =====================================================

    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return


    # =====================================================
    # STOP REPORT
    # =====================================================

    if text in (
        "⛔ توقف گزارش مستمر",
        "توقف گزارش مستمر",
    ):

        await stop_continuous_report(
            update
        )

        return


    # =====================================================
    # INTERVAL INPUT
    # =====================================================

    if chat_id in waiting_for_interval:

        try:

            interval = float(text)


            if interval < 1:

                await update.message.reply_text(

                    "⚠️ حداقل فاصله گزارش ۱ ثانیه است."
                )

                return


            if interval > 86400:

                await update.message.reply_text(

                    "⚠️ حداکثر فاصله گزارش "
                    "۸۶۴۰۰ ثانیه است."
                )

                return


            waiting_for_interval.discard(
                chat_id
            )


            old_task = continuous_tasks.pop(
                chat_id,
                None
            )


            if old_task:

                old_task.cancel()


            task = asyncio.create_task(

                continuous_temperature_report(

                    chat_id,

                    interval
                )
            )


            continuous_tasks[
                chat_id
            ] = task


            await update.message.reply_text(

                "✅ گزارش مستمر دما فعال شد.\n\n"

                f"⏱️ فاصله گزارش: "
                f"{interval:g} ثانیه\n\n"

                "برای توقف، دکمه "
                "«⛔ توقف گزارش مستمر» "
                "را بزنید.",

                reply_markup=main_menu(),
            )

            return


        except ValueError:

            await update.message.reply_text(

                "❌ فقط یک عدد وارد کنید.\n\n"

                "مثلاً:\n"
                "10\n"
                "30\n"
                "60"
            )

            return


    # =====================================================
    # LED ON
    # =====================================================

    if text in (
        "🟢 روشن کردن LED",
        "led on",
        "LED ON",
    ):

        await led_on(
            update
        )

        return


    # =====================================================
    # LED OFF
    # =====================================================

    if text in (
        "🔴 خاموش کردن LED",
        "led off",
        "LED OFF",
    ):

        await led_off(
            update
        )

        return


    # =====================================================
    # CURRENT TEMPERATURE
    # =====================================================

    if text in (
        "🌡️ دمای فعلی",
        "دمای فعلی",
        "دریافت دما",
        "temperature",
        "temp",
    ):

        await send_current_temperature(
            update
        )

        return


    # =====================================================
    # REPORT FILE
    # =====================================================

    if text in (
        "📊 گزارش دما",
        "گزارش دما",
        "report",
    ):

        await send_report(
            update
        )

        return


    # =====================================================
    # CONTINUOUS REPORT
    # =====================================================

    if text in (
        "📡 گزارش مستمر دما",
        "گزارش مستمر دما",
    ):

        await start_continuous_report(
            update
        )

        return


    # =====================================================
    # STATUS
    # =====================================================

    if text in (
        "📊 وضعیت سیستم",
        "وضعیت سیستم",
        "ℹ️ وضعیت",
        "status",
    ):

        await show_status(
            update
        )

        return


    # =====================================================
    # UNKNOWN
    # =====================================================

    await update.message.reply_text(

        "❓ گزینه موردنظر شناخته نشد.\n\n"
        "لطفاً از منوی پایین استفاده کنید.",

        reply_markup=main_menu(),
    )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
async def root():

    return {
        "status": "online",
        "service": "Telegram ESP32 Bot",
    }


@app.get("/health")
async def health():

    return {
        "status": "ok",
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
            detail="Unauthorized",
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
            detail="Webhook error",
        )


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup_event():

    global telegram_app
    global temperature_logger_task


    print()
    print("======================================")
    print("     TELEGRAM ESP32 RENDER BOT")
    print("======================================")


    # -----------------------------------------------------
    # CSV
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
    # INITIALIZE
    # -----------------------------------------------------

    await telegram_app.initialize()

    await telegram_app.start()


    # -----------------------------------------------------
    # LOGGER
    # -----------------------------------------------------

    temperature_logger_task = asyncio.create_task(
        temperature_logger()
    )


    # -----------------------------------------------------
    # WEBHOOK
    # -----------------------------------------------------

    webhook_url = (
        RENDER_URL
        + "/telegram"
    )


    print()
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


    print()
    print(
        "Telegram webhook configured."
    )

    print(
        "Bot is ready."
    )

    print(
        "Temperature logger: ACTIVE"
    )

    print(
        "Temperature save interval: 60 seconds"
    )

    print()


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown_event():

    global temperature_logger_task


    print(
        "Stopping bot..."
    )


    # -----------------------------------------------------
    # Temperature Logger
    # -----------------------------------------------------

    if temperature_logger_task:

        temperature_logger_task.cancel()

        try:

            await temperature_logger_task

        except asyncio.CancelledError:

            pass

        temperature_logger_task = None


    # -----------------------------------------------------
    # Continuous Reports
    # -----------------------------------------------------

    for task in list(
        continuous_tasks.values()
    ):

        task.cancel()


    continuous_tasks.clear()

    waiting_for_interval.clear()


    # -----------------------------------------------------
    # Telegram
    # -----------------------------------------------------

    if telegram_app:

        await telegram_app.stop()

        await telegram_app.shutdown()


    # -----------------------------------------------------
    # MQTT
    # -----------------------------------------------------

    mqtt_client.loop_stop()

    mqtt_client.disconnect()


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    uvicorn.run(

        "telegram_mqtt:app",

        host="0.0.0.0",

        port=PORT,
    )
