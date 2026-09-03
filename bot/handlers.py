from telegram import Update
from telegram.ext import ContextTypes
import logging
from core.ai_parser import parse_event_message
from core.db import insert_event
from core.config import DATA_DIR, ADMIN_CHAT_ID, PUBLIC_CHANNEL_ID
from utils.image_utils import save_image_locally
from utils.templates import format_instagram_story
from bot.keyboards import get_approval_keyboard

logger = logging.getLogger(__name__)

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.channel_post
    logger.info(f"Ricevuto messaggio dal chat_id: {message.chat_id}")

    if not message:
        return
        
    # Ignore messages sent by the bot itself to prevent infinite loops
    if message.from_user and message.from_user.is_bot:
        return
        
    # If the message already has our custom booking keyboard, it's a formatted message published by us, ignore it.
    if message.reply_markup and message.reply_markup.inline_keyboard:
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data and button.callback_data.startswith(("book_", "unbook_")):
                    return
        
    # Get text and image
    text = message.text or message.caption
    if not text:
        return
        
    image_bytes = None
    if message.photo:
        photo_file = await message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
    # Se il messaggio arriva dal canale pubblico, eliminalo per evitare duplicati non formattati
    if str(message.chat_id) == str(PUBLIC_CHANNEL_ID):
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Errore durante l'eliminazione del messaggio originale: {e}")
        message_link = None
    else:
        message_link = message.link
        
    await handle_event_extraction(text, image_bytes, context, message_link, message.message_id)
        
async def manual_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This responds to /process_event
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("Non sei autorizzato.")
        return
        
    # User might reply to a message or send text with it
    if update.message.reply_to_message:
        target_msg = update.message.reply_to_message
        text = target_msg.text or target_msg.caption
        
        image_bytes = None
        if target_msg.photo:
            photo_file = await target_msg.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
            
        await handle_event_extraction(text, image_bytes, context, target_msg.link, target_msg.message_id)
        await update.message.reply_text("Processato il messaggio risposto.")
    else:
        # try to parse from the command itself
        text_parts = update.message.text.split(maxsplit=1)
        if len(text_parts) > 1:
            text = text_parts[1]
            await handle_event_extraction(text, None, context, None, update.message.message_id)
            await update.message.reply_text("Processato il testo inviato.")
        else:
            await update.message.reply_text("Rispondi a un messaggio o fornisci il testo.")
            
async def handle_event_extraction(text, image_bytes, context, message_link=None, telegram_message_id=None):
    if not text:
        return
        
    event_data = parse_event_message(text)
    
    if not event_data or event_data.get('is_event') is False:
        logger.info("Message is not an event or could not be parsed.")
        return
        
    image_path = None
    if image_bytes:
        image_path = save_image_locally(image_bytes, DATA_DIR, event_data.get('normalized_date'))
        
    event_id = insert_event(event_data, image_path, text, message_link, telegram_message_id)
    if not event_id:
        logger.error("Failed to insert event into DB.")
        return
        
    # Send for approval
    story_text = format_instagram_story(event_data)
    keyboard = get_approval_keyboard(event_id)
    
    if image_path:
        with open(image_path, 'rb') as f:
            await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=f, caption=story_text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=story_text, reply_markup=keyboard)

async def manual_recap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
    
    args = context.args
    date_str = args[0] if args else None
    
    from core.scheduler import generate_daily_recap
    await generate_daily_recap(context.bot, date_str, is_manual=True)
    await update.message.reply_text(f"Recap generato per la data: {date_str or 'Oggi'}")

