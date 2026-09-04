from telegram import Update
from telegram.ext import ContextTypes
import logging
from core.db import update_event_status, get_event, get_pending_events_for_recap, book_seat, unbook_seat, update_telegram_message_info
from utils.image_utils import delete_local_image
from core.config import PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID
from utils.templates import format_public_event_message
from bot.keyboards import get_event_booking_keyboard

logger = logging.getLogger(__name__)

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("publish_event_"):
        event_id = int(data.split("_")[2])
        update_event_status(event_id, "approved")
        
        from bot.keyboards import get_cancel_only_keyboard
        keyboard = get_cancel_only_keyboard(event_id)
        
        try:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ APPROVATO", reply_markup=keyboard)
        except:
            await query.edit_message_text(text=f"{query.message.text}\n\n✅ APPROVATO", reply_markup=keyboard)
            
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
                # # 1. Upload to WP to get a public URL
                # media_info = upload_media(story_image_path)
                # if media_info and media_info.get('source_url'):
                #     public_url = media_info.get('source_url')
                #     
                #     # 2. Publish to IG
                #     success, msg = await publish_instagram_story(public_url)
                #     if success:
                #         await context.bot.send_message(chat_id=query.message.chat_id, text=f"✅ {msg}")
                #     else:
                #         await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Errore Instagram: {msg}")
                # else:
                #     await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Errore: Impossibile ottenere un URL pubblico per l'immagine (Upload WP fallito).")
                
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
        event_id = int(data.split("_")[2])
        update_event_status(event_id, "discarded")
        event = get_event(event_id)
        if event and event['image_path']:
            delete_local_image(event['image_path'])
        try:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ SCARTATO")
        except:
            await query.edit_message_text(text=f"{query.message.text}\n\n❌ SCARTATO")
            
    elif data.startswith("cancel_event_"):
        event_id = int(data.split("_")[2])
        update_event_status(event_id, "cancelled")
        try:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ ANNULLATO")
        except:
            await query.edit_message_text(text=f"{query.message.text}\n\n⚠️ ANNULLATO")
            
        event = get_event(event_id)
        if event and event.get('telegram_message_id') and PUBLIC_CHANNEL_ID:
            public_text = format_public_event_message(event)
            try:
                if event.get('image_path'):
                    await context.bot.edit_message_caption(
                        chat_id=PUBLIC_CHANNEL_ID,
                        message_id=event['telegram_message_id'],
                        caption=public_text,
                        reply_markup=None
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=PUBLIC_CHANNEL_ID,
                        message_id=event['telegram_message_id'],
                        text=public_text,
                        reply_markup=None
                    )
            except Exception as e:
                logger.error(f"Error updating public message on cancel: {e}")
        
    elif data.startswith("publish_recap_"):
        # Publish the message to the public channel here
        if PUBLIC_CHANNEL_ID:
            await context.bot.copy_message(chat_id=PUBLIC_CHANNEL_ID, from_chat_id=query.message.chat_id, message_id=query.message.message_id)
        try:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ RECAP PUBLISHED")
        except:
            await query.edit_message_text(text=f"{query.message.text}\n\n✅ RECAP PUBLISHED")
            
        # Generazione articolo WordPress post-pubblicazione
        date_str = data.split("_")[2]
        events = get_pending_events_for_recap(date_str)
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
            
            from core.ai_parser import generate_wordpress_article
            from core.wordpress import publish_article, upload_media
            from utils.image_utils import create_collage
            from core.config import DATA_DIR
            
            # Recreate collage and upload images
            image_paths = [ev['image_path'] for ev in events if ev['image_path']]
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
                        
            wp_content = generate_wordpress_article(recap_text, events)
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
        try:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ RECAP SCARTATO")
        except:
            await query.edit_message_text(text=f"{query.message.text}\n\n❌ RECAP SCARTATO")
            
    elif data.startswith("publish_wp_"):
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
                
    elif data.startswith("book_"):
        event_id = int(data.split("_")[1])
        user = query.from_user
        username = user.username or user.first_name
        
        success, msg = book_seat(event_id, user.id, username)
        await query.answer(msg, show_alert=not success)
        
        if success:
            event = get_event(event_id)
            if event:
                public_text = format_public_event_message(event)
                pub_keyboard = get_event_booking_keyboard(event_id)
                try:
                    # Se cliccato nel canale originale, query.message è il messaggio del canale.
                    # Se cliccato nel gruppo di discussione, query.message è il messaggio con i bottoni.
                    # Per essere sicuri, aggiorniamo SEMPRE il messaggio nel PUBLIC_CHANNEL_ID.
                    if PUBLIC_CHANNEL_ID and event.get('telegram_message_id'):
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
                            logger.error(f"Error updating public channel message on book: {e}")
                            # Fallback to updating the current message if it's the original one
                            if str(query.message.chat_id) == str(PUBLIC_CHANNEL_ID):
                                if event.get('image_path'):
                                    await query.edit_message_caption(caption=public_text, reply_markup=pub_keyboard)
                                else:
                                    await query.edit_message_text(text=public_text, reply_markup=pub_keyboard)
                except Exception as e:
                    logger.error(f"Error updating message on book: {e}")
                
                # Send a notification reply
                try:
                    notify_chat = int(DISCUSSION_GROUP_ID) if DISCUSSION_GROUP_ID else query.message.chat_id
                    await context.bot.send_message(
                        chat_id=notify_chat,
                        text=f"✅ @{username} ha prenotato 1 posto per: {event.get('title', 'Evento')}\n{event.get('message_link', '')}",
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Error sending notification on book: {e}")

    elif data.startswith("unbook_"):
        event_id = int(data.split("_")[1])
        user = query.from_user
        username = user.username or user.first_name
        
        success, msg = unbook_seat(event_id, user.id)
        await query.answer(msg, show_alert=not success)
        
        if success:
            event = get_event(event_id)
            if event:
                public_text = format_public_event_message(event)
                pub_keyboard = get_event_booking_keyboard(event_id)
                try:
                    # Se cliccato nel canale originale, query.message è il messaggio del canale.
                    # Se cliccato nel gruppo di discussione, query.message è il messaggio con i bottoni.
                    # Per essere sicuri, aggiorniamo SEMPRE il messaggio nel PUBLIC_CHANNEL_ID.
                    if PUBLIC_CHANNEL_ID and event.get('telegram_message_id'):
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
                            logger.error(f"Error updating public channel message on unbook: {e}")
                            # Fallback to updating the current message if it's the original one
                            if str(query.message.chat_id) == str(PUBLIC_CHANNEL_ID):
                                if event.get('image_path'):
                                    await query.edit_message_caption(caption=public_text, reply_markup=pub_keyboard)
                                else:
                                    await query.edit_message_text(text=public_text, reply_markup=pub_keyboard)
                except Exception as e:
                    logger.error(f"Error updating message on unbook: {e}")
                
                # Send a notification reply
                try:
                    notify_chat = int(DISCUSSION_GROUP_ID) if DISCUSSION_GROUP_ID else query.message.chat_id
                    await context.bot.send_message(
                        chat_id=notify_chat,
                        text=f"❌ @{username} ha liberato 1 posto per: {event.get('title', 'Evento')}\n{event.get('message_link', '')}",
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Error sending notification on unbook: {e}")

