from fastapi import FastAPI, HTTPException
import httpx
from typing import Dict
from datetime import datetime

app = FastAPI()

# API endpoints
LOGIN_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/authenticate"
USER_DETAILS_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/getUserDetailsById/{}"
TIMETABLE_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/academic/timeTableDetailsOfStudentOrEmployeeForMobile"
ATTENDANCE_API = "https://acharyajava.uz/AcharyaInstituteUZB/api/student/attendanceReportForStudentProfileByStudentId/{}/{}"

# Bizning userlar
USERS = {
    "student1": {
        "username": "ABT24CCS008",
        "password": "Kelajak5002@",
        "student_id": 689,
        "year_or_sem": 3
    },
    "student2": {
        "username": "ABC24CCL001",
        "password": "acharya1234",
        "student_id": 729,
        "year_or_sem": 3
    }
}


async def get_token(user_key: str) -> Dict:
    """Har safar yangi token olish"""
    creds = USERS.get(user_key)
    if not creds:
        raise HTTPException(status_code=404, detail="User topilmadi")

    async with httpx.AsyncClient() as client:
        res = await client.post(LOGIN_API, json={
            "username": creds["username"],
            "password": creds["password"]
        })

    if res.status_code != 200 or not res.json().get("success"):
        raise HTTPException(status_code=401, detail="Login xatolik")

    data = res.json()["data"]
    return {
        "token": data["token"],
        "user_id": data["userId"]
    }


@app.get("/profile/{user_key}")
async def get_profile(user_key: str):
    """User profilini olish"""
    if user_key not in USERS:
        raise HTTPException(status_code=404, detail="Faqat student1 va student2 mavjud")

    token_data = await get_token(user_key)
    headers = {"Authorization": f"Bearer {token_data['token']}"}

    async with httpx.AsyncClient() as client:
        detail_res = await client.get(USER_DETAILS_API.format(token_data["user_id"]), headers=headers)

    if detail_res.status_code != 200:
        raise HTTPException(status_code=500, detail="User ma'lumotini olishda xatolik")

    data = detail_res.json().get("data", {})

    return {
        "full_name": data.get("name"),
        "email": data.get("email"),
        "username": USERS[user_key]["username"]
    }


@app.get("/timetable/{user_key}")
async def get_timetable(user_key: str):
    """Bugungi kun timetable"""
    if user_key not in USERS:
        raise HTTPException(status_code=404, detail="User topilmadi")

    creds = USERS[user_key]
    token_data = await get_token(user_key)
    headers = {"Authorization": f"Bearer {token_data['token']}"}

    now = datetime.now()
    params = {
        "student_id": creds["student_id"],
        "year": now.year,
        "month": now.month
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(TIMETABLE_API, headers=headers, params=params)

    if res.status_code != 200:
        return {"message": "ERP bazasi ishlamayapti yoki noto‘g‘ri user_id"}

    raw_data = res.json().get("data", [])

    if not raw_data:
        return {"message": "Bugun dam olish kuni yoki ERP server ishlamayapti"}

    timetable = []
    today_str = now.strftime("%Y-%m-%d")

    for day in raw_data:
        for item in day:
            if (item.get("date_of_class") or item.get("from_date")) == today_str:
                timetable.append({
                    "date": today_str,
                    "time": item.get("timeSlots"),
                    "subject": item.get("course_name") or item.get("holiday_name"),
                    "short": item.get("course_short_name") or item.get("leave_type_short"),
                    "teacher": item.get("employee_name"),
                    "room": item.get("roomcode"),
                    "status": item.get("present_status") or item.get("attendance_status")
                })

    if not timetable:
        return {"message": "Bugun dars yo‘q yoki ERP server ishlamayapti"}

    return {
        "user": user_key,
        "date": today_str,
        "timetable": timetable
    }


@app.get("/attendance/{user_key}")
async def get_attendance(user_key: str):
    """Student davomatini olish"""
    if user_key not in USERS:
        raise HTTPException(status_code=404, detail="Faqat student1 va student2 mavjud")

    token_data = await get_token(user_key)
    headers = {"Authorization": f"Bearer {token_data['token']}"}

    student_id = USERS[user_key]["student_id"]
    year_or_sem = USERS[user_key]["year_or_sem"]
    url = ATTENDANCE_API.format(student_id, year_or_sem)

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="Davomat olishda xatolik")

    data = res.json().get("data", [])

    simplified = [
        {
            "course": item["course_name"],
            "present": item["present"],
            "total": item["total"],
            "percentage": item["percentage"]
        }
        for item in data
    ]

    return {"student": user_key, "attendance": simplified}
