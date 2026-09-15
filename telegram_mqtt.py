
import os
import ssl
import csv
import asyncio
import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt
import xlsxwriter

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

# =========================================================
# MQTT TOPIC
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

WEBHOOK_SECRET = (
    "HamedESP32_2026_X9"
)


# =========================================================
# TIMEZONE
# =========================================================

# زمان ثبت گزارش بر اساس ساعت ایران
LOCAL_TZ = ZoneInfo(
    "Asia/Tehran"
)


def current_time():
    """
    Current local time in Iran.
    """

    return datetime.now(
        LOCAL_TZ
    )


# =========================================================
# DATALOGGER
# =========================================================

CSV_FILE = (
    "temperature_datalog.csv"
)

EXCEL_FILE = (
    "temperature_datalog.xlsx"
)

# هر 60 ثانیه
DATALOG_INTERVAL = 60


# =========================================================
# GLOBAL TEMPERATURE
# =========================================================

latest_temperature = None

latest_temperature_time = None


# =========================================================
# TEMPERATURE REQUEST
# =========================================================

pending_temperature_future = None

temperature_request_lock = None

main_loop = None


# =========================================================
# TASKS
# =========================================================

temperature_logger_task = None

continuous_tasks = {}

waiting_for_interval = set()


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI()

telegram_app = None


# =========================================================
# TELEGRAM MENU
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
            "📄 دریافت دیتالاگر",
        ],

        [
            "📡 گزارش مستمر دما",
        ],

        [
            "⛔ توقف گزارش مستمر",
        ],

        [
            "📊 وضعیت سیستم",
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


# =========================================================
# CREATE CSV
# =========================================================

def initialize_csv():

    if os.path.exists(
        CSV_FILE
    ):

        return


    with open(
        CSV_FILE,
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
        "Temperature CSV file created."
    )


# =========================================================
# SAVE TEMPERATURE TO CSV
# =========================================================

def save_temperature(
    temperature
):

    initialize_csv()

    now = current_time()


    try:

        with open(
            CSV_FILE,
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
            f"Local time: "
            f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        print(
            "Timezone: Asia/Tehran"
        )

        print(
            "======================================"
        )


        # بلافاصله Excel را هم به‌روز می‌کنیم
        create_excel()


    except Exception as e:

        print(
            "CSV save error:"
        )

        print(e)


# =========================================================
# CREATE EXCEL FROM CSV
# =========================================================

def create_excel():

    initialize_csv()


    try:

        rows = []


        with open(
            CSV_FILE,
            "r",
            newline="",
            encoding="utf-8",
        ) as file:

            reader = csv.DictReader(
                file
            )

            for row in reader:

                try:

                    date_text = (
                        row["Date"]
                    )

                    time_text = (
                        row["Time"]
                    )

                    temperature = float(
                        row[
                            "Temperature_C"
                        ]
                    )


                    # ساخت Datetime واقعی
                    local_dt = datetime.strptime(
                        f"{date_text} {time_text}",
                        "%Y-%m-%d %H:%M:%S"
                    )


                    rows.append(
                        (
                            local_dt,
                            temperature
                        )
                    )


                except Exception:

                    continue


        # اگر فایل قبلی وجود دارد، جایگزین می‌شود
        workbook = xlsxwriter.Workbook(
            EXCEL_FILE
        )


        worksheet = workbook.add_worksheet(
            "Temperature Log"
        )


        # =================================================
        # FORMATS
        # =================================================

        title_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 16,
                "align": "center",
                "valign": "vcenter",
            }
        )


        header_format = workbook.add_format(
            {
                "bold": True,
                "border": 1,
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
            }
        )


        date_format = workbook.add_format(
            {
                "num_format": "yyyy-mm-dd",
                "border": 1,
            }
        )


        time_format = workbook.add_format(
            {
                "num_format": "hh:mm:ss",
                "border": 1,
            }
        )


        temperature_format = workbook.add_format(
            {
                "num_format": "0.00",
                "border": 1,
            }
        )


        # =================================================
        # TITLE
        # =================================================

        worksheet.merge_range(
            "A1:C1",
            "ESP32 Temperature Datalogger",
            title_format
        )


        # =================================================
        # HEADERS
        # =================================================

        worksheet.write(
            "A3",
            "Date",
            header_format
        )

        worksheet.write(
            "B3",
            "Time",
            header_format
        )

        worksheet.write(
            "C3",
            "Temperature (°C)",
            header_format
        )


        # =================================================
        # DATA
        # =================================================

        first_data_row = 3


        for index, (
            local_dt,
            temperature
        ) in enumerate(rows):

            row_number = (
                first_data_row
                + index
            )


            # Excel stores datetime without timezone.
            # We already converted it to Tehran local time.
            excel_dt = local_dt


            worksheet.write_datetime(
                row_number,
                0,
                excel_dt,
                date_format
            )


            worksheet.write_datetime(
                row_number,
                1,
                excel_dt,
                time_format
            )


            worksheet.write_number(
                row_number,
                2,
                temperature,
                temperature_format
            )


        # =================================================
        # COLUMN WIDTH
        # =================================================

        # این قسمت مشکل ######## را حل می‌کند
        worksheet.set_column(
            "A:A",
            15
        )

        worksheet.set_column(
            "B:B",
            12
        )

        worksheet.set_column(
            "C:C",
            20
        )

        worksheet.set_column(
            "E:E",
            3
        )

        worksheet.set_column(
            "F:F",
            18
        )


        # =================================================
        # FREEZE PANES
        # =================================================

        worksheet.freeze_panes(
            3,
            0
        )


        # =================================================
        # TABLE
        # =================================================

        if rows:

            last_data_row = (
                first_data_row
                + len(rows)
                - 1
            )


            worksheet.add_table(
                first_data_row,
                0,
                last_data_row,
                2,
                {
                    "name":
                        "TemperatureData",

                    "columns":
                        [
                            {
                                "header":
                                    "Date"
                            },

                            {
                                "header":
                                    "Time"
                            },

                            {
                                "header":
                                    "Temperature (°C)"
                            },
                        ],
                }
            )


            # =================================================
            # CHART
            # =================================================

            chart = workbook.add_chart(
                {
                    "type": "line"
                }
            )


            chart.add_series(
                {
                    "name":
                        "Temperature",

                    "categories":
                        [
                            "Temperature Log",
                            first_data_row,
                            1,
                            last_data_row,
                            1,
                        ],

                    "values":
                        [
                            "Temperature Log",
                            first_data_row,
                            2,
                            last_data_row,
                            2,
                        ],

                    "marker":
                        {
                            "type":
                                "circle",

                            "size":
                                4,
                        },
                }
            )


            chart.set_title(
                {
                    "name":
                        "Temperature vs Time"
                }
            )


            chart.set_x_axis(
                {
                    "name":
                        "Time",

                    "text_axis":
                        True,
                }
            )


            chart.set_y_axis(
                {
                    "name":
                        "Temperature (°C)",
                }
            )


            chart.set_legend(
                {
                    "none":
                        True
                }
            )


            chart.set_size(
                {
                    "width":
                        720,

                    "height":
                        420,
                }
            )


            worksheet.insert_chart(
                "E3",
                chart
            )


        # =================================================
        # REPORT INFORMATION
        # =================================================

        info_row = 0
        info_col = 5


        worksheet.write(
            info_row,
            info_col,
            "Generated",
            header_format
        )


        generated_time = current_time()


        worksheet.write(
            info_row,
            info_col + 1,
            generated_time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )


        worksheet.write(
            1,
            info_col,
            "Timezone",
            header_format
        )


        worksheet.write(
            1,
            info_col + 1,
            "Asia/Tehran"
        )


        worksheet.write(
            2,
            info_col,
            "Samples",
            header_format
        )


        worksheet.write(
            2,
            info_col + 1,
            len(rows)
        )


        workbook.close()


        print(
            f"Excel updated: "
            f"{len(rows)} samples"
        )


    except Exception as e:

        print(
            "Excel creation error:"
        )

        print(e)


# =========================================================
# MQTT CONNECT
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


        if (
            result[0]
            == mqtt.MQTT_ERR_SUCCESS
        ):

            print(
                f"Subscribed: "
                f"{MQTT_TOPIC}"
            )

        else:

            print(
                f"Subscribe failed: "
                f"{result}"
            )


# =========================================================
# MQTT DISCONNECT
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
# DELIVER TEMP
# =========================================================

def deliver_temperature(
    temperature
):

    global pending_temperature_future


    future = (
        pending_temperature_future
    )


    pending_temperature_future = None


    if (
        future is not None
        and not future.done()
    ):

        future.set_result(
            temperature
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
            .decode(
                "utf-8",
                errors="ignore"
            )
            .strip()
        )

    except Exception:

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
                payload[
                    5:
                ].strip()
            )


            latest_temperature = (
                temperature
            )

            latest_temperature_time = (
                current_time()
            )


            print(
                f"Temperature received: "
                f"{temperature:.2f} C"
            )


            if main_loop:

                main_loop.call_soon_threadsafe(
                    deliver_temperature,
                    temperature
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

        if main_loop:

            main_loop.call_soon_threadsafe(
                deliver_temperature,
                None
            )


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
    max_delay=30
)


mqtt_client.on_connect = on_connect

mqtt_client.on_disconnect = on_disconnect

mqtt_client.on_message = on_message


# =========================================================
# MQTT START
# =========================================================

def connect_mqtt():

    print(
        "Connecting to HiveMQ..."
    )


    try:

        mqtt_client.connect_async(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=60
        )

        mqtt_client.loop_start()


        print(
            "MQTT network loop started."
        )


    except Exception as e:

        print(
            "MQTT start error:"
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


    async with (
        temperature_request_lock
    ):

        loop = (
            asyncio.get_running_loop()
        )


        future = (
            loop.create_future()
        )


        pending_temperature_future = (
            future
        )


        result = mqtt_client.publish(

            MQTT_TOPIC,

            "GET_TEMP",

            qos=1,

            retain=False
        )


        if (
            result.rc
            != mqtt.MQTT_ERR_SUCCESS
        ):

            pending_temperature_future = None

            print(
                "GET_TEMP publish failed:"
            )

            print(
                result.rc
            )

            return None


        print(
            "MQTT -> GET_TEMP"
        )


        try:

            temperature = (
                await asyncio.wait_for(
                    future,
                    timeout=10
                )
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
# AUTOMATIC DATALOGGER
# =========================================================

async def automatic_datalogger():

    print()
    print(
        "======================================"
    )

    print(
        "AUTOMATIC DATALOGGER"
    )

    print(
        "Interval: 60 seconds"
    )

    print(
        "Timezone: Asia/Tehran"
    )

    print(
        "Status: ACTIVE"
    )

    print(
        "======================================"
    )


    while True:

        try:

            await asyncio.sleep(
                DATALOG_INTERVAL
            )


            # درخواست دمای تازه
            temperature = (
                await request_temperature()
            )


            if temperature is not None:

                save_temperature(
                    temperature
                )

            else:

                print(
                    "No fresh temperature received."
                )

                print(
                    "Nothing saved."
                )


        except asyncio.CancelledError:

            print(
                "Automatic datalogger stopped."
            )

            break


        except Exception as e:

            print(
                "Automatic datalogger error:"
            )

            print(e)


# =========================================================
# CURRENT TEMPERATURE
# =========================================================

async def show_temperature(
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

            "❌ دریافت دمای جدید "
            "از ESP32 انجام نشد.",

            reply_markup=main_menu()
        )

        return


    now = current_time()


    await update.message.reply_text(

        "🌡️ دمای فعلی ESP32\n\n"

        f"🌡️ {temperature:.2f} °C\n\n"

        f"🕐 "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}",

        reply_markup=main_menu()
    )


# =========================================================
# SEND EXCEL DATALOGGER
# =========================================================

async def send_datalogger(
    update: Update
):

    try:

        # قبل از ارسال، Excel را از CSV به‌روز می‌کنیم
        create_excel()


        if not os.path.exists(
            EXCEL_FILE
        ):

            await update.message.reply_text(

                "❌ فایل دیتالاگر وجود ندارد.",

                reply_markup=main_menu()
            )

            return


        file_size = os.path.getsize(
            EXCEL_FILE
        )


        if file_size == 0:

            await update.message.reply_text(

                "❌ فایل دیتالاگر خالی است.",

                reply_markup=main_menu()
            )

            return


        with open(
            EXCEL_FILE,
            "rb"
        ) as file:

            await update.message.reply_document(

                document=file,

                filename=(
                    "temperature_datalog.xlsx"
                ),

                caption=(

                    "📊 دیتالاگر دمای ESP32\n\n"

                    "⏱️ ثبت خودکار هر 60 ثانیه\n"

                    "🕐 زمان: Asia/Tehran\n"

                    "📈 شامل نمودار دما بر حسب زمان"
                )
            )


        await update.message.reply_text(

            "✅ فایل Excel ارسال شد.",

            reply_markup=main_menu()
        )


    except Exception as e:

        print(
            "Excel send error:"
        )

        print(e)


        await update.message.reply_text(

            "❌ ارسال فایل دیتالاگر انجام نشد.",

            reply_markup=main_menu()
        )


# =========================================================
# CONTINUOUS REPORT
# =========================================================

async def continuous_temperature_report(
    chat_id,
    interval,
):

    print(
        f"Continuous report STARTED "
        f"for {chat_id}"
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
                    )
                )

            else:

                now = current_time()


                await telegram_app.bot.send_message(

                    chat_id=chat_id,

                    text=(

                        "📡 گزارش مستمر دما\n\n"

                        f"🌡️ "
                        f"{temperature:.2f} °C\n\n"

                        f"🕐 "
                        f"{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

                        f"⏱️ "
                        f"هر {interval:g} ثانیه"
                    )
                )


            await asyncio.sleep(
                interval
            )


    except asyncio.CancelledError:

        print(
            f"Continuous report stopped "
            f"for {chat_id}"
        )


    finally:

        continuous_tasks.pop(
            chat_id,
            None
        )


# =========================================================
# START CONTINUOUS
# =========================================================

async def start_continuous_report(
    update: Update
):

    chat_id = (
        update.effective_chat.id
    )


    if chat_id in continuous_tasks:

        await update.message.reply_text(

            "📡 گزارش مستمر دما "
            "از قبل فعال است.",

            reply_markup=main_menu()
        )

        return


    waiting_for_interval.add(
        chat_id
    )


    await update.message.reply_text(

        "📡 گزارش مستمر دما\n\n"

        "هر چند ثانیه یک‌بار "
        "دما ارسال شود؟\n\n"

        "مثلاً:\n"
        "5\n"
        "10\n"
        "30\n"
        "60\n\n"

        "فقط عدد را ارسال کنید.",

        reply_markup=ReplyKeyboardRemove()
    )


# =========================================================
# STOP CONTINUOUS
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

            reply_markup=main_menu()
        )

    else:

        await update.message.reply_text(

            "ℹ️ گزارش مستمر دما فعال نیست.",

            reply_markup=main_menu()
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

        temp_text = (
            "❌ دریافت نشده"
        )

    else:

        temp_text = (
            f"{latest_temperature:.2f} °C"
        )


    report_status = (

        "🟢 فعال"

        if update.effective_chat.id
        in continuous_tasks

        else "🔴 غیرفعال"
    )


    now = current_time()


    await update.message.reply_text(

        "📊 وضعیت سیستم\n\n"

        f"📡 MQTT: {mqtt_status}\n"

        f"🌡️ دما: {temp_text}\n"

        f"📡 گزارش مستمر: {report_status}\n\n"

        f"📁 فایل:\n"
        f"{EXCEL_FILE}\n\n"

        f"⏱️ ثبت خودکار: "
        f"هر {DATALOG_INTERVAL} ثانیه\n"

        f"🕐 زمان محلی:\n"
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}\n"

        f"🌍 Timezone: Asia/Tehran",

        reply_markup=main_menu()
    )


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


    if not is_allowed(update):

        await update.message.reply_text(

            "⛔ شما اجازه استفاده از "
            "این ربات را ندارید."
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

        "به ربات کنترل ESP32 خوش آمدید.\n\n"

        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",

        reply_markup=main_menu()
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
            "⛔ شما اجازه استفاده از ربات را ندارید."
        )

        return


    chat_id = (
        update.effective_chat.id
    )


    text = (
        update.message.text.strip()
    )


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
    # STOP
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
    # INTERVAL
    # =====================================================

    if chat_id in waiting_for_interval:

        try:

            interval = float(
                text
            )


            if interval < 1:

                raise ValueError


            if interval > 86400:

                await update.message.reply_text(

                    "❌ حداکثر فاصله "
                    "86400 ثانیه است."
                )

                return


            waiting_for_interval.discard(
                chat_id
            )


            old_task = (
                continuous_tasks.pop(
                    chat_id,
                    None
                )
            )


            if old_task:

                old_task.cancel()


            continuous_tasks[
                chat_id
            ] = asyncio.create_task(

                continuous_temperature_report(

                    chat_id,

                    interval
                )
            )


            await update.message.reply_text(

                "✅ گزارش مستمر دما فعال شد.\n\n"

                f"⏱️ هر {interval:g} ثانیه\n\n"

                "برای توقف، "
                "⛔ توقف گزارش مستمر "
                "را بزنید.",

                reply_markup=main_menu()
            )


        except ValueError:

            await update.message.reply_text(

                "❌ لطفاً فقط عدد وارد کنید.\n\n"
                "مثلاً: 10"
            )


        return


    # =====================================================
    # LED ON
    # =====================================================

    if text in (
        "🟢 روشن کردن LED",
        "led on",
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

        await show_temperature(
            update
        )

        return


    # =====================================================
    # DATALOGGER FILE
    # =====================================================

    if text in (
        "📄 دریافت دیتالاگر",
        "دریافت دیتالاگر",
        "report",
    ):

        await send_datalogger(
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

            "❌ اتصال MQTT برقرار نیست.",

            reply_markup=main_menu()
        )

        return


    result = mqtt_client.publish(

        MQTT_TOPIC,

        "ON",

        qos=1,

        retain=False
    )


    if (
        result.rc
        == mqtt.MQTT_ERR_SUCCESS
    ):

        await update.message.reply_text(

            "🟢 LED روشن شد",

            reply_markup=main_menu()
        )

    else:

        await update.message.reply_text(

            "❌ ارسال فرمان انجام نشد.",

            reply_markup=main_menu()
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

            reply_markup=main_menu()
        )

        return


    result = mqtt_client.publish(

        MQTT_TOPIC,

        "OFF",

        qos=1,

        retain=False
    )


    if (
        result.rc
        == mqtt.MQTT_ERR_SUCCESS
    ):

        await update.message.reply_text(

            "🔴 LED خاموش شد",

            reply_markup=main_menu()
        )

    else:

        await update.message.reply_text(

            "❌ ارسال فرمان انجام نشد.",

            reply_markup=main_menu()
        )


# =========================================================
# WEB ROOT
# =========================================================

@app.get("/")
async def root():

    return {

        "status":
            "online",

        "service":
            "Telegram ESP32 Bot",
    }


# =========================================================
# HEALTH
# =========================================================

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


    if (
        received_secret
        != WEBHOOK_SECRET
    ):

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

@app.on_event(
    "startup"
)
async def startup_event():

    global telegram_app
    global main_loop
    global temperature_request_lock
    global temperature_logger_task


    main_loop = (
        asyncio.get_running_loop()
    )


    temperature_request_lock = (
        asyncio.Lock()
    )


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


    # =====================================================
    # REPORT FILE
    # =====================================================

    initialize_csv()

    create_excel()


    # =====================================================
    # MQTT
    # =====================================================

    connect_mqtt()


    # =====================================================
    # TELEGRAM
    # =====================================================

    telegram_app = (

        Application.builder()

        .token(
            TELEGRAM_BOT_TOKEN
        )

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

            filters.TEXT
            & ~filters.COMMAND,

            handle_message
        )
    )


    # =====================================================
    # INITIALIZE
    # =====================================================

    await telegram_app.initialize()

    await telegram_app.start()


    # =====================================================
    # DATALOGGER
    # =====================================================

    temperature_logger_task = (
        asyncio.create_task(
            automatic_datalogger()
        )
    )


    # =====================================================
    # WEBHOOK
    # =====================================================

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


    # =====================================================
    # TIME DEBUG
    # =====================================================

    print()
    print(
        "Current local time:"
    )

    print(
        current_time().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print(
        "Timezone: Asia/Tehran"
    )


    print()
    print(
        "Telegram webhook configured."
    )

    print(
        "Bot is ready."
    )

    print(
        "Automatic datalogger: ACTIVE"
    )

    print(
        "Interval: 60 seconds"
    )

    print()


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event(
    "shutdown"
)
async def shutdown_event():

    global temperature_logger_task


    print(
        "Stopping bot..."
    )


    # -----------------------------------------------------
    # Datalogger
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

