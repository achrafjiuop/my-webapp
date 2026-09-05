import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

BOT_TOKEN = "8108848585:AAFEIAoND3X1pIJnwnQgq1-zHHvz-PufZxs"
ADMIN_ID = 8742217342

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎬 أهلاً بك يا {user.first_name}!\n\n"
        f"✨ البوت يعمل الآن بنجاح تام وسليم 🚀\n"
        f"📥 أرسل رابط الفيديو للبدء!"
    )

def main():
    logger.info("🚀 بدء تشغيل البوت...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    
    logger.info("✅ البوت يعمل الآن ويستقبل الرسائل!")
    # الطريقة الأصح والأحدث لتشغيل البتون والانتظار دون أخطاء
    app.run_polling()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("⛔ تم إيقاف البوت بواسطة المستخدم")
