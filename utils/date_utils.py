import re
from datetime import datetime, date

DAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

WEEKDAYS_MAP = {
    # Italian
    "lunedì": 0, "lunedi": 0,
    "martedì": 1, "martedi": 1,
    "mercoledì": 2, "mercoledi": 2,
    "giovedì": 3, "giovedi": 3,
    "venerdì": 4, "venerdi": 4,
    "sabato": 5,
    "domenica": 6,
    # English
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

def parse_user_date(date_str: str) -> tuple[datetime, bool] | None:
    """
    Parses a user-supplied date string.
    Accepted formats:
    - DD-MM-YYYY or DD/MM/YYYY
    - DD-MM-YYYY HH:MM or DD/MM/YYYY HH:MM
    Allows single or double digits for day, month, and hour.
    
    Returns (datetime_obj, has_time) or None if format is invalid or date does not exist.
    """
    if not date_str or not isinstance(date_str, str):
        return None
        
    s = date_str.strip()
    m = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:\s+(\d{1,2}):(\d{2}))?$', s)
    if not m:
        return None
        
    day = int(m.group(1))
    month = int(m.group(2))
    year = int(m.group(3))
    has_time = m.group(4) is not None
    hour = int(m.group(4)) if has_time else 0
    minute = int(m.group(5)) if has_time else 0
    
    try:
        dt = datetime(year, month, day, hour, minute)
        return dt, has_time
    except ValueError:
        return None

def format_standard_event_date(dt: datetime, has_time: bool) -> tuple[str, str]:
    """
    Given a datetime and has_time flag:
    Returns (display_date, normalized_date).
    Example:
    ("Venerdì 05-09-2026 21:00", "05-09-2026") or ("Venerdì 05-09-2026", "05-09-2026")
    """
    weekday_str = DAYS_IT[dt.weekday()]
    norm_date = dt.strftime("%d-%m-%Y")
    if has_time:
        display_date = f"{weekday_str} {dt.strftime('%d-%m-%Y %H:%M')}"
    else:
        display_date = f"{weekday_str} {dt.strftime('%d-%m-%Y')}"
    return display_date, norm_date

def parse_date_tuple_from_str(date_str: str) -> tuple[int, int, int] | None:
    """
    Extracts (year, month, day) from a date string (handles DD-MM-YYYY, YYYY-MM-DD, slashes, dots).
    """
    if not date_str or not isinstance(date_str, str):
        return None
    s = date_str.strip()
    m = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', s)
    if m:
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            datetime(y, mo, d)
            return (y, mo, d)
        except ValueError:
            pass
    m = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', s)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            datetime(y, mo, d)
            return (y, mo, d)
        except ValueError:
            pass
    return None

def validate_event_date_anomalies(event_data: dict, raw_text: str = None, reference_date: date = None) -> list[str]:
    """
    Validates event date logic:
    1. Checks if date is in the past compared to reference_date (default: today).
    2. Checks if there is a weekday mismatch between text and the actual calendar day.
    3. Checks if a valid date is present.
    
    Returns a list of warning messages (empty if valid).
    """
    warnings = []
    if reference_date is None:
        reference_date = date.today()
        
    date_field = str(event_data.get('date') or '').strip()
    norm_field = str(event_data.get('normalized_date') or '').strip()
    
    parsed_tuple = parse_date_tuple_from_str(norm_field) or parse_date_tuple_from_str(date_field)
    
    if not parsed_tuple:
        warnings.append("⚠️ ATTENZIONE: Impossibile determinare una data valida per l'evento!")
        return warnings
        
    y, mo, d = parsed_tuple
    try:
        ev_date = date(y, mo, d)
    except ValueError:
        warnings.append("⚠️ ATTENZIONE: Data inesistente nel calendario!")
        return warnings
        
    formatted_d = f"{d:02d}-{mo:02d}-{y}"

    # Check Past Date
    if ev_date < reference_date:
        warnings.append(f"⚠️ ATTENZIONE: La data rilevata ({formatted_d}) risulta essere nel PASSATO!")
        
    # Check Weekday Mismatch
    text_to_check = date_field.lower()
    m_day = re.search(r'\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', text_to_check)
    if not m_day and raw_text:
        m_day = re.search(r'\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', raw_text.lower())
        
    if m_day:
        word = m_day.group(1).lower()
        if word in WEEKDAYS_MAP:
            expected_weekday_idx = WEEKDAYS_MAP[word]
            actual_weekday_idx = ev_date.weekday()
            if expected_weekday_idx != actual_weekday_idx:
                mentioned_name = DAYS_IT[expected_weekday_idx]
                actual_name = DAYS_IT[actual_weekday_idx]
                warnings.append(
                    f"⚠️ ATTENZIONE: Incongruenza data/giorno! Il testo menziona '{mentioned_name}', ma il {formatted_d} è {actual_name}."
                )
                
    return warnings
