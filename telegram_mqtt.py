
import os
import ssl
import asyncio
import logging

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

TELEGRAM_BOT_TOKEN = "8814366440:AAH_KHZ2jkce9AyIISaKq0OJ9Wk2oY6aRXU"

# فعلاً 0 یعنی همه کاربران مجاز هستند
ALLOWED_CHAT_ID = "0"


# =========================================================
# HIVEMQ
# =========================================================

MQTT_HOST = "c8f63357997a47a8b37f0495aac24c7d.s1.eu.hivemq.cloud"
MQTT_PORT = 8883

MQTT_USERNAME = "hamed_esp32"
MQTT_PASSWORD = "Ha00102030meD@"

# فقط یک Topic برای همه چیز
MQTT_TOPIC = "hamed/esp32/led"


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
# TEMPERATURE REPORTING
# =========================================================

# وضعیت گزارش مستمر برای هر کاربر
temperature_tasks = {}

# زمانی که آخرین درخواست دما ارسال شده
temperature_waiters = {}


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
# MQTT MESSAGE CALLBACK
# =========================================================

def on_message(
    client,
    userdata,
    msg
):

    try:

        message = msg.payload.decode("utf-8").strip()

        print("======================================")
        print("MQTT MESSAGE RECEIVED")
        print(f"Topic: {msg.topic}")
        print(f"Message: {message}")
        print("======================================")

        # ---------------------------------------------
        # دریافت دما
        # ---------------------------------------------

        if message.startswith("TEMP:"):

            temperature = message[5:].strip()

            # ارسال به Event Loop اصلی
            if telegram_app:

                asyncio.run_coroutine_threadsafe(
                    process_temperature(temperature),
                    telegram_app.loop
                )

    except Exception as e:

        print("MQTT message error:")
        print(e)


# =========================================================
# PROCESS TEMPERATURE
# =========================================================

async def process_temperature(temperature):

    # تمام کاربرانی که منتظر پاسخ دما هستند
    waiters = list(temperature_waiters.items())

    temperature_waiters.clear()

    for chat_id, future in waiters:

        try:

            if not future.done():

                future.set_result(temperature)

        except Exception as e:

            print("Temperature future error:")
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
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [

        ["🟢 LED ON", "🔴 LED OFF"],

        ["🌡️ دمای لحظه‌ای"],

        ["📊 گزارش مستمر دما"],

        ["⏹️ توقف گزارش"],

        ["📡 وضعیت سیستم"],

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
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
    print(f"Telegram Chat ID: {chat_id}")
    print("Command: /start")
    print("--------------------------------------")

    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return

    await update.message.reply_text(

        "🤖 ESP32 Control Bot\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",

        reply_markup=main_menu()
    )


# =========================================================
# GET TEMPERATURE
# =========================================================

async def get_temperature():

    if not mqtt_client.is_connected():

        return None

    loop = asyncio.get_running_loop()

    future = loop.create_future()

    # فعلاً فقط یک درخواست فعال
    temperature_waiters["main"] = future

    result = mqtt_client.publish(
        MQTT_TOPIC,
        "GET_TEMP",
        qos=1
    )

    if result.rc != mqtt.MQTT_ERR_SUCCESS:

        temperature_waiters.pop("main", None)

        return None

    try:

        temperature = await asyncio.wait_for(
            future,
            timeout=8
        )

        return temperature

    except asyncio.TimeoutError:

        temperature_waiters.pop("main", None)

        return None


# =========================================================
# CONTINUOUS TEMPERATURE REPORT
# =========================================================

async def temperature_report(
    chat_id,
    interval,
    context
):

    print("--------------------------------------")
    print("Temperature reporting started")
    print(f"Chat ID: {chat_id}")
    print(f"Interval: {interval} seconds")
    print("--------------------------------------")

    try:

        while True:

            # -----------------------------------------
            # درخواست دما
            # -----------------------------------------

            temperature = await get_temperature()

            if temperature is None:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ دریافت دما از ESP32 انجام نشد."
                )

            else:

                await context.bot.send_message(

                    chat_id=chat_id,

                    text=(
                        "🌡️ گزارش دما\n\n"
                        f"دمای فعلی: {temperature} °C\n\n"
                        f"⏱️ فاصله گزارش: {interval} ثانیه"
                    )
                )

            # -----------------------------------------
            # صبر تا گزارش بعدی
            # -----------------------------------------

            await asyncio.sleep(interval)

    except asyncio.CancelledError:

        print(
            f"Temperature reporting stopped "
            f"for chat {chat_id}"
        )

        raise

    except Exception as e:

        print("Temperature report error:")
        print(e)


# =========================================================
# START CONTINUOUS REPORT
# =========================================================

async def start_temperature_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    # اگر قبلاً گزارش فعال است
    if chat_id in temperature_tasks:

        await update.message.reply_text(
            "📊 گزارش مستمر دما از قبل فعال است."
        )

        return

    context.user_data["waiting_temperature_interval"] = True

    await update.message.reply_text(

        "📊 گزارش مستمر دما\n\n"
        "لطفاً فاصله زمانی ارسال گزارش را بر حسب ثانیه وارد کنید.\n\n"
        "مثلاً:\n"
        "5\n\n"
        "یعنی هر 5 ثانیه یک‌بار دما ارسال شود.",

        reply_markup=ReplyKeyboardRemove()
    )


# =========================================================
# STOP TEMPERATURE REPORT
# =========================================================

async def stop_temperature_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    task = temperature_tasks.get(chat_id)

    if task:

        task.cancel()

        temperature_tasks.pop(
            chat_id,
            None
        )

        context.user_data[
            "waiting_temperature_interval"
        ] = False

        await update.message.reply_text(

            "⏹️ گزارش مستمر دما متوقف شد.",

            reply_markup=main_menu()
        )

    else:

        await update.message.reply_text(

            "ℹ️ در حال حاضر گزارش مستمر دما فعال نیست.",

            reply_markup=main_menu()
        )


# =========================================================
# HANDLE TEXT MESSAGE
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

    text = update.message.text.strip()

    text_lower = text.lower()

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
    # WAITING FOR INTERVAL
    # =====================================================

    if context.user_data.get(
        "waiting_temperature_interval",
        False
    ):

        try:

            interval = float(text)

            if interval < 2:

                await update.message.reply_text(
                    "⚠️ لطفاً عددی حداقل 2 ثانیه وارد کنید."
                )

                return

            if interval > 86400:

                await update.message.reply_text(
                    "⚠️ حداکثر فاصله مجاز 86400 ثانیه است."
                )

                return

        except ValueError:

            await update.message.reply_text(
                "❌ لطفاً فقط عدد وارد کنید.\n\n"
                "مثلاً:\n"
                "5"
            )

            return


        # ---------------------------------------------
        # ثبت فاصله
        # ---------------------------------------------

        context.user_data[
            "waiting_temperature_interval"
        ] = False


        # اگر قبلاً task وجود داشت
        old_task = temperature_tasks.get(chat_id)

        if old_task:

            old_task.cancel()


        # ---------------------------------------------
        # ساخت Task جدید
        # ---------------------------------------------

        task = asyncio.create_task(

            temperature_report(
                chat_id,
                interval,
                context
            )
        )

        temperature_tasks[chat_id] = task


        await update.message.reply_text(

            "✅ گزارش مستمر دما فعال شد.\n\n"
            f"⏱️ هر {interval:g} ثانیه یک گزارش ارسال می‌شود.\n\n"
            "برای توقف، دکمه «⏹️ توقف گزارش» را بزنید.",

            reply_markup=main_menu()
        )

        return


    # =====================================================
    # LED ON
    # =====================================================

    if text == "🟢 LED ON" or text_lower == "led on":

        if not mqtt_client.is_connected():

            await update.message.reply_text(
                "❌ اتصال MQTT برقرار نیست.",
                reply_markup=main_menu()
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
                "❌ ارسال فرمان انجام نشد.",
                reply_markup=main_menu()
            )

        return


    # =====================================================
    # LED OFF
    # =====================================================

    if text == "🔴 LED OFF" or text_lower == "led off":

        if not mqtt_client.is_connected():

            await update.message.reply_text(
                "❌ اتصال MQTT برقرار نیست.",
                reply_markup=main_menu()
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
                "❌ ارسال فرمان انجام نشد.",
                reply_markup=main_menu()
            )

        return


    # =====================================================
    # SINGLE TEMPERATURE
    # =====================================================

    if (
        text == "🌡️ دمای لحظه‌ای"
        or text_lower == "temperature"
        or text_lower == "temp"
    ):

        if not mqtt_client.is_connected():

            await update.message.reply_text(
                "❌ اتصال MQTT برقرار نیست.",
                reply_markup=main_menu()
            )

            return

        await update.message.reply_text(
            "⏳ در حال دریافت دما..."
        )

        temperature = await get_temperature()

        if temperature is None:

            await update.message.reply_text(

                "❌ دریافت دما از ESP32 انجام نشد.",

                reply_markup=main_menu()
            )

        else:

            await update.message.reply_text(

                f"🌡️ دمای فعلی ESP32:\n\n"
                f"**{temperature} °C**",

                parse_mode="Markdown",

                reply_markup=main_menu()
            )

        return


    # =====================================================
    # CONTINUOUS REPORT
    # =====================================================

    if text == "📊 گزارش مستمر دما":

        await start_temperature_report(
            update,
            context
        )

        return


    # =====================================================
    # STOP REPORT
    # =====================================================

    if text == "⏹️ توقف گزارش":

        await stop_temperature_report(
            update,
            context
        )

        return


    # =====================================================
    # STATUS
    # =====================================================

    if (
        text == "📡 وضعیت سیستم"
        or text_lower == "status"
    ):

        mqtt_state = (
            "🟢 Connected"
            if mqtt_client.is_connected()
            else "🔴 Disconnected"
        )

        reporting = (
            "🟢 فعال"
            if chat_id in temperature_tasks
            else "🔴 غیرفعال"
        )

        await update.message.reply_text(

            "🤖 ESP32 Control\n\n"
            f"📡 MQTT: {mqtt_state}\n"
            f"📊 گزارش دما: {reporting}\n\n"
            f"📌 Topic:\n"
            f"{MQTT_TOPIC}",

            reply_markup=main_menu()
        )

        return


    # =====================================================
    # OLD COMMANDS
    # =====================================================

    if text_lower == "/menu":

        await update.message.reply_text(

            "📋 منوی کنترل ESP32:",

            reply_markup=main_menu()
        )

        return


    # =====================================================
    # INVALID
    # =====================================================

    await update.message.reply_text(

        "❓ گزینه موردنظر را از منوی پایین انتخاب کنید.",

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

    # =====================================================
    # MQTT
    # =====================================================

    connect_mqtt()


    # =====================================================
    # TELEGRAM APPLICATION
    # =====================================================

    telegram_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .updater(None)
        .build()
    )


    # =====================================================
    # HANDLERS
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
    # INITIALIZE TELEGRAM
    # =====================================================

    await telegram_app.initialize()

    await telegram_app.start()


    # =====================================================
    # SET WEBHOOK
    # =====================================================

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


    # توقف تمام گزارش‌ها

    for task in temperature_tasks.values():

        task.cancel()


    temperature_tasks.clear()


    # Telegram

    if telegram_app:

        await telegram_app.stop()

        await telegram_app.shutdown()


    # MQTT

    mqtt_client.loop_stop()

    mqtt_client.disconnect()


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    uvicorn.run(

        "telegram_mqtt:app",

        host="0.0.0.0",

        port=PORT
    )
