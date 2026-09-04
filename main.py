import logging
from telegram import Update
from telegram.ext import ContextTypes

from telegram.ext import Application, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from core.config import TELEGRAM_BOT_TOKEN, PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID, ADMIN_CHAT_ID
from core.db import init_db
from bot.handlers import (
    process_message, manual_trigger_command, manual_recap_command, 
    handle_discussion_forward, event_edit_command, bot_pause_command, 
    bot_resume_command, bot_status_command, event_sub_add_command,
    event_sub_remove_command, handle_admin_reply, cache_admin_media_group
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
    application.add_handler(CommandHandler("event_process", manual_trigger_command, block=False))
    application.add_handler(CommandHandler("ep", manual_trigger_command, block=False))
    application.add_handler(CommandHandler("recap_generate", manual_recap_command))
    application.add_handler(CommandHandler("rg", manual_recap_command))
    application.add_handler(CommandHandler("bot_pause", bot_pause_command))
    application.add_handler(CommandHandler("resume", bot_resume_command))
    application.add_handler(CommandHandler("bot_status", bot_status_command))
    
    edit_cmds = ["event_edit_title", "event_edit_date", "event_edit_normalized_date", "event_edit_system", "event_edit_seats", "event_edit_booked", "event_edit_host", "event_edit_extra", "event_edit_description", "event_edit_image"]
    for cmd in edit_cmds:
        application.add_handler(CommandHandler(cmd, event_edit_command, block=False))
    application.add_handler(CommandHandler("event_sub_add", event_sub_add_command))
    application.add_handler(CommandHandler("event_sub_remove", event_sub_remove_command))

    # Caption command handlers (PTB CommandHandler only matches message.text, not message.caption)
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/event_edit_"), event_edit_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/(event_process|ep)(\s|$|@)"), manual_trigger_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/(recap_generate|rg)(\s|$|@)"), manual_recap_command))
    
    # Listen to admin chat for prompt replies and album photos caching
    if ADMIN_CHAT_ID:
        try:
            admin_id = int(ADMIN_CHAT_ID)
            # Register caching in group=-1 so incoming admin photos are cached without consuming group=0
            application.add_handler(MessageHandler(filters.Chat(chat_id=admin_id) & (filters.PHOTO | filters.Document.IMAGE), cache_admin_media_group, block=False), group=-1)
            application.add_handler(MessageHandler(filters.Chat(chat_id=admin_id) & filters.TEXT & filters.REPLY, handle_admin_reply))
        except ValueError:
            logger.error("ADMIN_CHAT_ID deve essere un intero valido.")

    
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

