
import asyncio
import ssl

import paho.mqtt.client as mqtt
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# TELEGRAM
# =========================================================

# توکن رباتی که از BotFather گرفتی
TELEGRAM_BOT_TOKEN = "8814366440:AAH_KHZ2jkce9AyIISaKq0OJ9Wk2oY6aRXU"

# فعلاً 0 بگذار
# بعداً Chat ID خودت را اینجا قرار می‌دهیم تا فقط خودت
# بتوانی ESP32 را کنترل کنی.
ALLOWED_CHAT_ID = 0


# =========================================================
# MQTT - HiveMQ Cloud
# =========================================================

MQTT_HOST = "c8f63357997a47a8b37f0495aac24c7d.s1.eu.hivemq.cloud"
MQTT_PORT = 8883

MQTT_USERNAME = "hamed_esp32"
MQTT_PASSWORD = "Ha00102030meD@"

# همان Topic قبلی پروژه ESP32 تو
MQTT_TOPIC_LED = "hamed/esp32/led"


# =========================================================
# MQTT CALLBACKS
# =========================================================

def on_connect(client, userdata, flags, reason_code, properties):
    print("======================================")
    print("MQTT STATUS")
    print(f"Connected to HiveMQ")
    print(f"Reason code: {reason_code}")
    print("======================================")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    print("MQTT disconnected")
    print(f"Reason code: {reason_code}")


# =========================================================
# MQTT CLIENT
# =========================================================

mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="Telegram_ESP32_Controller"
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

try:
    print("Connecting to HiveMQ...")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)

    # برای حفظ اتصال MQTT
    mqtt_client.loop_start()

except Exception as e:
    print("MQTT CONNECTION ERROR:")
    print(e)


# =========================================================
# CHECK TELEGRAM USER
# =========================================================

def is_allowed(update: Update) -> bool:

    if update.effective_chat is None:
        return False

    chat_id = update.effective_chat.id

    # اگر هنوز 0 باشد، همه کاربران موقتاً مجاز هستند
    # فقط برای مرحله تست
    if ALLOWED_CHAT_ID == 0:
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
        f"🤖 ESP32 Control Bot\n\n"
        f"Chat ID:\n"
        f"{chat_id}\n\n"
        f"دستورهای قابل استفاده:\n"
        f"led on\n"
        f"led off"
    )


# =========================================================
# HANDLE TEXT MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id

    print("--------------------------------------")
    print(f"Telegram Chat ID: {chat_id}")
    print(f"Message: {update.message.text}")
    print("--------------------------------------")

    # -----------------------------------------
    # Security
    # -----------------------------------------

    if not is_allowed(update):

        await update.message.reply_text(
            "⛔ شما اجازه کنترل این دستگاه را ندارید."
        )

        return

    # -----------------------------------------
    # دریافت متن
    # -----------------------------------------

    text = update.message.text.strip().lower()

    # -----------------------------------------
    # LED ON
    # -----------------------------------------

    if text == "led on":

        result = mqtt_client.publish(
            MQTT_TOPIC_LED,
            "ON",
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            await update.message.reply_text(
                "🟢 LED روشن شد"
            )

            print("MQTT -> ON")

        else:

            await update.message.reply_text(
                "❌ ارسال فرمان MQTT انجام نشد."
            )

    # -----------------------------------------
    # LED OFF
    # -----------------------------------------

    elif text == "led off":

        result = mqtt_client.publish(
            MQTT_TOPIC_LED,
            "OFF",
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            await update.message.reply_text(
                "🔴 LED خاموش شد"
            )

            print("MQTT -> OFF")

        else:

            await update.message.reply_text(
                "❌ ارسال فرمان MQTT انجام نشد."
            )

    # -----------------------------------------
    # دستورات ناشناخته
    # -----------------------------------------

    else:

        await update.message.reply_text(
            "❓ دستور نامعتبر است.\n\n"
            "دستورهای مجاز:\n"
            "led on\n"
            "led off"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print("")
    print("======================================")
    print("     TELEGRAM ESP32 CONTROLLER")
    print("======================================")
    print("Bot is starting...")
    print("")

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # /start
    application.add_handler(
        CommandHandler("start", start_command)
    )

    # متن معمولی
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Telegram Bot is running...")
    print("Press Ctrl+C to stop.")
    print("")

    application.run_polling()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:

        print("")
        print("Stopping program...")

    finally:

        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

        except Exception:
            pass


