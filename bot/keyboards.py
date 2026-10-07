from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.config import TELEGRAM_BOT_USERNAME
from utils.templates import format_reservation_subscriber_display

def get_approval_keyboard(event_id):
    keyboard = [
        [
            InlineKeyboardButton("Publish", callback_data=f"publish_event_{event_id}"),
            InlineKeyboardButton("Discard", callback_data=f"discard_event_{event_id}")
        ],
        [
            InlineKeyboardButton("👥 Gestisci Iscritti", callback_data=f"manage_subs_{event_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_approved_event_keyboard(event_id):
    keyboard = [
        [
            InlineKeyboardButton("❌ Annulla Evento", callback_data=f"cancel_event_{event_id}"),
            InlineKeyboardButton("👥 Gestisci Iscritti", callback_data=f"manage_subs_{event_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_only_keyboard(event_id):
    return get_approved_event_keyboard(event_id)

def get_cancelled_event_keyboard(event_id):
    keyboard = [
        [
            InlineKeyboardButton("♻️ Riattiva Evento", callback_data=f"reactivate_event_{event_id}"),
            InlineKeyboardButton("👥 Gestisci Iscritti", callback_data=f"manage_subs_{event_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_subscribers_management_keyboard(event_id, reservations):
    keyboard = []
    for res in reservations:
        label = format_reservation_subscriber_display(res, as_html=False)
        seats = res.get('seats_booked', 1)
        res_id = res['id']
        label = label if len(label) <= 12 else label[:11] + "…"
        keyboard.append([
            InlineKeyboardButton(f"➖ {label} ({seats})", callback_data=f"sub_dec_{event_id}_{res_id}"),
            InlineKeyboardButton(f"➕ {label} ({seats})", callback_data=f"sub_inc_{event_id}_{res_id}")
        ])
    keyboard.append([
        InlineKeyboardButton("➕ Aggiungi Iscritto", callback_data=f"sub_addnew_{event_id}")
    ])
    keyboard.append([
        InlineKeyboardButton("🔄 Aggiorna", callback_data=f"manage_subs_{event_id}"),
        InlineKeyboardButton("❌ Chiudi", callback_data=f"close_subs_{event_id}")
    ])
    return InlineKeyboardMarkup(keyboard)

def get_recap_approval_keyboard(date_str):
    keyboard = [
        [
            InlineKeyboardButton("Publish Recap", callback_data=f"publish_recap_{date_str}"),
            InlineKeyboardButton("Discard Recap", callback_data=f"discard_recap_{date_str}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_wp_publish_keyboard(post_id):
    keyboard = [
        [
            InlineKeyboardButton("Pubblica su WordPress", callback_data=f"publish_wp_{post_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_event_booking_keyboard(event_id, event=None, bot_username=None):
    if event is None:
        from core.db import get_event
        event = get_event(event_id)
        
    is_full = False
    if event:
        max_seats = event.get('max_seats')
        booked_seats = int(event.get('booked_seats', 0) or 0)
        if max_seats is not None and booked_seats >= int(max_seats):
            is_full = True
            
    if is_full:
        book_button = InlineKeyboardButton("🚫 Esauriti", callback_data=f"full_{event_id}")
    else:
        book_button = InlineKeyboardButton("➕ Prenota", callback_data=f"book_{event_id}")

    unbook_button = InlineKeyboardButton("➖ Annulla", callback_data=f"unbook_{event_id}")

    if bot_username is None:
        bot_username = TELEGRAM_BOT_USERNAME

    row = [book_button]
    if bot_username:
        clean_username = bot_username.lstrip('@')
        list_button = InlineKeyboardButton("👥 Lista", url=f"https://t.me/{clean_username}?start=subs_{event_id}")
        row.append(list_button)
    row.append(unbook_button)

    return InlineKeyboardMarkup([row])

def get_schedule_repost_keyboard(scheduled_id, active_days=None):
    if active_days is None:
        active_days = []
    
    # Normalize active days to lowercase for comparison
    active_lower = [str(d).strip().lower() for d in active_days]

    def btn_label(key, name):
        # checked if key or name in active_lower
        is_checked = key.lower() in active_lower or name.lower() in active_lower
        icon = "✅" if is_checked else "⬜"
        return f"{icon} {name}"

    row1 = [
        InlineKeyboardButton(btn_label("lun", "Lunedì"), callback_data=f"sched_toggle_{scheduled_id}_lun"),
        InlineKeyboardButton(btn_label("mer", "Mercoledì"), callback_data=f"sched_toggle_{scheduled_id}_mer"),
        InlineKeyboardButton(btn_label("ven", "Venerdì"), callback_data=f"sched_toggle_{scheduled_id}_ven"),
    ]
    row2 = [
        InlineKeyboardButton(btn_label("sab", "Sabato"), callback_data=f"sched_toggle_{scheduled_id}_sab"),
        InlineKeyboardButton(btn_label("dom", "Domenica"), callback_data=f"sched_toggle_{scheduled_id}_dom"),
    ]
    row3 = [
        InlineKeyboardButton("🗑️ Elimina", callback_data=f"sched_del_{scheduled_id}"),
        InlineKeyboardButton("❌ Chiudi", callback_data=f"sched_close_{scheduled_id}"),
    ]
    return InlineKeyboardMarkup([row1, row2, row3])


