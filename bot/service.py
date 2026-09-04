import html
import os
import logging
from telegram import InputMediaPhoto
from core.db import get_event, update_discussion_message_info, book_seat, unbook_seat, get_user_conflicting_events
from core.config import PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID
from utils.templates import format_public_event_message, format_event_title_link
from bot.keyboards import get_event_booking_keyboard

logger = logging.getLogger(__name__)

async def update_event_messages(context, event_id, event=None, current_query=None, update_image=False):
    """
    Synchronizes public messages for an event:
    1. Updates the announcement message in PUBLIC_CHANNEL_ID (caption/text and keyboard).
    2. Updates the booking reply message in the discussion group (keyboard).
    """
    if event is None:
        event = get_event(event_id)
    if not event:
        return

    public_text = format_public_event_message(event)
    pub_keyboard = None
    if event.get('status') == 'approved':
        pub_keyboard = get_event_booking_keyboard(event_id, event=event)

    # 1. Update message in PUBLIC_CHANNEL_ID
    if PUBLIC_CHANNEL_ID and event.get('telegram_message_id'):
        try:
            if update_image and event.get('image_path') and os.path.exists(event['image_path']):
                try:
                    with open(event['image_path'], 'rb') as f:
                        await context.bot.edit_message_media(
                            chat_id=PUBLIC_CHANNEL_ID,
                            message_id=event['telegram_message_id'],
                            media=InputMediaPhoto(media=f, caption=public_text),
                            reply_markup=pub_keyboard
                        )
                except Exception as e:
                    logger.error(f"Error editing message media in public channel for event {event_id}: {e}")
            elif event.get('image_path'):
                try:
                    await context.bot.edit_message_caption(
                        chat_id=PUBLIC_CHANNEL_ID,
                        message_id=event['telegram_message_id'],
                        caption=public_text,
                        reply_markup=pub_keyboard
                    )
                except Exception as e:
                    if "not modified" not in str(e).lower():
                        await context.bot.edit_message_text(
                            chat_id=PUBLIC_CHANNEL_ID,
                            message_id=event['telegram_message_id'],
                            text=public_text,
                            reply_markup=pub_keyboard
                        )
            else:
                try:
                    await context.bot.edit_message_text(
                        chat_id=PUBLIC_CHANNEL_ID,
                        message_id=event['telegram_message_id'],
                        text=public_text,
                        reply_markup=pub_keyboard
                    )
                except Exception as e:
                    if "not modified" not in str(e).lower():
                        await context.bot.edit_message_caption(
                            chat_id=PUBLIC_CHANNEL_ID,
                            message_id=event['telegram_message_id'],
                            caption=public_text,
                            reply_markup=pub_keyboard
                        )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error updating public channel message for event {event_id}: {e}")

    # 2. Update message in discussion group
    disc_msg_id = event.get('discussion_message_id')
    disc_chat_id = event.get('discussion_chat_id') or DISCUSSION_GROUP_ID

    # If current_query is from discussion group, capture/store the IDs
    query_edited = False
    if current_query and current_query.message:
        if str(current_query.message.chat_id) != str(PUBLIC_CHANNEL_ID):
            disc_msg_id = current_query.message.message_id
            disc_chat_id = current_query.message.chat_id
            update_discussion_message_info(event_id, disc_msg_id, disc_chat_id)
            try:
                await current_query.edit_message_reply_markup(reply_markup=pub_keyboard)
                query_edited = True
            except Exception as e:
                if "not modified" not in str(e).lower():
                    logger.debug(f"Could not edit reply markup on current query message: {e}")

    if disc_msg_id and disc_chat_id and not query_edited:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=int(disc_chat_id),
                message_id=int(disc_msg_id),
                reply_markup=pub_keyboard
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error updating discussion reply markup for event {event_id}: {e}")

def format_user_mention(user):
    clean_username = (getattr(user, 'username', None) or '').strip().lstrip('@')
    if clean_username:
        return f"@{clean_username}"
    elif getattr(user, 'first_name', None):
        name = html.escape(user.first_name)
        user_id = getattr(user, 'id', None)
        if user_id:
            return f'<a href="tg://user?id={user_id}">{name}</a>'
        return name
    elif getattr(user, 'id', None):
        return f'<a href="tg://user?id={user.id}">Utente</a>'
    return "Utente"

def format_conflict_warning_message(user, conflicting_events):
    user_tag = format_user_mention(user)

    count = len(conflicting_events)
    if count == 1:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto a un altro evento per la stessa data:\n"
    else:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto ad altri {count} eventi per la stessa data:\n"

    items = []
    for ev in conflicting_events:
        title_display = format_event_title_link(ev)
        sys_val = ev.get('system')
        sys_str = f" (<i>{html.escape(sys_val)}</i>)" if sys_val else ""
        items.append(f"• {title_display}{sys_str}")

    list_str = "\n".join(items)
    footer = (
        "\n\n<i>La tua prenotazione è stata registrata regolarmente. "
        "Se necessario, ricordati di liberare il posto dall'evento a cui non parteciperai!</i>"
    )
    return f"{header}{list_str}{footer}"

async def send_conflict_warning(
    context,
    event,
    user,
    conflicting_events,
    notify_chat,
    reply_to_message_id=None
):
    if not conflicting_events:
        return

    warning_text = format_conflict_warning_message(user, conflicting_events)

    try:
        if reply_to_message_id:
            try:
                await context.bot.send_message(
                    chat_id=notify_chat,
                    text=warning_text,
                    reply_to_message_id=reply_to_message_id,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                return
            except Exception as e_reply:
                logger.warning(f"Failed to reply to discussion message {reply_to_message_id} with conflict warning: {e_reply}")

        await context.bot.send_message(
            chat_id=notify_chat,
            text=warning_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error sending conflict warning message: {e}")

async def handle_seat_booking(event_id, user, query, context):
    username = user.username or user.first_name
    success, msg = book_seat(event_id, user.id, username)
    try:
        await query.answer(msg, show_alert=not success)
    except Exception as e:
        logger.debug(f"Error answering callback query: {e}")

    if success:
        event = get_event(event_id)
        if event:
            await update_event_messages(context, event_id, event=event, current_query=query)

            notify_chat = int(DISCUSSION_GROUP_ID) if DISCUSSION_GROUP_ID else query.message.chat_id
            disc_msg_id = event.get('discussion_message_id')
            reply_id = None
            if query.message and query.message.chat_id == notify_chat:
                reply_id = query.message.message_id
            elif disc_msg_id:
                reply_id = int(disc_msg_id)

            # Send a notification reply
            try:
                user_tag = format_user_mention(user)
                event_display = format_event_title_link(event)
                booked_text = f"✅ {user_tag} ha prenotato 1 posto per: {event_display}"
                if reply_id:
                    try:
                        await context.bot.send_message(
                            chat_id=notify_chat,
                            text=booked_text,
                            reply_to_message_id=reply_id,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    except Exception as e_reply:
                        logger.warning(f"Failed to reply to discussion message {reply_id} on book: {e_reply}")
                        await context.bot.send_message(
                            chat_id=notify_chat,
                            text=booked_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                else:
                    await context.bot.send_message(
                        chat_id=notify_chat,
                        text=booked_text,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
            except Exception as e:
                logger.error(f"Error sending notification on book: {e}")

            # Check if user is already subscribed to other valid events on that same day
            try:
                conflicting_events = get_user_conflicting_events(
                    event_id=event_id,
                    user_id=user.id,
                    username=user.username or user.first_name
                )
                if conflicting_events:
                    await send_conflict_warning(
                        context=context,
                        event=event,
                        user=user,
                        conflicting_events=conflicting_events,
                        notify_chat=notify_chat,
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.error(f"Error checking or sending conflict warning: {e}")

async def handle_seat_unbooking(event_id, user, query, context):
    username = user.username or user.first_name
    success, msg = unbook_seat(event_id, user.id, username=username)
    try:
        await query.answer(msg, show_alert=not success)
    except Exception as e:
        logger.debug(f"Error answering callback query: {e}")

    if success:
        event = get_event(event_id)
        if event:
            await update_event_messages(context, event_id, event=event, current_query=query)

            # Send a notification reply
            try:
                notify_chat = int(DISCUSSION_GROUP_ID) if DISCUSSION_GROUP_ID else query.message.chat_id
                disc_msg_id = event.get('discussion_message_id')
                reply_id = None
                if query.message and query.message.chat_id == notify_chat:
                    reply_id = query.message.message_id
                elif disc_msg_id:
                    reply_id = int(disc_msg_id)

                user_tag = format_user_mention(user)
                event_display = format_event_title_link(event)
                unbooked_text = f"❌ {user_tag} ha liberato 1 posto per: {event_display}"

                if reply_id:
                    try:
                        await context.bot.send_message(
                            chat_id=notify_chat,
                            text=unbooked_text,
                            reply_to_message_id=reply_id,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    except Exception as e_reply:
                        logger.warning(f"Failed to reply to discussion message {reply_id} on unbook: {e_reply}")
                        await context.bot.send_message(
                            chat_id=notify_chat,
                            text=unbooked_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                else:
                    await context.bot.send_message(
                        chat_id=notify_chat,
                        text=unbooked_text,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
            except Exception as e:
                logger.error(f"Error sending notification on unbook: {e}")

async def send_admin_action_notice(
    context,
    event,
    target_username=None,
    target_user_id=None,
    action="add",
    seats=1,
    admin_user=None
):
    """
    Sends a notification to DISCUSSION_GROUP_ID whenever an event admin adds or removes
    subscribers/seats for a public event. Explicitly specifies that the operation was done
    by an event admin (distinguishing them from other types of admins).
    """
    if not DISCUSSION_GROUP_ID:
        return
    try:
        disc_chat_id = int(DISCUSSION_GROUP_ID)
    except (ValueError, TypeError):
        return

    if not event:
        return

    # Only send for approved/cancelled events or events already posted to public channel
    if event.get('status') not in ['approved', 'cancelled'] and not event.get('telegram_message_id'):
        return

    # Format event admin identifier
    admin_str = ""
    if admin_user:
        if getattr(admin_user, 'username', None):
            admin_str = f" (@{admin_user.username})"
        elif getattr(admin_user, 'first_name', None):
            admin_str = f" ({html.escape(admin_user.first_name)})"

    # Format target user tag
    clean_target = (target_username or '').strip().lstrip('@')
    if clean_target:
        user_tag = f"@{clean_target}"
    elif target_user_id:
        user_tag = f'<a href="tg://user?id={target_user_id}">Utente</a>'
    else:
        user_tag = "Utente"

    event_display = format_event_title_link(event)

    seats_count = max(1, int(seats or 1))
    if action == "add":
        verb = "Aggiunto 1 posto" if seats_count == 1 else f"Aggiunti {seats_count} posti"
        icon = "✅"
    else:
        verb = "Rimosso 1 posto" if seats_count == 1 else f"Rimossi {seats_count} posti"
        icon = "❌"

    text = (
        f"🛠️ <b>Operazione effettuata da un admin degli eventi{admin_str}:</b>\n"
        f"{icon} {verb} per {user_tag} per: {event_display}"
    )

    reply_to = event.get('discussion_message_id')
    try:
        if reply_to:
            await context.bot.send_message(
                chat_id=disc_chat_id,
                text=text,
                reply_to_message_id=reply_to,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        else:
            await context.bot.send_message(
                chat_id=disc_chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.warning(f"Error sending admin action notice to discussion group with reply_to={reply_to}: {e}")
        try:
            await context.bot.send_message(
                chat_id=disc_chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e2:
            logger.error(f"Error sending admin action notice directly to discussion group: {e2}")

