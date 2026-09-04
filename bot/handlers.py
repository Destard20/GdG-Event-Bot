import re
from telegram import Update
from telegram.ext import ContextTypes
import logging
from core.ai_parser import parse_event_message
from core.db import (
    insert_event,
    get_event_by_telegram_message_id,
    update_event_field,
    get_event,
    update_discussion_message_info,
    admin_add_subscriber,
    admin_remove_subscriber,
    get_reservation_by_user,
)
from core.config import DATA_DIR, ADMIN_CHAT_ID, PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID
from utils.image_utils import save_image_locally
from utils.templates import format_instagram_story, format_public_event_message
from utils.date_utils import parse_user_date, format_standard_event_date, validate_event_date_anomalies
from bot.keyboards import get_approval_keyboard, get_event_booking_keyboard
from bot.service import update_event_messages, send_admin_action_notice

logger = logging.getLogger(__name__)

is_bot_paused = False
last_recap_message_id = None
last_recap_events = None

async def bot_pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_bot_paused
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
    is_bot_paused = True
    logger.info("Bot execution paused by admin.")
    await update.message.reply_text("🔴 **Bot in pausa!**\nIl bot ora ignorerà tutti i messaggi inviati sul canale eventi.", parse_mode="Markdown")

async def bot_resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    warnings = validate_event_date_anomalies(event_data, raw_text=text)
    if warnings:
        warning_block = "🚨 ATTENZIONE ANOMALIE DATA:\n" + "\n".join(warnings) + "\n👉 Usa /event_edit_date per correggere prima di approvare.\n\n"
        story_text = warning_block + story_text

    caption_text = story_text
    if image_path and len(caption_text) > 1024:
        caption_text = caption_text[:1020] + "..."

    if image_path:
        with open(image_path, 'rb') as f:
            await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=f, caption=caption_text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=story_text, reply_markup=keyboard)

async def manual_recap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
    
    args = context.args
    date_str = None
    if args:
        parsed = parse_user_date(args[0])
        if not parsed:
            if update.message:
                await update.message.reply_text(
                    "❌ Formato data non valido.\n"
                    "Usa il formato DD-MM-YYYY (es. /recap_generate 05-09-2026)."
                )
            return
        dt, _ = parsed
        date_str = dt.strftime("%d-%m-%Y")
    
    from core.scheduler import generate_daily_recap
    reply_id = update.message.message_id if update.message else None
    success = await generate_daily_recap(context.bot, date_str, is_manual=True, reply_to_message_id=reply_id)
    if success:
        if update.message:
            await update.message.reply_text(f"Recap generato per la data: {date_str or 'Oggi'}")
        else:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Recap generato per la data: {date_str or 'Oggi'}")

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
        
    # Check if this event already has a discussion reply message
    if event.get('discussion_message_id'):
        logger.info(f"Event {event['id']} already has discussion_message_id={event['discussion_message_id']}")
        pub_keyboard = get_event_booking_keyboard(event['id'], event=event)
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=message.chat_id,
                message_id=event['discussion_message_id'],
                reply_markup=pub_keyboard
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error updating existing discussion reply markup: {e}")
        return

    # Send a reply with the booking keyboard
    pub_keyboard = get_event_booking_keyboard(event['id'], event=event)
    
    try:
        reply_msg = await context.bot.send_message(
            chat_id=message.chat_id,
            text="👇 Gestisci qui la tua prenotazione!",
            reply_to_message_id=message.message_id,
            reply_markup=pub_keyboard
        )
        update_discussion_message_info(event['id'], reply_msg.message_id, message.chat_id)
        logger.info(f"Successfully posted booking buttons reply in discussion group for event {event['id']}")
    except Exception as e:
        logger.error(f"Error sending booking buttons to discussion group: {e}")

def extract_event_id_from_reply(reply_msg):
    if not reply_msg:
        return None
    # 1. Check callback data on reply markup
    if reply_msg.reply_markup and reply_msg.reply_markup.inline_keyboard:
        for row in reply_msg.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    for prefix in [
                        "publish_event_",
                        "discard_event_",
                        "cancel_event_",
                        "reactivate_event_",
                        "manage_subs_",
                        "sub_inc_",
                        "sub_dec_",
                        "sub_addnew_",
                        "close_subs_",
                    ]:
                        if btn.callback_data.startswith(prefix):
                            parts = btn.callback_data.split("_")
                            try:
                                return int(parts[2])
                            except (IndexError, ValueError):
                                pass
    # 2. Check text or caption for #(\d+)
    content = reply_msg.caption or reply_msg.text or ""
    m = re.search(r"evento #(\d+)", content, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 3. Check DB telegram_message_id
    ev = get_event_by_telegram_message_id(reply_msg.message_id)
    if ev:
        return ev['id']
    return None

async def event_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
        
    if not update.message.reply_to_message:
        await update.message.reply_text("Rispondi al messaggio dell'evento che vuoi modificare.")
        return

    target_msg = update.message.reply_to_message
    event_id = extract_event_id_from_reply(target_msg)
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
        
    if field == "date":
        parsed = parse_user_date(value)
        if not parsed:
            await update.message.reply_text(
                "❌ Formato data non valido.\n"
                "Usa il formato DD-MM-YYYY o DD-MM-YYYY HH:MM (es. 05-09-2026 oppure 05-09-2026 21:00) (i / funzionano anche)."
            )
            return
        dt, has_time = parsed
        formatted_date, norm_date = format_standard_event_date(dt, has_time)
        s1 = update_event_field(event_id, "date", formatted_date)
        s2 = update_event_field(event_id, "normalized_date", norm_date)
        success = s1 and s2
    elif field == "normalized_date":
        parsed = parse_user_date(value)
        if not parsed:
            await update.message.reply_text(
                "❌ Formato data normalizzata non valido.\n"
                "Usa il formato DD-MM-YYYY (es. 05-09-2026)."
            )
            return
        dt, _ = parsed
        norm_date = dt.strftime("%d-%m-%Y")
        success = update_event_field(event_id, "normalized_date", norm_date)
    elif field == "seats":
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
                free = max(0, total - cur_booked)
                update_event_field(event_id, "seats", f"{free}/{total}")
                success = True
            except ValueError:
                await update.message.reply_text("Il valore per i posti deve essere un numero intero, 'X/Y' o 'null'.")
                return
    elif field == "booked_seats":
        try:
            b_val = int(value)
            success = update_event_field(event_id, "booked_seats", b_val)
            ev_now = get_event(event_id)
            if ev_now and ev_now.get('max_seats') is not None:
                max_s = ev_now['max_seats']
                free = max(0, max_s - b_val)
                update_event_field(event_id, "seats", f"{free}/{max_s}")
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
    
    if event.get('status') == 'pending':
        warnings = validate_event_date_anomalies(event)
        if warnings:
            warning_block = "🚨 ATTENZIONE ANOMALIE DATA:\n" + "\n".join(warnings) + "\n👉 Usa /event_edit_date per correggere prima di approvare.\n\n"
            story_text = warning_block + story_text

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
    if target_msg.photo and len(new_text) > 1024:
        new_text = new_text[:1020] + "..."
    
    try:
        if target_msg.photo:
            await target_msg.edit_caption(caption=new_text, reply_markup=keyboard)
        else:
            await target_msg.edit_text(text=new_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error editing admin message: {e}")
        await update.message.reply_text("Aggiornamento salvato nel DB, ma il testo del messaggio admin è identico al precedente.")
        
    # If approved and published, or cancelled, update public channel and discussion messages
    if event['status'] in ['approved', 'cancelled']:
        await update_event_messages(context, event_id, event=event)
            
    await update.message.reply_text(f"✅ Campo '{field}' aggiornato con successo!")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message:
        return
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return

    replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    if "Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #" not in replied_text:
        return

    m = re.search(r"all'evento #(\d+)", replied_text)
    if not m:
        return

    event_id = int(m.group(1))
    raw_text = (update.message.text or "").strip()
    parts = raw_text.split()
    if not parts:
        return

    username = parts[0]
    seats = 1
    if len(parts) > 1:
        try:
            seats = int(parts[1])
        except ValueError:
            seats = 1

    ok, msg = admin_add_subscriber(event_id, username, seats=seats)
    if ok:
        await update_event_messages(context, event_id)
        event = get_event(event_id)
        await send_admin_action_notice(
            context=context,
            event=event,
            target_username=username,
            action="add",
            seats=seats,
            admin_user=update.effective_user,
        )
        await update.message.reply_text(f"✅ {msg}")
    else:
        await update.message.reply_text(f"❌ {msg}")

async def event_sub_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return

    args = context.args or []
    event_id = None
    username = None
    seats = 1

    if update.message.reply_to_message:
        event_id = extract_event_id_from_reply(update.message.reply_to_message)

    if event_id:
        if len(args) < 1:
            await update.message.reply_text(
                "Uso in risposta a un evento: <code>/event_sub_add @username [posti]</code>",
                parse_mode="HTML",
            )
            return
        username = args[0]
        if len(args) >= 2:
            try:
                seats = int(args[1])
            except ValueError:
                await update.message.reply_text("I posti devono essere un numero intero.")
                return
    else:
        if len(args) < 2:
            await update.message.reply_text(
                "Uso: <code>/event_sub_add &lt;event_id&gt; @username [posti]</code>\n"
                "Oppure rispondi a un evento con: <code>/event_sub_add @username [posti]</code>",
                parse_mode="HTML",
            )
            return
        try:
            event_id = int(args[0])
        except ValueError:
            await update.message.reply_text("L'ID evento deve essere un numero intero.")
            return
        username = args[1]
        if len(args) >= 3:
            try:
                seats = int(args[2])
            except ValueError:
                await update.message.reply_text("I posti devono essere un numero intero.")
                return

    ok, msg = admin_add_subscriber(event_id, username, seats=seats)
    if ok:
        await update_event_messages(context, event_id)
        event = get_event(event_id)
        await send_admin_action_notice(
            context=context,
            event=event,
            target_username=username,
            action="add",
            seats=seats,
            admin_user=update.effective_user,
        )
        await update.message.reply_text(f"✅ {msg}")
    else:
        await update.message.reply_text(f"❌ {msg}")

async def event_sub_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return

    args = context.args or []
    event_id = None
    username = None
    seats = None

    if update.message.reply_to_message:
        event_id = extract_event_id_from_reply(update.message.reply_to_message)

    if event_id:
        if len(args) < 1:
            await update.message.reply_text(
                "Uso in risposta a un evento: <code>/event_sub_remove @username [posti]</code>",
                parse_mode="HTML",
            )
            return
        username = args[0]
        if len(args) >= 2:
            try:
                seats = int(args[1])
            except ValueError:
                await update.message.reply_text("I posti devono essere un numero intero.")
                return
    else:
        if len(args) < 2:
            await update.message.reply_text(
                "Uso: <code>/event_sub_remove &lt;event_id&gt; @username [posti]</code>\n"
                "Oppure rispondi a un evento con: <code>/event_sub_remove @username [posti]</code>",
                parse_mode="HTML",
            )
            return
        try:
            event_id = int(args[0])
        except ValueError:
            await update.message.reply_text("L'ID evento deve essere un numero intero.")
            return
        username = args[1]
        if len(args) >= 3:
            try:
                seats = int(args[2])
            except ValueError:
                await update.message.reply_text("I posti devono essere un numero intero.")
                return

    res = get_reservation_by_user(event_id, username=username)
    seats_to_remove = seats
    if res and (seats_to_remove is None or int(seats_to_remove) > res.get('seats_booked', 0)):
        seats_to_remove = res.get('seats_booked', 1)
    if seats_to_remove is None:
        seats_to_remove = 1

    ok, msg = admin_remove_subscriber(event_id, username, seats=seats)
    if ok:
        await update_event_messages(context, event_id)
        event = get_event(event_id)
        await send_admin_action_notice(
            context=context,
            event=event,
            target_username=username,
            target_user_id=res.get('user_id') if res else None,
            action="remove",
            seats=seats_to_remove,
            admin_user=update.effective_user,
        )
        await update.message.reply_text(f"✅ {msg}")
    else:
        await update.message.reply_text(f"❌ {msg}")

