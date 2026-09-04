import html
import logging
from telegram import Update
from telegram.ext import ContextTypes
from core.db import (
    update_event_status,
    delete_event,
    get_event,
    get_pending_events_for_recap,
    update_telegram_message_info,
    get_reservations_for_event,
    get_reservation,
    admin_add_seat,
    admin_remove_seat,
    admin_add_subscriber,
    admin_remove_subscriber,
)
from utils.image_utils import delete_local_image
from core.config import PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID
from utils.templates import format_public_event_message
from bot.keyboards import (
    get_event_booking_keyboard,
    get_approved_event_keyboard,
    get_cancelled_event_keyboard,
    get_subscribers_management_keyboard,
)
from bot.service import (
    update_event_messages,
    handle_seat_booking,
    handle_seat_unbooking,
    send_admin_action_notice,
    format_event_title_link,
)

logger = logging.getLogger(__name__)

def update_status_suffix(msg_text, new_suffix):
    text = msg_text or ""
    for s in ["\n\n✅ APPROVATO", "\n\n⚠️ ANNULLATO", "\n\n✅ RIATTIVATO", "\n\n❌ SCARTATO"]:
        if text.endswith(s):
            text = text[:-len(s)]
    return f"{text}{new_suffix}"

def format_subscribers_tags(reservations):
    tags = []
    seen = set()
    for res in reservations:
        uname = (res.get('username') or '').strip()
        uid = res.get('user_id')
        if uname:
            tag = uname if uname.startswith('@') else f"@{uname}"
        elif uid:
            tag = f'<a href="tg://user?id={uid}">Utente</a>'
        else:
            continue
            
        if tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return ", ".join(tags)

async def send_cancellation_notice(context, event):
    if not DISCUSSION_GROUP_ID:
        return
    try:
        disc_chat_id = int(DISCUSSION_GROUP_ID)
    except ValueError:
        return

    event_id = event['id']
    event_display = format_event_title_link(event)
    reservations = get_reservations_for_event(event_id)
    tags_str = format_subscribers_tags(reservations)
    
    if tags_str:
        text = f"⚠️ <b>ATTENZIONE:</b> L'evento {event_display} è stato <b>ANNULLATO</b>!\n\nIscritti avvisati: {tags_str}"
    else:
        text = f"⚠️ <b>ATTENZIONE:</b> L'evento {event_display} è stato <b>ANNULLATO</b>!"
        
    reply_to = event.get('discussion_message_id')
    try:
        if reply_to:
            await context.bot.send_message(chat_id=disc_chat_id, text=text, reply_to_message_id=reply_to, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await context.bot.send_message(chat_id=disc_chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Error sending cancellation notice to discussion group with reply_to={reply_to}: {e}")
        try:
            await context.bot.send_message(chat_id=disc_chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e2:
            logger.error(f"Error sending cancellation notice directly to discussion group: {e2}")

async def send_reactivation_notice(context, event):
    if not DISCUSSION_GROUP_ID:
        return
    try:
        disc_chat_id = int(DISCUSSION_GROUP_ID)
    except ValueError:
        return

    event_id = event['id']
    event_display = format_event_title_link(event)
    reservations = get_reservations_for_event(event_id)
    tags_str = format_subscribers_tags(reservations)
    
    if tags_str:
        text = f"✅ <b>ATTENZIONE:</b> L'evento {event_display} è stato <b>RIATTIVATO</b>!\n\nIscritti prenotati: {tags_str}"
    else:
        text = f"✅ <b>ATTENZIONE:</b> L'evento {event_display} è stato <b>RIATTIVATO</b>!"
        
    reply_to = event.get('discussion_message_id')
    try:
        if reply_to:
            await context.bot.send_message(chat_id=disc_chat_id, text=text, reply_to_message_id=reply_to, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await context.bot.send_message(chat_id=disc_chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Error sending reactivation notice to discussion group with reply_to={reply_to}: {e}")
        try:
            await context.bot.send_message(chat_id=disc_chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e2:
            logger.error(f"Error sending reactivation notice directly to discussion group: {e2}")

def format_subscribers_management_view(event, reservations):
    event_display = format_event_title_link(event)
    booked = int(event.get('booked_seats', 0) or 0)
    max_s = event.get('max_seats')
    max_str = str(max_s) if max_s is not None else "Nessun limite"
    
    text = (
        f"👥 <b>Gestione Iscritti</b>\n"
        f"📌 {event_display}\n"
        f"🪑 Posti occupati: <b>{booked}/{max_str}</b>\n\n"
    )
    
    if not reservations:
        text += "<i>Nessun utente iscritto al momento.</i>\n"
    else:
        text += "<b>Iscritti:</b>\n"
        for i, s in enumerate(reservations, 1):
            uname = s.get('username') or f"ID:{s.get('user_id')}"
            if not uname.startswith('@') and not uname.startswith('ID:'):
                uname = f"@{uname}"
            seats = s.get('seats_booked', 1)
            posti_str = "posto" if seats == 1 else "posti"
            text += f"{i}. <b>{html.escape(uname)}</b> — {seats} {posti_str}\n"
            
    text += (
        f"\n<i>Modifica con i tasti sotto oppure invia:</i>\n"
        f"<code>/event_sub_add {event['id']} @username [posti]</code>\n"
        f"<code>/event_sub_remove {event['id']} @username [posti]</code>"
    )
    return text

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    data = query.data
    
    if data.startswith("publish_event_"):
        await query.answer()
        event_id = int(data.split("_")[2])
        update_event_status(event_id, "approved")
        
        keyboard = get_approved_event_keyboard(event_id)
        msg_text = query.message.caption or query.message.text or ""
        new_text = update_status_suffix(msg_text, "\n\n✅ APPROVATO")
        
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=new_text, reply_markup=keyboard)
            else:
                await query.edit_message_text(text=new_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error updating admin message on publish: {e}")
            
        # IG Publishing flow
        event = get_event(event_id)
        if event:
            # Publish to public channel
            if PUBLIC_CHANNEL_ID:
                try:
                    public_text = format_public_event_message(event)
                    pub_keyboard = get_event_booking_keyboard(event_id)
                    if event.get('image_path'):
                        with open(event['image_path'], 'rb') as f:
                            pub_msg = await context.bot.send_photo(
                                chat_id=PUBLIC_CHANNEL_ID,
                                photo=f,
                                caption=public_text,
                                reply_markup=pub_keyboard
                            )
                    else:
                        pub_msg = await context.bot.send_message(
                            chat_id=PUBLIC_CHANNEL_ID,
                            text=public_text,
                            reply_markup=pub_keyboard
                        )
                    update_telegram_message_info(event_id, pub_msg.message_id, pub_msg.link)
                except Exception as e:
                    logger.error(f"Error publishing to public channel: {e}")
            
            await context.bot.send_message(chat_id=query.message.chat_id, text="⏳ Generazione e pubblicazione Storia Instagram in corso...")
            
            from utils.image_utils import create_story_image
            from core.config import DATA_DIR
            from core.wordpress import upload_media
            from core.instagram import publish_instagram_story
            import json
            
            story_image_path = create_story_image(event, event.get('image_path'), DATA_DIR)
            
            if story_image_path:
                # [TEMPORARILY DISABLED] IG Publishing flow
                # Send the generated image back to the admin chat so we can review it!
                with open(story_image_path, 'rb') as f:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id, 
                        photo=f, 
                        caption="✅ Immagine Storia generata (Pubblicazione IG disabilitata temporaneamente per test)."
                    )
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Errore durante la generazione dell'immagine della storia.")
        
    elif data.startswith("discard_event_"):
        await query.answer()
        event_id = int(data.split("_")[2])
        event = get_event(event_id)
        if event and event.get('image_path'):
            delete_local_image(event['image_path'])
        delete_event(event_id)
        msg_text = query.message.caption or query.message.text or ""
        new_text = update_status_suffix(msg_text, "\n\n❌ SCARTATO")
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=new_text)
            else:
                await query.edit_message_text(text=new_text)
        except Exception as e:
            logger.error(f"Error updating admin message on discard: {e}")
            
    elif data.startswith("cancel_event_"):
        await query.answer()
        event_id = int(data.split("_")[2])
        update_event_status(event_id, "cancelled")
        
        keyboard = get_cancelled_event_keyboard(event_id)
        msg_text = query.message.caption or query.message.text or ""
        new_text = update_status_suffix(msg_text, "\n\n⚠️ ANNULLATO")
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=new_text, reply_markup=keyboard)
            else:
                await query.edit_message_text(text=new_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error updating admin message on cancel: {e}")
            
        event = get_event(event_id)
        if event:
            await update_event_messages(context, event_id, event=event, current_query=query)
            await send_cancellation_notice(context, event)

    elif data.startswith("reactivate_event_"):
        await query.answer("Evento riattivato!")
        event_id = int(data.split("_")[2])
        update_event_status(event_id, "approved")
        
        keyboard = get_approved_event_keyboard(event_id)
        msg_text = query.message.caption or query.message.text or ""
        new_text = update_status_suffix(msg_text, "\n\n✅ APPROVATO")
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=new_text, reply_markup=keyboard)
            else:
                await query.edit_message_text(text=new_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error updating admin message on reactivate: {e}")
            
        event = get_event(event_id)
        if event:
            await update_event_messages(context, event_id, event=event, current_query=query)
            await send_reactivation_notice(context, event)
        
    elif data.startswith("publish_recap_"):
        await query.answer()
        # Publish the message to the public channel here
        date_str = data.split("_")[2]
        events = get_pending_events_for_recap(date_str)
        pub_msg = None

        if PUBLIC_CHANNEL_ID:
            pub_msg = await context.bot.copy_message(chat_id=PUBLIC_CHANNEL_ID, from_chat_id=query.message.chat_id, message_id=query.message.message_id)

            if pub_msg:
                import bot.handlers
                bot.handlers.last_recap_message_id = pub_msg.message_id
                bot.handlers.last_recap_events = events

        try:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ RECAP PUBLISHED")
        except:
            await query.edit_message_text(text=f"{query.message.text}\n\n✅ RECAP PUBLISHED")
            
        # Generazione articolo WordPress post-pubblicazione
        if events:
            await context.bot.send_message(chat_id=query.message.chat_id, text="⏳ Generazione della bozza su WordPress in corso...")
            
            from datetime import datetime
            try:
                now = datetime.strptime(date_str, "%d-%m-%Y")
            except ValueError:
                now = datetime.now()
                
            days_it = {
                "Monday": "Lunedì", "Tuesday": "Martedì", "Wednesday": "Mercoledì",
                "Thursday": "Giovedì", "Friday": "Venerdì", "Saturday": "Sabato", "Sunday": "Domenica"
            }
            day_str = days_it.get(now.strftime("%A"), now.strftime("%A"))
            
            from utils.templates import recap_generate_text
            recap_text = recap_generate_text(day_str, date_str, events)
            
            from core.ai_parser import generate_wordpress_article, GeminiQuotaError, GEMINI_DEPLETED_ALERT
            from core.wordpress import publish_article, upload_media
            from utils.image_utils import create_collage
            from core.config import DATA_DIR
            
            # Recreate collage and upload images
            image_paths = [ev['image_path'] for ev in events if ev.get('image_path')]
            collage_path = create_collage(image_paths, DATA_DIR, date_str)
            
            # ----------------------------------------------------
            # GENERATE RECAP INSTAGRAM STORY
            # ----------------------------------------------------
            from utils.image_utils import create_recap_story_image
            recap_story_path = create_recap_story_image(events, collage_path, date_str, DATA_DIR)
            
            if recap_story_path:
                with open(recap_story_path, 'rb') as f:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id, 
                        photo=f, 
                        caption="✅ Immagine Storia RECAP generata (Pubblicazione IG disabilitata temporaneamente per test)."
                    )
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Errore durante la generazione della Storia Recap.")
            # ----------------------------------------------------
            
            for ev in events:
                if ev.get('image_path'):
                    media_info = upload_media(ev['image_path'])
                    if media_info:
                        ev['wp_media_url'] = media_info.get('source_url')
                        
            try:
                wp_content = generate_wordpress_article(recap_text, events)
            except GeminiQuotaError as e:
                logger.error(f"Gemini quota depleted during WP article generation: {e}")
                wp_content = None
                try:
                    await context.bot.send_message(chat_id=query.message.chat_id, text=GEMINI_DEPLETED_ALERT)
                except Exception as send_err:
                    logger.error(f"Failed to send quota alert to admin: {send_err}")
            if wp_content:
                wp_title = f"Eventi della Serata: {day_str} {date_str}"
                media_id = None
                if collage_path:
                    collage_info = upload_media(collage_path)
                    if collage_info:
                        media_id = collage_info.get('id')
                
                wp_link, post_id = publish_article(wp_title, wp_content, media_id=media_id)
                if wp_link and post_id:
                    # Update DB with WP info
                    from core.db import update_events_wp_info
                    event_ids = [ev['id'] for ev in events]
                    update_events_wp_info(event_ids, post_id, wp_link)
                    
                    from bot.keyboards import get_wp_publish_keyboard
                    wp_keyboard = get_wp_publish_keyboard(post_id)
                    await context.bot.send_message(
                        chat_id=query.message.chat_id, 
                        text=f"✅ Bozza articolo creata su WordPress:\n{wp_link}\n\nClicca qui sotto per pubblicarla pubblicamente.",
                        reply_markup=wp_keyboard
                    )
                else:
                    await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Errore durante la creazione dell'articolo su WordPress.")
        
    elif data.startswith("discard_recap_"):
        await query.answer()
        try:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ RECAP SCARTATO")
        except:
            await query.edit_message_text(text=f"{query.message.text}\n\n❌ RECAP SCARTATO")
            
    elif data.startswith("publish_wp_"):
        await query.answer()
        post_id = int(data.split("_")[2])
        from core.wordpress import update_article_status
        success = update_article_status(post_id, "publish")
        
        if success:
            try:
                await query.edit_message_text(text=f"{query.message.text}\n\n✅ ARTICOLO PUBBLICATO PUBBLICAMENTE!")
            except:
                pass
        else:
            try:
                await query.edit_message_text(text=f"{query.message.text}\n\n❌ Errore durante la pubblicazione dell'articolo.")
            except:
                pass

    elif data.startswith("full_"):
        event_id = int(data.split("_")[1])
        event = get_event(event_id)
        if not event:
            try:
                await query.answer("Evento non trovato.", show_alert=True)
            except Exception:
                pass
            return

        max_s = event.get('max_seats')
        booked = int(event.get('booked_seats', 0) or 0)
        is_full = (max_s is not None) and (booked >= max_s)

        if is_full:
            try:
                await query.answer("I posti per questo tavolo sono esauriti!", show_alert=True)
            except Exception:
                pass
            await update_event_messages(context, event_id, event=event, current_query=query)
        else:
            await handle_seat_booking(event_id, query.from_user, query, context)

    elif data.startswith("book_"):
        event_id = int(data.split("_")[1])
        await handle_seat_booking(event_id, query.from_user, query, context)

    elif data.startswith("unbook_"):
        event_id = int(data.split("_")[1])
        await handle_seat_unbooking(event_id, query.from_user, query, context)
    elif data.startswith("manage_subs_"):
        await query.answer()
        event_id = int(data.split("_")[2])
        event = get_event(event_id)
        if not event:
            await query.answer("Evento non trovato.", show_alert=True)
            return
            
        reservations = get_reservations_for_event(event_id)
        text = format_subscribers_management_view(event, reservations)
        keyboard = get_subscribers_management_keyboard(event_id, reservations)
        
        # If clicked from the management message itself (e.g. Aggiorna)
        if query.message and query.message.text and "Gestione Iscritti" in query.message.text:
            try:
                await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Edit message unchanged on refresh: {e}")
        else:
            # Clicked from the event card: send management interface as reply
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                reply_markup=keyboard,
                reply_to_message_id=query.message.message_id,
                parse_mode="HTML"
            )

    elif data.startswith("sub_inc_"):
        parts = data.split("_")
        event_id = int(parts[2])
        res_id = int(parts[3])
        res = get_reservation(res_id)
        ok, msg = admin_add_seat(event_id, res_id)
        if not ok:
            await query.answer(msg, show_alert=True)
        else:
            await query.answer(msg)
            await update_event_messages(context, event_id)
            event = get_event(event_id)
            if res:
                await send_admin_action_notice(
                    context=context,
                    event=event,
                    target_username=res.get('username'),
                    target_user_id=res.get('user_id'),
                    action="add",
                    seats=1,
                    admin_user=query.from_user,
                )
            reservations = get_reservations_for_event(event_id)
            text = format_subscribers_management_view(event, reservations)
            keyboard = get_subscribers_management_keyboard(event_id, reservations)
            try:
                await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass

    elif data.startswith("sub_dec_"):
        parts = data.split("_")
        event_id = int(parts[2])
        res_id = int(parts[3])
        res = get_reservation(res_id)
        ok, msg = admin_remove_seat(event_id, res_id)
        if not ok:
            await query.answer(msg, show_alert=True)
        else:
            await query.answer(msg)
            await update_event_messages(context, event_id)
            event = get_event(event_id)
            if res:
                await send_admin_action_notice(
                    context=context,
                    event=event,
                    target_username=res.get('username'),
                    target_user_id=res.get('user_id'),
                    action="remove",
                    seats=1,
                    admin_user=query.from_user,
                )
            reservations = get_reservations_for_event(event_id)
            text = format_subscribers_management_view(event, reservations)
            keyboard = get_subscribers_management_keyboard(event_id, reservations)
            try:
                await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass

    elif data.startswith("sub_addnew_"):
        await query.answer()
        event_id = int(data.split("_")[2])
        from telegram import ForceReply
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✏️ Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #{event_id} (es. <code>@mario</code> oppure <code>@mario 2</code>):\nOppure usa: <code>/event_sub_add {event_id} @username [posti]</code>",
            reply_markup=ForceReply(selective=True),
            parse_mode="HTML"
        )

    elif data.startswith("close_subs_"):
        await query.answer("Chiuso.")
        try:
            await query.message.delete()
        except Exception:
            pass


