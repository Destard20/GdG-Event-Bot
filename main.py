import logging
from telegram import Update
from telegram.ext import ContextTypes

from telegram.ext import Application, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from core.config import TELEGRAM_BOT_TOKEN, PUBLIC_CHANNEL_ID
from core.db import init_db
from bot.handlers import process_message, manual_trigger_command, manual_recap_command
from bot.callbacks import handle_approval
from core.scheduler import start_scheduler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Set httpx logging to WARNING to prevent clutter from Telegram getUpdates polling
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN non impostato.")
        return
        
    init_db()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Handlers for admin commands
    application.add_handler(CommandHandler("process_event", manual_trigger_command))
    application.add_handler(CommandHandler("generate_recap", manual_recap_command))
    
    # Listen to public channel
    if PUBLIC_CHANNEL_ID:
        try:
            channel_id = int(PUBLIC_CHANNEL_ID)
            application.add_handler(MessageHandler(filters.Chat(chat_id=channel_id) & (filters.TEXT | filters.PHOTO), process_message))
        except ValueError:
            logger.error("PUBLIC_CHANNEL_ID deve essere un intero valido.")
            
    async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message or update.channel_post
        if msg:
            logger.info(f"Ricevuto update non gestito da chat_id: {msg.chat_id} (Verifica se coincide con PUBLIC_CHANNEL_ID: {PUBLIC_CHANNEL_ID})")
            
    application.add_handler(MessageHandler(filters.ALL, debug_all))
        
    # Callback queries (buttons)
    application.add_handler(CallbackQueryHandler(handle_approval))
    
    # Start scheduler
    start_scheduler(application.bot)
    
    logger.info("Bot in esecuzione...")
    application.run_polling()

if __name__ == '__main__':
    main()

