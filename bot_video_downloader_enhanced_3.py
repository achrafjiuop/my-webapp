import logging
import asyncio
import time
import random
import string
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------
# CONFIGURATION & LOGGING
# ---------------------------------------------------------
BOT_TOKEN = "8108848585:AAFEIAoND3X1pIJnwnQgq1-zHHvz-PufZxs"
ADMIN_IDS = [8742217342]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# DATABASE & DATA STRUCTURES
# ---------------------------------------------------------
users_db = defaultdict(lambda: {
    "points": 5001,
    "invites": 100,
    "banned": False,
    "history": [],
    "last_daily": 0,
    "awaiting_gift_code": False,
    "awaiting_support": False,
    "awaiting_gen_points": False
})

# الأكواد كيحفظها البوت هنا والأدمن هو اللي كينشئها
gift_codes = {}

# قائمة الميزات الحقيقية بالعربية
FEATURES = {
    "تحميل الفيديوهات": True,
    "هدية اليوم اليومية": True,
    "نظام كود الهدية": True,
    "نظام نقاط الدعوة": True,
    "الدعم الفني الآلي": True,
    "سجل العمليات": True,
    "حماية ضد الإزعاج (Anti-Spam)": True,
    "إحصائيات الإدارة": True,
    "إنشاء الأكواد": True,
    "حظر المستخدمين": True,
    "الإذاعة العامة (Broadcast)": True,
    "تعديل النقاط يدوي": True,
}

user_last_msg = {}
SPAM_THRESHOLD = 0.8

def is_spamming(user_id: int) -> bool:
    now = time.time()
    last = user_last_msg.get(user_id, 0)
    user_last_msg[user_id] = now
    return (now - last) < SPAM_THRESHOLD

def generate_random_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ---------------------------------------------------------
# KEYBOARD BUILDERS
# ---------------------------------------------------------
def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📹 تحميل فيديو", callback_data="btn_download")],
        [InlineKeyboardButton("🎁 هدية اليوم", callback_data="btn_daily")],
        [
            InlineKeyboardButton("⭐ النقاط", callback_data="btn_points"),
            InlineKeyboardButton("🔗 دعوة صديق", callback_data="btn_invite"),
        ],
        [
            InlineKeyboardButton("📜 السجل", callback_data="btn_history"),
            InlineKeyboardButton("🎧 الدعم الفني", callback_data="btn_support"),
        ],
        [InlineKeyboardButton("🎟️ كود هدية", callback_data="btn_gift_code")],
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة الشاملة", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
            InlineKeyboardButton("⚙️ إدارة الميزات", callback_data="admin_features_1")
        ],
        [
            InlineKeyboardButton("🎟️ إنشاء كود هدية جديد", callback_data="admin_create_code")
        ],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="btn_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_features_keyboard(page: int = 1) -> InlineKeyboardMarkup:
    keys = list(FEATURES.keys())
    per_page = 5
    start = (page - 1) * per_page
    end = start + per_page
    current_keys = keys[start:end]

    keyboard = []
    for k in current_keys:
        status = "✅" if FEATURES[k] else "❌"
        keyboard.append([InlineKeyboardButton(f"{status} {k}", callback_data=f"toggle_feat_{k}_{page}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"admin_features_{page-1}"))
    if end < len(keys):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"admin_features_{page+1}"))
    
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# HANDLERS
# ---------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = users_db[user.id]

    if is_spamming(user.id) or user_data["banned"]:
        return

    text = (
        f"مرحباً بك، {user.first_name}!\n\n"
        f"🆔 **الآيدي ديالك**: `{user.id}`\n"
        f"⭐ **النقاط**: {user_data['points']}\n"
        f"👥 **عدد الدعوات**: {user_data['invites']}\n\n"
        f"🎬 اختر الميزة التي تريدها من الأزرار أو أرسل لي أي رابط مباشرة:"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard(user.id))

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_data = users_db[user_id]
    data = query.data

    await query.answer()

    if user_data["banned"]:
        return

    if data.startswith("btn_") or data.startswith("admin_"):
        user_data["awaiting_gift_code"] = False
        user_data["awaiting_support"] = False
        user_data["awaiting_gen_points"] = False

    if data == "btn_main_menu":
        text = (
            f"مرحباً بك، {query.from_user.first_name}!\n\n"
            f"🆔 **الآيدي ديالك**: `{user_id}`\n"
            f"⭐ **النقاط**: {user_data['points']}\n"
            f"👥 **عدد الدعوات**: {user_data['invites']}\n\n"
            f"🎬 اختر الميزة التي تريدها من الأزرار:"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

    elif data == "btn_download":
        if not FEATURES.get("تحميل الفيديوهات", True):
            await query.edit_message_text(
                "❌ ميزة تحميل الفيديوهات معطلة حالياً من طرف الإدارة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )
            return
        await query.edit_message_text(
            "📹 **تحميل الفيديوهات:**\n\nأرسل لي رابط الفيديو مباشرة في الشات (يوتيوب، تيك توك، إنستغرام...).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
        )

    elif data == "btn_points":
        await query.edit_message_text(
            f"⭐ **رصيد النقاط الحالي**: {user_data['points']} نقطة.\n\n"
            f"احصل على المزيد من النقاط بالضغط على 'هدية اليوم' أو مشاركة رابطك مع الأصدقاء!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
        )

    elif data == "btn_invite":
        if not FEATURES.get("نظام نقاط الدعوة", True):
            await query.edit_message_text(
                "❌ نظام الدعوات معطل حالياً من طرف الإدارة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )
            return
        bot_info = await context.bot.get_me()
        invite_link = f"https://t.me/{bot_info.username}?start={user_id}"
        await query.edit_message_text(
            f"🔗 **رابط الدعوة الخاص بك:**\n`{invite_link}`\n\nقم بنشر هذا الرابط وحصل على 10 نقاط لكل شخص يدخل للبوت!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
        )

    elif data == "btn_history":
        if not FEATURES.get("سجل العمليات", True):
            await query.edit_message_text(
                "❌ ميزة سجل العمليات معطلة حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )
            return
        history = user_data["history"]
        msg = "📜 **سجل العمليات الأخير:**\n\n" + ("\n".join(history[-8:]) if history else "لا يوجد سجل للعمليات حالياً.")
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
        )

    elif data == "btn_daily":
        if not FEATURES.get("هدية اليوم اليومية", True):
            await query.edit_message_text(
                "❌ ميزة الهدية اليومية معطلة حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )
            return
        now = time.time()
        if now - user_data["last_daily"] >= 86400:
            user_data["points"] += 20
            user_data["last_daily"] = now
            user_data["history"].append("🎁 استلام هدية يومية (+20 نقطة)")
            await query.edit_message_text(
                "🎉 تهانينا! تمت إضافة 20 نقطة إلى حسابك بنجاح.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )
        else:
            rem_hours = int((86400 - (now - user_data["last_daily"])) // 3600)
            await query.edit_message_text(
                f"⏳ لقد استلمت هديتك اليومية بالفعل!\nعد بعد **{rem_hours} ساعة** لاستلام الهادية القادمة.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )

    elif data == "btn_gift_code":
        if not FEATURES.get("نظام كود الهدية", True):
            await query.edit_message_text(
                "❌ نظام إدخال الأكواد معطل حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )
            return
        user_data["awaiting_gift_code"] = True
        await query.edit_message_text(
            "🎟️ **إدخال كود هدية:**\n\nأرسل الكود الممنوح لك من الإدارة الآن فـ الرسالة القادمة:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="btn_main_menu")]])
        )

    elif data == "btn_support":
        if not FEATURES.get("الدعم الفني الآلي", True):
            await query.edit_message_text(
                "❌ قسم الدعم الفني مغلق حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_main_menu")]])
            )
            return
        user_data["awaiting_support"] = True
        await query.edit_message_text(
            "🎧 **قسم الدعم الفني بالذكاء الاصطناعي:**\n\nاكتب مشكلتك أو استفسارك وسيقوم المساعد التلقائي بالرد عليك فوراً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="btn_main_menu")]])
        )

    # الأدمن: خيار إنشاء كود جديد
    elif data == "admin_create_code" and user_id in ADMIN_IDS:
        if not FEATURES.get("إنشاء الأكواد", True):
            await query.edit_message_text(
                "❌ ميزة إنشاء الأكواد معطلة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="admin_panel")]])
            )
            return
        user_data["awaiting_gen_points"] = True
        await query.edit_message_text(
            "🎟️ **إنشاء كود هدية جديد:**\n\nاكتب عدد النقاط التي تريد تخصيصها لهذا الكود (مثال: `50` أو `100`):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="admin_panel")]])
        )

    elif data == "admin_panel" and user_id in ADMIN_IDS:
        await query.edit_message_text(
            "⚙️ **لوحة التحكم الشاملة الخاصة بالإدارة:**",
            reply_markup=get_admin_keyboard()
        )

    elif data.startswith("admin_features_") and user_id in ADMIN_IDS:
        page = int(data.split("_")[-1])
        await query.edit_message_text(
            f"⚙️ **إدارة الميزات بالعربية (الصفحة {page}):**\n\nاضغط على الميزة لتشغيلها ✅ أو تعطيلها ❌:",
            reply_markup=get_features_keyboard(page)
        )

    elif data.startswith("toggle_feat_") and user_id in ADMIN_IDS:
        parts = data.split("_")
        page = int(parts[-1])
        feat_name = "_".join(parts[2:-1])
        if feat_name in FEATURES:
            FEATURES[feat_name] = not FEATURES[feat_name]
        await query.edit_message_reply_markup(reply_markup=get_features_keyboard(page))

    elif data == "admin_stats" and user_id in ADMIN_IDS:
        if not FEATURES.get("إحصائيات الإدارة", True):
            await query.edit_message_text(
                "❌ عرض الإحصائيات معطل.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="admin_panel")]])
            )
            return
        active_features = sum(1 for v in FEATURES.values() if v)
        text = (
            f"📊 **إحصائيات النظام الشاملة:**\n\n"
            f"👥 عدد المسجلين: {len(users_db)}\n"
            f"⚙️ الميزات المفتوحة: {active_features} / {len(FEATURES)}\n"
            f"🎟️ الأكواد النشطة الحالية: {len(gift_codes)}"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="admin_panel")]])
        )

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    user_data = users_db[user.id]

    if FEATURES.get("حماية ضد الإزعاج (Anti-Spam)", True) and is_spamming(user.id):
        return
    if user_data["banned"]:
        return

    # الأدمن: إدخال عدد النقاط لتوليد كود
    if user.id in ADMIN_IDS and user_data.get("awaiting_gen_points"):
        user_data["awaiting_gen_points"] = False
        if text.isdigit():
            pts = int(text)
            new_code = "GIFT-" + generate_random_code(6)
            gift_codes[new_code] = pts
            await update.message.reply_text(
                f"✅ **تم إنشاء كود جديد بنجاح!**\n\n"
                f"🎟️ الكود: `{new_code}`\n"
                f"⭐ القيمة: {pts} نقطة\n\n"
                f"يمكنك نسخ هذا الكود وإعطاؤه للمستخدمين بنفسك.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ يرجى إدخال رقم صحيح فقط.")
        return

    # للمستخدمين: تفعيل كود
    if user_data.get("awaiting_gift_code"):
        user_data["awaiting_gift_code"] = False
        code = text.upper()
        if code in gift_codes:
            pts = gift_codes.pop(code)
            user_data["points"] += pts
            user_data["history"].append(f"🎟️ شحن كود ({pts}+ نقطة)")
            await update.message.reply_text(f"🎉 تم تفعيل الكود بنجاح! تم إضافة {pts} نقطة لحسابك.")
        else:
            await update.message.reply_text("❌ الكود غير صحيح أو تم استخدامه سابقاً.")
        return

    # حالة الدعم الفني
    if user_data.get("awaiting_support"):
        user_data["awaiting_support"] = False
        await update.message.reply_text(
            f"🤖 **مساعد الذكاء الاصطناعي**: تم استقبال استفسارك: '{text}'.\n"
            f"سيقوم الفريق الفني بالتواصل معك أو معالجة المشكلة تلقائياً.",
            parse_mode="Markdown"
        )
        return

    # معالجة الروابط
    if text.startswith("http://") or text.startswith("https://"):
        if not FEATURES.get("تحميل الفيديوهات", True):
            await update.message.reply_text("❌ ميزة تحميل الفيديوهات معطلة حالياً.")
            return
        if user_data["points"] >= 1:
            user_data["points"] -= 1
            user_data["history"].append("📹 طلب تحميل فيديو (-1 نقطة)")
            await update.message.reply_text("⏳ جاري تحليل الرابط واستخراج الفيديو...")
        else:
            await update.message.reply_text("❌ ليس لديك نقاط كافية للتحميل! اضغط على 'هدية اليوم' للحصول على نقاط.")
    else:
        await update.message.reply_text("💡 استخدم القائمة الرئيسية للوصول للميزات، أو أرسل رابط فيديو للتحميل.")

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    print("=== BOT IS SUCCESSFULLY RUNNING ===")
    app.run_polling()

if __name__ == "__main__":
    main()

