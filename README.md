# TenderRisk Analyzer

ابزار وب برای بررسی ریسک اسناد مناقصه از نگاه **کارفرما**.

## معماری پیشنهادی (ساده و عملی)

| بخش | کجا | نقش |
|-----|-----|-----|
| Frontend | **Vercel** | سایت کاربر |
| Database + Files | **Supabase** | Postgres + Storage |
| Backend (OCR/API) | **Railway** | FastAPI — چون OCR روی Vercel جا نمی‌شود |

اگر برنامه‌نویس نیستی، فقط فایل **[SETUP-FA.md](./SETUP-FA.md)** را مرحله‌به‌مرحله انجام بده.

## توسعه محلی

### Backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env
npm run dev
```

- UI: http://localhost:5173  
- API: http://127.0.0.1:8000/api/health  

## فایل‌های مهم اتصال ابری

- `supabase/schema.sql` — ساخت جداول در Supabase  
- `backend/.env.example` — متغیرهای بک‌اند  
- `frontend/.env.example` — آدرس API برای Vercel  
- `backend/Dockerfile` — دیپلوی Railway  
- `frontend/vercel.json` — دیپلوی Vercel  
