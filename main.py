import logging
from telegram import Update
from telegram.ext import ContextTypes

from telegram.ext import Application, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from core.config import TELEGRAM_BOT_TOKEN, PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID
from core.db import init_db
from bot.handlers import (
    process_message, manual_trigger_command, manual_recap_command, 
    handle_discussion_forward, edit_event_command, pause_command, 
    resume_command, bot_status_command
)
from bot.callbacks import handle_approval
from core.scheduler import start_scheduler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Set httpx logging to WARNING to prevent clutter from Telegram getUpdates polling
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def post_init(application: Application):
    from core.scheduler import start_scheduler
    start_scheduler(application.bot)

async def post_shutdown(application: Application):
    from core.scheduler import stop_scheduler
    stop_scheduler()

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN non impostato.")
        return
        
    init_db()
    
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Handlers for admin commands
    application.add_handler(CommandHandler("process_event", manual_trigger_command))
    application.add_handler(CommandHandler("generate_recap", manual_recap_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("bot_status", bot_status_command))
    
    edit_cmds = ["edit_title", "edit_date", "edit_normalized_date", "edit_system", "edit_seats", "edit_booked", "edit_host", "edit_extra", "edit_description"]
    for cmd in edit_cmds:
        application.add_handler(CommandHandler(cmd, edit_event_command))
    
    # Listen to public channel
    if PUBLIC_CHANNEL_ID:
        try:
            channel_id = int(PUBLIC_CHANNEL_ID)
            application.add_handler(MessageHandler(filters.Chat(chat_id=channel_id) & (filters.TEXT | filters.PHOTO), process_message))
        except ValueError:
            logger.error("PUBLIC_CHANNEL_ID deve essere un intero valido.")
            
    # Listen to discussion group for automatic forwards
    if DISCUSSION_GROUP_ID:
        try:
            discussion_id = int(DISCUSSION_GROUP_ID)
            application.add_handler(MessageHandler(filters.Chat(chat_id=discussion_id), handle_discussion_forward))
        except ValueError:
            logger.error("DISCUSSION_GROUP_ID deve essere un intero valido.")
            
    async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message or update.channel_post
        if msg:
            logger.info(f"Ricevuto update non gestito da chat_id: {msg.chat_id} (Verifica se coincide con PUBLIC_CHANNEL_ID: {PUBLIC_CHANNEL_ID})")
            
    application.add_handler(MessageHandler(filters.ALL, debug_all))
        
    # Callback queries (buttons)
    application.add_handler(CallbackQueryHandler(handle_approval))
    
    logger.info("Bot in esecuzione...")
    application.run_polling()

if __name__ == '__main__':
    main()

