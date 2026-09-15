
import os
import ssl
import csv
import asyncio
import logging
import uuid
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

# توکن جدید BotFather را اینجا قرار بده
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


# =========================================================
# MQTT TOPIC
# فقط همین Topic
# =========================================================

MQTT_TOPIC = "hamed/esp32/led"


# =========================================================
# RENDER
# =========================================================

RENDER_URL = (
    "https://telegram-esp32-control.onrender.com"
)

# Render این مقدار را خودش می‌دهد
PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)

WEBHOOK_SECRET = "HamedESP32_2026_X9"


# =========================================================
# FILE
# =========================================================

REPORT_FILE = "temperature_report.csv"

# ذخیره خودکار هر 60 ثانیه
AUTO_LOG_INTERVAL = 60


# =========================================================
# GLOBAL VARIABLES
# =========================================================

app = FastAPI()

telegram_app = None

main_loop = None

latest_temperature = None

latest_temperature_time = None

pending_temperature_future = None

temperature_request_lock = None


# =========================================================
# REPORT TASK
# =========================================================

temperature_logger_task = None

continuous_tasks = {}

waiting_for_interval = set()


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
        [
            "📡 وضعیت سیستم",
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


# =========================================================
# CSV FILE
# =========================================================

def initialize_report_file():

    try:

        if not os.path.exists(
            REPORT_FILE
        ):

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

            print(
                "Temperature report file created."
            )

    except Exception as e:

        print(
            "Report file creation error:"
        )

        print(e)


# =========================================================
# SAVE TEMPERATURE
# =========================================================

def save_temperature(
    temperature
):

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
                    now.strftime(
                        "%Y-%m-%d"
                    ),
                    now.strftime(
                        "%H:%M:%S"
                    ),
                    f"{temperature:.2f}",
                ]
            )

        print(
            "======================================"
        )

        print(
            "TEMPERATURE SAVED"
        )

        print(
            f"Temperature: "
            f"{temperature:.2f} C"
        )

        print(
            f"Time: "
            f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        print(
            "======================================"
        )

    except Exception as e:

        print(
            "Temperature save error:"
        )

        print(e)


# =========================================================
# MQTT CALLBACK - CONNECT
# =========================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties,
):

    print()
    print(
        "======================================"
    )

    print(
        "MQTT STATUS"
    )

    print(
        "Connected to HiveMQ"
    )

    print(
        f"Reason code: {reason_code}"
    )

    print(
        "======================================"
    )


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
                f"Subscribe failed: {result}"
            )


# =========================================================
# MQTT CALLBACK - DISCONNECT
# =========================================================

def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties,
):

    print()
    print(
        "MQTT disconnected"
    )

    print(
        f"Reason code: {reason_code}"
    )


# =========================================================
# DELIVER TEMPERATURE
# =========================================================

def deliver_temperature(
    temperature
):

    global pending_temperature_future

    if (
        pending_temperature_future
        is not None
        and not pending_temperature_future.done()
    ):

        pending_temperature_future.set_result(
            temperature
        )

    pending_temperature_future = None


# =========================================================
# MQTT CALLBACK - MESSAGE
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
            .decode(
                "utf-8",
                errors="ignore",
            )
            .strip()
        )

    except Exception as e:

        print(
            "MQTT decode error:"
        )

        print(e)

        return


    print()
    print(
        "======================================"
    )

    print(
        "MQTT MESSAGE"
    )

    print(
        f"Topic: {message.topic}"
    )

    print(
        f"Message: {payload}"
    )

    print(
        "======================================"
    )


    # =====================================================
    # TEMPERATURE
    # =====================================================

    if payload.startswith(
        "TEMP:"
    ):

        try:

            temperature = float(
                payload[5:].strip()
            )


            latest_temperature = (
                temperature
            )

            latest_temperature_time = (
                datetime.now()
            )


            print(
                f"Temperature received: "
                f"{temperature:.2f} C"
            )


            # ---------------------------------------------
            # اگر درخواست دما در حال انتظار است
            # نتیجه را به همان درخواست تحویل بده
            # ---------------------------------------------

            if main_loop:

                main_loop.call_soon_threadsafe(
                    deliver_temperature,
                    temperature,
                )


        except ValueError:

            print(
                "Invalid temperature value."
            )

        return


    # =====================================================
    # TEMPERATURE ERROR
    # =====================================================

    if payload == "TEMP_ERROR":

        print(
            "ESP32 reported DS18B20 error."
        )

        if main_loop:

            main_loop.call_soon_threadsafe(
                deliver_temperature,
                None,
            )

        return


# =========================================================
# MQTT CLIENT
# =========================================================

client_id = (
    "Telegram_Render_"
    + uuid.uuid4().hex[:12]
)


mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=client_id,
)


mqtt_client.username_pw_set(
    MQTT_USERNAME,
    MQTT_PASSWORD,
)


mqtt_client.tls_set(
    cert_reqs=ssl.CERT_REQUIRED,
    tls_version=ssl.PROTOCOL_TLS_CLIENT,
)


mqtt_client.reconnect_delay_set(
    min_delay=2,
    max_delay=30,
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

        # connect_async اجازه می‌دهد
        # Paho اتصال را خودش مدیریت کند

        mqtt_client.connect_async(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=60,
        )

        mqtt_client.loop_start()

        print(
            "MQTT network loop started."
        )

    except Exception as e:

        print(
            "MQTT START ERROR:"
        )

        print(e)


# =========================================================
# REQUEST FRESH TEMPERATURE
# =========================================================

async def request_temperature():

    global pending_temperature_future

    if not mqtt_client.is_connected():

        print(
            "MQTT is not connected."
        )

        return None


    # جلوگیری از هم‌زمان شدن چند درخواست
    async with temperature_request_lock:

        loop = asyncio.get_running_loop()

        future = loop.create_future()

        pending_temperature_future = (
            future
        )


        print(
            "MQTT -> GET_TEMP"
        )


        result = mqtt_client.publish(
            MQTT_TOPIC,
            "GET_TEMP",
            qos=1,
            retain=False,
        )


        if (
            result.rc
            != mqtt.MQTT_ERR_SUCCESS
        ):

            pending_temperature_future = None

            print(
                f"GET_TEMP publish failed: "
                f"{result.rc}"
            )

            return None


        try:

            temperature = await asyncio.wait_for(
                future,
                timeout=10,
            )

            return temperature


        except asyncio.TimeoutError:

            print(
                "GET_TEMP timeout."
            )

            return None


        finally:

            if (
                pending_temperature_future
                is future
            ):

                pending_temperature_future = None


# =========================================================
# AUTOMATIC 60 SECOND LOGGER
# =========================================================

async def automatic_temperature_logger():

    print()
    print(
        "======================================"
    )

    print(
        "AUTOMATIC TEMPERATURE LOGGER"
    )

    print(
        "Interval: 60 seconds"
    )

    print(
        "Status: ACTIVE"
    )

    print(
        "======================================"
    )


    while True:

        try:

            # دقیقاً هر 60 ثانیه یک
            # درخواست جدید می‌فرستیم

            await asyncio.sleep(
                AUTO_LOG_INTERVAL
            )


            temperature = (
                await request_temperature()
            )


            if temperature is not None:

                save_temperature(
                    temperature
                )

            else:

                print(
                    "No fresh temperature received. "
                    "Nothing saved."
                )


        except asyncio.CancelledError:

            print(
                "Automatic logger stopped."
            )

            break


        except Exception as e:

            print(
                "Automatic logger error:"
            )

            print(e)


# =========================================================
# SECURITY
# =========================================================

def is_allowed(
    update: Update
):

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
# START COMMAND
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_chat:
        return

    if not update.message:
        return


    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه استفاده از ربات را ندارید."
        )

        return


    chat_id = (
        update.effective_chat.id
    )


    print(
        f"Telegram Chat ID: {chat_id}"
    )


    await update.message.reply_text(

        "🤖 ESP32 Control Bot\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",

        reply_markup=main_menu(),
    )


# =========================================================
# CURRENT TEMPERATURE
# =========================================================

async def show_current_temperature(
    update: Update
):

    await update.message.reply_text(
        "⏳ در حال دریافت دمای جدید..."
    )


    temperature = (
        await request_temperature()
    )


    if temperature is None:

        await update.message.reply_text(

            "❌ دریافت دما از ESP32 انجام نشد.\n\n"
            "مطمئن شوید ESP32 روشن و متصل به MQTT است.",

            reply_markup=main_menu(),
        )

        return


    now = datetime.now()


    await update.message.reply_text(

        "🌡️ دمای فعلی ESP32\n\n"

        f"🌡️ {temperature:.2f} °C\n\n"

        f"🕐 زمان دریافت:\n"
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}",

        reply_markup=main_menu(),
    )


# =========================================================
# LED ON
# =========================================================

async def led_on(
    update: Update
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
        retain=False,
    )


    if result.rc == mqtt.MQTT_ERR_SUCCESS:

        print(
            "MQTT -> ON"
        )


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
    update: Update
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
        retain=False,
    )


    if result.rc == mqtt.MQTT_ERR_SUCCESS:

        print(
            "MQTT -> OFF"
        )


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
# SEND REPORT FILE
# =========================================================

async def send_report(
    update: Update
):

    initialize_report_file()


    try:

        file_size = os.path.getsize(
            REPORT_FILE
        )


        if file_size <= 50:

            await update.message.reply_text(

                "⚠️ فایل گزارش هنوز رکوردی ندارد.\n\n"
                "حداقل یک دمای جدید باید در فایل ثبت شود.",

                reply_markup=main_menu(),
            )

            return


        with open(
            REPORT_FILE,
            "rb"
        ) as file:

            await update.message.reply_document(

                document=file,

                filename=(
                    "temperature_report.csv"
                ),

                caption=(
                    "📊 گزارش دمای ESP32\n\n"
                    "📝 ثبت خودکار هر 60 ثانیه"
                ),
            )


        await update.message.reply_text(

            "✅ فایل گزارش ارسال شد.",

            reply_markup=main_menu(),
        )


    except Exception as e:

        print(
            "Report sending error:"
        )

        print(e)


        await update.message.reply_text(

            "❌ ارسال فایل گزارش انجام نشد.",

            reply_markup=main_menu(),
        )


# =========================================================
# CONTINUOUS TEMPERATURE REPORT
# =========================================================

async def continuous_temperature_report(
    chat_id,
    interval,
):

    print()
    print(
        f"Continuous report STARTED "
        f"for {chat_id}"
    )

    print(
        f"Interval = {interval} seconds"
    )


    try:

        while (
            chat_id
            in continuous_tasks
        ):

            temperature = (
                await request_temperature()
            )


            if temperature is None:

                await telegram_app.bot.send_message(

                    chat_id=chat_id,

                    text=(
                        "⚠️ دریافت دمای جدید "
                        "از ESP32 انجام نشد."
                    ),
                )

            else:

                now = datetime.now()


                await telegram_app.bot.send_message(

                    chat_id=chat_id,

                    text=(

                        "📡 گزارش مستمر دما\n\n"

                        f"🌡️ "
                        f"{temperature:.2f} °C\n\n"

                        f"🕐 "
                        f"{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

                        f"⏱️ هر "
                        f"{interval:g} ثانیه"
                    ),
                )


            await asyncio.sleep(
                interval
            )


    except asyncio.CancelledError:

        print(
            f"Continuous report "
            f"STOPPED for {chat_id}"
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
    update: Update
):

    chat_id = (
        update.effective_chat.id
    )


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
        "دمای جدید ارسال شود؟\n\n"

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
    update: Update
):

    chat_id = (
        update.effective_chat.id
    )


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
    update: Update
):

    mqtt_status = (
        "🟢 Connected"
        if mqtt_client.is_connected()
        else "🔴 Disconnected"
    )


    if latest_temperature is None:

        temperature_text = (
            "❌ هنوز دریافت نشده"
        )

    else:

        temperature_text = (
            f"{latest_temperature:.2f} °C"
        )


    reporting = (
        "🟢 فعال"
        if update.effective_chat.id
        in continuous_tasks
        else "🔴 غیرفعال"
    )


    await update.message.reply_text(

        "📊 وضعیت سیستم\n\n"

        f"📡 MQTT: {mqtt_status}\n"

        f"🌡️ دما: {temperature_text}\n"

        f"📡 گزارش مستمر: {reporting}\n\n"

        f"MQTT Topic:\n"
        f"{MQTT_TOPIC}\n\n"

        "ESP32:\n"
        "GPIO2 = LED\n"
        "GPIO23 = DS18B20",

        reply_markup=main_menu(),
    )


# =========================================================
# TEXT HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_chat:
        return

    if not update.message:
        return


    if not is_allowed(update):

        await update.message.reply_text(

            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return


    chat_id = (
        update.effective_chat.id
    )


    text = update.message.text.strip()


    print()
    print(
        "--------------------------------------"
    )

    print(
        f"Chat ID: {chat_id}"
    )

    print(
        f"Message: {text}"
    )

    print(
        "--------------------------------------"
    )


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
    # WAITING FOR INTERVAL
    # =====================================================

    if chat_id in waiting_for_interval:

        try:

            interval = float(text)


            if interval < 1:

                raise ValueError


            if interval > 86400:

                await update.message.reply_text(

                    "❌ حداکثر فاصله 86400 ثانیه است."
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

                "✅ گزارش مستمر فعال شد.\n\n"

                f"⏱️ هر {interval:g} ثانیه\n\n"

                "برای توقف، "
                "⛔ توقف گزارش مستمر "
                "را بزنید.",

                reply_markup=main_menu(),
            )


        except ValueError:

            await update.message.reply_text(

                "❌ لطفاً فقط یک عدد وارد کنید.\n\n"
                "مثلاً:\n"
                "10\n"
                "30\n"
                "60",
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
    # CURRENT TEMP
    # =====================================================

    if text in (
        "🌡️ دمای فعلی",
        "دمای فعلی",
        "دریافت دما",
        "temperature",
        "temp",
    ):

        await show_current_temperature(
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
        "📡 وضعیت سیستم",
        "وضعیت سیستم",
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

        "❓ گزینه نامعتبر است.\n\n"
        "لطفاً از منوی پایین استفاده کنید.",

        reply_markup=main_menu(),
    )


# =========================================================
# HEALTH
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

    received_secret = (
        request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )
    )


    if received_secret != WEBHOOK_SECRET:

        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )


    try:

        data = await request.json()


        update = Update.de_json(
            data,
            telegram_app.bot,
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
    global main_loop
    global temperature_request_lock
    global temperature_logger_task


    main_loop = asyncio.get_running_loop()

    temperature_request_lock = asyncio.Lock()


    print()
    print(
        "======================================"
    )

    print(
        "     TELEGRAM ESP32 RENDER BOT"
    )

    print(
        "======================================"
    )


    # -----------------------------------------------------
    # CSV
    # -----------------------------------------------------

    initialize_report_file()


    # -----------------------------------------------------
    # MQTT
    # -----------------------------------------------------

    connect_mqtt()


    # -----------------------------------------------------
    # Telegram
    # -----------------------------------------------------

    telegram_app = (

        Application.builder()

        .token(
            TELEGRAM_BOT_TOKEN
        )

        .updater(None)

        .build()
    )


    # -----------------------------------------------------
    # Handlers
    # -----------------------------------------------------

    telegram_app.add_handler(

        CommandHandler(
            "start",
            start_command,
        )
    )


    telegram_app.add_handler(

        CommandHandler(
            "led_on",
            led_on,
        )
    )


    telegram_app.add_handler(

        CommandHandler(
            "led_off",
            led_off,
        )
    )


    telegram_app.add_handler(

        CommandHandler(
            "temperature",
            show_current_temperature,
        )
    )


    telegram_app.add_handler(

        CommandHandler(
            "report",
            send_report,
        )
    )


    telegram_app.add_handler(

        CommandHandler(
            "status",
            show_status,
        )
    )


    telegram_app.add_handler(

        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )


    # -----------------------------------------------------
    # Initialize
    # -----------------------------------------------------

    await telegram_app.initialize()

    await telegram_app.start()


    # -----------------------------------------------------
    # Automatic Logger
    # -----------------------------------------------------

    temperature_logger_task = asyncio.create_task(

        automatic_temperature_logger()
    )


    # -----------------------------------------------------
    # Webhook
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

        allowed_updates=Update.ALL_TYPES,
    )


    print()
    print(
        "Telegram webhook configured."
    )

    print(
        "Bot is ready."
    )

    print(
        "Automatic logger: ACTIVE"
    )

    print(
        "Interval: 60 seconds"
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
    # Automatic logger
    # -----------------------------------------------------

    if temperature_logger_task:

        temperature_logger_task.cancel()

        try:

            await temperature_logger_task

        except asyncio.CancelledError:

            pass


        temperature_logger_task = None


    # -----------------------------------------------------
    # Continuous reports
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

