import asyncio
import os
import re
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes
import logging
from core.ai_parser import parse_event_message, GeminiQuotaError, GEMINI_DEPLETED_ALERT
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
from utils.image_utils import save_image_locally, create_collage_from_bytes, delete_local_image
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

media_groups = {}
admin_media_groups = {}

def cleanup_admin_media_cache(now=None, max_age_seconds=3600, max_entries=20):
    if now is None:
        now = asyncio.get_event_loop().time()
    expired = [k for k, v in admin_media_groups.items() if now - v.get("last_received", 0) > max_age_seconds]
    for k in expired:
        admin_media_groups.pop(k, None)
    if len(admin_media_groups) > max_entries:
        sorted_keys = sorted(admin_media_groups.keys(), key=lambda k: admin_media_groups[k].get("last_received", 0))
        for k in sorted_keys[:-max_entries]:
            admin_media_groups.pop(k, None)

async def cache_admin_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    msg_photo = getattr(msg, "photo", None)
    msg_doc = getattr(msg, "document", None)
    is_image_doc = msg_doc and getattr(msg_doc, "mime_type", "").startswith("image/")
    if not (msg_photo and isinstance(msg_photo, (list, tuple))) and not is_image_doc:
        return

    media_group_id = getattr(msg, "media_group_id", None)
    if not media_group_id or not isinstance(media_group_id, str):
        return

    now = asyncio.get_event_loop().time()
    cleanup_admin_media_cache(now)

    if media_group_id not in admin_media_groups:
        admin_media_groups[media_group_id] = {
            "images": {},
            "captions": {},
            "last_received": now,
            "pending_downloads": 0,
        }

    entry = admin_media_groups[media_group_id]
    entry["last_received"] = now

    caption = getattr(msg, "caption", None)
    if caption:
        entry["captions"][msg.message_id] = caption

    entry["pending_downloads"] += 1
    try:
        if msg_photo and isinstance(msg_photo, (list, tuple)) and len(msg_photo) > 0:
            photo_file = await msg_photo[-1].get_file()
        else:
            photo_file = await msg_doc.get_file()
        img_bytes = await photo_file.download_as_bytearray()
        entry["images"][msg.message_id] = img_bytes
    except Exception as e:
        logger.error(f"Error caching admin photo in media group {media_group_id}: {e}")
    finally:
        entry["pending_downloads"] -= 1

async def _get_media_group_data_from_cache(
    media_group_id: str,
    wait_if_missing: bool = True,
    timeout: float = 3.5,
    debounce: float = 1.0,
):
    if not media_group_id:
        return None, None

    start_wait = asyncio.get_event_loop().time()
    if wait_if_missing:
        while media_group_id not in admin_media_groups:
            if asyncio.get_event_loop().time() - start_wait > timeout:
                return None, None
            await asyncio.sleep(0.1)
    else:
        if media_group_id not in admin_media_groups:
            return None, None

    group_entry = admin_media_groups[media_group_id]
    while asyncio.get_event_loop().time() - start_wait < timeout:
        if group_entry.get("pending_downloads", 0) > 0:
            await asyncio.sleep(0.1)
            continue
        elapsed = asyncio.get_event_loop().time() - group_entry.get("last_received", 0)
        if elapsed < debounce:
            await asyncio.sleep(0.1)
            continue
        break

    image_bytes = None
    images_dict = group_entry.get("images", {})
    if images_dict:
        sorted_mids = sorted(images_dict.keys())
        cached_images = [images_dict[mid] for mid in sorted_mids if images_dict[mid]]
        if len(cached_images) > 1:
            logger.info(f"Building collage for admin media group {media_group_id} with {len(cached_images)} images.")
            image_bytes = create_collage_from_bytes(cached_images)
        elif len(cached_images) == 1:
            image_bytes = cached_images[0]

    first_caption = None
    if group_entry.get("captions"):
        for mid in sorted(group_entry["captions"].keys()):
            if group_entry["captions"][mid]:
                first_caption = group_entry["captions"][mid]
                break

    return image_bytes, first_caption

async def finalize_media_group(media_group_id: str, context: ContextTypes.DEFAULT_TYPE):
    # Wait for 2.0 seconds from the last received message in this media group
    while True:
        group = media_groups.get(media_group_id)
        if not group:
            return

        elapsed = asyncio.get_event_loop().time() - group.get("last_received", 0)
        if elapsed < 2.0:
            await asyncio.sleep(2.0 - elapsed)
            continue

        if group.get("pending_downloads", 0) > 0:
            await asyncio.sleep(0.2)
            continue

        break

    group = media_groups.pop(media_group_id, None)
    if not group:
        return

    text = group.get("text")
    images = group.get("images", [])
    message_link = group.get("message_link")
    message_id = group.get("message_id")

    if not text:
        logger.info(f"Media group {media_group_id} had no text caption. Ignoring.")
        return

    # If multiple images, create collage
    if len(images) > 1:
        logger.info(f"Building horizontal collage for event with {len(images)} images.")
        collage_bytes = create_collage_from_bytes(images)
        image_bytes_to_use = collage_bytes or images[0]
    elif len(images) == 1:
        image_bytes_to_use = images[0]
    else:
        image_bytes_to_use = None

    await handle_event_extraction(
        text=text,
        image_bytes=image_bytes_to_use,
        context=context,
        message_link=message_link,
        telegram_message_id=message_id,
        is_manual_trigger=False
    )

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_bot_paused:
        logger.info("Bot in pausa: messaggio dal canale eventi ignorato.")
        return

    message = update.message or update.channel_post
    if not message:
        return

    logger.info(f"Ricevuto messaggio dal chat_id: {message.chat_id}")

    # Ignore messages sent by the bot itself to prevent infinite loops
    if message.from_user and message.from_user.is_bot:
        return

    # If the message already has our custom booking keyboard, it's a formatted message published by us, ignore it.
    if message.reply_markup and message.reply_markup.inline_keyboard:
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data and button.callback_data.startswith(("book_", "unbook_")):
                    return

    # Se il messaggio arriva dal canale pubblico, eliminalo per evitare duplicati non formattati
    is_public_channel = str(message.chat_id) == str(PUBLIC_CHANNEL_ID)
    if is_public_channel:
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Errore durante l'eliminazione del messaggio originale: {e}")

    media_group_id = message.media_group_id
    if media_group_id:
        now = asyncio.get_event_loop().time()
        if media_group_id not in media_groups:
            media_groups[media_group_id] = {
                "images": [],
                "text": None,
                "message_link": None if is_public_channel else message.link,
                "message_id": message.message_id,
                "last_received": now,
                "pending_downloads": 0,
                "task": None,
            }

        group = media_groups[media_group_id]
        group["last_received"] = now

        text = message.text or message.caption
        if text and not group["text"]:
            group["text"] = text

        if not is_public_channel and not group["message_link"]:
            group["message_link"] = message.link

        if message.photo:
            group["pending_downloads"] += 1
            try:
                photo_file = await message.photo[-1].get_file()
                img_bytes = await photo_file.download_as_bytearray()
                group["images"].append(img_bytes)
            except Exception as e:
                logger.error(f"Error downloading photo in media group {media_group_id}: {e}")
            finally:
                group["pending_downloads"] -= 1

        if group["task"] is None:
            group["task"] = asyncio.create_task(
                finalize_media_group(media_group_id, context)
            )
        return

    # Single message (not part of an album)
    text = message.text or message.caption
    if not text:
        return

    image_bytes = None
    if message.photo:
        try:
            photo_file = await message.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
        except Exception as e:
            logger.error(f"Error downloading photo: {e}")

    message_link = None if is_public_channel else message.link
    await handle_event_extraction(text, image_bytes, context, message_link, message.message_id)
        
async def manual_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This responds to /event_process or /ep
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("Non sei autorizzato.")
        return

    # User might reply to a message or send text with it
    if update.message.reply_to_message:
        target_msg = update.message.reply_to_message

        # Check text in command vs target message
        text = None
        cmd_raw = update.message.text or update.message.caption or ""
        text_parts = cmd_raw.split(maxsplit=1)
        if len(text_parts) > 1 and text_parts[1].strip():
            text = text_parts[1].strip()

        if not text:
            text = target_msg.text or target_msg.caption

        image_bytes = None
        media_group_id = getattr(target_msg, "media_group_id", None)
        if isinstance(media_group_id, str):
            cached_image_bytes, first_caption = await _get_media_group_data_from_cache(media_group_id, wait_if_missing=False)
            if cached_image_bytes is not None:
                image_bytes = cached_image_bytes
            if not text and first_caption:
                text = first_caption

        target_photo = getattr(target_msg, "photo", None)
        if image_bytes is None and target_photo and isinstance(target_photo, (list, tuple)) and len(target_photo) > 0:
            try:
                photo_file = await target_photo[-1].get_file()
                image_bytes = await photo_file.download_as_bytearray()
            except Exception as e:
                logger.error(f"Error downloading photo in manual trigger: {e}")

        target_doc = getattr(target_msg, "document", None)
        if image_bytes is None and target_doc and getattr(target_doc, "mime_type", "").startswith("image/"):
            try:
                doc_file = await target_doc.get_file()
                image_bytes = await doc_file.download_as_bytearray()
            except Exception as e:
                logger.error(f"Error downloading document image in manual trigger: {e}")

        if not text:
            await update.message.reply_text("Nessun testo trovato nel messaggio o nel comando. Includi il testo o invia una didascalia.")
            return

        success = await handle_event_extraction(text, image_bytes, context, target_msg.link, target_msg.message_id, is_manual_trigger=True)
        if success:
            await update.message.reply_text("Processato il messaggio risposto.")
    else:
        # Check from the command message itself
        cmd_raw = update.message.text or update.message.caption or ""
        text_parts = cmd_raw.split(maxsplit=1)
        text = text_parts[1].strip() if len(text_parts) > 1 else None

        image_bytes = None
        media_group_id = getattr(update.message, "media_group_id", None)
        if isinstance(media_group_id, str):
            cached_image_bytes, first_caption = await _get_media_group_data_from_cache(media_group_id, wait_if_missing=True)
            if cached_image_bytes is not None:
                image_bytes = cached_image_bytes
            if not text and first_caption:
                text = first_caption

        msg_photo = getattr(update.message, "photo", None)
        if image_bytes is None and msg_photo and isinstance(msg_photo, (list, tuple)) and len(msg_photo) > 0:
            try:
                photo_file = await msg_photo[-1].get_file()
                image_bytes = await photo_file.download_as_bytearray()
            except Exception as e:
                logger.error(f"Error downloading photo in direct manual trigger: {e}")

        msg_doc = getattr(update.message, "document", None)
        if image_bytes is None and msg_doc and getattr(msg_doc, "mime_type", "").startswith("image/"):
            try:
                doc_file = await msg_doc.get_file()
                image_bytes = await doc_file.download_as_bytearray()
            except Exception as e:
                logger.error(f"Error downloading document image in direct manual trigger: {e}")

        if text:
            success = await handle_event_extraction(text, image_bytes, context, update.message.link, update.message.message_id, is_manual_trigger=True)
            if success:
                await update.message.reply_text("Processato il testo inviato.")
        else:
            await update.message.reply_text("Rispondi a un messaggio o fornisci il testo.")
            
async def handle_event_extraction(text, image_bytes, context, message_link=None, telegram_message_id=None, is_manual_trigger=False):
    if not text:
        return False
        
    try:
        event_data = parse_event_message(text)
    except GeminiQuotaError as e:
        logger.error(f"Gemini quota depleted during event extraction: {e}")
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=GEMINI_DEPLETED_ALERT)
        except Exception as send_err:
            logger.error(f"Failed to send quota alert to admin: {send_err}")
        return False
        
    if not event_data or event_data.get('is_event') is False:
        logger.info("Message is not an event or could not be parsed.")
        return False
        
    image_path = None
    if image_bytes:
        image_path = save_image_locally(image_bytes, DATA_DIR, event_data.get('normalized_date'))
        
    event_id = insert_event(event_data, image_path, text, message_link, telegram_message_id)
    if not event_id:
        logger.error("Failed to insert event into DB.")
        return False
        
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

    return True

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
                cb_data = getattr(btn, "callback_data", None)
                if cb_data and isinstance(cb_data, str):
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
                        "book_",
                        "unbook_",
                        "show_subs_",
                    ]:
                        if cb_data.startswith(prefix):
                            suffix = cb_data[len(prefix):]
                            try:
                                return int(suffix.split("_")[0])
                            except (IndexError, ValueError):
                                pass
    # 2. Check text or caption for #(\d+) or evento #(\d+)
    raw_content = getattr(reply_msg, "caption", None) or getattr(reply_msg, "text", None) or ""
    if isinstance(raw_content, str):
        m = re.search(r"(?:evento\s*)?#(\d+)", raw_content, re.IGNORECASE)
        if m:
            return int(m.group(1))
    # 3. Check DB telegram_message_id
    msg_id = getattr(reply_msg, "message_id", None)
    if isinstance(msg_id, int):
        ev = get_event_by_telegram_message_id(msg_id)
        if ev:
            return ev['id']
    return None

async def _extract_image_bytes_from_update(update: Update):
    if not update.message:
        return None

    # Priority 1: Check media directly attached to the current message
    media_group_id = getattr(update.message, "media_group_id", None)
    if isinstance(media_group_id, str):
        cached, _ = await _get_media_group_data_from_cache(media_group_id, wait_if_missing=True)
        if cached:
            return cached

    msg_photo = getattr(update.message, "photo", None)
    if msg_photo and isinstance(msg_photo, (list, tuple)) and len(msg_photo) > 0:
        try:
            f = await msg_photo[-1].get_file()
            return await f.download_as_bytearray()
        except Exception as e:
            logger.error(f"Error downloading photo from message: {e}")

    msg_doc = getattr(update.message, "document", None)
    if msg_doc and getattr(msg_doc, "mime_type", "").startswith("image/"):
        try:
            f = await msg_doc.get_file()
            return await f.download_as_bytearray()
        except Exception as e:
            logger.error(f"Error downloading document image from message: {e}")

    # Priority 2: Check media in the replied-to message
    if update.message.reply_to_message:
        reply_mgid = getattr(update.message.reply_to_message, "media_group_id", None)
        if isinstance(reply_mgid, str):
            cached, _ = await _get_media_group_data_from_cache(reply_mgid, wait_if_missing=False)
            if cached:
                return cached

        reply_photo = getattr(update.message.reply_to_message, "photo", None)
        if reply_photo and isinstance(reply_photo, (list, tuple)) and len(reply_photo) > 0:
            try:
                f = await reply_photo[-1].get_file()
                return await f.download_as_bytearray()
            except Exception as e:
                logger.error(f"Error downloading photo from reply: {e}")

        reply_doc = getattr(update.message.reply_to_message, "document", None)
        if reply_doc and getattr(reply_doc, "mime_type", "").startswith("image/"):
            try:
                f = await reply_doc.get_file()
                return await f.download_as_bytearray()
            except Exception as e:
                logger.error(f"Error downloading document image from reply: {e}")

    return None

async def event_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return
        
    text_raw = update.message.text or update.message.caption or ""
    text_parts = text_raw.split(maxsplit=1)
    if not text_parts:
        return
    cmd = text_parts[0].lower().split("@")[0]
    value = text_parts[1].strip() if len(text_parts) > 1 else ""
    
    field_map = {
        "/event_edit_title": "title",
        "/event_edit_date": "date",
        "/event_edit_normalized_date": "normalized_date",
        "/event_edit_system": "system",
        "/event_edit_seats": "seats",
        "/event_edit_booked": "booked_seats",
        "/event_edit_host": "host",
        "/event_edit_extra": "extra_info",
        "/event_edit_description": "description",
        "/event_edit_image": "image_path"
    }
    
    field = field_map.get(cmd)
    if not field:
        return

    event_id = None
    target_msg = None

    if cmd == "/event_edit_image" and value.isdigit():
        event_id = int(value)
        if update.message.reply_to_message and extract_event_id_from_reply(update.message.reply_to_message) == event_id:
            target_msg = update.message.reply_to_message

    if not event_id:
        if not update.message.reply_to_message:
            await update.message.reply_text("Rispondi al messaggio dell'evento che vuoi modificare.")
            return

        target_msg = update.message.reply_to_message
        event_id = extract_event_id_from_reply(target_msg)

    if not event_id:
        await update.message.reply_text("Impossibile determinare l'ID dell'evento da questo messaggio. Assicurati di rispondere al messaggio con i pulsanti (Publish, Discard, Cancel).")
        return

    current_event = get_event(event_id)
    if not current_event:
        await update.message.reply_text("Evento non trovato nel database (potrebbe essere stato eliminato o scartato).")
        return
        
    if field == "image_path":
        image_bytes = await _extract_image_bytes_from_update(update)
        if not image_bytes:
            await update.message.reply_text("Devi allegare un'immagine (o un album) a questo comando, oppure rispondere a un'immagine con il comando.")
            return

        old_image_path = current_event.get("image_path")
        new_image_path = save_image_locally(image_bytes, DATA_DIR, current_event.get("normalized_date"))
        if not new_image_path:
            await update.message.reply_text("Errore durante il salvataggio dell'immagine.")
            return

        success = update_event_field(event_id, "image_path", new_image_path)
        if success and old_image_path and old_image_path != new_image_path:
            delete_local_image(old_image_path)
    elif field == "date":
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
    if target_msg:
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
        if getattr(target_msg, "photo", None) and len(new_text) > 1024:
            new_text = new_text[:1020] + "..."
        
        try:
            if field == "image_path" and getattr(target_msg, "photo", None) and event.get('image_path') and os.path.exists(event['image_path']):
                with open(event['image_path'], 'rb') as f:
                    await target_msg.edit_media(
                        media=InputMediaPhoto(media=f, caption=new_text),
                        reply_markup=keyboard
                    )
            elif getattr(target_msg, "photo", None):
                await target_msg.edit_caption(caption=new_text, reply_markup=keyboard)
            else:
                await target_msg.edit_text(text=new_text, reply_markup=keyboard)
        except Exception as e:
            if "not modified" in str(e).lower() or "message is not modified" in str(e).lower():
                pass
            else:
                logger.error(f"Error editing admin message: {e}")
            
    # If approved and published, or cancelled, update public channel and discussion messages
    if event['status'] in ['approved', 'cancelled']:
        await update_event_messages(context, event_id, event=event, update_image=(field == "image_path"))
            
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

