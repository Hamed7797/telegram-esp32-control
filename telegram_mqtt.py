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

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"

ALLOWED_CHAT_ID = "0"


# =========================================================
# HIVEMQ
# =========================================================

MQTT_HOST = (
    "c8f63357997a47a8b37f0495aac24c7d"
    ".s1.eu.hivemq.cloud"
)

MQTT_PORT = 8883

MQTT_USERNAME = "hamed_esp32"

MQTT_PASSWORD = "YOUR_MQTT_PASSWORD"

# =========================================================
# فقط یک Topic
# =========================================================

MQTT_TOPIC = "hamed/esp32/led"


# =========================================================
# RENDER
# =========================================================

RENDER_URL = "https://telegram-esp32-control.onrender.com"

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
# MQTT VARIABLES
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


# =========================================================
# TEMPERATURE
# =========================================================

latest_temperature = None

temperature_waiting = False

temperature_event = asyncio.Event()


# =========================================================
# CONTINUOUS REPORTING
# =========================================================

report_tasks = {}


# =========================================================
# MQTT CONNECT
# =========================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties
):

    print()
    print("======================================")
    print("MQTT STATUS")
    print("Connected to HiveMQ")
    print(f"Reason code: {reason_code}")
    print("======================================")


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

    print()
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

    try:

        payload = (
            message.payload
            .decode("utf-8")
            .strip()
        )

        print()
        print("======================================")
        print("MQTT MESSAGE")
        print(f"Topic: {message.topic}")
        print(f"Message: {payload}")
        print("======================================")

        # ---------------------------------------------
        # Temperature
        # ---------------------------------------------

        if payload.startswith("TEMP:"):

            value = payload.replace(
                "TEMP:",
                ""
            ).strip()

            try:

                latest_temperature = float(value)

                print(
                    f"Temperature received: "
                    f"{latest_temperature:.2f} C"
                )

                try:
                    temperature_event.set()

                except Exception:
                    pass

            except ValueError:

                print(
                    "Invalid temperature value."
                )

        elif payload == "TEMP_ERROR":

            print(
                "ESP32 reported DS18B20 error."
            )

            try:
                temperature_event.set()

            except Exception:
                pass

    except Exception as e:

        print(
            "MQTT message error:",
            e
        )


# =========================================================
# ASSIGN CALLBACKS
# =========================================================

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

        # Subscribe to same topic
        mqtt_client.subscribe(
            MQTT_TOPIC,
            qos=1
        )

        print(
            "Subscribed:",
            MQTT_TOPIC
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

    if not update.effective_chat:
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
            "🟢 LED ON",
            "🔴 LED OFF"
        ],

        [
            "🌡️ دمای فعلی"
        ],

        [
            "📊 گزارش مستمر دما"
        ],

        [
            "⛔ توقف گزارش"
        ],

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================================================
# START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    print()
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
# GET TEMPERATURE
# =========================================================

async def get_temperature(
    update: Update
):

    global latest_temperature
    global temperature_waiting
    global temperature_event

    if not mqtt_client.is_connected():

        await update.message.reply_text(
            "❌ اتصال MQTT برقرار نیست."
        )

        return

    # ---------------------------------------------
    # Reset previous value
    # ---------------------------------------------

    latest_temperature = None

    temperature_waiting = True

    temperature_event = asyncio.Event()

    # ---------------------------------------------
    # Send GET_TEMP
    # ---------------------------------------------

    result = mqtt_client.publish(
        MQTT_TOPIC,
        "GET_TEMP",
        qos=1
    )

    if result.rc != mqtt.MQTT_ERR_SUCCESS:

        temperature_waiting = False

        await update.message.reply_text(
            "❌ درخواست دما ارسال نشد."
        )

        return

    print(
        "MQTT -> GET_TEMP"
    )

    # ---------------------------------------------
    # Wait for ESP32 response
    # ---------------------------------------------

    try:

        await asyncio.wait_for(
            temperature_event.wait(),
            timeout=8
        )

    except asyncio.TimeoutError:

        temperature_waiting = False

        await update.message.reply_text(
            "❌ دریافت دما از ESP32 انجام نشد."
        )

        return

    temperature_waiting = False

    # ---------------------------------------------
    # Check result
    # ---------------------------------------------

    if latest_temperature is None:

        await update.message.reply_text(
            "❌ سنسور DS18B20 پاسخ معتبر نداد."
        )

        return

    await update.message.reply_text(

        "🌡️ دمای فعلی ESP32:\n\n"
        f"🌡️ {latest_temperature:.2f} °C",

        reply_markup=main_menu()
    )


# =========================================================
# CONTINUOUS REPORT
# =========================================================

async def continuous_temperature_report(
    chat_id: int,
    interval: int,
    context: ContextTypes.DEFAULT_TYPE
):

    print()
    print(
        f"Starting temperature report "
        f"for chat {chat_id}"
    )

    try:

        while True:

            # -----------------------------------------
            # MQTT check
            # -----------------------------------------

            if not mqtt_client.is_connected():

                try:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "❌ اتصال MQTT برقرار نیست."
                        )
                    )

                except Exception:
                    pass

                await asyncio.sleep(interval)

                continue

            # -----------------------------------------
            # Reset
            # -----------------------------------------

            global latest_temperature
            global temperature_event

            latest_temperature = None

            temperature_event = asyncio.Event()

            # -----------------------------------------
            # Request temperature
            # -----------------------------------------

            result = mqtt_client.publish(
                MQTT_TOPIC,
                "GET_TEMP",
                qos=1
            )

            if result.rc != mqtt.MQTT_ERR_SUCCESS:

                await asyncio.sleep(interval)

                continue

            print(
                f"Report -> GET_TEMP "
                f"(chat {chat_id})"
            )

            # -----------------------------------------
            # Wait for ESP32
            # -----------------------------------------

            try:

                await asyncio.wait_for(
                    temperature_event.wait(),
                    timeout=8
                )

            except asyncio.TimeoutError:

                try:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "⚠️ دریافت دما از ESP32 "
                            "انجام نشد."
                        )
                    )

                except Exception:
                    pass

                await asyncio.sleep(interval)

                continue

            # -----------------------------------------
            # Send temperature
            # -----------------------------------------

            if latest_temperature is not None:

                await context.bot.send_message(

                    chat_id=chat_id,

                    text=(
                        "📊 گزارش دما\n\n"
                        f"🌡️ دما: "
                        f"{latest_temperature:.2f} °C"
                    )
                )

            # -----------------------------------------
            # Wait
            # -----------------------------------------

            await asyncio.sleep(interval)

    except asyncio.CancelledError:

        print(
            f"Temperature report stopped "
            f"for chat {chat_id}"
        )

        raise


# =========================================================
# START CONTINUOUS REPORT
# =========================================================

async def start_temperature_report(
    update: Update,
    interval: int
):

    chat_id = update.effective_chat.id

    # ---------------------------------------------
    # Stop previous report
    # ---------------------------------------------

    if chat_id in report_tasks:

        old_task = report_tasks[chat_id]

        if not old_task.done():

            old_task.cancel()

    # ---------------------------------------------
    # Create new task
    # ---------------------------------------------

    task = asyncio.create_task(

        continuous_temperature_report(
            chat_id,
            interval,
            update.get_bot().application
        )
    )

    report_tasks[chat_id] = task

    await update.message.reply_text(

        "📊 گزارش مستمر دما فعال شد.\n\n"
        f"⏱️ هر {interval} ثانیه یک گزارش ارسال می‌شود.\n\n"
        "برای توقف، گزینه «⛔ توقف گزارش» را بزنید.",

        reply_markup=main_menu()
    )


# =========================================================
# STOP REPORT
# =========================================================

async def stop_temperature_report(
    update: Update
):

    chat_id = update.effective_chat.id

    if chat_id not in report_tasks:

        await update.message.reply_text(

            "ℹ️ در حال حاضر گزارش مستمر "
            "دما فعال نیست.",

            reply_markup=main_menu()
        )

        return

    task = report_tasks[chat_id]

    if not task.done():

        task.cancel()

    del report_tasks[chat_id]

    await update.message.reply_text(

        "⛔ گزارش مستمر دما متوقف شد.",

        reply_markup=main_menu()
    )


# =========================================================
# HANDLE TEXT
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    if not update.message:
        return

    text = (
        update.message.text
        .strip()
        .lower()
    )

    chat_id = update.effective_chat.id

    print()
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

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return

    # =====================================================
    # LED ON
    # =====================================================

    if text in [
        "🟢 led on",
        "led on"
    ]:

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

        return

    # =====================================================
    # LED OFF
    # =====================================================

    if text in [
        "🔴 led off",
        "led off"
    ]:

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

        return

    # =====================================================
    # CURRENT TEMPERATURE
    # =====================================================

    if text in [
        "🌡️ دمای فعلی",
        "دمای فعلی",
        "temperature",
        "temp"
    ]:

        await get_temperature(update)

        return

    # =====================================================
    # CONTINUOUS REPORT
    # =====================================================

    if text in [
        "📊 گزارش مستمر دما",
        "گزارش مستمر دما"
    ]:

        context.user_data[
            "waiting_for_interval"
        ] = True

        await update.message.reply_text(

            "⏱️ لطفاً مشخص کنید هر چند ثانیه "
            "یک بار گزارش دما ارسال شود.\n\n"

            "مثلاً:\n"
            "5\n"
            "10\n"
            "30\n"
            "60",

            reply_markup=ReplyKeyboardRemove()
        )

        return

    # =====================================================
    # STOP REPORT
    # =====================================================

    if text in [
        "⛔ توقف گزارش",
        "توقف گزارش"
    ]:

        await stop_temperature_report(
            update
        )

        return

    # =====================================================
    # INTERVAL
    # =====================================================

    if context.user_data.get(
        "waiting_for_interval",
        False
    ):

        try:

            interval = int(text)

            if interval < 2:

                await update.message.reply_text(

                    "⚠️ حداقل زمان گزارش "
                    "2 ثانیه است.\n\n"
                    "یک عدد بزرگ‌تر وارد کنید."
                )

                return

            if interval > 3600:

                await update.message.reply_text(

                    "⚠️ حداکثر زمان گزارش "
                    "3600 ثانیه است.\n\n"
                    "لطفاً مقدار دیگری وارد کنید."
                )

                return

        except ValueError:

            await update.message.reply_text(

                "❌ لطفاً فقط عدد وارد کنید.\n\n"
                "مثلاً:\n"
                "5\n"
                "10\n"
                "30\n"
                "60"
            )

            return

        context.user_data[
            "waiting_for_interval"
        ] = False

        await start_temperature_report(
            update,
            interval
        )

        return

    # =====================================================
    # INVALID
    # =====================================================

    await update.message.reply_text(

        "❓ لطفاً یکی از گزینه‌های منو را انتخاب کنید.",

        reply_markup=main_menu()
    )


# =========================================================
# HEALTH
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
            "Webhook error:",
            e
        )

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

    print()
    print("======================================")
    print("     TELEGRAM ESP32 RENDER BOT")
    print("======================================")

    # -----------------------------------------------------
    # MQTT
    # -----------------------------------------------------

    connect_mqtt()

    # -----------------------------------------------------
    # Telegram
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
    # Webhook
    # -----------------------------------------------------

    webhook_url = (
        RENDER_URL +
        "/telegram"
    )

    print()
    print(
        "Setting Telegram webhook..."
    )

    print(webhook_url)

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

    print()


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown_event():

    print(
        "Stopping bot..."
    )

    # Stop temperature reports

    for task in report_tasks.values():

        if not task.done():

            task.cancel()

    report_tasks.clear()

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
