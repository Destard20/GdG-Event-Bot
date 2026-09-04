import sqlite3
import logging
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
            # Check for extra_info column migration on existing databases
            cursor.execute("PRAGMA table_info(events)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'extra_info' not in columns:
                cursor.execute("ALTER TABLE events ADD COLUMN extra_info TEXT")
            conn.commit()
    except Exception as e:
        logger.error(f"Error initializing DB: {e}")

def insert_event(event_data, image_path, original_text, message_link=None, telegram_message_id=None):
    try:
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
    allowed_fields = ['title', 'date', 'normalized_date', 'system', 'host', 'max_seats', 'description', 'extra_info']
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
                
            if ev['max_seats'] is not None and ev['booked_seats'] >= ev['max_seats']:
                return False, "Nessun posto disponibile."
                
            # Check if reservation exists
            cursor.execute('SELECT seats_booked FROM reservations WHERE event_id = ? AND user_id = ?', (event_id, user_id))
            res = cursor.fetchone()
            
            if res:
                cursor.execute('UPDATE reservations SET seats_booked = seats_booked + 1, username = ? WHERE event_id = ? AND user_id = ?', (username, event_id, user_id))
            else:
                cursor.execute('INSERT INTO reservations (event_id, user_id, username, seats_booked) VALUES (?, ?, ?, 1)', (event_id, user_id, username))
                
            cursor.execute('UPDATE events SET booked_seats = booked_seats + 1 WHERE id = ?', (event_id,))
            conn.commit()
            return True, "Prenotazione aggiunta."
    except Exception as e:
        logger.error(f"Error booking seat: {e}")
        return False, "Errore durante la prenotazione."

def unbook_seat(event_id, user_id):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT status FROM events WHERE id = ?', (event_id,))
            ev = cursor.fetchone()
            if ev and ev['status'] == 'cancelled':
                return False, "Evento annullato."
                
            cursor.execute('SELECT seats_booked FROM reservations WHERE event_id = ? AND user_id = ?', (event_id, user_id))
            res = cursor.fetchone()
            
            if not res or res['seats_booked'] <= 0:
                return False, "Non hai posti prenotati da liberare."
                
            if res['seats_booked'] == 1:
                cursor.execute('DELETE FROM reservations WHERE event_id = ? AND user_id = ?', (event_id, user_id))
            else:
                cursor.execute('UPDATE reservations SET seats_booked = seats_booked - 1 WHERE event_id = ? AND user_id = ?', (event_id, user_id))
                
            cursor.execute('UPDATE events SET booked_seats = booked_seats - 1 WHERE id = ?', (event_id,))
            conn.commit()
            return True, "Prenotazione rimossa."
    except Exception as e:
        logger.error(f"Error unbooking seat: {e}")
        return False, "Errore durante la rimozione della prenotazione."

def update_telegram_message_info(event_id, message_id, message_link):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE events SET telegram_message_id = ?, message_link = ? WHERE id = ?', (message_id, message_link, event_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating telegram message info: {e}")

