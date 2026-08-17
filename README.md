# Tender Risk-MSA

[![Status](https://img.shields.io/badge/Status-In%20Development-yellow)](https://github.com/saharnsarlak-star/construction-ai)
[![Phase](https://img.shields.io/badge/Phase%202-Upcoming-lightgrey)](https://github.com/saharnsarlak-star/construction-ai)

ابزار وب برای بررسی ریسک اسناد مناقصه از نگاه **کارفرما**.

## Project Status

**Phase 2 — In Development / Upcoming**

This repository is the **next planned phase** of the MSA platform. It is under active development and is **not** a complete, production-ready module.

Tender Risk-MSA represents the next planned phase of the MSA platform, focused on automated tender-document validation and readiness scoring.

## معماری پیشنهادی (ساده و عملی)

شرح کامل و به‌روز معماری (استخراج، OCR/CAD، IFC/GAEB، موتور تحلیل): **[ARCHITECTURE.md](./ARCHITECTURE.md)**  

پایهٔ تحلیلی بعدی (Pipeline + Normalization + Ontology — Part 1): **[docs/ARCHITECTURE-PART1-FOUNDATION.md](./docs/ARCHITECTURE-PART1-FOUNDATION.md)**  
عمق تحلیلی Contract / BOQ / Drawings — Part 2: **[docs/ARCHITECTURE-PART2-CONTRACT-BOQ-DRAWINGS.md](./docs/ARCHITECTURE-PART2-CONTRACT-BOQ-DRAWINGS.md)**  
Tender / Specs / Standards — Part 3: **[docs/ARCHITECTURE-PART3-TENDER-SPECS-STANDARDS.md](./docs/ARCHITECTURE-PART3-TENDER-SPECS-STANDARDS.md)**  
Schedule / Geotech / ER / Addenda — Part 4: **[docs/ARCHITECTURE-PART4-SCHEDULE-GEOTECH-ER-ADDENDA.md](./docs/ARCHITECTURE-PART4-SCHEDULE-GEOTECH-ER-ADDENDA.md)**  
Knowledge Graph / Risk KB / Explainable Findings — Part 5: **[docs/ARCHITECTURE-PART5-GRAPH-RISK-XAI.md](./docs/ARCHITECTURE-PART5-GRAPH-RISK-XAI.md)**  
Ontology (authoritative) — Part 6: **[docs/ARCHITECTURE-PART6-ONTOLOGY.md](./docs/ARCHITECTURE-PART6-ONTOLOGY.md)**  
Seed rules Batch 1 (6 document types → `rules_registry`): **[docs/SEED-RULES-BATCH1.md](./docs/SEED-RULES-BATCH1.md)**  
Seed rules Batch 2 (remaining 4 types → `rules_registry`): **[docs/SEED-RULES-BATCH2.md](./docs/SEED-RULES-BATCH2.md)**

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

- `supabase/schema.sql` — اسکیمای MVP فعلی (پروژه‌های زنده)  
- `supabase/schema_additive_country_logic.sql` — افزودن `project_type` + پروفایل کشور (بدون شکستن MVP)  
- `supabase/schema_ctkm.sql` — مدل کامل CTKM (مرحله بعد؛ فعلاً Run نکنید مگر مهاجرت کامل)  
- `backend/.env.example` — متغیرهای بک‌اند  
- `frontend/.env.example` — آدرس API برای Vercel  
- `backend/Dockerfile` — دیپلوی Railway  
- `frontend/vercel.json` — دیپلوی Vercel  

منطق تحلیل کشورمحور در کد بک‌اند: `backend/app/knowledge/` (پروفایل، قالب سند، قواعد با override، پرامپت AI).
