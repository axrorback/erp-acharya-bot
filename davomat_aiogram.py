# davomat_aiogram.py
import os
import sqlite3
import time
import logging
from datetime import datetime
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from cryptography.fernet import Fernet, InvalidToken
import asyncio
from dotenv import load_dotenv

load_dotenv()

# --- Konfiguratsiya ---
ALLOWED_USERS = [7184964035, 5789956459,7711778383]
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FERNET_KEY = os.getenv("FERNET_KEY")
if not TELEGRAM_TOKEN or not FERNET_KEY:
    raise RuntimeError("Iltimos TELEGRAM_TOKEN va FERNET_KEY ni muhitga o'rnating.")

LOGIN_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/authenticate"
TIMETABLE_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/academic/timeTableDetailsOfStudentOrEmployeeForMobile"
ATTENDANCE_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/student/attendanceReportForStudentProfileByStudentId/"

DEFAULT_TOKEN_TTL = 24 * 3600  # 24 soat

# --- DB init ---
DB_PATH = "users.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        tg_id INTEGER UNIQUE,
        api_username TEXT,
        password_enc TEXT,
        token TEXT,
        token_acquired INTEGER,
        token_ttl INTEGER,
        api_user_id INTEGER,
        full_name TEXT,
        lang TEXT DEFAULT 'uz'
    )
    """
)
conn.commit()

# --- Crypto ---
fernet = Fernet(FERNET_KEY.encode())

# --- Bot ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- FSM ---
class LoginStates(StatesGroup):
    waiting_lang = State()
    waiting_username = State()
    waiting_password = State()

# --- Translation texts ---
TEXTS = {
    "uz": {
        "greet": "👋 Salom! Iltimos username kiriting:",
        "ask_password": "🔒 Endi password yuboring:",
        "login_success": "✅ Login muvaffaqiyatli! Tugmalardan foydalaning:",
        "login_fail": "❌ Login ishlamadi — username yoki password xato.",
        "already_logged": "✅ Siz allaqachon tizimga kiringansiz.",
        "choose_lang": "Tilni tanlang / Select language:",
        "token_expired": "🔄 Token muddati tugagan — avtomatik qayta autentifikatsiya qilinmoqda...",
        "attendance_empty": "📭 Bugun darslar topilmadi.",
        "attendance_fail": "❌ Jadvalni olishda muammo yuz berdi.",
        "attendance_network": "❌ Jadvalni olishda tarmoq xatosi.",
    },
    "en": {
        "greet": "👋 Hello! Please enter your username:",
        "ask_password": "🔒 Now send your password:",
        "login_success": "✅ Login successful! Use the buttons below:",
        "login_fail": "❌ Login failed — wrong username or password.",
        "already_logged": "✅ You are already logged in.",
        "choose_lang": "Select language / Tilni tanlang:",
        "token_expired": "🔄 Token expired — re-authenticating...",
        "attendance_empty": "📭 No classes today.",
        "attendance_fail": "❌ Failed to fetch timetable.",
        "attendance_network": "❌ Network error while fetching timetable.",
    }
}

def t(row, key):
    lang = "uz"
    if row:
        try:
            lang = row[9] if len(row) > 9 and row[9] else "uz"
        except IndexError:
            lang = "uz"
    return TEXTS.get(lang, TEXTS["uz"]).get(key, key)

# --- Helper functions ---
def get_user_by_tg(tg_id):
    cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    return cur.fetchone()

def upsert_user(tg_id, api_username=None, password_enc=None, token=None, token_acquired=None, token_ttl=None, api_user_id=None, full_name=None, lang=None):
    existing = get_user_by_tg(tg_id)
    if existing:
        fields, vals = [], []
        if api_username is not None: fields.append("api_username = ?"); vals.append(api_username)
        if password_enc is not None: fields.append("password_enc = ?"); vals.append(password_enc)
        if token is not None: fields.append("token = ?"); vals.append(token)
        if token_acquired is not None: fields.append("token_acquired = ?"); vals.append(token_acquired)
        if token_ttl is not None: fields.append("token_ttl = ?"); vals.append(token_ttl)
        if api_user_id is not None: fields.append("api_user_id = ?"); vals.append(api_user_id)
        if full_name is not None: fields.append("full_name = ?"); vals.append(full_name)
        if lang is not None: fields.append("lang = ?"); vals.append(lang)
        vals.append(tg_id)
        if fields:
            sql = f"UPDATE users SET {', '.join(fields)} WHERE tg_id = ?"
            cur.execute(sql, tuple(vals))
            conn.commit()
    else:
        cur.execute(
            "INSERT INTO users (tg_id, api_username, password_enc, token, token_acquired, token_ttl, api_user_id, full_name, lang) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tg_id, api_username, password_enc, token, token_acquired, token_ttl, api_user_id, full_name, lang or "uz")
        )
        conn.commit()

def encrypt_password(password_plain):
    return fernet.encrypt(password_plain.encode()).decode()

def decrypt_password(password_enc):
    if not password_enc: return None
    try: return fernet.decrypt(password_enc.encode()).decode()
    except InvalidToken: return None

def token_is_valid(row):
    if not row: return False
    token = row[4]; acquired = row[5]; ttl = row[6] or DEFAULT_TOKEN_TTL
    if not token or not acquired: return False
    return (acquired + ttl) > int(time.time())

# --- Keyboards ---
def main_keyboard(row):
    lang = "uz"
    if row and len(row) > 9 and row[9]: lang = row[9]
    if lang=="en":
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📅 Today's Classes")],
                [KeyboardButton(text="✅ Attendance")]
            ],
            resize_keyboard=True
        )
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📅 Bugungi darslar")],
                [KeyboardButton(text="✅ Davomat")]
            ],
            resize_keyboard=True
        )

def lang_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🇺🇿 O'zbek"), KeyboardButton(text="🇬🇧 English")]],
        resize_keyboard=True
    )


# --- Bot Handlers ---
@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    tg_id = message.from_user.id

    # ❌ Avval ruxsatni tekshiramiz
    if tg_id not in ALLOWED_USERS:
        await message.answer("❌ Sizga ruxsat yo‘q.\n\n"
                             "Bu bot faqat @axrorback va @asad_back uchun.")
        return

    # ✅ Agar ruxsat bo‘lsa, davom etadi
    row = get_user_by_tg(tg_id)
    if row and token_is_valid(row):
        await message.answer(
            f"{t(row, 'already_logged')}\n👤 {row[8]}\n🆔 {row[7]}",
            reply_markup=main_keyboard(row)
        )
        return

    await message.answer(t(row, "choose_lang"), reply_markup=lang_keyboard())
    await state.set_state(LoginStates.waiting_lang)

@dp.message(LoginStates.waiting_lang)
async def handle_lang(message: Message, state: FSMContext):
    lang_choice = message.text.strip()
    lang = "uz" if "uz" in lang_choice.lower() else "en"
    await state.update_data(lang=lang)
    await message.answer(t(None,"greet"))
    await state.set_state(LoginStates.waiting_username)

@dp.message(LoginStates.waiting_username)
async def handle_username(message: Message, state: FSMContext):
    await state.update_data(api_username=message.text.strip())
    data = await state.get_data()
    lang = data.get("lang","uz")
    await message.answer(t(None,"ask_password"))
    await state.set_state(LoginStates.waiting_password)

@dp.message(LoginStates.waiting_password)
async def handle_password(message: Message, state: FSMContext):
    data = await state.get_data()
    api_username = data.get("api_username")
    password_plain = message.text.strip()
    lang = data.get("lang","uz")
    tg_id = message.from_user.id

    success = await try_login_and_store(tg_id, api_username, password_plain, lang)
    if success:
        try: await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except: pass
        await message.answer(t(None,"login_success"), reply_markup=main_keyboard(get_user_by_tg(tg_id)))
    else:
        await message.answer(t(None,"login_fail"))
    await state.clear()

async def try_login_and_store(tg_id, api_username, password_plain, lang, ctx_message=None):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(LOGIN_API,json={"username":api_username,"password":password_plain}) as resp:
                if resp.status!=200: return False
                result = await resp.json()
        except: return False
    if not result.get("success"): return False
    data = result.get("data",{})
    token = data.get("token")
    api_user_id = data.get("userId")
    full_name = data.get("name") or data.get("fullName") or ""
    token_ttl = data.get("expiresIn") or DEFAULT_TOKEN_TTL
    acquired = int(time.time())
    password_enc = encrypt_password(password_plain)
    upsert_user(tg_id, api_username, password_enc, token, acquired, token_ttl, api_user_id, full_name, lang)
    return True

# --- Bugungi darslar ---
@dp.message(F.text.in_(["📅 Bugungi darslar","📅 Today's Classes"]))
async def today_classes(message: Message):
    tg_id = message.from_user.id
    row = get_user_by_tg(tg_id)
    if not row:
        await message.answer("❌ Avval login qiling (`/start`)."); return
    if not token_is_valid(row):
        api_username = row[2]; password_plain = decrypt_password(row[3])
        if api_username and password_plain:
            await message.answer(t(row,"token_expired"))
            ok = await try_login_and_store(tg_id, api_username, password_plain, row[9])
            if not ok:
                await message.answer("❌ Avtomatik loginni amalga oshib bo'lmadi. /start bilan qayta login qiling."); return
            row = get_user_by_tg(tg_id)
        else:
            await message.answer("❗ Parol bazada mavjud emas — /start bilan qayta login qiling."); return

    token = row[4]; api_user_id = row[7]
    today = datetime.now(); year, month = today.year, today.month
    url = f"{TIMETABLE_API}?student_id={api_user_id}&year={year}&month={month}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status!=200: await message.answer(t(row,"attendance_fail")); return
                data = await resp.json()
        except:
            await message.answer(t(row,"attendance_network")); return

    today_str = today.strftime("%Y-%m-%d")
    lessons = []
    for week_block in data.get("data", []):
        for lesson in week_block:
            if lesson.get("selected_date") == today_str:
                course_name = lesson.get("course_name") or "-"
                short = lesson.get("course_short_name") or "-"
                code = lesson.get("course_assignment_coursecode") or lesson.get("course_code") or "-"
                teacher = lesson.get("employee_name") or "-"
                timeslot = lesson.get("timeSlots") or f"{lesson.get('start_time','-')} - {lesson.get('end_time','-')}"
                room = lesson.get("roomcode") or "-"
                lessons.append(f"📚 {course_name}\n🔖 Short: {short} | Kod: {code}\n👨‍🏫 {teacher}\n⏰ {timeslot}\n🏫 {room}")
    if lessons: await message.answer("\n\n".join(lessons))
    else: await message.answer(t(row,"attendance_empty"))

# --- Davomat tugmasi ---
@dp.message(F.text.in_(["✅ Davomat","✅ Attendance"]))
async def attendance_report(message: Message):
    tg_id = message.from_user.id
    row = get_user_by_tg(tg_id)
    if not row:
        await message.answer("❌ Avval login qiling (`/start`)."); return
    if not token_is_valid(row):
        api_username = row[2]; password_plain = decrypt_password(row[3])
        if api_username and password_plain:
            await message.answer(t(row,"token_expired"))
            ok = await try_login_and_store(tg_id, api_username, password_plain, row[9])
            if not ok:
                await message.answer("❌ Avtomatik login amalga oshmadi. /start bilan qayta login qiling."); return
            row = get_user_by_tg(tg_id)
        else:
            await message.answer("❗ Parol bazada mavjud emas — /start bilan qayta login qiling."); return

    token = row[4]; api_user_id = row[7]
    url = f"{ATTENDANCE_API}{api_user_id}/3"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status!=200: await message.answer(t(row,"attendance_fail")); return
                data = await resp.json()
        except: await message.answer(t(row,"attendance_network")); return

    if not data.get("success"): await message.answer(t(row,"attendance_fail")); return
    items = data.get("data",[])
    if not items: await message.answer(t(row,"attendance_empty")); return

    msg_lines = []
    for i in items:
        course_name = i.get("course_name") or "-"
        code = i.get("course_assignment_coursecode") or "-"
        present = i.get("present") or 0
        total = i.get("total") or 0
        percentage = i.get("percentage") or 0
        msg_lines.append(f"📚 {course_name} | {code}\n✅ {present}/{total} | {percentage}%")
    await message.answer("\n\n".join(msg_lines))


USER_DETAILS_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/getUserDetailsById/{}"
ROLES_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/findRoles/{}"
API_BASE = "https://acharyajava.uz/AcharyaInstituteUZB/api"

# localized labels for /me response
LABELS = {
    "uz": {
        "title": "👤 Profil ma'lumotlari",
        "id": "🆔 ID",
        "name": "👤 Ism",
        "username": "💻 API username",
        "emp_id": "🔢 Emp/Std ID",
        "email": "📧 Email",
        "mobile": "📱 Telefon",
        "role": "🎭 Rol",
        "role_id": "🔖 Role ID",
        "usertype": "🔰 User type"
    },
    "en": {
        "title": "👤 Profile info",
        "id": "🆔 ID",
        "name": "👤 Name",
        "username": "💻 API username",
        "emp_id": "🔢 Emp/Std ID",
        "email": "📧 Email",
        "mobile": "📱 Mobile",
        "role": "🎭 Role",
        "role_id": "🔖 Role ID",
        "usertype": "🔰 User type"
    }
}

def get_lang_from_row(row):
    # your DB returns tuple: lang is at index 9 per your schema; default 'uz'
    try:
        return row[9] if row and len(row) > 9 and row[9] else "uz"
    except Exception:
        return "uz"

async def fetch_user_details_and_roles(session, token: str, api_user_id: int):
    headers = {"Authorization": f"Bearer {token}"}
    user_json = None
    roles_json = None

    # 1) user details by id
    try:
        ud_url = USER_DETAILS_API.format(api_user_id)
        async with session.get(ud_url, headers=headers, timeout=20) as ud_resp:
            if ud_resp.status == 200:
                user_json = await ud_resp.json()
            else:
                # non-200 -> return what we have (None)
                return None, None
    except Exception:
        return None, None

    # 2) roles
    try:
        roles_url = ROLES_API.format(api_user_id)
        async with session.get(roles_url, headers=headers, timeout=10) as r_resp:
            if r_resp.status == 200:
                roles_json = await r_resp.json()
            else:
                roles_json = None
    except Exception:
        roles_json = None

    return user_json, roles_json

@dp.message(F.text == "/me")
async def cmd_me(message: Message):
    tg_id = message.from_user.id
    row = get_user_by_tg(tg_id)   # your existing function that returns tuple

    if not row:
        await message.answer("❌ Avval login qiling (`/start`).")
        return

    # token index = 4 in your schema (0=id,1=tg_id,2=api_username,3=password_enc,4=token,...)
    token = row[4]
    api_user_id = row[7]   # API's user id (must be present; if not, ask to relogin)
    lang = get_lang_from_row(row)
    L = LABELS.get(lang, LABELS["uz"])

    if not token:
        await message.answer("⚠️ Token topilmadi. Iltimos /start bilan qayta login qiling.")
        return
    if not api_user_id:
        await message.answer("⚠️ API user id topilmadi. Iltimos /start bilan qayta login qiling.")
        return

    async with aiohttp.ClientSession() as session:
        user_json, roles_json = await fetch_user_details_and_roles(session, token, api_user_id)

    if not user_json or not user_json.get("success"):
        # token eskirgan yoki API javobi xato
        await message.answer("⚠️ Profilni olishda xatolik. Token muddati tugagan yoki server javob bermadi. Iltimos /start bilan qayta login qiling.")
        return

    user_info = user_json.get("data", {}) or {}

    # extract common fields (use keys you saw in Flask flow)
    name = user_info.get("name") or user_info.get("preferredName") or user_info.get("userName") or "-"
    email = user_info.get("email") or user_info.get("emailId") or "-"
    mobile = user_info.get("mobileNumber") or user_info.get("mobile") or "-"
    emp_or_std_id = user_info.get("empOrStdId") or "-"
    usertype = user_info.get("usertype") or "-"

    # roles parsing: API returns data (list). adapt to structure you observed:
    role_name = "Noma'lum"
    role_short = "N/A"
    role_id = "-"
    if roles_json and roles_json.get("data"):
        # sometimes role data is a list; take first
        rd = roles_json.get("data")
        if isinstance(rd, list) and len(rd) > 0:
            r0 = rd[0]
            # r0 might be dict or nested - try common keys
            if isinstance(r0, dict):
                role_name = r0.get("role_name") or r0.get("role") or r0.get("name") or role_name
                role_short = r0.get("role_short_name") or r0.get("roleShort") or role_short
                role_id = r0.get("role_id") or r0.get("id") or role_id

    # also include api username from DB (index 2)
    api_username = row[2] or "-"

    # build message (HTML)
    text = (
        f"{L['title']}\n\n"
        f"{L['id']}: <code>{api_user_id}</code>\n"
        f"{L['name']}: {name}\n"
        f"{L['username']}: <code>{api_username}</code>\n"
        f"{L['emp_id']}: {emp_or_std_id}\n"
        f"{L['email']}: {email}\n"
        f"{L['mobile']}: {mobile}\n"
        f"{L['role']}: {role_name} ({role_short})\n"
        f"{L['role_id']}: {role_id}\n"
        f"{L['usertype']}: {usertype}\n"
    )

    await message.answer(text, parse_mode="HTML")

# --- Run bot ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
