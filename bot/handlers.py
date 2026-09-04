from telegram import Update
from telegram.ext import ContextTypes
import logging
from core.ai_parser import parse_event_message
from core.db import insert_event
from core.config import DATA_DIR, ADMIN_CHAT_ID, PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID
from utils.image_utils import save_image_locally
from utils.templates import format_instagram_story, format_public_event_message
from bot.keyboards import get_approval_keyboard, get_event_booking_keyboard
from core.db import get_event_by_telegram_message_id, update_event_field, get_event

logger = logging.getLogger(__name__)

is_bot_paused = False
last_recap_message_id = None
last_recap_events = None

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_bot_paused
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
    is_bot_paused = True
    logger.info("Bot execution paused by admin.")
    await update.message.reply_text("🔴 **Bot in pausa!**\nIl bot ora ignorerà tutti i messaggi inviati sul canale eventi.", parse_mode="Markdown")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_bot_paused
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
    is_bot_paused = False
    logger.info("Bot execution resumed by admin.")
    await update.message.reply_text("🟢 **Bot riattivato!**\nIl bot ricomincerà a monitorare il canale eventi.", parse_mode="Markdown")

async def bot_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
    status = "🔴 IN PAUSA (monitoraggio canale eventi disattivato)" if is_bot_paused else "🟢 ATTIVO (monitoraggio canale eventi funzionante)"
    await update.message.reply_text(f"Stato del bot: {status}")

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_bot_paused:
        logger.info("Bot in pausa: messaggio dal canale eventi ignorato.")
        return

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
    # This responds to /event_process or /ep
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
            
        await handle_event_extraction(text, image_bytes, context, target_msg.link, target_msg.message_id, is_manual_trigger=True)
        await update.message.reply_text("Processato il messaggio risposto.")
    else:
        # try to parse from the command itself
        text_parts = update.message.text.split(maxsplit=1)
        if len(text_parts) > 1:
            text = text_parts[1]
            await handle_event_extraction(text, None, context, None, update.message.message_id, is_manual_trigger=True)
            await update.message.reply_text("Processato il testo inviato.")
        else:
            await update.message.reply_text("Rispondi a un messaggio o fornisci il testo.")
            
async def handle_event_extraction(text, image_bytes, context, message_link=None, telegram_message_id=None, is_manual_trigger=False):
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
        
    # Send original text for comparison only if intercepted from channel (not manual trigger in admin chat)
    if not is_manual_trigger:
        orig_msg = f"📥 Testo originale del messaggio:\n\n{text}"
        if len(orig_msg) > 4000:
            orig_msg = orig_msg[:3990] + "..."
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=orig_msg)
        except Exception as e:
            logger.error(f"Error sending original text to admin: {e}")
        
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

async def handle_discussion_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.channel_post
    if not message:
        return
        
    is_auto = getattr(message, 'is_automatic_forward', False)
    forward_origin = getattr(message, 'forward_origin', None)
    
    # If not an automatic forward or channel forward, ignore standard user chat
    if not is_auto and (not forward_origin or getattr(forward_origin, 'type', None) != 'channel'):
        return
        
    forward_msg_id = None
    if forward_origin and getattr(forward_origin, 'type', None) == 'channel':
        forward_msg_id = getattr(forward_origin, 'message_id', None)
    elif hasattr(message, 'forward_from_message_id'):
        forward_msg_id = message.forward_from_message_id
        
    logger.info(f"Detected channel forward in discussion group: msg_id={message.message_id}, origin_msg_id={forward_msg_id}")
    
    if not forward_msg_id:
        return
        
    global last_recap_message_id, last_recap_events
    if forward_msg_id and forward_msg_id == last_recap_message_id:
        from utils.templates import recap_links_text
        links_text = recap_links_text(last_recap_events)
        if links_text:
            try:
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=links_text,
                    reply_to_message_id=message.message_id,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                logger.info(f"Successfully posted recap links reply in discussion group for recap message {forward_msg_id}")
            except Exception as e:
                logger.error(f"Error posting recap links to discussion group: {e}")
        return

    # Get event from DB using the telegram_message_id
    event = get_event_by_telegram_message_id(forward_msg_id)
    if not event:
        logger.warning(f"No event found in DB for forwarded message_id={forward_msg_id}")
        return
        
    # Send a reply with the booking keyboard
    pub_keyboard = get_event_booking_keyboard(event['id'], event=event)
    
    try:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text="👇 Gestisci qui la tua prenotazione!",
            reply_to_message_id=message.message_id,
            reply_markup=pub_keyboard
        )
        logger.info(f"Successfully posted booking buttons reply in discussion group for event {event['id']}")
    except Exception as e:
        logger.error(f"Error sending booking buttons to discussion group: {e}")

async def event_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
        
    if not update.message.reply_to_message:
        await update.message.reply_text("Rispondi al messaggio dell'evento che vuoi modificare.")
        return

    target_msg = update.message.reply_to_message
    
    # Try to find event_id from inline keyboard
    event_id = None
    if target_msg.reply_markup and target_msg.reply_markup.inline_keyboard:
        for row in target_msg.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data:
                    if button.callback_data.startswith(("publish_event_", "discard_event_", "cancel_event_")):
                        event_id = int(button.callback_data.split("_")[2])
                        break
            if event_id:
                break
                
    if not event_id:
        await update.message.reply_text("Impossibile determinare l'ID dell'evento da questo messaggio. Assicurati di rispondere al messaggio con i pulsanti (Publish, Discard, Cancel).")
        return
        
    text_parts = update.message.text.split(maxsplit=1)
    cmd = text_parts[0].lower()
    value = text_parts[1] if len(text_parts) > 1 else ""
    
    field_map = {
        "/event_edit_title": "title",
        "/event_edit_date": "date",
        "/event_edit_normalized_date": "normalized_date",
        "/event_edit_system": "system",
        "/event_edit_seats": "seats",
        "/event_edit_booked": "booked_seats",
        "/event_edit_host": "host",
        "/event_edit_extra": "extra_info",
        "/event_edit_description": "description"
    }
    
    field = field_map.get(cmd)
    if not field:
        return
        
    if field == "seats":
        # Handle "null", "nessuno", "0", "unlimited"
        if value.lower() in ["null", "nessuno", "0", "unlimited", ""]:
            update_event_field(event_id, "max_seats", None)
            update_event_field(event_id, "seats", "no limit")
            success = True
        elif "/" in value:
            parts = value.split("/")
            try:
                free = int(parts[0].strip())
                total = int(parts[1].strip())
                booked = max(0, total - free)
                update_event_field(event_id, "max_seats", total)
                update_event_field(event_id, "booked_seats", booked)
                update_event_field(event_id, "seats", f"{free}/{total}")
                success = True
            except ValueError:
                await update.message.reply_text("Formato non valido. Usa 'X/Y' (es. '2/2'), un numero intero (es. '4'), o 'null'.")
                return
        else:
            try:
                total = int(value)
                update_event_field(event_id, "max_seats", total)
                ev_now = get_event(event_id)
                cur_booked = ev_now.get('booked_seats', 0) if ev_now else 0
                if cur_booked > total:
                    update_event_field(event_id, "booked_seats", 0)
                update_event_field(event_id, "seats", f"{total}/{total}")
                success = True
            except ValueError:
                await update.message.reply_text("Il valore per i posti deve essere un numero intero (o 'X/Y' o 'null').")
                return
    elif field == "booked_seats":
        try:
            b_val = int(value)
            success = update_event_field(event_id, "booked_seats", b_val)
        except ValueError:
            await update.message.reply_text("Il valore per i posti prenotati deve essere un numero intero.")
            return
    elif field == "extra_info":
        if value.lower() in ["null", "nessuno", "0", "none", "elimina", "cancella"]:
            value = ""
        success = update_event_field(event_id, "extra_info", value)
    else:
        success = update_event_field(event_id, field, value)
    if not success:
        await update.message.reply_text("Errore durante l'aggiornamento del database.")
        return
        
    # Reload event
    event = get_event(event_id)
    if not event:
        await update.message.reply_text("Evento non trovato nel DB dopo l'aggiornamento.")
        return

    # Update admin message
    story_text = format_instagram_story(event)
    
    # Preserve status text and keyboard
    status_text = ""
    keyboard = target_msg.reply_markup
    
    if event['status'] == 'approved':
        status_text = "\n\n✅ APPROVATO"
    elif event['status'] == 'discarded':
        status_text = "\n\n❌ SCARTATO"
    elif event['status'] == 'cancelled':
        status_text = "\n\n⚠️ ANNULLATO"
        
    new_text = story_text + status_text
    
    try:
        if target_msg.photo:
            await target_msg.edit_caption(caption=new_text, reply_markup=keyboard)
        else:
            await target_msg.edit_text(text=new_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error editing admin message: {e}")
        await update.message.reply_text("Aggiornamento salvato nel DB, ma il testo del messaggio admin è identico al precedente.")
        
    # If approved and published, update public channel
    if event['status'] in ['approved', 'cancelled'] and event.get('telegram_message_id') and PUBLIC_CHANNEL_ID:
        public_text = format_public_event_message(event)
        
        pub_keyboard = None
        if event['status'] == 'approved':
            pub_keyboard = get_event_booking_keyboard(event_id, event=event)
            
        try:
            if event.get('image_path'):
                await context.bot.edit_message_caption(
                    chat_id=PUBLIC_CHANNEL_ID,
                    message_id=event['telegram_message_id'],
                    caption=public_text,
                    reply_markup=pub_keyboard
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=PUBLIC_CHANNEL_ID,
                    message_id=event['telegram_message_id'],
                    text=public_text,
                    reply_markup=pub_keyboard
                )
        except Exception as e:
            logger.error(f"Error editing public channel message: {e}")
            await update.message.reply_text("Attenzione: l'evento è stato aggiornato, ma il testo del post sul canale pubblico era identico e non è stato modificato (normale se aggiorni dati non mostrati sul canale come l'host).")
            
    await update.message.reply_text(f"✅ Campo '{field}' aggiornato con successo!")

