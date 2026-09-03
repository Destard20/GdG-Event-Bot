from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_approval_keyboard(event_id):
    keyboard = [
        [
            InlineKeyboardButton("Publish", callback_data=f"publish_event_{event_id}"),
            InlineKeyboardButton("Discard", callback_data=f"discard_event_{event_id}"),
            InlineKeyboardButton("Cancel", callback_data=f"cancel_event_{event_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_only_keyboard(event_id):
    keyboard = [
        [
            InlineKeyboardButton("Cancel", callback_data=f"cancel_event_{event_id}")
        ]
    ]
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


def get_event_booking_keyboard(event_id):
    keyboard = [
        [
            InlineKeyboardButton("➕ Mi prenoto", callback_data=f"book_{event_id}"),
            InlineKeyboardButton("➖ Tolgo prenotazione", callback_data=f"unbook_{event_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

