"""Seed 20 curated financial/dispute experiences (admin knowledge base)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import ExperienceKnowledgeItem
from app.services.experience_layer import normalize_origin_kind

# title, description, prevention, keywords, category
EXPERIENCES: list[dict] = [
    {
        "experience_id": "EXP-FIN-001",
        "title": "عدم ثبت به‌موقع اخطار ادعا (Claim Notice)",
        "description": (
            "پیمانکار در مهلت قراردادی (معمولاً ۲۸ روز) اخطار کتبی ادعای تأخیر/خسارت را به کارفرما یا مهندس مشاور نمی‌دهد؛ "
            "طبق شرایط عمومی، این تأخیر می‌تواند کل حق ادعا را ساقط کند، حتی اگر ادعا از نظر ماهوی درست باشد."
        ),
        "prevention": "الزام به ثبت مکاتبات با مهلت مشخص در شرایط خصوصی + یادآوری خودکار برای تیم پیمانکار.",
        "keywords": ["اخطار", "ادعا", "claim", "notice", "۲۸ روز", "مهلت اطلاع"],
        "category": "contract_claims",
    },
    {
        "experience_id": "EXP-FIN-002",
        "title": "ابهام در شرح کار و حدود مسئولیت",
        "description": (
            "مرز مسئولیت بین پیمانکار اصلی، پیمانکاران جزء، و کارفرما (مثلاً تأمین برق موقت، باربرداری) به‌روشنی مشخص نیست؛ "
            "در حین اجرا هرکدام کار را به‌عهده دیگری می‌گذارند و کار متوقف یا با تأخیر انجام می‌شود."
        ),
        "prevention": "جدول تفکیک مسئولیت (RACI) به‌عنوان پیوست شرح خدمات الزامی شود.",
        "keywords": ["حدود کار", "شرح خدمات", "مسئولیت", "scope", "interface"],
        "category": "contract_claims",
    },
    {
        "experience_id": "EXP-FIN-003",
        "title": "عدم تطابق مقادیر متره با نقشه‌های اجرایی",
        "description": (
            "مقدار یک آیتم در BOQ با آنچه از نقشه محاسبه می‌شود متفاوت است؛ "
            "در حین اجرا پیمانکار مابه‌التفاوت را ادعا می‌کند و کارفرما آن را نمی‌پذیرد."
        ),
        "prevention": "بازمقایسه و بازمحاسبه مستقل مقادیر کلیدی BOQ از روی نقشه، پیش از انتشار اسناد مناقصه.",
        "keywords": ["متره", "BOQ", "مقادیر", "نقشه", "مغایرت کمی"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-004",
        "title": "صدور شفاهی دستور تغییر کار (Variation)",
        "description": (
            "ناظر یا کارفرما به‌صورت شفاهی درخواست تغییر یا کار اضافه می‌کند؛ "
            "بعداً بر سر وقوع، حجم، یا مبنای قیمت آن تغییر اختلاف پیش می‌آید چون هیچ سند مکتوبی وجود ندارد."
        ),
        "prevention": "الزام قراردادی صریح که هیچ تغییری بدون دستور تغییر مکتوب (Variation Order) قابل اجرا/پرداخت نیست.",
        "keywords": ["دستور تغییر", "variation order", "کار اضافه", "تغییر مقادیر"],
        "category": "contract_claims",
    },
    {
        "experience_id": "EXP-FIN-005",
        "title": "جدول جرائم تأخیر بدون سقف منطقی",
        "description": (
            "جریمه روزانه تأخیر (LD) طوری تعیین شده که در مدت کوتاهی به سقف غیرمنطقی (بیش از ۲۰-۳۰٪ ارزش پیمان) می‌رسد؛ "
            "این نوع بند در مراجع حقوقی قابل طعن است و پیمانکاران معتبر از شرکت در مناقصه صرف‌نظر می‌کنند یا بعداً دعوی می‌کنند."
        ),
        "prevention": "سقف جریمه تأخیر متناسب با استاندارد رایج (۱۰-۲۰٪ ارزش پیمان) تعیین شود.",
        "keywords": ["جریمه تأخیر", "LD", "delay damages", "سقف جریمه"],
        "category": "contract_claims",
    },
    {
        "experience_id": "EXP-FIN-006",
        "title": "فرمول تعدیل آحاد بها یا Base Date نامشخص",
        "description": (
            "اسناد مشخص نمی‌کنند پیمان مشمول تعدیل است یا نه، یا به کدام بخشنامه/Base Date ارجاع می‌دهد؛ "
            "در پایان کار محاسبه مبلغ تعدیل محل اختلاف اصلی می‌شود."
        ),
        "prevention": "ذکر صریح مشمولیت تعدیل، شماره بخشنامه، و تاریخ مبنا در شرایط خصوصی.",
        "keywords": ["تعدیل", "آحاد بها", "Base Date", "بخشنامه تعدیل"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-007",
        "title": "آزادسازی ضمانت‌نامه انجام تعهدات بدون شرایط شفاف",
        "description": (
            "زمان و شرایط دقیق آزادسازی (کامل یا تدریجی) ضمانت‌نامه حسن انجام کار مشخص نیست؛ "
            "در پایان پروژه کارفرما آزادسازی را به تأخیر می‌اندازد و پیمانکار منابع مالی‌اش را برای مدت طولانی بلوکه‌شده می‌بیند."
        ),
        "prevention": "جدول زمانی و درصدی مشخص برای کاهش تدریجی/آزادسازی ضمانت‌نامه در شرایط خصوصی درج شود.",
        "keywords": ["ضمانت‌نامه", "performance bond", "آزادسازی", "تضمین"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-008",
        "title": "عدم مستندسازی صورت‌جلسه تحویل کارگاه",
        "description": (
            "تاریخ و شرایط تحویل کارگاه به پیمانکار به‌صورت رسمی صورت‌جلسه نمی‌شود؛ "
            "چون مبنای محاسبه تمدید مدت (EOT) از همین تاریخ شروع می‌شود، نبود سند رسمی کل محاسبات بعدی را مخدوش می‌کند."
        ),
        "prevention": "الزام به تنظیم و امضای صورت‌جلسه تحویل کارگاه در روز اول، پیوست‌شده به اسناد پیمان.",
        "keywords": ["تحویل کارگاه", "site handover", "صورت‌جلسه", "EOT"],
        "category": "schedule",
    },
    {
        "experience_id": "EXP-FIN-009",
        "title": "اقلام Provisional Sum بدون سازوکار تسویه شفاف",
        "description": (
            "مبالغ پیش‌بینی‌شده برای اقلام نامشخص (Provisional Sum) در قرارداد هست، "
            "ولی نحوه تسویه نهایی روشن نیست؛ در پایان کار بر سر مبلغ نهایی این اقلام اختلاف پیش می‌آید."
        ),
        "prevention": "رویه مشخص تأیید و تسویه هر آیتم Provisional Sum پیش از اجرا در شرایط خصوصی تعریف شود.",
        "keywords": ["Provisional Sum", "Prime Cost", "اقلام باز", "تسویه"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-010",
        "title": "عدم تطابق دوره تضمین (Defects Liability) بین اسناد",
        "description": (
            "مدت دوره تضمین در موافقت‌نامه، شرایط خصوصی، و برنامه زمانبندی یکسان نیست؛ "
            "در پایان پروژه معلوم نمی‌شود مسئولیت رفع نواقص تا چه تاریخی بر عهده پیمانکار است."
        ),
        "prevention": "یک عدد واحد برای دوره تضمین در تمام اسناد پروژه Cross-check شود پیش از امضا.",
        "keywords": ["دوره تضمین", "defects liability", "تحویل قطعی"],
        "category": "schedule",
    },
    {
        "experience_id": "EXP-FIN-011",
        "title": "کسور وجه‌الضمان (Retention) بدون شرایط شفاف آزادسازی",
        "description": (
            "درصد کسور و زمان دقیق بازپرداخت آن مشخص نیست؛ "
            "پیمانکار در پایان کار مبلغ نگه‌داشته‌شده را با تأخیر طولانی یا با کسر دریافت می‌کند."
        ),
        "prevention": "درصد دقیق و زمان‌بندی آزادسازی کسور در جدول پرداخت به‌صراحت درج شود.",
        "keywords": ["کسور", "وجه‌الضمان", "retention", "حسن انجام کار"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-012",
        "title": "خلط فورس‌ماژور با سایر تأخیرات مجاز",
        "description": (
            "تعریف فورس‌ماژور در اسناد با سایر انواع تأخیر مجاز (تأخیر کارفرما، تعلیق کار) به‌روشنی تفکیک نشده؛ "
            "پیمانکار تأخیرات عادی را تحت پوشش فورس‌ماژور ادعا می‌کند و کارفرما آن را رد می‌کند."
        ),
        "prevention": "تعریف فورس‌ماژور دقیقاً مطابق شرایط عمومی و جدا از سایر مواد تمدید مدت در شرایط خصوصی تکرار/تأیید شود.",
        "keywords": ["فورس ماژور", "force majeure", "تعلیق کار", "رویداد قهری"],
        "category": "contract_claims",
    },
    {
        "experience_id": "EXP-FIN-013",
        "title": "نبود الزام اثبات پرداخت به پیمانکاران جزء",
        "description": (
            "قرارداد پیمانکار جزء را ملزم نمی‌کند اثبات کند مبالغ دریافتی از کارفرما را به‌موقع به پیمانکاران زیرمجموعه پرداخت کرده؛ "
            "ریسک توقف کار توسط پیمانکار جزء طلبکار وجود دارد."
        ),
        "prevention": "الزام ارائه مدرک پرداخت پیمانکاران جزء به‌عنوان پیش‌شرط صدور گواهی پرداخت بعدی.",
        "keywords": ["پیمانکار جزء", "subcontractor", "زنجیره پرداخت"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-014",
        "title": "عدم تطابق واحد پول قرارداد با اقلام وارداتی",
        "description": (
            "قرارداد به ریال است ولی بخشی از اقلام (تجهیزات وارداتی) وابسته به ارز خارجی‌اند و مکانیزم تعدیل نرخ ارز مشخص نشده؛ "
            "نوسان ارز به منبع اصلی اختلاف مالی تبدیل می‌شود."
        ),
        "prevention": "نرخ ارز مرجع و مکانیزم تعدیل آن برای اقلام وارداتی به‌صراحت در شرایط خصوصی درج شود.",
        "keywords": ["ارز", "نرخ تبدیل", "اقلام وارداتی", "currency"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-015",
        "title": "مغایرت صورت‌وضعیت موقت با پیشرفت فیزیکی واقعی",
        "description": (
            "درصد پیشرفت اعلام‌شده در صورت‌وضعیت ماهانه با پیشرفت واقعی سایت هم‌خوانی ندارد؛ "
            "منجر به رد صورت‌وضعیت توسط ناظر و تأخیر در پرداخت می‌شود."
        ),
        "prevention": "الزام تأیید مشترک درصد پیشرفت (ناظر + پیمانکار) با مستندات تصویری/اندازه‌گیری پیش از ثبت صورت‌وضعیت.",
        "keywords": ["صورت‌وضعیت", "پیشرفت فیزیکی", "interim payment"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-016",
        "title": "عدم توافق قیمت اقلام ستاره‌دار پیش از اجرا",
        "description": (
            "آیتمی که در فهرست بهای پایه نیست (ستاره‌دار) بدون توافق قبلی بر سر قیمت اجرا می‌شود؛ "
            "بعد از اتمام کار پیمانکار و کارفرما بر سر نرخ منصفانه آن اختلاف پیدا می‌کنند."
        ),
        "prevention": "الزام به تعیین و تأیید کتبی نرخ هر قلم ستاره‌دار پیش از شروع اجرای همان قلم.",
        "keywords": ["اقلام ستاره‌دار", "قیمت جدید", "star items"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-017",
        "title": "ابهام مسئولیت تأمین زیرساخت موقت کارگاهی",
        "description": (
            "تأمین برق، آب، و دفاتر موقت کارگاه بین کارفرما و پیمانکار به‌روشنی تقسیم نشده؛ "
            "پیمانکار هزینه‌های پیش‌بینی‌نشده متحمل می‌شود و آن را به‌عنوان ادعای جبران هزینه مطرح می‌کند."
        ),
        "prevention": "جدول مشخص تأمین تأسیسات موقت کارگاهی با ذکر طرف مسئول هر مورد، پیوست شرح خدمات.",
        "keywords": ["تجهیز کارگاه", "زیرساخت موقت", "برق موقت"],
        "category": "procurement_tender",
    },
    {
        "experience_id": "EXP-FIN-018",
        "title": "تغییر محدوده کار بدون تعدیل متناظر برنامه زمانبندی",
        "description": (
            "وقتی محدوده کار تغییر می‌کند، برنامه زمانبندی به‌روزرسانی رسمی نمی‌شود؛ "
            "در پایان پروژه ادعای تمدید مدت پیمانکار چون به تغییر مستند در برنامه مرتبط نیست، توسط کارفرما رد می‌شود."
        ),
        "prevention": "الزام به‌روزرسانی برنامه زمانبندی و ثبت اثر هر Variation Order روی مسیر بحرانی، هم‌زمان با صدور دستور تغییر.",
        "keywords": ["تغییر محدوده", "برنامه زمانبندی", "EOT", "impact"],
        "category": "schedule",
    },
    {
        "experience_id": "EXP-FIN-019",
        "title": "مغایرت پوشش بیمه با ارزش واقعی پروژه یا ریسک‌های آن",
        "description": (
            "سقف بیمه تمام‌خطر پیمانکاران (CAR/EAR) کمتر از ارزش واقعی پروژه تعیین شده، یا بیمه مسئولیت شخص ثالث کافی نیست؛ "
            "در صورت بروز خسارت، بخشی بیمه‌نشده می‌ماند و مسئولیت مالی جبران آن محل نزاع می‌شود."
        ),
        "prevention": "بررسی و تطبیق سقف پوشش بیمه با برآورد به‌روز ارزش پروژه پیش از صدور بیمه‌نامه.",
        "keywords": ["بیمه", "CAR", "EAR", "پوشش بیمه", "خسارت"],
        "category": "boq_cost",
    },
    {
        "experience_id": "EXP-FIN-020",
        "title": "ابهام در معیار پذیرش کیفیت و نقاط بازرسی الزامی",
        "description": (
            "معیار دقیق پذیرش کیفیت یک آیتم اجرایی و نقاط بازرسی الزامی پیش از پوشش کار (Hold Point) مشخص نیست؛ "
            "تفسیر متفاوت از یک معیار نانوشته هزینه اجرای مجدد یا اختلاف مالی ایجاد می‌کند."
        ),
        "prevention": "معیار پذیرش عددی برای اقلام حساس + فهرست Hold Point های الزامی در برنامه کیفیت پیوست شود.",
        "keywords": ["پذیرش کیفیت", "Hold Point", "تلرانس", "کنترل کیفیت"],
        "category": "drawing_technical",
    },
]


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        inserted = 0
        updated = 0
        for row in EXPERIENCES:
            eid = row["experience_id"]
            existing = (
                await db.execute(
                    select(ExperienceKnowledgeItem).where(ExperienceKnowledgeItem.experience_id == eid)
                )
            ).scalar_one_or_none()
            payload = {
                "title": row["title"],
                "description": row["description"],
                "category": row["category"],
                "origin_kind": normalize_origin_kind("admin_curated"),
                "source": "seed:financial_dispute_20",
                "author": "admin",
                "validation_status": "validated",
                "confidence_level": "high",
                "related_risk_category": row["category"],
                "recommended_prevention": row["prevention"],
                "match_keywords_json": json.dumps(row["keywords"], ensure_ascii=False),
                "is_active": True,
            }
            if existing is None:
                db.add(ExperienceKnowledgeItem(experience_id=eid, version=1, **payload))
                inserted += 1
            else:
                for k, v in payload.items():
                    setattr(existing, k, v)
                existing.version = int(existing.version or 1) + 1
                updated += 1
        await db.commit()
        total = (
            await db.execute(select(ExperienceKnowledgeItem))
        ).scalars().all()
        print(f"seeded inserted={inserted} updated={updated} table_count={len(total)}")


if __name__ == "__main__":
    asyncio.run(main())
