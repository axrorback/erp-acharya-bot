from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from datetime import datetime, timedelta
import httpx, requests, jwt

# === CONFIG ===
SECRET_KEY = "super-secret-key"  # ⚠️ Buni .env faylda saqlang
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

app = FastAPI(title="Acharya Student API (Secure)")

# === API URL ===
BASE_URL = "https://acharyajava.uz/AcharyaInstituteUZB/api"
LOGIN_API = f"{BASE_URL}/authenticate"
USER_DETAILS_API = f"{BASE_URL}/getUserDetailsById/{{}}"
TIMETABLE_API = f"{BASE_URL}/academic/timeTableDetailsOfStudentOrEmployeeForMobile"
ATTENDANCE_API = f"{BASE_URL}/student/attendanceReportForStudentProfileByStudentId/{{}}/{{}}"
MENTOR_API = f"{BASE_URL}/proctor/fetchAllProctorStudentAssignmentDetail?page=0&page_size=10000&sort=created_date"

# Rector login (mentor uchun)
RECTOR_USER = "Rector"
RECTOR_PASS = "acharya1234"
rector_cache = {"token": None}

# ERP token cache (user_id → token)
erp_cache = {}

# JWT auth schema
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# === Rector token olish ===
def rector_token():
    if rector_cache["token"] is None:
        payload = {"username": RECTOR_USER, "password": RECTOR_PASS}
        res = requests.post(LOGIN_API, json=payload, verify=False)
        if res.status_code != 200:
            raise Exception("❌ Rector login failed")
        rector_cache["token"] = res.json()["data"]["token"]
    return rector_cache["token"]


# === ERP login ===
async def erp_login(username: str, password: str):
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(LOGIN_API, json={"username": username, "password": password})
    if res.status_code != 200 or not res.json().get("success"):
        raise HTTPException(status_code=401, detail="❌ Login failed")
    return res.json()["data"]


# === JWT yaratish ===
def create_jwt(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# === JWT tekshirish ===
def verify_jwt(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid JWT")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="JWT invalid")


# === Mentor topish ===
def find_mentor(auid: str):
    headers = {"Authorization": f"Bearer {rector_token()}"}
    res = requests.get(MENTOR_API, headers=headers, verify=False)
    if res.status_code != 200:
        return None, None
    students = res.json().get("data", {}).get("Paginated_data", {}).get("content", [])
    for s in students:
        if s["auid"] == auid:
            return s["employee_name"], s["empcode"]
    return None, None


# === LOGIN ===
@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    data = await erp_login(form_data.username, form_data.password)
    token = data["token"]
    user_id = data["userId"]

    # ERP token cache
    erp_cache[user_id] = token

    # JWT qaytarish
    jwt_token = create_jwt({"sub": form_data.username, "user_id": user_id})
    return {"access_token": jwt_token, "token_type": "bearer"}


# === PROFILE ===
@app.get("/profile/")
async def profile(user=Depends(verify_jwt)):
    user_id = user["user_id"]
    token = erp_cache.get(user_id)
    if not token:
        raise HTTPException(status_code=401, detail="ERP token yo‘q")

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.get(USER_DETAILS_API.format(user_id), headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="❌ ERP dan profil olishda xato")

    data = res.json()["data"]
    mentor_name, mentor_auid = find_mentor(user["sub"])

    return {
        "full_name": data.get("name"),
        "email": data.get("email"),
        "username": user["sub"],
        "student_id": data.get("empOrStdId"),
        "year_or_sem": data.get("year_or_sem"),
        "mentor": mentor_name or "Mentor topilmadi",
        "mentor_auid": mentor_auid or "-"
    }


# === TIMETABLE ===
@app.get("/timetable")
async def timetable(user=Depends(verify_jwt)):
    user_id = user["user_id"]
    token = erp_cache.get(user_id)
    if not token:
        raise HTTPException(status_code=401, detail="ERP token yo‘q")

    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now()
    params = {"student_id": user_id, "year": now.year, "month": now.month}

    async with httpx.AsyncClient(verify=False) as client:
        res = await client.get(TIMETABLE_API, headers=headers, params=params)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="❌ Jadval olishda xato")

    raw_data = res.json().get("data", [])
    today_str = now.strftime("%Y-%m-%d")
    timetable = []

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

    mentor_name, mentor_auid = find_mentor(user["sub"])
    return {
        "date": today_str,
        "timetable": timetable or "Bugun dars yo‘q",
        "mentor": mentor_name or "Mentor topilmadi",
        "mentor_auid": mentor_auid or "-"
    }


# === ATTENDANCE ===
@app.get("/attendance")
async def attendance(user=Depends(verify_jwt)):
    user_id = user["user_id"]
    token = erp_cache.get(user_id)
    if not token:
        raise HTTPException(status_code=401, detail="ERP token yo‘q")

    headers = {"Authorization": f"Bearer {token}"}
    year_or_sem = "2025"  # ⚠️ Kerakli qiymatni o‘zingizga moslab qo‘ying
    url = ATTENDANCE_API.format(user_id, year_or_sem)

    async with httpx.AsyncClient(verify=False) as client:
        res = await client.get(url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="❌ Attendance olishda xato")

    data = res.json().get("data", [])
    simplified = [
        {"course": item["course_name"], "present": item["present"], "total": item["total"], "percentage": item["percentage"]}
        for item in data
    ]

    mentor_name, mentor_auid = find_mentor(user["sub"])
    return {
        "attendance": simplified,
        "mentor": mentor_name or "Mentor topilmadi",
        "mentor_auid": mentor_auid or "-"
    }
