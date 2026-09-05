#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sqlite3
import logging
from typing import Dict, List, Tuple

BOT_TOKEN = "8108848585:AAFEIAoND3X1pIJnwnQgq1-zHHvz-PufZxs"
ADMIN_IDS = [8742217342]
MAX_SIZE_MB = 100
DB_FILE = "bot_data.db"
FEATURES_FILE = "data/features.json"

os.makedirs("data", exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, 
    MessageHandler, CallbackQueryHandler, filters, ConversationHandler
)
from config import BOT_TOKEN, ADMIN_IDS, logger, admin_system, feature_system

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    admin_system.log_action(user.id, "start", f"User: {user.first_name}")
    
    keyboard = [
        [InlineKeyboardButton("📥 تحميل", callback_data="download"),
         InlineKeyboardButton("⚙️ إعدادات", callback_data="settings")],
        [InlineKeyboardButton("💬 دعم ذكي", callback_data="ai_support"),
         InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🛡️ لوحة الأدمن", callback_data="admin_panel")])
    
    await update.message.reply_text(
        f"🎬 مرحباً {user.first_name}!\n\n"
        f"🌟 بوت تحميل الفيديوهات v4.0\n"
        f"✨ يعمل بكفاءة عالية وأمان تام\n",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def main():
    logger.info("🚀 بدء البوت...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    
    await app.initialize()
    await app.start()
    logger.info("✅ البوت يعمل بنجاح!")
    
    await app.updater.start_polling()
    await app.idle()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔ تم إيقاف البوت")

