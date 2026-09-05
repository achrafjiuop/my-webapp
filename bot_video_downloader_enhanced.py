"""
بوت تيليجرام لتحميل الفيديوهات من مواقع التواصل الاجتماعي
(يوتيوب، تيك توك، انستغرام، تويتر/X، فيسبوك...)
مع نظام إدارة متقدم - 100 ميزة قابلة للتفعيل/التطفيل
"""

import os
import json
import logging
import tempfile
import subprocess
import math
import yt_dlp
from datetime import datetime, timedelta
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# توكن البوت (من @BotFather)
BOT_TOKEN = "8108848585:AAFEIAoND3X1pIJnwnQgq1-zHHvz-PufZxs"

# الـ Telegram ID الخاص بـ صاحب البوت حتى توصلو رسائل الدعم
ADMIN_ID = 8742217342

# الحد الأقصى لحجم الفيديو المرسل عبر تيليجرام (بالميغابايت)
MAX_SIZE_MB = 50

# تكلفة تحميل الفيديو بالنقاط: نقطة واحدة لكل دقيقة، بحد أدنى نقطة واحدة
POINTS_PER_MINUTE = 1
MIN_VIDEO_COST = 1

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== نظام النقاط والدعوات ====================

POINTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
PROMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "promo_codes.json")

# الصلاحيات لي يستطيع الأدمن يقيد بيها مستخدم معين
VALID_RESTRICTIONS = ("download", "daily", "invite", "support")

# حماية من السبام: عدد الطلبات المسموحة والمدة (بالثواني)
RATE_LIMIT_MAX_REQUESTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60
rate_limit_tracker = {}  # user_id -> deque of timestamps (في الذاكرة فقط)

# مستخدمين في حالة "كيكتبو رسالة دعم" (في الذاكرة فقط)
waiting_support = set()

# مستخدمين ضغطوا على زر "تحميل فيديو" وننتظر منهم يرسلوا الرابط (في الذاكرة فقط)
waiting_download = set()

# روابط وصلت وتنتظر اختيار الصيغة (فيديو/صوت) من صاحبه
pending_link = {}

# مستخدمين ضغطوا على زر "كود هدية" وننتظر منهم يرسلوا الكود (في الذاكرة فقط)
waiting_redeem = set()

# خريطة: message_id (الخاص بـ الرسالة لي وصلت للأدمن) -> user_id الخاص بـ صاحبه
support_replies = {}

# حالة الأدمن عندما يكون بصدد تعديل نقاط/دعوات مستخدم معين (في الذاكرة فقط)
waiting_admin_action = {}

# تحميلات في الانتظار تنتظر تأكيد المستخدم (في الذاكرة فقط)
pending_downloads = {}

# مستخدمين ضغطوا على "صورة الغلاف" وتنتظر أن يرسلوا رابط الفيديو (في الذاكرة فقط)
waiting_thumbnail = set()

# مستخدمين ضغطوا على "تحميل الترجمة" وتنتظر أن يرسلوا رابط الفيديو (في الذاكرة فقط)
waiting_subtitle = set()

# مستخدمين ضغطوا على "قص مقطع" وتنتظر منهم رابط الفيديو (في الذاكرة فقط)
waiting_clip_link = set()

# مستخدمين أرسلوا رابط القص وتنتظر منهم وقت البداية والنهاية -> user_id: url
waiting_clip_times = {}

# مستخدمين ضغطوا على "البحث في يوتيوب" وتنتظر منهم كلمة البحث (في الذاكرة فقط)
waiting_ytsearch = set()

# نتائج بحث يوتيوب المعروضة مؤقتًا -> user_id: {index: url}
ytsearch_results = {}


# ==================== جميع الـ 100 ميزة (الإعدادات الافتراضية) ====================

DEFAULT_SETTINGS = {
    # ==================== نظام النقاط والمكافآت (1–15) ====================
    "1_level_system_enabled": True,  # نظام المستويات
    "2_streak_bonus_enabled": True,  # مكافأة تسجيل الدخول المتواصل
    "3_point_charge_enabled": True,  # بطاقة شحن النقاط
    "4_point_expiry_enabled": False,  # نقاط انتهاء الصلاحية
    "5_first_daily_bonus_enabled": True,  # نقاط مكافأة على التحميل الأول في اليوم
    "6_weekly_challenge_enabled": True,  # تحدي أسبوعي
    "7_cashback_system_enabled": True,  # نظام الكاش باك
    "8_share_bot_points_enabled": True,  # نقاط على مشاركة البوت
    "9_rating_bonus_enabled": True,  # نقاط على التقييم
    "10_welcome_bonus_enabled": True,  # رصيد مجاني للمستخدم الجديد
    "11_limited_coupon_enabled": True,  # كوبون بوقت محدد
    "12_birthday_bonus_enabled": True,  # مكافأة عيد الميلاد
    "13_daily_tasks_enabled": True,  # مهام يومية
    "14_points_transfer_enabled": True,  # تحويل النقاط بين المستخدمين
    "15_gift_points_enabled": True,  # إرسال نقاط هدية

    # ==================== نظام التحميل (16–30) ====================
    "16_video_quality_selection_enabled": True,  # اختيار جودة الفيديو
    "17_playlist_download_enabled": True,  # تحميل قائمة التشغيل
    "18_subtitle_download_enabled": True,  # تحميل الترجمة
    "19_thumbnail_download_enabled": True,  # تحميل صورة الغلاف
    "20_batch_download_enabled": True,  # تحميل متعدد
    "21_download_history_enabled": True,  # سجل التحميلات
    "22_quick_redownload_enabled": True,  # إعادة التحميل السريعة
    "23_youtube_shorts_support_enabled": True,  # دعم Shorts
    "24_livestream_download_enabled": True,  # تحميل Live Stream
    "25_dailymotion_support_enabled": True,  # دعم Dailymotion
    "26_reddit_support_enabled": True,  # دعم Reddit
    "27_instagram_bulk_enabled": True,  # تحميل صور Instagram كـ ZIP
    "28_audio_compression_enabled": True,  # ضغط الصوت
    "29_video_only_mode_enabled": True,  # فيديو بدون صوت
    "30_high_quality_audio_enabled": True,  # صوت بجودة عالية

    # ==================== نظام الدعوات (31–40) ====================
    "31_multi_tier_referral_enabled": True,  # مستويات مكافأة متعددة
    "32_referral_leaderboard_enabled": True,  # لوحة صدارة الدعوات
    "33_bulk_invite_enabled": True,  # دعوة جماعية
    "34_referral_tracking_enabled": True,  # متابعة حالة الدعوات
    "35_first_download_bonus_enabled": True,  # مكافأة على أول تحميل
    "36_referred_bonus_enabled": True,  # نقاط للمدعو أيضاً
    "37_multilevel_referral_enabled": True,  # دعوات متعددة المستويات
    "38_referral_notification_enabled": True,  # إشعار فوري عند الدعوة
    "39_export_referrals_enabled": True,  # تصدير قائمة المدعوين
    "40_daily_referral_cap_enabled": True,  # حد أقصى يومي للدعوات

    # ==================== واجهة المستخدم (41–55) ====================
    "41_refined_menu_enabled": True,  # قائمة رئيسية منقحة
    "42_multi_language_enabled": True,  # لغات متعددة
    "43_user_card_enabled": True,  # بطاقة المستخدم
    "44_daily_reminder_enabled": True,  # إشعار تذكير يومي
    "45_help_command_enabled": True,  # قائمة الأوامر
    "46_quick_reply_buttons_enabled": True,  # أزرار الرد السريع
    "47_level_progress_bar_enabled": True,  # شريط تقدم المستوى
    "48_language_customization_enabled": True,  # تخصيص اللغة
    "49_dark_mode_enabled": False,  # وضع الليل
    "50_time_based_greeting_enabled": True,  # ترحيب حسب الوقت
    "51_transaction_confirmation_enabled": True,  # تأكيد العمليات
    "52_balance_comparison_enabled": True,  # مقارنة الرصيد
    "53_personal_stats_enabled": True,  # إحصائيات شخصية
    "54_about_command_enabled": True,  # صفحة عن البوت
    "55_faq_section_enabled": True,  # قسم الأسئلة الشائعة

    # ==================== نظام الإدارة (56–70) ====================
    "56_multi_admin_enabled": True,  # أدمن متعدد
    "57_db_export_enabled": True,  # تصدير قاعدة البيانات
    "58_user_search_enabled": True,  # البحث عن مستخدم
    "59_detailed_userinfo_enabled": True,  # معلومات مستخدم تفصيلية
    "60_temporary_ban_enabled": True,  # حظر مؤقت
    "61_admin_error_notification_enabled": True,  # إشعار الأخطاء
    "62_daily_admin_report_enabled": True,  # تقرير يومي
    "63_auto_backup_enabled": True,  # نسخة احتياطية تلقائية
    "64_detailed_stats_enabled": True,  # إحصائيات مفصلة
    "65_account_deletion_enabled": True,  # حذف حساب (GDPR)
    "66_maintenance_message_enabled": True,  # رسالة صيانة مخصصة
    "67_scheduled_broadcast_enabled": True,  # جدولة الإذاعات
    "68_filtered_broadcast_enabled": True,  # تصفية الإذاعات
    "69_admin_activity_log_enabled": True,  # سجل نشاط الأدمن
    "70_stats_comparison_enabled": True,  # مقارنة الإحصائيات

    # ==================== الأمان والحماية (71–80) ====================
    "71_captcha_enabled": False,  # Captcha
    "72_fake_account_detection_enabled": True,  # كشف الحسابات المزيفة
    "73_spam_auto_report_enabled": True,  # تقرير السبام التلقائي
    "74_daily_download_limit_enabled": True,  # حد أقصى يومي للتحميل
    "75_blacklist_urls_enabled": True,  # قائمة النطاقات المحظورة
    "76_url_validation_enabled": True,  # التحقق من صحة الرابط
    "77_duplicate_download_prevention_enabled": True,  # منع التحميل المتزامن
    "78_data_encryption_enabled": True,  # تشفير البيانات
    "79_report_system_enabled": True,  # نظام الإبلاغ
    "80_whitelist_enabled": False,  # قائمة بيضاء

    # ==================== الإحصائيات والتقارير (81–87) ====================
    "81_activity_chart_enabled": True,  # رسم بياني للنشاط
    "82_top_users_enabled": True,  # أفضل 10 مستخدمين
    "83_source_stats_enabled": True,  # إحصائيات المواقع
    "84_peak_hours_tracking_enabled": True,  # تتبع أوقات الذروة
    "85_points_tracking_enabled": True,  # تتبع النقاط
    "86_user_retention_stats_enabled": True,  # معدل الاحتفاظ
    "87_avg_video_duration_enabled": True,  # متوسط مدة الفيديوهات

    # ==================== الاشتراكات والدفع (88–93) ====================
    "88_vip_subscription_enabled": False,  # اشتراك VIP
    "89_trial_period_enabled": False,  # فترة تجربة مجانية
    "90_crypto_payment_enabled": False,  # دفع بالعملات الرقمية
    "91_invoice_system_enabled": False,  # نظام الفواتير
    "92_gift_subscription_enabled": False,  # هدية اشتراك
    "93_subscription_reminder_enabled": False,  # تذكير انتهاء الاشتراك

    # ==================== ميزات اجتماعية وأخرى (94–100) ====================
    "94_official_channel_enabled": False,  # قناة تيليجرام رسمية
    "95_support_group_enabled": False,  # مجموعة الدعم
    "96_rating_system_enabled": True,  # نظام التقييم
    "97_weekly_contest_enabled": True,  # مسابقة أسبوعية
    "98_channel_subscribe_bonus_enabled": True,  # نقاط الاشتراك بقناة
    "99_inline_mode_enabled": True,  # Inline Mode
    "100_web_app_enabled": False,  # واجهة ويب

    # ==================== ميزات جديدة (101–107) ====================
    "101_audio_extraction_enabled": True,  # استخراج الصوت (MP3)
    "102_video_compression_enabled": True,  # ضغط الفيديو
    "103_clip_cutting_enabled": True,  # قص المقاطع
    "104_referral_system_enabled": True,  # نظام الإحالة
    "105_quick_save_mode_enabled": False,  # وضع الحفظ السريع
    "106_youtube_search_enabled": True,  # البحث في يوتيوب
    "107_maintenance_mode_enabled": False,  # وضع الصيانة
}

FEATURE_LABELS = {
    "1_level_system_enabled": "نظام المستويات",
    "2_streak_bonus_enabled": "مكافأة تسجيل الدخول المتواصل",
    "3_point_charge_enabled": "بطاقة شحن النقاط",
    "4_point_expiry_enabled": "نقاط انتهاء الصلاحية",
    "5_first_daily_bonus_enabled": "نقاط مكافأة على التحميل الأول في اليوم",
    "6_weekly_challenge_enabled": "تحدي أسبوعي",
    "7_cashback_system_enabled": "نظام الكاش باك",
    "8_share_bot_points_enabled": "نقاط على مشاركة البوت",
    "9_rating_bonus_enabled": "نقاط على التقييم",
    "10_welcome_bonus_enabled": "رصيد مجاني للمستخدم الجديد",
    "11_limited_coupon_enabled": "كوبون بوقت محدد",
    "12_birthday_bonus_enabled": "مكافأة عيد الميلاد",
    "13_daily_tasks_enabled": "مهام يومية",
    "14_points_transfer_enabled": "تحويل النقاط بين المستخدمين",
    "15_gift_points_enabled": "إرسال نقاط هدية",
    "16_video_quality_selection_enabled": "اختيار جودة الفيديو",
    "17_playlist_download_enabled": "تحميل قائمة التشغيل",
    "18_subtitle_download_enabled": "تحميل الترجمة",
    "19_thumbnail_download_enabled": "تحميل صورة الغلاف",
    "20_batch_download_enabled": "تحميل متعدد",
    "21_download_history_enabled": "سجل التحميلات",
    "22_quick_redownload_enabled": "إعادة التحميل السريعة",
    "23_youtube_shorts_support_enabled": "دعم Shorts",
    "24_livestream_download_enabled": "تحميل Live Stream",
    "25_dailymotion_support_enabled": "دعم Dailymotion",
    "26_reddit_support_enabled": "دعم Reddit",
    "27_instagram_bulk_enabled": "تحميل صور Instagram كـ ZIP",
    "28_audio_compression_enabled": "ضغط الصوت",
    "29_video_only_mode_enabled": "فيديو بدون صوت",
    "30_high_quality_audio_enabled": "صوت بجودة عالية",
    "31_multi_tier_referral_enabled": "مستويات مكافأة متعددة",
    "32_referral_leaderboard_enabled": "لوحة صدارة الدعوات",
    "33_bulk_invite_enabled": "دعوة جماعية",
    "34_referral_tracking_enabled": "متابعة حالة الدعوات",
    "35_first_download_bonus_enabled": "مكافأة على أول تحميل",
    "36_referred_bonus_enabled": "نقاط للمدعو أيضاً",
    "37_multilevel_referral_enabled": "دعوات متعددة المستويات",
    "38_referral_notification_enabled": "إشعار فوري عند الدعوة",
    "39_export_referrals_enabled": "تصدير قائمة المدعوين",
    "40_daily_referral_cap_enabled": "حد أقصى يومي للدعوات",
    "41_refined_menu_enabled": "قائمة رئيسية منقحة",
    "42_multi_language_enabled": "لغات متعددة",
    "43_user_card_enabled": "بطاقة المستخدم",
    "44_daily_reminder_enabled": "إشعار تذكير يومي",
    "45_help_command_enabled": "قائمة الأوامر",
    "46_quick_reply_buttons_enabled": "أزرار الرد السريع",
    "47_level_progress_bar_enabled": "شريط تقدم المستوى",
    "48_language_customization_enabled": "تخصيص اللغة",
    "49_dark_mode_enabled": "وضع الليل",
    "50_time_based_greeting_enabled": "ترحيب حسب الوقت",
    "51_transaction_confirmation_enabled": "تأكيد العمليات",
    "52_balance_comparison_enabled": "مقارنة الرصيد",
    "53_personal_stats_enabled": "إحصائيات شخصية",
    "54_about_command_enabled": "صفحة عن البوت",
    "55_faq_section_enabled": "قسم الأسئلة الشائعة",
    "56_multi_admin_enabled": "أدمن متعدد",
    "57_db_export_enabled": "تصدير قاعدة البيانات",
    "58_user_search_enabled": "البحث عن مستخدم",
    "59_detailed_userinfo_enabled": "معلومات مستخدم تفصيلية",
    "60_temporary_ban_enabled": "حظر مؤقت",
    "61_admin_error_notification_enabled": "إشعار الأخطاء",
    "62_daily_admin_report_enabled": "تقرير يومي",
    "63_auto_backup_enabled": "نسخة احتياطية تلقائية",
    "64_detailed_stats_enabled": "إحصائيات مفصلة",
    "65_account_deletion_enabled": "حذف حساب (GDPR)",
    "66_maintenance_message_enabled": "رسالة صيانة مخصصة",
    "67_scheduled_broadcast_enabled": "جدولة الإذاعات",
    "68_filtered_broadcast_enabled": "تصفية الإذاعات",
    "69_admin_activity_log_enabled": "سجل نشاط الأدمن",
    "70_stats_comparison_enabled": "مقارنة الإحصائيات",
    "71_captcha_enabled": "Captcha",
    "72_fake_account_detection_enabled": "كشف الحسابات المزيفة",
    "73_spam_auto_report_enabled": "تقرير السبام التلقائي",
    "74_daily_download_limit_enabled": "حد أقصى يومي للتحميل",
    "75_blacklist_urls_enabled": "قائمة النطاقات المحظورة",
    "76_url_validation_enabled": "التحقق من صحة الرابط",
    "77_duplicate_download_prevention_enabled": "منع التحميل المتزامن",
    "78_data_encryption_enabled": "تشفير البيانات",
    "79_report_system_enabled": "نظام الإبلاغ",
    "80_whitelist_enabled": "قائمة بيضاء",
    "81_activity_chart_enabled": "رسم بياني للنشاط",
    "82_top_users_enabled": "أفضل 10 مستخدمين",
    "83_source_stats_enabled": "إحصائيات المواقع",
    "84_peak_hours_tracking_enabled": "تتبع أوقات الذروة",
    "85_points_tracking_enabled": "تتبع النقاط",
    "86_user_retention_stats_enabled": "معدل الاحتفاظ",
    "87_avg_video_duration_enabled": "متوسط مدة الفيديوهات",
    "88_vip_subscription_enabled": "اشتراك VIP",
    "89_trial_period_enabled": "فترة تجربة مجانية",
    "90_crypto_payment_enabled": "دفع بالعملات الرقمية",
    "91_invoice_system_enabled": "نظام الفواتير",
    "92_gift_subscription_enabled": "هدية اشتراك",
    "93_subscription_reminder_enabled": "تذكير انتهاء الاشتراك",
    "94_official_channel_enabled": "قناة تيليجرام رسمية",
    "95_support_group_enabled": "مجموعة الدعم",
    "96_rating_system_enabled": "نظام التقييم",
    "97_weekly_contest_enabled": "مسابقة أسبوعية",
    "98_channel_subscribe_bonus_enabled": "نقاط الاشتراك بقناة",
    "99_inline_mode_enabled": "Inline Mode",
    "100_web_app_enabled": "واجهة ويب",
    "101_audio_extraction_enabled": "استخراج الصوت (MP3)",
    "102_video_compression_enabled": "ضغط الفيديو",
    "103_clip_cutting_enabled": "قص المقاطع",
    "104_referral_system_enabled": "نظام الإحالة",
    "105_quick_save_mode_enabled": "وضع الحفظ السريع",
    "106_youtube_search_enabled": "البحث في يوتيوب",
    "107_maintenance_mode_enabled": "وضع الصيانة",
}


def load_users():
    if os.path.exists(POINTS_FILE):
        try:
            with open(POINTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_users(data):
    with open(POINTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"total_downloads": 0}
    return {"total_downloads": 0}


def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def increment_downloads():
    stats = load_stats()
    stats["total_downloads"] = stats.get("total_downloads", 0) + 1
    save_stats(stats)
    return stats["total_downloads"]


def increment_user_downloads(user_id):
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    users[uid]["downloads_count"] = users[uid].get("downloads_count", 0) + 1
    save_users(users)
    return users[uid]["downloads_count"]


def build_profile_text(user):
    users = load_users()
    uid = str(user.id)
    data = users.get(uid, {})
    points = data.get("points", 0)
    invited = get_invited_count(user.id)
    downloads = data.get("downloads_count", 0)
    joined = data.get("joined_at", "غير معروف")
    name = user.first_name or "صديقي"
    return (
        f"👤 الملف الشخصي لـ {name}\n\n"
        f"🆔 المعرف: {user.id}\n"
        f"📅 تاريخ الانضمام: {joined}\n"
        f"⭐ النقاط الحالية: {points}\n"
        f"🎬 عدد التحميلات: {downloads}\n"
        f"👥 عدد الدعوات: {invited}\n"
    )


def is_banned(user_id):
    users = load_users()
    return users.get(str(user_id), {}).get("banned", False)


def set_banned(user_id, banned=True):
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    users[uid]["banned"] = banned
    save_users(users)


def get_restrictions(user_id):
    users = load_users()
    return users.get(str(user_id), {}).get("restrictions", [])


def add_restriction(user_id, perm):
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    restr = users[uid].get("restrictions", [])
    if perm not in restr:
        restr.append(perm)
    users[uid]["restrictions"] = restr
    save_users(users)


def remove_restriction(user_id, perm):
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    restr = users[uid].get("restrictions", [])
    if perm in restr:
        restr.remove(perm)
    users[uid]["restrictions"] = restr
    save_users(users)


def has_restriction(user_id, perm):
    return perm in get_restrictions(user_id)


# ==================== إعدادات قابلة للتفعيل/التعطيل من طرف الأدمن ====================


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except Exception:
            return dict(DEFAULT_SETTINGS)
    return dict(DEFAULT_SETTINGS)


def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_setting(key):
    return load_settings().get(key, DEFAULT_SETTINGS.get(key, True))


def toggle_setting(key):
    settings = load_settings()
    settings[key] = not settings.get(key, DEFAULT_SETTINGS.get(key, True))
    save_settings(settings)
    return settings[key]


def is_weekend_today():
    """الجمعة والسبت كعطلة نهاية الأسبوع (مغرب/دول عربية)."""
    return datetime.now().weekday() in (4, 5)


# ==================== أكواد الهدية (Promo Codes) ====================

def load_promo_codes():
    if os.path.exists(PROMO_FILE):
        try:
            with open(PROMO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_promo_codes(data):
    with open(PROMO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_promo_code(code, points, max_uses):
    codes = load_promo_codes()
    code = code.upper().strip()
    codes[code] = {"points": points, "max_uses": max_uses, "used_by": []}
    save_promo_codes(codes)
    return code


def redeem_promo_code(user_id, code):
    """يرجع (success, message)."""
    codes = load_promo_codes()
    code = code.upper().strip()
    uid = str(user_id)

    if code not in codes:
        return False, "❌ هذا الكود غير صحيح."

    entry = codes[code]
    if uid in entry.get("used_by", []):
        return False, "❌ سبق لك استخدام هذا الكود."
    if len(entry.get("used_by", [])) >= entry.get("max_uses", 0):
        return False, "❌ هذا الكود وصل للحد الأقصى للاستخدام."

    entry["used_by"].append(uid)
    save_promo_codes(codes)

    points = entry.get("points", 0)
    new_total = add_points(user_id, points, reason=f"🎟️ كود هدية: {code}")
    return True, f"✅ ربحت {points} نقطة! رصيدك الحالي: {new_total} نقطة"


# ==================== حماية من السبام (Rate Limiting) ====================

def check_rate_limit(user_id):
    """يرجع True إلا كان مسموح للمستخدم يكمل، False إلا كان يقوم بـ سبام."""
    now = datetime.now().timestamp()
    dq = rate_limit_tracker.setdefault(user_id, deque())
    while dq and now - dq[0] > RATE_LIMIT_WINDOW_SECONDS:
        dq.popleft()
    if len(dq) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    dq.append(now)
    return True


def get_points(user_id):
    users = load_users()
    uid = str(user_id)
    return users.get(uid, {}).get("points", 0)


def get_invited_count(user_id):
    users = load_users()
    uid = str(user_id)
    organic = sum(1 for u in users.values() if u.get("invited_by") == uid)
    bonus = users.get(uid, {}).get("bonus_invites", 0)
    return organic + bonus


def log_transaction(users, uid, amount, reason):
    """يضيف عملية جديدة لسجل المستخدم (يحتفظ بآخر 10 عمليات فقط)."""
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    history = users[uid].get("history", [])
    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "amount": amount,
        "reason": reason,
    })
    users[uid]["history"] = history[-10:]


def add_points(user_id, amount, reason="تعديل يدوي"):
    """يضيف (أو ينقص إلا كان الرقم سالب) نقاط لمستخدم معين، ويرجع المجموع الجديد."""
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    users[uid]["points"] = users[uid].get("points", 0) + amount
    log_transaction(users, uid, amount, reason)
    save_users(users)
    return users[uid]["points"]


def set_points(user_id, amount, reason="تحديد يدوي"):
    """يحدد نقاط مستخدم معين بالضبط بالرقم المعطى."""
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    old = users[uid].get("points", 0)
    users[uid]["points"] = amount
    log_transaction(users, uid, amount - old, reason)
    save_users(users)
    return users[uid]["points"]


def set_invite_bonus(user_id, target_count):
    """يحدد عدد الدعوات الظاهر لمستخدم معين بالضبط بالرقم المعطى."""
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}
    organic = sum(1 for u in users.values() if u.get("invited_by") == uid)
    users[uid]["bonus_invites"] = target_count - organic
    save_users(users)
    return organic + users[uid]["bonus_invites"]


def calculate_video_cost(duration_sec):
    """يحسب تكلفة تحميل الفيديو بالنقاط: نقطة واحدة لكل دقيقة، بحد أدنى نقطة واحدة."""
    if not duration_sec or duration_sec <= 0:
        return MIN_VIDEO_COST
    minutes = math.ceil(duration_sec / 60)
    return max(minutes * POINTS_PER_MINUTE, MIN_VIDEO_COST)


def format_duration(duration_sec):
    """يحوّل المدة بالثواني لصيغة مقروءة (دقائق وثواني)."""
    if not duration_sec or duration_sec <= 0:
        return "غير معروفة"
    minutes = int(duration_sec // 60)
    seconds = int(duration_sec % 60)
    return f"{minutes} د {seconds} ث"


def claim_daily_point(user_id):
    """يعطي نقطة مجانية واحدة كل 24 ساعة. يرجع (success, hours_left, minutes_left, رصيد_النقاط)."""
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"points": 0, "invited_by": None}

    now = datetime.now()
    last_claim_str = users[uid].get("last_daily_claim")

    if last_claim_str:
        try:
            last_claim = datetime.strptime(last_claim_str, "%Y-%m-%d %H:%M:%S")
            elapsed = now - last_claim
        except ValueError:
            elapsed = timedelta(hours=24)

        if elapsed < timedelta(hours=24):
            remaining = timedelta(hours=24) - elapsed
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return False, hours, minutes, users[uid].get("points", 0)

    gift_amount = 1
    reason = "🎁 هدية يومية"
    if get_setting("weekend_bonus_enabled") and is_weekend_today():
        gift_amount = 2
        reason = "🎁 هدية يومية (مضاعفة نهاية الأسبوع)"

    users[uid]["points"] = users[uid].get("points", 0) + gift_amount
    users[uid]["last_daily_claim"] = now.strftime("%Y-%m-%d %H:%M:%S")
    log_transaction(users, uid, gift_amount, reason)
    save_users(users)
    return True, 0, 0, users[uid]["points"]


def register_user(user_id, invited_by=None):
    users = load_users()
    uid = str(user_id)
    is_new = uid not in users

    if is_new:
        users[uid] = {
            "points": 0,
            "invited_by": None,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "downloads_count": 0,
        }

    got_bonus = False
    if is_new and invited_by and str(invited_by) != uid and users[uid]["invited_by"] is None:
        users[uid]["invited_by"] = str(invited_by)
        inviter_id = str(invited_by)
        if inviter_id not in users:
            users[inviter_id] = {"points": 0, "invited_by": None}
        users[inviter_id]["points"] += 5
        log_transaction(users, inviter_id, 5, "مكافأة دعوة صديق")
        got_bonus = True

    save_users(users)
    return got_bonus, is_new


# ==================== أدوات معالجة الفيديو ====================

def compress_video(input_path: str, output_path: str, target_size_mb: float, duration_sec: float) -> bool:
    if not duration_sec or duration_sec <= 0:
        duration_sec = 60

    target_size_bits = target_size_mb * 8 * 1024 * 1024
    target_size_bits *= 0.9

    audio_bitrate_kbps = 128
    video_bitrate_kbps = max(
        int((target_size_bits / duration_sec / 1000) - audio_bitrate_kbps),
        100,
    )

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264",
        "-b:v", f"{video_bitrate_kbps}k",
        "-maxrate", f"{video_bitrate_kbps}k", "-bufsize", f"{video_bitrate_kbps * 2}k",
        "-vf", "scale=-2:480",
        "-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k",
        "-preset", "ultrafast",
        "-threads", "0",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and os.path.exists(output_path)


def split_video(input_path, tmp_dir, max_size_mb, duration_sec):
    if not duration_sec or duration_sec <= 0:
        duration_sec = 60

    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    num_parts = math.ceil(file_size_mb / (max_size_mb * 0.9))
    if num_parts < 2:
        num_parts = 2
    part_duration = int(duration_sec / num_parts) + 1

    output_pattern = os.path.join(tmp_dir, "part_%03d.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c", "copy",
        "-map", "0",
        "-f", "segment",
        "-segment_time", str(part_duration),
        "-reset_timestamps", "1",
        output_pattern,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Split error: {e}")
        return []
    return _collect_parts(tmp_dir)


def _collect_parts(tmp_dir):

    parts = sorted(
        os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)
        if f.startswith("part_") and f.endswith(".mp4")
    )
    return parts


def compress_video_manual(input_path: str, output_path: str, duration_sec: float) -> bool:
    """ضغط يدوي للفيديو (يُستخدم مع ميزة «ضغط الفيديو»، بمعزل عن الضغط التلقائي عند تجاوز الحجم الأقصى)."""
    return compress_video(input_path, output_path, MAX_SIZE_MB * 0.6, duration_sec)


def cut_video_clip(input_path: str, output_path: str, start_sec: float, end_sec: float) -> bool:
    """يقص جزءًا من فيديو بين ثانيتين محددتين."""
    duration = max(end_sec - start_sec, 1)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", input_path,
        "-t", str(duration),
        "-c", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and os.path.exists(output_path):
        return True
    # بعض الفيديوهات تحتاج لإعادة الترميز إذا فشل النسخ المباشر
    cmd_reencode = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264", "-c:a", "aac",
        output_path,
    ]
    result = subprocess.run(cmd_reencode, capture_output=True)
    return result.returncode == 0 and os.path.exists(output_path)


def parse_time_to_seconds(text: str):
    """يحوّل نصًا مثل '1:30' أو '90' إلى عدد الثواني. يرجع None إذا كانت الصيغة غير صحيحة."""
    text = text.strip()
    try:
        if ":" in text:
            parts_ = [int(p) for p in text.split(":")]
            seconds = 0
            for p in parts_:
                seconds = seconds * 60 + p
            return seconds
        return int(float(text))
    except ValueError:
        return None


# ==================== اللوحة الرئيسية ====================

def build_dashboard_text(user):
    p = get_points(user.id)
    invited = get_invited_count(user.id)
    name = user.first_name or "صديقي"
    return (
        f"👋 مرحبا بيك، {name}!\n\n"
        f"🆔 الآيدي الخاص بك: {user.id}\n"
        f"⭐ النقاط: {p}\n"
        f"👥 عدد الدعوات: {invited}\n\n"
        f"🎬 أرسل لي رابط فيديو من يوتيوب، تيك توك، إنستغرام، "
        f"تويتر أو فيسبوك، وتستطيع تختار تحمل الفيديو كامل ولا الصوت (MP3) فقط.\n\n"
        f"💸 كل تحميل يكلف {POINTS_PER_MINUTE} نقطة لكل دقيقة من الفيديو "
        f"(بحد أدنى {MIN_VIDEO_COST} نقطة). ادعي أصدقاءك حتى تربح نقاط، "
        f"ولا تنسى تاخد 🎁 هدية اليوم!"
    )


def build_dashboard_keyboard(is_admin=False):
    rows = [
        [InlineKeyboardButton("📥 تحميل فيديو", callback_data="menu_dl")],
        [
            InlineKeyboardButton("✂️ قص مقطع", callback_data="menu_clip"),
            InlineKeyboardButton("🔎 بحث في يوتيوب", callback_data="menu_ytsearch"),
        ],
        [
            InlineKeyboardButton("📸 صورة الغلاف", callback_data="menu_thumbnail"),
            InlineKeyboardButton("📝 تحميل الترجمة", callback_data="menu_subtitle"),
        ],
        [InlineKeyboardButton("🎁 هدية اليوم", callback_data="menu_daily")],
        [
            InlineKeyboardButton("⭐ النقاط", callback_data="menu_points"),
            InlineKeyboardButton("🔗 دعوة صديق", callback_data="menu_invite"),
        ],
        [
            InlineKeyboardButton("👤 ملفي الشخصي", callback_data="menu_profile"),
            InlineKeyboardButton("📜 السجل", callback_data="menu_history"),
        ],
        [InlineKeyboardButton("🎧 الدعم الفني", callback_data="menu_support")],
        [InlineKeyboardButton("🎟️ كود هدية", callback_data="menu_redeem")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ لوحة الإدارة", callback_data="menu_admin")])
    return InlineKeyboardMarkup(rows)


def build_format_choice_keyboard():
    rows = [
        [
            InlineKeyboardButton("🎬 فيديو", callback_data="fmt_video"),
            InlineKeyboardButton("🎵 استخراج الصوت (MP3)", callback_data="fmt_audio"),
        ],
    ]
    if get_setting("102_video_compression_enabled"):
        rows.append([InlineKeyboardButton("📦 فيديو مضغوط (حجم أصغر)", callback_data="fmt_compressed")])
    return InlineKeyboardMarkup(rows)


def build_confirm_download_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ نعم، حمّل", callback_data="confirm_download"),
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel_download"),
        ]
    ])


def format_history_text(users, uid):
    hist = users.get(uid, {}).get("history", [])
    if not hist:
        return "📜 لا توجد أي عملية مسجلة بعد."
    lines = ["📜 آخر عملياتك:\n"]
    for entry in reversed(hist):
        amount = entry.get("amount", 0)
        sign = "+" if amount >= 0 else ""
        lines.append(
            f"🕐 {entry.get('time', '?')} | {sign}{amount} نقطة | {entry.get('reason', '')}"
        )
    return "\n".join(lines)


def build_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة نقاط", callback_data="admin_add_points")],
        [InlineKeyboardButton("✏️ تحديد نقاط بالضبط", callback_data="admin_set_points")],
        [InlineKeyboardButton("👥 تحديد عدد الدعوات", callback_data="admin_set_invites")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
        [
            InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban"),
            InlineKeyboardButton("✅ إلغاء حظر", callback_data="admin_unban"),
        ],
        [
            InlineKeyboardButton("🔒 تقييد صلاحية", callback_data="admin_restrict"),
            InlineKeyboardButton("🔓 رفع تقييد", callback_data="admin_unrestrict"),
        ],
        [InlineKeyboardButton("🎟️ إنشاء كود هدية", callback_data="admin_create_promo")],
        [
            InlineKeyboardButton(
                ("✅" if get_setting("107_maintenance_mode_enabled") else "❌") + " وضع الصيانة",
                callback_data="toggle_107_maintenance_mode_enabled",
            ),
            InlineKeyboardButton(
                ("✅" if get_setting("105_quick_save_mode_enabled") else "❌") + " الحفظ السريع",
                callback_data="toggle_105_quick_save_mode_enabled",
            ),
        ],
        [InlineKeyboardButton("⚙️ إدارة كل الميزات (107)", callback_data="menu_features")],
        [InlineKeyboardButton("⬅️ رجوع للقائمة", callback_data="menu_back")],
    ])


def build_features_keyboard(page=1):
    """بناء لوحة الميزات مع دعم الصفحات (بما أن عندنا 100 ميزة)"""
    settings = load_settings()
    
    # تقسيم الميزات إلى مجموعات حسب الفئة
    categories = {
        "النقاط والمكافآت (1-15)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(1, 16)))],
        "نظام التحميل (16-30)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(16, 31)))],
        "نظام الدعوات (31-40)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(31, 41)))],
        "واجهة المستخدم (41-55)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(41, 56)))],
        "الإدارة (56-70)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(56, 71)))],
        "الأمان (71-80)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(71, 81)))],
        "الإحصائيات (81-87)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(81, 88)))],
        "الاشتراكات (88-93)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(88, 94)))],
        "اجتماعي (94-100)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(94, 101)))],
        "ميزات جديدة (101-107)": [k for k in DEFAULT_SETTINGS.keys() if k.startswith(tuple(f"{i}_" for i in range(101, 108)))],
    }
    
    rows = []
    category_list = list(categories.items())
    
    if page <= len(category_list):
        category_name, keys = category_list[page - 1]
        rows.append([InlineKeyboardButton(f"📑 {category_name}", callback_data="noop")])
        
        for key in sorted(keys, key=lambda k: int(k.split("_")[0])):
            state = "✅" if settings.get(key, True) else "❌"
            feature_name = FEATURE_LABELS.get(key, key.replace("_", " ").replace("enabled", "").strip())
            rows.append([InlineKeyboardButton(f"{state} {feature_name}", callback_data=f"toggle_{key}")])
    
    # أزرار الملاحة
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"features_page_{page-1}"))
    if page < len(category_list):
        nav_row.append(InlineKeyboardButton("التالي ➡️", callback_data=f"features_page_{page+1}"))
    
    if nav_row:
        rows.append(nav_row)
    
    rows.append([InlineKeyboardButton("⬅️ رجوع للإدارة", callback_data="menu_admin")])
    
    return InlineKeyboardMarkup(rows)


def build_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ رجوع للقائمة", callback_data="menu_back")]
    ])


# ==================== أوامر البوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if is_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    invited_by = None
    if context.args:
        try:
            invited_by = int(context.args[0])
        except (ValueError, IndexError):
            invited_by = None

    got_bonus, is_new = register_user(user.id, invited_by)
    waiting_support.discard(user.id)

    if is_new and user.id != ADMIN_ID:
        try:
            username_part = f"@{user.username}" if user.username else "بدون اسم مستخدم"
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 مستخدم جديد سجل في البوت!\n"
                    f"👤 {user.full_name} ({username_part})\n"
                    f"🆔 {user.id}"
                ),
            )
        except Exception as e:
            logger.error(f"Admin new-user notify error: {e}")

    text = build_dashboard_text(user)
    if got_bonus:
        text += "\n\n✅ تم تسجيلك عبر دعوة صديق!"

    await update.message.reply_text(
        text, reply_markup=build_dashboard_keyboard(user.id == ADMIN_ID)
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if is_banned(user.id) and user.id != ADMIN_ID:
        await query.edit_message_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    if get_setting("107_maintenance_mode_enabled") and user.id != ADMIN_ID:
        await query.edit_message_text(
            "🛠️ البوت متوقف مؤقتا للصيانة، أعد المحاولة من بعد."
        )
        return

    if query.data == "menu_points":
        p = get_points(user.id)
        await query.edit_message_text(
            f"⭐ رصيدك الحالي: {p} نقطة",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_dl":
        waiting_download.add(user.id)
        await query.edit_message_text(
            "📥 أرسل لي الآن رابط الفيديو (يبدأ بـ http:// أو https://).",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_daily":
        if has_restriction(user.id, "daily"):
            await query.edit_message_text(
                "🚫 تم تقييدك من ميزة الهدية اليومية من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        if not get_setting("daily_gift_enabled"):
            await query.edit_message_text(
                "🎁 ميزة الهدية اليومية متوقفة حاليا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        success, hours, minutes, points_now = claim_daily_point(user.id)
        if success:
            await query.edit_message_text(
                f"🎁 مبروك! ربحت نقطة مجانية.\n⭐ رصيدك الحالي: {points_now} نقطة",
                reply_markup=build_back_keyboard(),
            )
        else:
            await query.edit_message_text(
                "⏳ يجب أن تستنى "
                f"{hours} ساعة و {minutes} دقيقة قبل ما تستطيع تاخد هدية اليوم مرة أخرى.\n"
                f"⭐ رصيدك الحالي: {points_now} نقطة",
                reply_markup=build_back_keyboard(),
            )

    elif query.data == "menu_invite":
        if has_restriction(user.id, "invite"):
            await query.edit_message_text(
                "🚫 تم تقييدك من ميزة الدعوة من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        bot_username = context.bot.username
        link = f"https://t.me/{bot_username}?start={user.id}"
        invited = get_invited_count(user.id)
        await query.edit_message_text(
            f"🔗 رابط الدعوة الخاص بك:\n{link}\n\n"
            f"💰 كل شخص يدخل عبر رابطك يمنحك 5 نقاط.\n"
            f"👥 عدد الأشخاص لي دعوتيهم: {invited}",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_support":
        if has_restriction(user.id, "support"):
            await query.edit_message_text(
                "🚫 تم تقييدك من ميزة الدعم الفني من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        waiting_support.add(user.id)
        await query.edit_message_text(
            "🎧 اكتب الآن رسالتك وستصل مباشرة لفريق الدعم.\n\n"
            "✍️ أرسل رسالتك في أي وقت (بدون أوامر).",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_history":
        users = load_users()
        text = format_history_text(users, str(user.id))
        await query.edit_message_text(text, reply_markup=build_back_keyboard())

    elif query.data == "menu_redeem":
        waiting_redeem.add(user.id)
        await query.edit_message_text(
            "🎟️ أرسل لي الآن كود الهدية.",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_profile":
        if not get_setting("53_personal_stats_enabled"):
            await query.edit_message_text(
                "👤 ميزة الملف الشخصي متوقفة حاليًا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        await query.edit_message_text(
            build_profile_text(user), reply_markup=build_back_keyboard()
        )

    elif query.data == "menu_thumbnail":
        if not get_setting("19_thumbnail_download_enabled"):
            await query.edit_message_text(
                "📸 ميزة تحميل صورة الغلاف متوقفة حاليًا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        waiting_thumbnail.add(user.id)
        await query.edit_message_text(
            "📸 أرسل لي الآن رابط الفيديو حتى أرسل لك صورة الغلاف الخاصة به.",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_subtitle":
        if not get_setting("18_subtitle_download_enabled"):
            await query.edit_message_text(
                "📝 ميزة تحميل الترجمة متوقفة حاليًا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        waiting_subtitle.add(user.id)
        await query.edit_message_text(
            "📝 أرسل لي الآن رابط الفيديو حتى أحاول تحميل ملف الترجمة الخاص به.",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_clip":
        if not get_setting("103_clip_cutting_enabled"):
            await query.edit_message_text(
                "✂️ ميزة قص المقاطع متوقفة حاليًا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        waiting_clip_link.add(user.id)
        await query.edit_message_text(
            "✂️ أرسل لي الآن رابط الفيديو الذي تريد قص جزء منه.",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_ytsearch":
        if not get_setting("106_youtube_search_enabled"):
            await query.edit_message_text(
                "🔎 ميزة البحث في يوتيوب متوقفة حاليًا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        waiting_ytsearch.add(user.id)
        await query.edit_message_text(
            "🔎 اكتب الآن الكلمة أو الجملة التي تريد البحث عنها في يوتيوب.",
            reply_markup=build_back_keyboard(),
        )

    elif query.data.startswith("ytpick_"):
        idx = query.data[len("ytpick_"):]
        results = ytsearch_results.get(user.id, {})
        url = results.get(idx)
        if not url:
            await query.edit_message_text(
                "❌ انتهت صلاحية نتائج هذا البحث. أعد البحث من جديد.",
                reply_markup=build_back_keyboard(),
            )
            return
        pending_link[user.id] = url
        await query.edit_message_text(
            "🎬 هل تريد تحميل الفيديو كاملاً أم استخراج الصوت (MP3) فقط؟",
            reply_markup=build_format_choice_keyboard(),
        )

    elif query.data == "confirm_download":
        pending = pending_downloads.pop(user.id, None)
        if not pending:
            await query.edit_message_text(
                "❌ لا يوجد أي تحميل في الانتظار (يمكن انتهت صلالأنو).",
                reply_markup=build_back_keyboard(),
            )
            return
        await query.edit_message_text("⏳ جاري تحميل الفيديو...")
        await execute_download(
            update,
            context,
            pending["url"],
            pending["cost"],
            False,
            query.message,
            pending.get("format", "video"),
        )

    elif query.data == "cancel_download":
        pending_downloads.pop(user.id, None)
        await query.edit_message_text(
            "❌ تم إلغاء التحميل. ما تخصمش عليك أي نقطة.",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_admin":
        if user.id != ADMIN_ID:
            return
        await query.edit_message_text(
            "⚙️ لوحة الإدارة\n\nاختر شنو تريد تعدل:",
            reply_markup=build_admin_keyboard(),
        )

    elif query.data in ("admin_add_points", "admin_set_points", "admin_set_invites"):
        if user.id != ADMIN_ID:
            return
        waiting_admin_action[user.id] = query.data
        if query.data == "admin_add_points":
            prompt = (
                "➕ أرسل: ID رقم\n\n"
                "مثال: 123456789 10\n"
                "(سوف تُضاف 10 نقاط لهذا المستخدم)"
            )
        elif query.data == "admin_set_points":
            prompt = (
                "✏️ أرسل: ID رقم\n\n"
                "مثال: 123456789 50\n"
                "(نقاط هذا المستخدم ستصبح 50 بالضبط)"
            )
        else:
            prompt = (
                "👥 أرسل: ID رقم\n\n"
                "مثال: 123456789 5\n"
                "(عدد دعوات هذا المستخدم سيصبح 5 بالضبط)"
            )
        await query.edit_message_text(prompt, reply_markup=build_back_keyboard())

    elif query.data in ("admin_ban", "admin_unban"):
        if user.id != ADMIN_ID:
            return
        waiting_admin_action[user.id] = query.data
        if query.data == "admin_ban":
            prompt = "🚫 أرسل: ID المستخدم لي تريد تحظرو\nمثال: 123456789"
        else:
            prompt = "✅ أرسل: ID المستخدم لي تريد تلغي عليه الحظر\nمثال: 123456789"
        await query.edit_message_text(prompt, reply_markup=build_back_keyboard())

    elif query.data == "admin_stats":
        if user.id != ADMIN_ID:
            return
        users = load_users()
        total_users = len(users)
        total_points = sum(u.get("points", 0) for u in users.values())
        total_banned = sum(1 for u in users.values() if u.get("banned"))
        stats = load_stats()
        total_downloads = stats.get("total_downloads", 0)
        await query.edit_message_text(
            "📊 إحصائيات البوت\n\n"
            f"👥 عدد المستخدمين: {total_users}\n"
            f"⭐ مجموع النقاط (الرصيد الحالي لكل الناس): {total_points}\n"
            f"🎬 عدد التحميلات الكلي: {total_downloads}\n"
            f"🚫 عدد المحظورين: {total_banned}",
            reply_markup=build_admin_keyboard(),
        )

    elif query.data in ("admin_restrict", "admin_unrestrict"):
        if user.id != ADMIN_ID:
            return
        waiting_admin_action[user.id] = query.data
        perms_list = " / ".join(VALID_RESTRICTIONS)
        if query.data == "admin_restrict":
            prompt = (
                f"🔒 أرسل: ID الصلاحية\n\n"
                f"الصلاحيات المتاحة: {perms_list}\n"
                f"مثال: 123456789 download"
            )
        else:
            prompt = (
                f"🔓 أرسل: ID الصلاحية\n\n"
                f"الصلاحيات المتاحة: {perms_list}\n"
                f"مثال: 123456789 download"
            )
        await query.edit_message_text(prompt, reply_markup=build_back_keyboard())

    elif query.data == "admin_create_promo":
        if user.id != ADMIN_ID:
            return
        waiting_admin_action[user.id] = query.data
        await query.edit_message_text(
            "🎟️ أرسل: كود النقاط الاستخدامات\n\n"
            "مثال: WELCOME10 10 100\n"
            "(الكود WELCOME10، يعطي 10 نقاط، يستطيع يتستعمل من طرف 100 شخص)",
            reply_markup=build_back_keyboard(),
        )

    elif query.data == "menu_features":
        if user.id != ADMIN_ID:
            return
        await query.edit_message_text(
            "⚙️ إدارة الميزات (107 ميزة)\n\nاختر الفئة التي تريد إدارتها:",
            reply_markup=build_features_keyboard(1),
        )

    elif query.data.startswith("features_page_"):
        if user.id != ADMIN_ID:
            return
        page = int(query.data.split("_")[-1])
        await query.edit_message_text(
            "⚙️ إدارة الميزات (107 ميزة)\n\nاضغط على الميزة حتى تشعلها/تطفيها:",
            reply_markup=build_features_keyboard(page),
        )

    elif query.data.startswith("toggle_"):
        if user.id != ADMIN_ID:
            return
        setting_key = query.data[len("toggle_"):]
        if setting_key not in DEFAULT_SETTINGS:
            return
        new_value = toggle_setting(setting_key)
        state_text = "✅ مفعّلة" if new_value else "❌ متوقفة"
        await query.answer(f"تم التحديث: {state_text}", show_alert=False)
        if setting_key in ("107_maintenance_mode_enabled", "105_quick_save_mode_enabled"):
            await query.edit_message_text(
                "⚙️ لوحة الإدارة\n\nاختر ما تريد تعديله:",
                reply_markup=build_admin_keyboard(),
            )
        else:
            await query.edit_message_text(
                "⚙️ إدارة الميزات (107 ميزة)\n\nاضغط على الميزة حتى تشعلها/تطفيها:",
                reply_markup=build_features_keyboard(1),
            )

    elif query.data in ("fmt_video", "fmt_audio", "fmt_compressed"):
        url = pending_link.pop(user.id, None)
        if not url:
            await query.edit_message_text(
                "❌ لا يوجد أي رابط في الانتظار. أعد اضغط «📥 تحميل فيديو».",
                reply_markup=build_back_keyboard(),
            )
            return

        if query.data == "fmt_audio" and not get_setting("101_audio_extraction_enabled"):
            await query.edit_message_text(
                "🎵 ميزة استخراج الصوت متوقفة حاليًا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return
        if query.data == "fmt_compressed" and not get_setting("102_video_compression_enabled"):
            await query.edit_message_text(
                "📦 ميزة ضغط الفيديو متوقفة حاليًا من طرف الإدارة.",
                reply_markup=build_back_keyboard(),
            )
            return

        fmt_map = {"fmt_video": "video", "fmt_audio": "audio", "fmt_compressed": "compressed"}
        fmt = fmt_map[query.data]
        fmt_labels = {"video": "🎬 فيديو", "audio": "🎵 صوت (MP3)", "compressed": "📦 فيديو مضغوط"}
        is_admin = user.id == ADMIN_ID

        if is_admin:
            await query.edit_message_text("⏳ جاري تحميل الفيديو...")
            await execute_download(update, context, url, 0, True, query.message, fmt)
            return

        await query.edit_message_text("🔎 جاري التحقق من الفيديو...")

        try:
            probe_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(probe_opts) as probe_ydl:
                probe_info = probe_ydl.extract_info(url, download=False)
            duration_probe = probe_info.get("duration") or 0
            title = probe_info.get("title") or "بلا عنوان"
        except Exception as e:
            logger.error(f"Probe error: {e}")
            duration_probe = 0
            title = "بلا عنوان"

        cost = calculate_video_cost(duration_probe)
        user_points = get_points(user.id)

        if user_points < cost:
            await query.edit_message_text(
                "❌ نقاطك غير كافية لهذا التحميل.\n\n"
                f"🎬 {title}\n"
                f"⏱️ المدة: {format_duration(duration_probe)}\n"
                f"💰 التكلفة: {cost} نقطة\n"
                f"⭐ رصيدك الحالي: {user_points} نقطة\n\n"
                "🔗 ادعي أصدقاءك عبر زر «دعوة صديق» حتى تربح نقاط."
            )
            return

        fmt_label = fmt_labels[fmt]

        if get_setting("105_quick_save_mode_enabled"):
            # وضع الحفظ السريع: تنزيل مباشر بدون شاشة تأكيد
            await query.edit_message_text(f"⏳ {fmt_label} - جاري التحميل مباشرة (وضع الحفظ السريع)...")
            await execute_download(update, context, url, cost, False, query.message, fmt)
            return

        pending_downloads[user.id] = {"url": url, "cost": cost, "format": fmt}
        await query.edit_message_text(
            f"{fmt_label} جاهز للتحميل\n\n"
            f"🎬 {title}\n"
            f"⏱️ المدة: {format_duration(duration_probe)}\n"
            f"💰 التكلفة: {cost} نقطة\n"
            f"⭐ رصيدك الحالي: {user_points} نقطة\n\n"
            "متأكد تريد تكمل التحميل؟",
            reply_markup=build_confirm_download_keyboard(),
        )

    elif query.data == "menu_back":
        waiting_support.discard(user.id)
        waiting_admin_action.pop(user.id, None)
        pending_downloads.pop(user.id, None)
        waiting_download.discard(user.id)
        waiting_redeem.discard(user.id)
        pending_link.pop(user.id, None)
        waiting_thumbnail.discard(user.id)
        waiting_subtitle.discard(user.id)
        waiting_clip_link.discard(user.id)
        waiting_clip_times.pop(user.id, None)
        waiting_ytsearch.discard(user.id)
        ytsearch_results.pop(user.id, None)
        await query.edit_message_text(
            build_dashboard_text(user),
            reply_markup=build_dashboard_keyboard(user.id == ADMIN_ID),
        )


async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    p = get_points(user_id)
    await update.message.reply_text(f"⭐ رصيدك: {p} نقطة")


async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if has_restriction(user_id, "invite"):
        await update.message.reply_text("🚫 تم تقييدك من ميزة الدعوة من طرف الإدارة.")
        return
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={user_id}"
    p = get_points(user_id)
    await update.message.reply_text(
        f"🔗 رابط الدعوة الخاص بك:\n{link}\n\n"
        f"💰 كل شخص يدخل عبر رابطك يمنحك 5 نقاط.\n"
        f"⭐ رصيدك الحالي: {p} نقطة"
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_users()
    text = format_history_text(users, str(user_id))
    await update.message.reply_text(text)


async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not get_setting("promo_codes_enabled"):
        await update.message.reply_text("🎟️ ميزة أكواد الهدية متوقفة حاليا.")
        return
    if not context.args:
        waiting_redeem.add(user.id)
        await update.message.reply_text("🎟️ أرسل لي الآن كود الهدية.")
        return
    code = context.args[0]
    success, message = redeem_promo_code(user.id, code)
    await update.message.reply_text(message)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    waiting_support.discard(user.id)
    waiting_download.discard(user.id)
    waiting_redeem.discard(user.id)
    waiting_admin_action.pop(user.id, None)
    pending_downloads.pop(user.id, None)
    pending_link.pop(user.id, None)
    waiting_thumbnail.discard(user.id)
    waiting_subtitle.discard(user.id)
    waiting_clip_link.discard(user.id)
    waiting_clip_times.pop(user.id, None)
    waiting_ytsearch.discard(user.id)
    ytsearch_results.pop(user.id, None)
    await update.message.reply_text("✅ تم إلغاء أي عملية جارية.")


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("الاستعمال: /broadcast <الرسالة>")
        return

    message_text = " ".join(context.args)
    users = load_users()
    sent, failed = 0, 0
    for uid in users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 {message_text}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ توصلت الرسالة لـ {sent} مستخدم. فشلت مع {failed}.")


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يفتح لوحة تحكم الأدمن مباشرة عبر الأمر /admin."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "⚙️ لوحة الإدارة\n\nاختر ما تريد تعديله:",
        reply_markup=build_admin_keyboard(),
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يفعل وضعية الدعم إذا كتب /support بدون نص، أو يرسل الرسالة مباشرة إذا كان هناك نص."""
    user = update.effective_user
    if has_restriction(user.id, "support"):
        await update.message.reply_text("🚫 تم تقييدك من ميزة الدعم الفني.")
        return
    if not context.args:
        waiting_support.add(user.id)
        await update.message.reply_text(
            "🎧 اكتب الآن رسالتك وستصل مباشرة لفريق الدعم."
        )
        return

    message_text = " ".join(context.args)
    await send_support_message(update, context, message_text)


async def send_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
    user = update.effective_user
    username_part = f"@{user.username}" if user.username else "بدون اسم مستخدم"

    admin_message = (
        f"📩 رسالة دعم جديدة\n"
        f"من: {user.full_name} ({username_part})\n"
        f"ID: {user.id}\n\n"
        f"الرسالة:\n{message_text}"
    )

    try:
        sent = await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message)
        support_replies[sent.message_id] = user.id
        await update.message.reply_text("✅ تم إرسال رسالتك للدعم، سيتم الرد عليك قريبا.")
    except Exception as e:
        logger.error(f"Support message error: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء إرسال رسالتك، حاول مرة أخرى.")


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعمل فقط مع الأدمن: عندما يرد (Reply) على رسالة دعم وصلته، يرسل ردّه إلى المستخدم."""
    replied = update.message.reply_to_message
    if not replied:
        return

    target_user_id = support_replies.get(replied.message_id)
    if not target_user_id:
        await download_video(update, context)
        return

    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"🎧 رد فريق الدعم:\n\n{update.message.text}",
        )
        await update.message.reply_text("✅ تم إرسال ردك للمستخدم.")
    except Exception as e:
        logger.error(f"Admin reply error: {e}")
        await update.message.reply_text("❌ تعذر إرسال الرد، حاول مرة أخرى.")


async def admin_panel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعمل فقط مع الأدمن، عندما يكون في حالة تعديل نقاط/دعوات/حظر مستخدم معين."""
    user = update.effective_user

    if user.id not in waiting_admin_action:
        await download_video(update, context)
        return

    action = waiting_admin_action.get(user.id)
    text = update.message.text.strip()
    parts = text.split()

    if action in ("admin_ban", "admin_unban"):
        if len(parts) != 1:
            await update.message.reply_text(
                "❌ الصيغة غلط. المطلوب: ID فقط\nمثال: 123456789"
            )
            return
        try:
            target_id = int(parts[0])
        except ValueError:
            await update.message.reply_text("❌ خاص الـ ID يكون رقم صحيح.")
            return

        if target_id == ADMIN_ID:
            await update.message.reply_text("❌ لا تستطيع حظر نفسك.")
            return

        waiting_admin_action.pop(user.id, None)
        if action == "admin_ban":
            set_banned(target_id, True)
            await update.message.reply_text(f"🚫 تم حظر المستخدم {target_id}.")
        else:
            set_banned(target_id, False)
            await update.message.reply_text(f"✅ تم إلغاء الحظر على المستخدم {target_id}.")
        return

    if action in ("admin_restrict", "admin_unrestrict"):
        if len(parts) != 2:
            await update.message.reply_text(
                "❌ الصيغة غلط. المطلوب: ID الصلاحية\n"
                f"الصلاحيات المتاحة: {' / '.join(VALID_RESTRICTIONS)}\n"
                "مثال: 123456789 download"
            )
            return
        target_id_str, perm = parts
        try:
            target_id = int(target_id_str)
        except ValueError:
            await update.message.reply_text("❌ خاص الـ ID يكون رقم صحيح.")
            return
        if perm not in VALID_RESTRICTIONS:
            await update.message.reply_text(
                f"❌ الصلاحية غير صحيحة. الصلاحيات المتاحة: {' / '.join(VALID_RESTRICTIONS)}"
            )
            return

        waiting_admin_action.pop(user.id, None)
        if action == "admin_restrict":
            add_restriction(target_id, perm)
            await update.message.reply_text(
                f"🔒 تم تقييد المستخدم {target_id} من صلاحية «{perm}»."
            )
        else:
            remove_restriction(target_id, perm)
            await update.message.reply_text(
                f"🔓 تم رفع التقييد عن المستخدم {target_id} فصلاحية «{perm}»."
            )
        return

    if action == "admin_create_promo":
        if len(parts) != 3:
            await update.message.reply_text(
                "❌ الصيغة غلط. المطلوب: كود النقاط الاستخدامات\n"
                "مثال: WELCOME10 10 100"
            )
            return
        code_str, points_str, uses_str = parts
        try:
            points_val = int(points_str)
            uses_val = int(uses_str)
        except ValueError:
            await update.message.reply_text("❌ النقاط والاستخدامات خاصهم يكونو أرقام صحيحة.")
            return

        waiting_admin_action.pop(user.id, None)
        final_code = create_promo_code(code_str, points_val, uses_val)
        await update.message.reply_text(
            f"🎟️ تم إنشاء الكود: {final_code}\n"
            f"💰 يعطي: {points_val} نقطة\n"
            f"👥 حد الاستخدام: {uses_val} شخص"
        )
        return

    if len(parts) != 2:
        await update.message.reply_text(
            "❌ الصيغة غلط. المطلوب: ID رقم\nمثال: 123456789 10"
        )
        return

    target_id_str, value_str = parts
    try:
        target_id = int(target_id_str)
        value = int(value_str)
    except ValueError:
        await update.message.reply_text("❌ خاص الـ ID والرقم يكونو أرقام صحيحة.")
        return

    waiting_admin_action.pop(user.id, None)

    if action == "admin_add_points":
        new_total = add_points(target_id, value, reason="تعديل الأدمن (إضافة)")
        await update.message.reply_text(
            f"✅ تم! نقاط المستخدم {target_id} الآن: {new_total}"
        )
    elif action == "admin_set_points":
        new_total = set_points(target_id, value, reason="تعديل الأدمن (تحديد)")
        await update.message.reply_text(
            f"✅ تم! نقاط المستخدم {target_id} تحددات فـ: {new_total}"
        )
    elif action == "admin_set_invites":
        new_total = set_invite_bonus(target_id, value)
        await update.message.reply_text(
            f"✅ تم! عدد دعوات المستخدم {target_id} الآن: {new_total}"
        )


async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if is_banned(user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    if get_setting("107_maintenance_mode_enabled") and user.id != ADMIN_ID:
        await update.message.reply_text(
            "🛠️ البوت متوقف مؤقتا للصيانة، أعد المحاولة من بعد."
        )
        return

    if user.id in waiting_support:
        if has_restriction(user.id, "support"):
            waiting_support.discard(user.id)
            await update.message.reply_text("🚫 تم تقييدك من ميزة الدعم الفني.")
            return
        waiting_support.discard(user.id)
        await send_support_message(update, context, update.message.text.strip())
        return

    if user.id in waiting_redeem:
        waiting_redeem.discard(user.id)
        if not get_setting("promo_codes_enabled"):
            await update.message.reply_text("🎟️ ميزة أكواد الهدية متوقفة حاليا.")
            return
        code = update.message.text.strip()
        success, message = redeem_promo_code(user.id, code)
        await update.message.reply_text(message)
        return

    if user.id in waiting_ytsearch:
        waiting_ytsearch.discard(user.id)
        query_text = update.message.text.strip()
        status_msg = await update.message.reply_text("🔎 جاري البحث في يوتيوب...")
        try:
            search_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                results = ydl.extract_info(f"ytsearch5:{query_text}", download=False)
            entries = results.get("entries", []) if results else []
        except Exception as e:
            logger.error(f"YouTube search error: {e}")
            entries = []

        if not entries:
            await status_msg.edit_text("❌ لم أجد أي نتائج لهذا البحث. حاول بكلمات أخرى.")
            return

        mapping = {}
        rows = []
        for i, entry in enumerate(entries[:5]):
            video_id = entry.get("id")
            title = entry.get("title") or "بلا عنوان"
            url = f"https://www.youtube.com/watch?v={video_id}"
            mapping[str(i)] = url
            short_title = title if len(title) <= 45 else title[:42] + "..."
            rows.append([InlineKeyboardButton(f"🎬 {short_title}", callback_data=f"ytpick_{i}")])
        rows.append([InlineKeyboardButton("⬅️ رجوع للقائمة", callback_data="menu_back")])
        ytsearch_results[user.id] = mapping
        await status_msg.edit_text(
            "🔎 اختر أحد النتائج التالية:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if user.id in waiting_thumbnail:
        waiting_thumbnail.discard(user.id)
        url = update.message.text.strip()
        if not url.startswith(("http://", "https://")):
            await update.message.reply_text("❌ هذا ليس رابطًا صحيحًا. يجب أن يبدأ بـ http:// أو https://.")
            return
        status_msg = await update.message.reply_text("📸 جاري جلب صورة الغلاف...")
        try:
            probe_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            thumbnail_url = info.get("thumbnail")
            title = info.get("title") or "بلا عنوان"
            if not thumbnail_url:
                await status_msg.edit_text("❌ لم أجد صورة غلاف لهذا الفيديو.")
                return
            await status_msg.delete()
            await update.message.reply_photo(photo=thumbnail_url, caption=f"📸 {title}")
        except Exception as e:
            logger.error(f"Thumbnail error: {e}")
            await status_msg.edit_text("❌ حدث خطأ أثناء جلب صورة الغلاف. تأكد من صحة الرابط.")
        return

    if user.id in waiting_subtitle:
        waiting_subtitle.discard(user.id)
        url = update.message.text.strip()
        if not url.startswith(("http://", "https://")):
            await update.message.reply_text("❌ هذا ليس رابطًا صحيحًا. يجب أن يبدأ بـ http:// أو https://.")
            return
        status_msg = await update.message.reply_text("📝 جاري البحث عن ملف الترجمة...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_template = os.path.join(tmp_dir, "sub.%(ext)s")
            sub_opts = {
                "outtmpl": output_template,
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["ar", "en"],
                "quiet": True,
                "no_warnings": True,
            }
            try:
                with yt_dlp.YoutubeDL(sub_opts) as ydl:
                    ydl.extract_info(url, download=True)
                sub_files = [
                    os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)
                    if f.endswith((".vtt", ".srt"))
                ]
                if not sub_files:
                    await status_msg.edit_text("❌ لم أجد ملف ترجمة متاح لهذا الفيديو.")
                    return
                await status_msg.delete()
                for sub_path in sub_files:
                    with open(sub_path, "rb") as sub_file:
                        await update.message.reply_document(document=sub_file)
            except Exception as e:
                logger.error(f"Subtitle error: {e}")
                await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الترجمة. تأكد من صحة الرابط.")
        return

    if user.id in waiting_clip_link:
        url = update.message.text.strip()
        if not url.startswith(("http://", "https://")):
            await update.message.reply_text("❌ هذا ليس رابطًا صحيحًا. يجب أن يبدأ بـ http:// أو https://.")
            return
        waiting_clip_link.discard(user.id)
        waiting_clip_times[user.id] = url
        await update.message.reply_text(
            "⏱️ الآن أرسل لي وقت البداية والنهاية للمقطع مفصولين بمسافة.\n\n"
            "مثال: 0:10 0:45\n"
            "(يعني قص المقطع من الثانية 10 إلى الثانية 45)"
        )
        return

    if user.id in waiting_clip_times:
        url = waiting_clip_times.pop(user.id)
        parts_txt = update.message.text.strip().split()
        if len(parts_txt) != 2:
            await update.message.reply_text("❌ الصيغة غير صحيحة. المطلوب: وقت_البداية وقت_النهاية\nمثال: 0:10 0:45")
            return
        start_sec = parse_time_to_seconds(parts_txt[0])
        end_sec = parse_time_to_seconds(parts_txt[1])
        if start_sec is None or end_sec is None or end_sec <= start_sec:
            await update.message.reply_text("❌ الأوقات غير صحيحة. تأكد أن وقت النهاية أكبر من وقت البداية.")
            return

        status_msg = await update.message.reply_text("⏳ جاري تحميل الفيديو لقص المقطع منه...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_template = os.path.join(tmp_dir, "media.%(ext)s")
            ydl_opts = {
                "outtmpl": output_template,
                "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best",
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "max_filesize": 2000 * 1024 * 1024,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)
                downloaded_files = [
                    os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)
                    if os.path.isfile(os.path.join(tmp_dir, f))
                ]
                if not downloaded_files:
                    await status_msg.edit_text("❌ لم أستطع تحميل الفيديو. تأكد أن الرابط صحيح وعمومي.")
                    return
                source_path = max(downloaded_files, key=os.path.getsize)

                await status_msg.edit_text("✂️ جاري قص المقطع...")
                clip_path = os.path.join(tmp_dir, "clip.mp4")
                ok = cut_video_clip(source_path, clip_path, start_sec, end_sec)
                if not ok or not os.path.exists(clip_path):
                    await status_msg.edit_text("❌ لم أستطع قص المقطع من هذا الفيديو.")
                    return

                await status_msg.edit_text("📤 جاري الإرسال...")
                with open(clip_path, "rb") as clip_file:
                    await update.message.reply_video(
                        video=clip_file,
                        caption=f"✂️ مقطع من {parts_txt[0]} إلى {parts_txt[1]}",
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=60,
                        pool_timeout=60,
                    )
                await status_msg.delete()
            except Exception as e:
                logger.error(f"Clip cutting error: {e}")
                await status_msg.edit_text("❌ حدث خطأ أثناء قص المقطع. تأكد من صحة الرابط والأوقات.")
        return

    text = update.message.text.strip()
    is_link = text.startswith(("http://", "https://"))

    if not is_link:
        if user.id in waiting_download:
            waiting_download.discard(user.id)
            await update.message.reply_text(
                "❌ هذا ليس رابطًا صحيحًا. الرابط يجب أن يبدأ بـ http:// أو https://.\n"
                "اضغط زر «📥 تحميل فيديو» وأعد إرسال الرابط."
            )
        else:
            await update.message.reply_text(
                "🎬 حتى تحمّل فيديو، اضغط زر «📥 تحميل فيديو» في القائمة الرئيسية "
                "(اكتب /start إذا لم تكن قد بدأت) وأرسل لي الرابط."
            )
        return

    waiting_download.discard(user.id)

    if has_restriction(user.id, "download") and user.id != ADMIN_ID:
        await update.message.reply_text("🚫 تم تقييدك من ميزة التحميل من طرف الإدارة.")
        return

    if not check_rate_limit(user.id) and user.id != ADMIN_ID:
        await update.message.reply_text(
            "⏳ تمهل قليلاً! أرسلت روابط كثيرة في وقت قصير، انتظر قليلاً ثم أعد المحاولة."
        )
        return

    url = text
    pending_link[user.id] = url
    await update.message.reply_text(
        "🎬 هل تريد تحميل الفيديو كاملاً أم استخراج الصوت (MP3) فقط؟",
        reply_markup=build_format_choice_keyboard(),
    )


async def execute_download(update, context, url, cost, is_admin, status_msg, fmt="video"):
    """تقوم بالتحميل الفعلي، الضغط/التقسيم إذا لزم (فيديو فقط)، الإرسال، وخصم النقاط."""
    user = update.effective_user

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_template = os.path.join(tmp_dir, "media.%(ext)s")

        if fmt == "audio":
            ydl_opts = {
                "outtmpl": output_template,
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "quiet": True,
                "no_warnings": True,
                "max_filesize": 2000 * 1024 * 1024,
            }
        else:
            ydl_opts = {
                "outtmpl": output_template,
                "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best",
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "max_filesize": 2000 * 1024 * 1024,
            }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            downloaded_files = [
                f for f in os.listdir(tmp_dir)
                if os.path.isfile(os.path.join(tmp_dir, f))
            ]

            if not downloaded_files:
                await status_msg.edit_text(
                    "❌ لم أستطع تحميل الملف. تأكد أن الرابط صحيح وعمومي."
                )
                return

            filename = max(
                (os.path.join(tmp_dir, f) for f in downloaded_files),
                key=os.path.getsize,
            )

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            duration = info.get("duration") or 0

            if fmt == "compressed":
                await status_msg.edit_text("📦 جاري ضغط الفيديو...")
                compressed_path = os.path.join(tmp_dir, "manual_compressed.mp4")
                ok = compress_video_manual(filename, compressed_path, duration)
                if ok and os.path.exists(compressed_path):
                    filename = compressed_path
                    file_size_mb = os.path.getsize(filename) / (1024 * 1024)
                fmt = "video"  # نتابع بقية المسار كفيديو عادي بعد الضغط

            if fmt == "video" and file_size_mb > MAX_SIZE_MB:
                await status_msg.edit_text(
                    f"📦 الفيديو كبير ({file_size_mb:.1f}MB)، جاري ضغطه..."
                )
                compressed_path = os.path.join(tmp_dir, "compressed.mp4")
                ok = compress_video(filename, compressed_path, MAX_SIZE_MB, duration)

                if not ok or not os.path.exists(compressed_path):
                    await status_msg.edit_text(
                        "❌ لم أستطع ضغط الفيديو. جرب فيديو أقصر."
                    )
                    return

                filename = compressed_path
                file_size_mb = os.path.getsize(filename) / (1024 * 1024)

                if file_size_mb > MAX_SIZE_MB:
                    await status_msg.edit_text(
                        f"✂️ الفيديو كبير ({file_size_mb:.1f}MB)، جاري تقسيمه لأجزاء..."
                    )
                    parts = split_video(filename, tmp_dir, MAX_SIZE_MB, duration)
                    if not parts:
                        await status_msg.edit_text("❌ فشل تقسيم الفيديو.")
                        return
                    await status_msg.delete()
                    for i, part_path in enumerate(parts, start=1):
                        with open(part_path, "rb") as part_file:
                            await update.effective_message.reply_video(
                                video=part_file,
                                caption=f"📦 جزء {i}/{len(parts)} - {info.get('title', 'فيديو معدل')}",
                                read_timeout=180,
                                write_timeout=180,
                                connect_timeout=60,
                                pool_timeout=60,
                            )
                    increment_downloads()
                    increment_user_downloads(user.id)
                    if not is_admin and cost > 0:
                        remaining = add_points(user.id, -cost, reason="تحميل فيديو")
                        await update.effective_message.reply_text(
                            f"💰 تم خصم {cost} نقطة. رصيدك الحالي: {remaining} نقطة"
                        )
                    return

            if fmt == "audio" and file_size_mb > MAX_SIZE_MB:
                await status_msg.edit_text(
                    f"❌ الملف الصوتي كبير كثيرًا ({file_size_mb:.1f}MB) حتى يتم إرساله."
                )
                return

            await status_msg.edit_text("📤 جاري الإرسال...")

            if fmt == "audio":
                with open(filename, "rb") as audio_file:
                    await update.effective_message.reply_audio(
                        audio=audio_file,
                        title=info.get("title", "صوت"),
                        performer=info.get("uploader", ""),
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=60,
                        pool_timeout=60,
                    )
            else:
                with open(filename, "rb") as video_file:
                    await update.effective_message.reply_video(
                        video=video_file,
                        caption=f"✅ {info.get('title', 'تم تحميل الفيديو')}",
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=60,
                        pool_timeout=60,
                    )
            await status_msg.delete()
            increment_downloads()
            increment_user_downloads(user.id)

            if not is_admin and cost > 0:
                remaining = add_points(user.id, -cost, reason="تحميل فيديو")
                await update.effective_message.reply_text(
                    f"💰 تم خصم {cost} نقطة. رصيدك الحالي: {remaining} نقطة"
                )

        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error: {e}")
            await status_msg.edit_text(
                "❌ لم أستطع تحميل هذا الفيديو. تأكد أن الرابط صحيح وأن الفيديو عمومي (public)."
            )
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await status_msg.edit_text("❌ حدث خطأ غير متوقع، حاول مرة أخرى.")


def main():
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("invite", invite))
    app.add_handler(CommandHandler("points", points))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(menu_callback))

    # رسائل الأدمن لي كتكون Reply (رد) يجب أن تفوت قبل الهاندلر العام
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(user_id=ADMIN_ID) & filters.REPLY,
            admin_reply,
        )
    )

    # رسائل الأدمن العادية (غير Reply) - تعمل لوحة الإدارة إلا كان في حالة تعديل
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(user_id=ADMIN_ID) & ~filters.REPLY,
            admin_panel_input,
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_video))

    print("🤖 البوت الآن مدخل مع نظام الـ 100 ميزة...")
    app.run_polling()


if __name__ == "__main__":
    main()
