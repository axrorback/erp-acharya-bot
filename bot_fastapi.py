from aiogram import Bot, Dispatcher, F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message
import asyncio
import logging
import httpx

TOKEN = "._."
BASE_URL = "http://127.0.0.1:8000"
ADMINS = [7184964035, 5789956459]

USERS = {
    "student1": {"username": "ABT24CCS008(AxrorBek)"},
    "student2": {"username": "ABC24CCL001(Asadbek)"},
}

bot = Bot(token=TOKEN)
dp = Dispatcher()

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Davomat")],
        [KeyboardButton(text="📅 Dars jadvali")],
        [KeyboardButton(text="👤 Profil")],
    ],
    resize_keyboard=True
)

ok_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ Orqaga")]],
    resize_keyboard=True
)

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# 🔹 Start komandasi
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Siz admin emassiz!\n\nBu bot faqat @axrorback va @asad_back uchun ")
    await message.answer("👋 Salom!\nKerakli bo‘limni tanlang:", reply_markup=main_kb)


# 🔹 Davomat
@dp.message(F.text == "📊 Davomat")
async def attendance_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Sizga ruxsat yo‘q")

    user_key = "student1" if message.from_user.id == 5789956459 else "student2"
    username = USERS[user_key]["username"]

    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/attendance/{user_key}")

    if res.status_code != 200:
        return await message.answer("❌ Davomatni olishda xatolik", reply_markup=ok_kb)

    data = res.json()
    attendance = data.get("attendance", [])

    if not attendance:
        return await message.answer("❌ Bugun dars bo‘lmadi yoki server ishlamayapti", reply_markup=ok_kb)

    text = f"📊 *Davomat — {username}*\n\n"
    for item in attendance:
        percent = int(item['percentage'])
        emoji = "🟢" if percent >= 75 else "🟡" if percent >= 50 else "🔴"
        text += (f"{emoji} *{item['course']}*\n"
                 f"   ✅ Davomat: {item['present']} / {item['total']}\n"
                 f"   📈 Foiz: {item['percentage']}%\n\n")

    await message.answer(text, parse_mode="Markdown", reply_markup=ok_kb)


# 🔹 Dars jadvali
@dp.message(F.text == "📅 Dars jadvali")
async def timetable_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Sizga ruxsat yo‘q")

    user_key = "student1" if message.from_user.id == 5789956459 else "student2"
    username = USERS[user_key]["username"]

    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/timetable/{user_key}")

    if res.status_code != 200:
        return await message.answer("❌ Jadvalni olishda xatolik", reply_markup=ok_kb)

    data = res.json()
    timetable = data.get("timetable")

    if not timetable:
        return await message.answer("❌ Bugun dars bo‘lmagan ko‘rinadi", reply_markup=ok_kb)

    text = f"📅 *Bugungi darslar — {username}*\n\n"
    for t in timetable:
        text += (f"🕒 {t['time']}\n"
                 f"📘 {t['subject']} ({t['short']})\n"
                 f"👨‍🏫 {t['teacher']}\n"
                 f"🏫 {t['room']}\n"
                 f"📌 Status: {t['status']}\n\n")

    await message.answer(text, parse_mode="Markdown", reply_markup=ok_kb)


# 🔹 Profil
@dp.message(F.text == "👤 Profil")
async def profile_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Sizga ruxsat yo‘q")

    user_key = "student1" if message.from_user.id == 5789956459 else "student2"
    username = USERS[user_key]["username"]

    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/profile/{user_key}")

    if res.status_code != 200:
        return await message.answer("❌ Profilni olishda xatolik", reply_markup=ok_kb)

    data = res.json()
    text = (f"👤 *Profil — {username}*\n\n"
            f"📛 Ism: {data.get('full_name')}\n\n"
            f"🎓 Pochta: {data.get('email')}\n\n"
            f"🏫 AUID: {data.get('username')}\n\n"
            )

    await message.answer(text, parse_mode="Markdown", reply_markup=ok_kb)


# 🔹 Orqaga
@dp.message(F.text == "⬅️ Orqaga")
async def back_cmd(message: Message):
    await message.answer("🔙 Asosiy menyu", reply_markup=main_kb)


# 🚀 Run
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
