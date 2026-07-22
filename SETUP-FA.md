# راهنمای ساده اتصال (برای غیربرنامه‌نویس)

هدف نهایی:

1. **Supabase** = دیتابیس + جای ذخیره فایل‌ها  
2. **Railway** = مغز برنامه (تحلیل و OCR) — چون روی Vercel جا نمی‌شود  
3. **Vercel** = سایت/فرانت که کاربر می‌بیند  

تو فقط در سایت‌ها کلیک کن؛ کد را من آماده کرده‌ام.

---

## مرحله ۱ — Supabase (جداول)

1. برو به [supabase.com](https://supabase.com) و پروژه‌ات را باز کن.  
2. از منوی چپ: **SQL Editor** → **New query**  
3. محتوای فایل `supabase/schema.sql` همین پروژه را کپی کن و **Run** بزن.  
4. از منوی چپ: **Storage** → **New bucket**  
   - اسم: `project-documents`  
   - فعلاً Public نباشد (Private)  
5. کلیدها را بردار (برای مرحله بعد لازم است):  
   - **Project Settings → API**  
     - `Project URL`  
     - `service_role` (مخفی بماند؛ به کسی نده)  
   - **Project Settings → Database**  
     - Connection string نوع **URI** (با رمز دیتابیس)

---

## مرحله ۲ — Railway (بک‌اند) — ساده‌ترین انتخاب برای تو

چرا Railway؟ چون برنامه باید PDFهای بزرگ را OCR کند و Vercel برای این کار مناسب نیست.

1. برو به [railway.app](https://railway.app) و با همان ایمیل ثبت‌نام/ورود کن.  
2. **New Project** → **Deploy from GitHub** (اول پروژه را روی GitHub بگذار)  
   یا اگر GitHub نداری: **Empty Project** → **Add service** → **Docker** و فولدر `backend` را آپلود/متصل کن.  
3. Root / مسیر سرویس را روی فولدر **`backend`** بگذار (جایی که `Dockerfile` هست).  
4. در Railway برو به **Variables** و این‌ها را بگذار (از Supabase کپی):

```
DATABASE_URL=...همان URI دیتابیس سوپابیس...
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...service_role...
SUPABASE_BUCKET=project-documents
CORS_ORIGINS=http://localhost:5173,https://YOUR_VERCEL_URL.vercel.app
```

5. بعد از Deploy، لینک عمومی بگیر (مثل `https://xxx.up.railway.app`).  
6. در مرورگر باز کن: `https://xxx.up.railway.app/api/health`  
   باید چیزی شبیه `{"status":"ok",...}` ببینی.

---

## مرحله ۳ — Vercel (سایت)

1. برو به [vercel.com](https://vercel.com) با همان ایمیل.  
2. **Add New Project** → ریپوی GitHub همین پروژه را انتخاب کن.  
3. تنظیمات مهم:  
   - **Root Directory** = `frontend`  
   - Framework = Vite  
4. در **Environment Variables** این را بگذار:

```
VITE_API_BASE=https://YOUR_RAILWAY_APP.up.railway.app/api
```

5. Deploy بزن. لینک Vercel را کپی کن.  
6. برگرد Railway → متغیر `CORS_ORIGINS` را آپدیت کن و لینک Vercel را اضافه کن، بعد Redeploy.

---

## چک نهایی

- باز کردن سایت Vercel  
- ساخت یک پروژه تست  
- آپلود یک فایل کوچک  
- زدن «اجرای تحلیل ریسک»

اگر جایی گیر کردی، فقط بگو در کدام مرحله‌ای (۱ یا ۲ یا ۳) و چه پیام خطایی می‌بینی.

---

## نکته امنیتی خیلی مهم

- کلید `service_role` را **هیچ‌وقت** در فرانت یا چت عمومی نگذار.  
- فقط داخل Variables بک‌اند (Railway) قرار بگیرد.
