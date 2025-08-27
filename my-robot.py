# -*- coding: utf-8 -*-
import os
import sqlite3
import logging
from typing import Optional, Tuple

from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ApplicationHandlerStop
)
from telegram.request import HTTPXRequest
from pydub import AudioSegment, effects as pd_effects
from deep_translator import GoogleTranslator

# -------- FFmpeg for pydub --------
AudioSegment.converter = "ffmpeg"
AudioSegment.ffprobe = "ffprobe"

# -------- Config --------
TOKEN = "8325388752:AAHxyg5wu6D0EQJvNPAo10XQWkAzLWJjkzw"  # ← توکن خودت را قرار بده
ADMIN_ID = 5765026394                 # ← آیدی عددی ادمین
CARD_NUMBER = "6037-xxxx-xxxx-xxxx"
DB_PATH = "bot.db"

# ======== Multilingual UI (NEW) ========
LANG_KEY = "ui_lang"

TEXTS = {
    "fa": {
        "choose_lang": "لطفاً زبان ربات را انتخاب کنید:",
        "welcome": "سلام 👋\nبه ربات تغییر صدا + ترجمه متن خوش اومدی!",
        "menu": [
            ["🌐 ترجمه متن"],
            ["🎤 تغییر صدا", "🎛️ انتخاب افکت"],
            ["📊 موجودی", "💳 خرید امتیاز"]
        ],
        "back_home": "بازگشت به منوی اصلی:"
    },
    "en": {
        "choose_lang": "Please choose the bot language:",
        "welcome": "Hello 👋\nWelcome to the Voice Changer + Translator bot!",
        "menu": [
            ["🌐 Translate Text"],
            ["🎤 Voice Changer", "🎛️ Choose Effect"],
            ["📊 Balance", "💳 Buy Credits"]
        ],
        "back_home": "Back to Home:"
    }
}


def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get(LANG_KEY, "fa")


def T(context: ContextTypes.DEFAULT_TYPE, key: str) -> str:
    lang = get_lang(context)
    return TEXTS.get(lang, TEXTS["fa"]).get(key, "")


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇮🇷 فارسی",  callback_data="lang:fa"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
        ]
    ])


def main_menu_markup(context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(TEXTS[get_lang(context)]["menu"], resize_keyboard=True)


# ======== UI (legacy labels kept for code logic) ========
main_menu = [
    ["🌐 ترجمه متن"],
    ["🎤 تغییر صدا", "🎛️ انتخاب افکت"],
    ["📊 موجودی", "💳 خرید امتیاز"]
]


def effects_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("Pitch ↑", callback_data="eff:pitch_up"),
            InlineKeyboardButton("Pitch ↓", callback_data="eff:pitch_down"),
        ],
        [
            InlineKeyboardButton("Speed ↑", callback_data="eff:speed_up"),
            InlineKeyboardButton("Slow",     callback_data="eff:slow_down"),
        ],
        [
            InlineKeyboardButton("Robot 🤖", callback_data="eff:robot"),
            InlineKeyboardButton("Echo 🌊",  callback_data="eff:echo"),
        ],
        [
            InlineKeyboardButton("Voice ♀️", callback_data="eff:female"),
            InlineKeyboardButton("Voice ♂️", callback_data="eff:male"),
        ],
        [InlineKeyboardButton("حذف افکت (عادی)", callback_data="eff:none")],
    ]
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📈 آمار", callback_data="admin:stats"),
            InlineKeyboardButton(
                "👤 جستجوی کاربر", callback_data="admin:search"),
        ],
        [
            InlineKeyboardButton("➕ افزودن امتیاز", callback_data="admin:add"),
            InlineKeyboardButton(
                "➖ کسر امتیاز",     callback_data="admin:sub"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def translate_lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(" فارسی 🇮🇷 ", callback_data="trg:fa"),
            InlineKeyboardButton(" English 🇬🇧 ", callback_data="trg:en"),
        ],
        [
            InlineKeyboardButton("Türkçe 🇹🇷", callback_data="trg:tr"),
            InlineKeyboardButton("العربية 🇸🇦", callback_data="trg:ar"),
        ],
        [
            InlineKeyboardButton("Русский 🇷🇺", callback_data="trg:ru"),
            InlineKeyboardButton("اردو 🇵🇰",    callback_data="trg:ur"),
        ],
    ])


def translate_session_keyboard(trg: str) -> InlineKeyboardMarkup:
    """کیبورد مخصوص صفحه‌ی ترجمه: تغییر زبان یا بازگشت به منو"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔁 تغییر زبان مقصد (فعلی: {trg})", callback_data="tr:change_lang")],
        [InlineKeyboardButton("⬅️ بازگشت به منوی اصلی",
                              callback_data="tr:back_home")]
    ])


# ======== Flags (per-user state) ========
FLAG_AWAIT_TRANSLATE = "await_translate"  # آیا کاربر در حالت ترجمه است؟
KEY_TRG_LANG = "trg_lang"                 # زبان مقصد ترجمه

# ======== Logging ========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("voice-bot-final")

# =========================
# == SQLite: Data Layer  ==
# =========================


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            name      TEXT DEFAULT '',
            points    INTEGER NOT NULL DEFAULT 0,
            effect    TEXT NOT NULL DEFAULT 'none'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            amount    INTEGER NOT NULL,
            points    INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def ensure_user(user_id: int, name: Optional[str] = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO users(user_id,name,points,effect) VALUES(?,?,0,'none')",
            (user_id, name or "")
        )
    else:
        if name:
            cur.execute("UPDATE users SET name=? WHERE user_id=?",
                        (name, user_id))
    conn.commit()
    conn.close()


def get_user(user_id: int) -> Tuple[int, str, int, str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, name, points, effect FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        ensure_user(user_id)
        return get_user(user_id)
    conn.close()
    return row  # (user_id, name, points, effect)


def add_points(user_id: int, delta: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET points = points + ? WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()


def sub_points(user_id: int, delta: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET points = MAX(points - ?, 0) WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()


def set_effect(user_id: int, eff: str):
    conn = get_conn()
    conn.execute("UPDATE users SET effect=? WHERE user_id=?", (eff, user_id))
    conn.commit()
    conn.close()


def get_stats() -> Tuple[int, int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(points) FROM users")
    cnt, s = cur.fetchone()
    conn.close()
    return (cnt or 0, s or 0)


def save_payment(user_id: int, amount: int, points: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO payments(user_id, amount, points) VALUES(?,?,?)",
        (user_id, amount, points)
    )
    conn.commit()
    conn.close()

# =========================
# == Effects (Voice FX)  ==
# =========================


def get_effect_label(code: str) -> str:
    mapping = {
        "none": "بدون افکت",
        "pitch_up": "Pitch ↑",
        "pitch_down": "Pitch ↓",
        "speed_up": "Speed ↑",
        "slow_down": "Slow",
        "robot": "Robot 🤖",
        "echo": "Echo 🌊",
        "female": "Voice ♀️",
        "male": "Voice ♂️",
    }
    return mapping.get(code, code)


def apply_effect(sound: AudioSegment, eff: str) -> AudioSegment:
    try:
        if eff == "none":
            return sound

        if eff == "pitch_up":
            return sound._spawn(sound.raw_data, overrides={
                "frame_rate": int(sound.frame_rate * 1.2)
            }).set_frame_rate(sound.frame_rate)

        if eff == "pitch_down":
            return sound._spawn(sound.raw_data, overrides={
                "frame_rate": int(sound.frame_rate * 0.85)
            }).set_frame_rate(sound.frame_rate)

        if eff == "speed_up":
            return pd_effects.speedup(sound, playback_speed=1.25, chunk_size=50, crossfade=10)

        if eff == "slow_down":
            return sound._spawn(sound.raw_data, overrides={
                "frame_rate": int(sound.frame_rate * 0.85)
            }).set_frame_rate(sound.frame_rate)

        if eff == "robot":
            s1 = sound.low_pass_filter(4000).high_pass_filter(200)
            delayed = s1 - 8
            delayed = delayed.overlay(s1, position=15)
            return delayed

        if eff == "echo":
            out = sound
            for i, delay_ms in enumerate([120, 240, 360], start=1):
                out = out.overlay(sound - (8 * i), position=delay_ms)
            return out

        if eff == "female":
            s = sound._spawn(sound.raw_data, overrides={
                "frame_rate": int(sound.frame_rate * 1.15)
            }).set_frame_rate(sound.frame_rate)
            return s.high_pass_filter(300)

        if eff == "male":
            s = sound._spawn(sound.raw_data, overrides={
                "frame_rate": int(sound.frame_rate * 0.9)
            }).set_frame_rate(sound.frame_rate)
            return s.low_pass_filter(3000)

        return sound
    except Exception:
        logger.exception("apply_effect error")
        return sound

# =========================
# == User Handlers       ==
# =========================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # فقط زبان می‌پرسیم؛ منو بعد از انتخاب زبان می‌آید
    user = update.effective_user
    ensure_user(user.id, user.full_name or user.username)
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    await update.effective_message.reply_text(
        T(context, "choose_lang"),
        reply_markup=language_keyboard()
    )


async def language_choose_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not q.data.startswith("lang:"):
        return
    lang = q.data.split(":", 1)[1]
    context.user_data[LANG_KEY] = lang
    await q.edit_message_text(T(context, "welcome"))
    await q.message.reply_text(
        T(context, "back_home"),
        reply_markup=main_menu_markup(context)
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("✅ ربات روشنه.")


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    user = update.effective_user
    ensure_user(user.id, user.full_name or user.username)
    _, _, points, eff = get_user(user.id)
    await update.message.reply_text(
        f"📊 موجودی: {points} امتیاز\n🎛️ افکت فعلی: {get_effect_label(eff)}",
        reply_markup=main_menu_markup(context)
    )


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    await update.message.reply_text(
        "💳 راهنمای پرداخت و دریافت امتیاز\n"
        "— شماره کارت برای واریز:\n"
        f"   {CARD_NUMBER}\n\n"
        "— تبدیل مبلغ به امتیاز:\n"
        "   به ازای هر ۱۰,۰۰۰ تومان → ۲۰۰ امتیاز (هر امتیاز = ۱ بار تغییر صدا)\n"
        "   مثال: ۳۰,۰۰۰ تومان → ۶۰۰ امتیاز (۶۰۰ بار تبدیل)\n\n"
        "— مراحل:\n"
        "   1) مبلغ دلخواه را کارت‌به‌کارت کنید.\n"
        "   2) یک عکس واضح از رسید را اینجا ارسال کنید.\n"
        "   3) ادمین رسید را بررسی و تأیید می‌کند.\n"
        "   4) امتیازها به‌صورت خودکار به حساب شما اضافه می‌شود.\n\n"
        "ℹ️ نکته: فقط «عکس» رسید را ارسال کنید؛ پیام‌های متنی به عنوان رسید پذیرفته نمی‌شوند ✅",
        reply_markup=main_menu_markup(context)
    )


async def choose_effect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    user = update.effective_user
    ensure_user(user.id, user.full_name or user.username)
    _, _, _, eff = get_user(user.id)
    cur = get_effect_label(eff)
    await update.message.reply_text(
        f"🎛️ افکت فعلی شما: {cur}\nیکی از افکت‌های زیر رو انتخاب کن:",
        reply_markup=effects_keyboard()
    )


async def effect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    user = q.from_user
    if not q.data.startswith("eff:"):
        return
    code = q.data.split(":", 1)[1]
    ensure_user(user.id, user.full_name or user.username)
    set_effect(user.id, code)
    await q.edit_message_text(f"✅ افکت شما تنظیم شد: {get_effect_label(code)}")


async def change_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    await update.message.reply_text("🎤 لطفاً یک ویس تلگرامی یا فایل صوتی (mp3/ogg/...) ارسال کنید.")


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.full_name or user.username)

    _, _, points, eff = get_user(user.id)
    if points <= 0:
        await update.message.reply_text("❌ امتیاز کافی ندارید. لطفاً از «💳 خرید امتیاز» استفاده کنید.")
        return

    tg_file = None
    in_name = None
    in_fmt = None
    if update.message.voice:
        tg_file = await update.message.voice.get_file()
        in_name, in_fmt = "input.ogg", "ogg"
    elif update.message.audio:
        tg_file = await update.message.audio.get_file()
        in_name, in_fmt = "input.mp3", "mp3"
    else:
        await update.message.reply_text("لطفاً ویس یا فایل صوتی ارسال کنید.")
        return

    try:
        await tg_file.download_to_drive(in_name)
        sound = AudioSegment.from_file(in_name, format=in_fmt)
        processed = apply_effect(sound, eff)
        out_name = "output.ogg"
        processed.export(out_name, format="ogg")

        sub_points(user.id, 1)
        with open(out_name, "rb") as f:
            await update.message.reply_voice(
                voice=f,
                caption=f"✅ تغییر صدا انجام شد! (۱ امتیاز کسر شد)\n🎛️ افکت: {get_effect_label(eff)}"
            )
    except Exception:
        logger.exception("voice_handler error:")
        await update.message.reply_text("❌ خطا در پردازش صدا. دوباره تلاش کنید.")
    finally:
        try:
            if in_name and os.path.exists(in_name):
                os.remove(in_name)
            if os.path.exists("output.ogg"):
                os.remove("output.ogg")
        except:
            pass

# =========================
# == Translation (TEXT)  ==
# =========================


async def translate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فعال‌سازی حالت ترجمه‌ی متن با انتخاب زبان مقصد"""
    context.user_data[FLAG_AWAIT_TRANSLATE] = True
    context.user_data[KEY_TRG_LANG] = "fa"
    await update.message.reply_text(
        "🌐 حالت «ترجمه متن» فعال شد.\n"
        "زبان مقصد را انتخاب کن و سپس متن خود را بفرست:",
        reply_markup=translate_lang_keyboard()
    )


async def translate_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not q.data.startswith("trg:"):
        return
    trg = q.data.split(":", 1)[1]
    # تثبیت حالت ترجمه و زبان مقصد
    context.user_data[FLAG_AWAIT_TRANSLATE] = True
    context.user_data[KEY_TRG_LANG] = trg
    await q.edit_message_text(f"✅ زبان مقصد ترجمه: {trg}\nاکنون متن خود را ارسال کنید تا ترجمه شود.")


async def translate_session_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت از صفحه ترجمه به منوی اصلی"""
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    await update.effective_message.reply_text(
        T(context, "back_home"),
        reply_markup=main_menu_markup(context)
    )


async def translate_session_change_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش مجدد انتخاب زبان مقصد"""
    await update.effective_message.reply_text(
        "زبان مقصد را انتخاب کنید:",
        reply_markup=translate_lang_keyboard()
    )

# اینترسپتور با اولویت بالا: وقتی حالت ترجمه روشنه، همهٔ متن‌های «غیردستوری» را ترجمه کن


async def translate_text_interceptor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(FLAG_AWAIT_TRANSLATE):
        return  # اجازه بده بقیه هندلرها کارشون رو بکنن

    msg = update.message
    if not msg or not msg.text:
        return

    txt = msg.text.strip()

    # اگر با / شروع شده، «دستور» است → اجازه بده به هندلرهای فرمان برود
    if txt.startswith("/"):
        return

    # خروج از حالت ترجمه با کلمات رایج
    if txt.lower() in ("خروج", "cancel", "انصراف"):
        context.user_data[FLAG_AWAIT_TRANSLATE] = False
        await msg.reply_text(
            "↩️ حالت ترجمه غیرفعال شد.",
            reply_markup=main_menu_markup(context)
        )
        raise ApplicationHandlerStop

    trg = context.user_data.get(KEY_TRG_LANG, "fa")
    try:
        out = GoogleTranslator(source="auto", target=trg).translate(txt)
        await msg.reply_text(
            f"🔁 ترجمه ({trg}):\n{out}",
            reply_markup=translate_session_keyboard(trg)
        )
    except Exception:
        logger.exception("translate error:")
        await msg.reply_text(
            "❌ خطا در ترجمه (اتصال/فیلتر؟).",
            reply_markup=translate_session_keyboard(trg)
        )

    # پیام ترجمه شد و دوباره صفحه‌ی ترجمه با دکمه برگشت/تغییر زبان نمایش داده شد
    raise ApplicationHandlerStop

# دستور سریع ترجمه بدون منو: /tr <lang> <text>


async def tr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt_args = context.args
    if not txt_args:
        await update.message.reply_text("استفاده: /tr <lang> <text>\nمثال: /tr en سلام خوبی؟")
        return
    trg = txt_args[0]
    text = " ".join(txt_args[1:]).strip()
    if not text:
        await update.message.reply_text("لطفاً بعد از زبان، متن را هم بنویس.\nمثال: /tr en سلام خوبی؟")
        return
    try:
        out = GoogleTranslator(source="auto", target=trg).translate(text)
        # پس از ترجمه‌ی دستوری، وارد صفحه‌ی ترجمه هم می‌شویم تا تجربه یکنواخت باشد
        context.user_data[FLAG_AWAIT_TRANSLATE] = True
        context.user_data[KEY_TRG_LANG] = trg
        await update.message.reply_text(
            f"🔁 ترجمه ({trg}):\n{out}",
            reply_markup=translate_session_keyboard(trg)
        )
    except Exception as e:
        logger.exception("tr_cmd translate error:")
        await update.message.reply_text("❌ خطا در ترجمه (اتصال/فیلتر؟).")

# =========================
# == Payments / Receipts ==
# =========================


async def receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فقط عکس رسید را به ادمین فوروارد می‌کنیم (نه متن)."""
    user = update.effective_user
    ensure_user(user.id, user.full_name or user.username)
    try:
        await context.bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=update.message.chat_id,
            message_id=update.message.message_id
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"📩 رسید جدید از کاربر {user.id}\n"
            f"برای تأیید از دستور استفاده کنید:\n/confirm {user.id} مبلغ"
        )
        await update.message.reply_text("✅ رسید شما ارسال شد. منتظر تأیید ادمین باشید.")
    except Exception:
        logger.exception("receipt forward error")
        await update.message.reply_text("❌ خطا در ارسال رسید. لطفاً دوباره تلاش کنید.")


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])  # تومان
    except:
        await update.message.reply_text("❌ فرمت دستور اشتباه است.\nمثال:\n/confirm 123456789 20000")
        return

    points_to_add = (amount // 10000) * 200
    ensure_user(user_id)
    add_points(user_id, points_to_add)
    save_payment(user_id, amount, points_to_add)

    _, _, new_pts, _ = get_user(user_id)
    await context.bot.send_message(user_id, f"✅ پرداخت تأیید شد. {points_to_add} امتیاز به حساب شما اضافه شد. موجودی: {new_pts}")
    await update.message.reply_text(f"✅ به کاربر {user_id} {points_to_add} امتیاز اضافه شد. موجودی: {new_pts}")

# =========================
# == Admin Panel         ==
# =========================
AWAIT_SEARCH = "admin_await_search_user"
AWAIT_ADD = "admin_await_add_points"
AWAIT_SUB = "admin_await_sub_points"


def clear_admin_flags(context: ContextTypes.DEFAULT_TYPE):
    context.user_data[AWAIT_SEARCH] = False
    context.user_data[AWAIT_ADD] = False
    context.user_data[AWAIT_SUB] = False


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[FLAG_AWAIT_TRANSLATE] = False
    if update.effective_user.id != ADMIN_ID:
        return
    clear_admin_flags(context)
    await update.message.reply_text("🛠 پنل ادمین:", reply_markup=admin_keyboard())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.answer()
        return

    q = update.callback_query
    await q.answer()
    data = q.data
    clear_admin_flags(context)

    if data == "admin:stats":
        total_users, total_points = get_stats()
        await q.edit_message_text(f"📈 آمار:\n👥 کاربران: {total_users}\n⭐ مجموع امتیاز: {total_points}")

    elif data == "admin:search":
        context.user_data[AWAIT_SEARCH] = True
        await q.edit_message_text("🔎 آیدی عددی کاربر را بفرست (مثال: 123456789).")

    elif data == "admin:add":
        context.user_data[AWAIT_ADD] = True
        await q.edit_message_text("➕ فرمت پیام: `user_id points`\nمثال: `123456789 400`")

    elif data == "admin:sub":
        context.user_data[AWAIT_SUB] = True
        await q.edit_message_text("➖ فرمت پیام: `user_id points`\nمثال: `123456789 50`")


async def admin_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    txt = (update.message.text or "").strip()

    if context.user_data.get(AWAIT_SEARCH):
        try:
            uid = int(txt)
            uid, name, pts, eff = get_user(uid)
            await update.message.reply_text(
                f"👤 کاربر: {name}\n🆔 {uid}\n⭐ امتیاز: {pts}\n🎛️ افکت: {get_effect_label(eff)}"
            )
        except:
            await update.message.reply_text("❌ ورودی نامعتبر. فقط آیدی عددی ارسال کن.")
        finally:
            clear_admin_flags(context)
        return

    if context.user_data.get(AWAIT_ADD):
        try:
            uid_s, pts_s = txt.split()
            uid, pts = int(uid_s), int(pts_s)
            ensure_user(uid)
            add_points(uid, pts)
            _, _, new_pts, _ = get_user(uid)
            await update.message.reply_text(f"✅ به کاربر {uid} {pts} امتیاز اضافه شد. موجودی: {new_pts}")
            try:
                await context.bot.send_message(uid, f"✅ {pts} امتیاز به حساب شما اضافه شد. موجودی: {new_pts}")
            except:
                pass
        except:
            await update.message.reply_text("❌ فرمت نامعتبر. مثال: `123456789 200`")
        finally:
            clear_admin_flags(context)
        return

    if context.user_data.get(AWAIT_SUB):
        try:
            uid_s, pts_s = txt.split()
            uid, pts = int(uid_s), int(pts_s)
            ensure_user(uid)
            sub_points(uid, pts)
            _, _, new_pts, _ = get_user(uid)
            await update.message.reply_text(f"✅ از کاربر {uid} {pts} امتیاز کسر شد. موجودی: {new_pts}")
            try:
                await context.bot.send_message(uid, f"ℹ️ {pts} امتیاز از حساب شما کسر شد. موجودی: {new_pts}")
            except:
                pass
        except:
            await update.message.reply_text("❌ فرمت نامعتبر. مثال: `123456789 50`")
        finally:
            clear_admin_flags(context)
        return

# =========================
# == Main / Bootstrap    ==
# =========================


def main():
    init_db()

    PROXY_URL = None  # اگر نیاز داری: "http://HOST:PORT" یا "socks5://HOST:PORT"
    request = HTTPXRequest(
        proxy_url=PROXY_URL,
        connect_timeout=30.0,
        read_timeout=30.0,
        pool_timeout=30.0,
    )

    app = Application.builder().token(TOKEN).request(request).build()

    # ======= اینترسپتور ترجمه (اولویت بالا: گروه -1) =======
    app.add_handler(MessageHandler(
        filters.TEXT, translate_text_interceptor), group=-1)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(
        language_choose_callback, pattern=r"^lang:"))
    app.add_handler(CommandHandler("ping",  ping))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("tr", tr_cmd))

    # Menus  (Regex فارسی + انگلیسی)
    app.add_handler(MessageHandler(filters.Regex(r"ترجمه\s*متن")
                    | filters.Regex(r"Translate\s*Text"), translate_menu))
    app.add_handler(MessageHandler(filters.Regex("📊 موجودی")
                    | filters.Regex("Balance"), balance))
    app.add_handler(MessageHandler(filters.Regex("💳 خرید امتیاز")
                    | filters.Regex(r"Buy\s*Credits"), buy))
    app.add_handler(MessageHandler(filters.Regex("🎤 تغییر صدا")
                    | filters.Regex(r"Voice\s*Changer"), change_voice))
    app.add_handler(MessageHandler(filters.Regex("🎛️ انتخاب افکت")
                    | filters.Regex(r"Choose\s*Effect"), choose_effect))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(
        effect_callback,               pattern=r"^eff:"))
    app.add_handler(CallbackQueryHandler(
        admin_callback,                pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(
        translate_lang_callback,       pattern=r"^trg:"))
    app.add_handler(CallbackQueryHandler(
        translate_session_back,        pattern=r"^tr:back_home"))
    app.add_handler(CallbackQueryHandler(
        translate_session_change_lang, pattern=r"^tr:change_lang"))

    # Admin typed flows
    app.add_handler(MessageHandler(filters.TEXT & filters.User(
        user_id=ADMIN_ID), admin_text_router))

    # Audio / Voice
    app.add_handler(MessageHandler(
        filters.VOICE | filters.AUDIO, voice_handler))

    # Receipt ONLY photos (نه TEXT!)
    app.add_handler(MessageHandler(filters.PHOTO, receipt_handler))

    logger.info("Bot is starting polling...")
    app.run_polling(drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
