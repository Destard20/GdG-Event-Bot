import sqlite3
import logging
import re
from core.config import DB_PATH

logger = logging.getLogger(__name__)

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    date TEXT,
                    normalized_date TEXT,
                    system TEXT,
                    host TEXT,
                    seats TEXT,
                    booked_seats INTEGER DEFAULT 0,
                    max_seats INTEGER,
                    description TEXT,
                    extra_info TEXT,
                    original_text TEXT,
                    image_path TEXT,
                    status TEXT DEFAULT 'pending',
                    is_recap INTEGER DEFAULT 0,
                    message_link TEXT,
                    telegram_message_id INTEGER,
                    discussion_message_id INTEGER,
                    discussion_chat_id TEXT,
                    wp_post_id INTEGER,
                    wp_post_url TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    seats_booked INTEGER DEFAULT 0
                )
            ''')
            # Check for column migrations on existing databases
            cursor.execute("PRAGMA table_info(events)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'extra_info' not in columns:
                cursor.execute("ALTER TABLE events ADD COLUMN extra_info TEXT")
            if 'discussion_message_id' not in columns:
                cursor.execute("ALTER TABLE events ADD COLUMN discussion_message_id INTEGER")
            if 'discussion_chat_id' not in columns:
                cursor.execute("ALTER TABLE events ADD COLUMN discussion_chat_id TEXT")
            conn.commit()
    except Exception as e:
        logger.error(f"Error initializing DB: {e}")

def insert_event(event_data, image_path, original_text, message_link=None, telegram_message_id=None):
    try:
        if message_link is None and isinstance(event_data, dict):
            message_link = event_data.get('message_link')
        if telegram_message_id is None and isinstance(event_data, dict):
            telegram_message_id = event_data.get('telegram_message_id')

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO events (title, date, normalized_date, system, host, seats, booked_seats, max_seats, description, extra_info, original_text, image_path, status, is_recap, message_link, telegram_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
            ''', (
                event_data.get('title', ''),
                event_data.get('date', ''),
                event_data.get('normalized_date', ''),
                event_data.get('system', ''),
                event_data.get('host', ''),
                event_data.get('seats', ''),
                event_data.get('booked_seats', 0),
                event_data.get('max_seats', None),
                event_data.get('description', ''),
                event_data.get('extra_info', ''),
                original_text,
                image_path,
                message_link,
                telegram_message_id
            ))
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error inserting event: {e}")
        return None

def update_event_status(event_id, status):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE events SET status = ? WHERE id = ?', (status, event_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating event status: {e}")

def update_event_field(event_id, field, value):
    allowed_fields = [
        'title', 'date', 'normalized_date', 'system', 'host',
        'seats', 'booked_seats', 'max_seats', 'description', 'extra_info',
        'discussion_message_id', 'discussion_chat_id', 'image_path'
    ]
    if field not in allowed_fields:
        return False
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE events SET {field} = ? WHERE id = ?', (value, event_id))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error updating event field {field}: {e}")
        return False

def delete_event(event_id):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM reservations WHERE event_id = ?', (event_id,))
            cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error deleting event {event_id}: {e}")
        return False

def get_event(event_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM events WHERE id = ?', (event_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error getting event: {e}")
        return None

def get_pending_events_for_recap(date_str):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Fetch ALL approved and cancelled events matching the exact target date string (in DD-MM-YYYY)
            cursor.execute('SELECT * FROM events WHERE status IN ("approved", "cancelled") AND normalized_date = ?', (date_str,))
                
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting events for recap: {e}")
        return []

def mark_events_as_recap(event_ids):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('UPDATE events SET is_recap = 1 WHERE id = ?', [(eid,) for eid in event_ids])
            conn.commit()
    except Exception as e:
        logger.error(f"Error marking events as recap: {e}")

def update_events_wp_info(event_ids, post_id, post_url):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                'UPDATE events SET wp_post_id = ?, wp_post_url = ? WHERE id = ?', 
                [(post_id, post_url, eid) for eid in event_ids]
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating events wp info: {e}")

def get_event_by_telegram_message_id(message_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM events WHERE telegram_message_id = ?', (message_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error getting event by telegram message id: {e}")
        return None

def book_seat(event_id, user_id, username):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Check availability
            cursor.execute('SELECT booked_seats, max_seats, status FROM events WHERE id = ?', (event_id,))
            ev = cursor.fetchone()
            if not ev: return False, "Evento non trovato."
            
            if ev['status'] == 'cancelled':
                return False, "Evento annullato."
                
            booked_count = int(ev['booked_seats'] or 0)
            if ev['max_seats'] is not None and booked_count >= int(ev['max_seats']):
                return False, "Nessun posto disponibile."
                
            clean_username = (username or '').strip().lstrip('@')
            # Check if reservation exists (by user_id or matching username)
            cursor.execute(
                'SELECT id, seats_booked FROM reservations WHERE event_id = ? AND (user_id = ? OR (user_id IS NULL AND LOWER(username) = LOWER(?)))',
                (event_id, user_id, clean_username)
            )
            res = cursor.fetchone()
            
            if res:
                cursor.execute(
                    'UPDATE reservations SET seats_booked = seats_booked + 1, username = ?, user_id = ? WHERE id = ?',
                    (clean_username, user_id, res['id'])
                )
            else:
                cursor.execute(
                    'INSERT INTO reservations (event_id, user_id, username, seats_booked) VALUES (?, ?, ?, 1)',
                    (event_id, user_id, clean_username)
                )
                
            new_booked = booked_count + 1
            if ev['max_seats'] is not None:
                max_s = int(ev['max_seats'])
                free = max(0, max_s - new_booked)
                cursor.execute('UPDATE events SET booked_seats = ?, seats = ? WHERE id = ?', (new_booked, f"{free}/{max_s}", event_id))
            else:
                cursor.execute('UPDATE events SET booked_seats = ? WHERE id = ?', (new_booked, event_id))
            conn.commit()
            return True, "Prenotazione aggiunta."
    except Exception as e:
        logger.error(f"Error booking seat: {e}")
        return False, "Errore durante la prenotazione."

def unbook_seat(event_id, user_id, username=None):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT booked_seats, max_seats, status FROM events WHERE id = ?', (event_id,))
            ev = cursor.fetchone()
            if not ev:
                return False, "Evento non trovato."
            if ev['status'] == 'cancelled':
                return False, "Evento annullato."
                
            clean_username = (username or '').strip().lstrip('@')
            cursor.execute(
                'SELECT id, seats_booked FROM reservations WHERE event_id = ? AND (user_id = ? OR (LOWER(username) = LOWER(?) AND ? != ""))',
                (event_id, user_id, clean_username, clean_username)
            )
            res = cursor.fetchone()
            
            if not res or res['seats_booked'] <= 0:
                return False, "Non hai posti prenotati da liberare."
                
            if res['seats_booked'] == 1:
                cursor.execute('DELETE FROM reservations WHERE id = ?', (res['id'],))
            else:
                cursor.execute('UPDATE reservations SET seats_booked = seats_booked - 1 WHERE id = ?', (res['id'],))
                
            booked_count = int(ev['booked_seats'] or 0)
            new_booked = max(0, booked_count - 1)
            if ev['max_seats'] is not None:
                max_s = int(ev['max_seats'])
                free = max(0, max_s - new_booked)
                cursor.execute('UPDATE events SET booked_seats = ?, seats = ? WHERE id = ?', (new_booked, f"{free}/{max_s}", event_id))
            else:
                cursor.execute('UPDATE events SET booked_seats = ? WHERE id = ?', (new_booked, event_id))
            conn.commit()
            return True, "Prenotazione rimossa."
    except Exception as e:
        logger.error(f"Error unbooking seat: {e}")
        return False, "Errore durante la rimozione della prenotazione."

def get_reservations_for_event(event_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM reservations WHERE event_id = ? ORDER BY id ASC', (event_id,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting reservations for event {event_id}: {e}")
        return []
def get_reservation(reservation_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error getting reservation {reservation_id}: {e}")
        return None

def get_reservation_by_user(event_id, username=None, user_id=None):
    try:
        clean_username = (username or '').strip().lstrip('@')
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if user_id is not None and clean_username:
                cursor.execute(
                    'SELECT * FROM reservations WHERE event_id = ? AND (user_id = ? OR (username IS NOT NULL AND LOWER(username) = LOWER(?)))',
                    (event_id, user_id, clean_username)
                )
            elif user_id is not None:
                cursor.execute(
                    'SELECT * FROM reservations WHERE event_id = ? AND user_id = ?',
                    (event_id, user_id)
                )
            elif clean_username:
                cursor.execute(
                    'SELECT * FROM reservations WHERE event_id = ? AND username IS NOT NULL AND LOWER(username) = LOWER(?)',
                    (event_id, clean_username)
                )
            else:
                return None
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error getting reservation by user: {e}")
        return None


def parse_date_tuple(date_str):
    if not date_str or not isinstance(date_str, str):
        return None
    s = date_str.strip()
    m = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', s)
    if m:
        try:
            return (int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    m = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', s)
    if m:
        try:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None

def are_events_on_same_day(ev1, ev2):
    if not ev1 or not ev2:
        return False
    norm1 = ev1.get('normalized_date')
    norm2 = ev2.get('normalized_date')
    if norm1 and norm2:
        d1 = parse_date_tuple(norm1)
        d2 = parse_date_tuple(norm2)
        if d1 and d2:
            return d1 == d2
        if norm1.strip() and norm2.strip():
            return norm1.strip().lower() == norm2.strip().lower()

    date1 = ev1.get('date')
    date2 = ev2.get('date')
    d1 = parse_date_tuple(norm1 or date1)
    d2 = parse_date_tuple(norm2 or date2)
    if d1 and d2:
        return d1 == d2

    if date1 and date2 and date1.strip() and date2.strip():
        return date1.strip().lower() == date2.strip().lower()

    return False

def get_user_conflicting_events(event_id, user_id=None, username=None):
    """
    Returns a list of other valid events (status not in ('cancelled', 'discarded'))
    on the same day as event_id where the user is currently subscribed
    (seats_booked > 0).
    """
    try:
        target_event = get_event(event_id)
        if not target_event:
            return []

        clean_username = (username or '').strip().lstrip('@')
        uid = int(user_id) if user_id is not None else None

        if uid is None and not clean_username:
            return []

        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            params = [event_id]
            user_conds = []
            if uid is not None:
                user_conds.append('reservations.user_id = ?')
                params.append(uid)
            if clean_username:
                user_conds.append('(reservations.username IS NOT NULL AND LOWER(reservations.username) = LOWER(?))')
                params.append(clean_username)

            if not user_conds:
                return []

            user_clause = f"({' OR '.join(user_conds)})"
            query = f'''
                SELECT DISTINCT events.*
                FROM events
                JOIN reservations ON events.id = reservations.event_id
                WHERE events.id != ?
                  AND events.status NOT IN ('cancelled', 'discarded')
                  AND reservations.seats_booked > 0
                  AND {user_clause}
                ORDER BY events.id ASC
            '''
            cursor.execute(query, tuple(params))
            candidate_events = [dict(row) for row in cursor.fetchall()]

        conflicts = [
            ev for ev in candidate_events
            if are_events_on_same_day(target_event, ev)
        ]
        return conflicts
    except Exception as e:
        logger.error(f"Error getting user conflicting events: {e}")
        return []


def admin_add_seat(event_id, reservation_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT booked_seats, max_seats, status FROM events WHERE id = ?', (event_id,))
            ev = cursor.fetchone()
            if not ev:
                return False, "Evento non trovato."
            if ev['status'] == 'cancelled':
                return False, "Evento annullato."
                
            booked_count = int(ev['booked_seats'] or 0)
            if ev['max_seats'] is not None and booked_count >= int(ev['max_seats']):
                return False, "Capienza massima raggiunta!"
                
            cursor.execute('SELECT id, seats_booked, username FROM reservations WHERE id = ? AND event_id = ?', (reservation_id, event_id))
            res = cursor.fetchone()
            if not res:
                return False, "Prenotazione non trovata."
                
            cursor.execute('UPDATE reservations SET seats_booked = seats_booked + 1 WHERE id = ?', (reservation_id,))
            new_booked = booked_count + 1
            if ev['max_seats'] is not None:
                max_s = int(ev['max_seats'])
                free = max(0, max_s - new_booked)
                cursor.execute('UPDATE events SET booked_seats = ?, seats = ? WHERE id = ?', (new_booked, f"{free}/{max_s}", event_id))
            else:
                cursor.execute('UPDATE events SET booked_seats = ? WHERE id = ?', (new_booked, event_id))
            conn.commit()
            u_name = res['username'] or "Utente"
            return True, f"Aggiunto 1 posto a {u_name}."
    except Exception as e:
        logger.error(f"Error in admin_add_seat: {e}")
        return False, "Errore durante l'aggiunta del posto."

def admin_remove_seat(event_id, reservation_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT booked_seats, max_seats, status FROM events WHERE id = ?', (event_id,))
            ev = cursor.fetchone()
            if not ev:
                return False, "Evento non trovato."
                
            cursor.execute('SELECT id, seats_booked, username FROM reservations WHERE id = ? AND event_id = ?', (reservation_id, event_id))
            res = cursor.fetchone()
            if not res:
                return False, "Prenotazione non trovata."
                
            if res['seats_booked'] <= 1:
                cursor.execute('DELETE FROM reservations WHERE id = ?', (reservation_id,))
            else:
                cursor.execute('UPDATE reservations SET seats_booked = seats_booked - 1 WHERE id = ?', (reservation_id,))
                
            booked_count = int(ev['booked_seats'] or 0)
            new_booked = max(0, booked_count - 1)
            if ev['max_seats'] is not None:
                max_s = int(ev['max_seats'])
                free = max(0, max_s - new_booked)
                cursor.execute('UPDATE events SET booked_seats = ?, seats = ? WHERE id = ?', (new_booked, f"{free}/{max_s}", event_id))
            else:
                cursor.execute('UPDATE events SET booked_seats = ? WHERE id = ?', (new_booked, event_id))
            conn.commit()
            u_name = res['username'] or "Utente"
            return True, f"Rimosso 1 posto a {u_name}."
    except Exception as e:
        logger.error(f"Error in admin_remove_seat: {e}")
        return False, "Errore durante la rimozione del posto."

def admin_add_subscriber(event_id, username, seats=1, user_id=None):
    try:
        seats = int(seats)
        if seats <= 0:
            return False, "Il numero di posti deve essere almeno 1."
        clean_username = (username or '').strip().lstrip('@')
        if not clean_username and user_id is None:
            return False, "Specificare un username o un user_id valido."
            
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT booked_seats, max_seats, status FROM events WHERE id = ?', (event_id,))
            ev = cursor.fetchone()
            if not ev:
                return False, "Evento non trovato."
            if ev['status'] == 'cancelled':
                return False, "Evento annullato. Riattivalo prima di aggiungere iscritti."
                
            booked_count = int(ev['booked_seats'] or 0)
            if ev['max_seats'] is not None:
                max_s = int(ev['max_seats'])
                if booked_count + seats > max_s:
                    avail = max(0, max_s - booked_count)
                    return False, f"Capienza superata! Posti disponibili: {avail}/{max_s}."
                    
            cursor.execute(
                'SELECT id, seats_booked FROM reservations WHERE event_id = ? AND (user_id = ? OR (LOWER(username) = LOWER(?) AND ? != ""))',
                (event_id, user_id, clean_username, clean_username)
            )
            res = cursor.fetchone()
            if res:
                cursor.execute(
                    'UPDATE reservations SET seats_booked = seats_booked + ?, username = ? WHERE id = ?',
                    (seats, clean_username or res['username'], res['id'])
                )
            else:
                cursor.execute(
                    'INSERT INTO reservations (event_id, user_id, username, seats_booked) VALUES (?, ?, ?, ?)',
                    (event_id, user_id, clean_username, seats)
                )
                
            new_booked = booked_count + seats
            if ev['max_seats'] is not None:
                max_s = int(ev['max_seats'])
                free = max(0, max_s - new_booked)
                cursor.execute('UPDATE events SET booked_seats = ?, seats = ? WHERE id = ?', (new_booked, f"{free}/{max_s}", event_id))
            else:
                cursor.execute('UPDATE events SET booked_seats = ? WHERE id = ?', (new_booked, event_id))
            conn.commit()
            display_name = f"@{clean_username}" if clean_username else f"ID:{user_id}"
            return True, f"Iscritto {display_name} registrato con successo ({seats} posto/i)."
    except Exception as e:
        logger.error(f"Error in admin_add_subscriber: {e}")
        return False, "Errore durante l'aggiunta dell'iscritto."

def admin_remove_subscriber(event_id, username, seats=None):
    try:
        clean_username = (username or '').strip().lstrip('@')
        if not clean_username:
            return False, "Specificare un username valido."
            
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT booked_seats, max_seats, status FROM events WHERE id = ?', (event_id,))
            ev = cursor.fetchone()
            if not ev:
                return False, "Evento non trovato."
                
            cursor.execute(
                'SELECT id, seats_booked FROM reservations WHERE event_id = ? AND LOWER(username) = LOWER(?)',
                (event_id, clean_username)
            )
            res = cursor.fetchone()
            if not res:
                return False, f"Nessun iscritto trovato con username @{clean_username}."
                
            current_seats = res['seats_booked']
            if seats is None or int(seats) >= current_seats:
                seats_to_remove = current_seats
                cursor.execute('DELETE FROM reservations WHERE id = ?', (res['id'],))
            else:
                seats_to_remove = int(seats)
                cursor.execute('UPDATE reservations SET seats_booked = seats_booked - ? WHERE id = ?', (seats_to_remove, res['id']))
                
            booked_count = int(ev['booked_seats'] or 0)
            new_booked = max(0, booked_count - seats_to_remove)
            if ev['max_seats'] is not None:
                max_s = int(ev['max_seats'])
                free = max(0, max_s - new_booked)
                cursor.execute('UPDATE events SET booked_seats = ?, seats = ? WHERE id = ?', (new_booked, f"{free}/{max_s}", event_id))
            else:
                cursor.execute('UPDATE events SET booked_seats = ? WHERE id = ?', (new_booked, event_id))
            conn.commit()
            return True, f"Rimossi {seats_to_remove} posto/i per @{clean_username}."
    except Exception as e:
        logger.error(f"Error in admin_remove_subscriber: {e}")
        return False, "Errore durante la rimozione dell'iscritto."


def update_telegram_message_info(event_id, message_id, message_link):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE events SET telegram_message_id = ?, message_link = ? WHERE id = ?', (message_id, message_link, event_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating telegram message info: {e}")

def update_discussion_message_info(event_id, message_id, chat_id=None):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            if chat_id is not None:
                cursor.execute('UPDATE events SET discussion_message_id = ?, discussion_chat_id = ? WHERE id = ?', (message_id, str(chat_id), event_id))
            else:
                cursor.execute('UPDATE events SET discussion_message_id = ? WHERE id = ?', (message_id, event_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating discussion message info: {e}")

def get_event_by_discussion_message_id(message_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM events WHERE discussion_message_id = ?', (message_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error getting event by discussion message id: {e}")
        return None

