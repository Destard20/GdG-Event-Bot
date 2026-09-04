import google.generativeai as genai
import json
import logging
import re
from core.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

class GeminiQuotaError(Exception):
    """Raised when Gemini API quota is exceeded or prepayment credits are depleted."""
    pass

GEMINI_DEPLETED_ALERT = "🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."

genai.configure(api_key=GEMINI_API_KEY)

def parse_event_message(message_text):
    prompt = f"""
    You are an AI parser for a tabletop games association in Italy (Gilda del Grifone). 
    Analyze the following message and extract the event information into a strict JSON format.
    The message usually announces a game session (roleplaying, board game, etc.).
    
    If the message is NOT an event announcement (e.g. general chat, irrelevant to games), 
    return EXACTLY: {{"is_event": false}}
    
    If it is an event, extract the following fields:
    - "title": The title of the event or game.
    - "date": The date and time (keep the string exactly as in the message or format nicely).
    - "normalized_date": The date converted to DD-MM-YYYY format (assuming the current year is 2026 if not specified).
    - "system": The game system or genre (if any, e.g., "Sine Requie", "D&D", or board game name).
    - "host": The Master, Host, or Organizer's name and/or tag.
    - "seats": The display string for available seats (e.g. "2/4", "no limit"). If 0 seats are free, output "0/0 Completo".
    - "booked_seats": The number of already booked seats (integer, default 0).
      CRITICAL RULE FOR SEATS:
      In this Italian association, "Posti: X/Y", "Posti liberi: X/Y", or "Posti disponibili: X/Y" ALWAYS means:
      X = FREE/AVAILABLE seats that can be booked through this bot.
      Y = TOTAL seats at the table. Any difference (Y - X) represents players already booked outside the bot (e.g. host's friends).
      IMPORTANT: The bot ONLY manages bookings for the open seats.
      Therefore, the event's bookable capacity MUST always be X:
      max_seats = X
      booked_seats = 0
      seats = "X/X" (or "0/0 Completo" if X is 0)
      
      Examples:
      - "Posti: 2/2" -> 2 free seats -> booked_seats = 0, max_seats = 2, seats = "2/2"
      - "Posti: 1/4" -> 1 free seat -> booked_seats = 0, max_seats = 1, seats = "1/1"
      - "Posti: 4/5" -> 4 free seats -> booked_seats = 0, max_seats = 4, seats = "4/4"
      - "Posti liberi: 2/4" -> 2 free seats -> booked_seats = 0, max_seats = 2, seats = "2/2"
      - "Posti: 0/3 Completo" -> 0 free seats -> booked_seats = 0, max_seats = 0, seats = "0/0 Completo"
      - "Posti: 4" (single number, no slash) -> 4 total available seats -> booked_seats = 0, max_seats = 4, seats = "4/4"
      - "Posti: no limit" or "quanti volete" -> booked_seats = 0, max_seats = null, seats = "no limit"
    - "max_seats": The maximum number of available seats (integer, or null if there is no limit).
    - "extra_info": Additional metadata or disclaimers if present in the message, specifically:
      - Difficulty / Beginner friendliness (e.g. "Difficoltà: adatto a tutti", "Adatto a neofiti: Sì")
      - Format / Duration / Campaign info (e.g. "ONESHOT", "CAMPAGNA (5 episodi)", "Durata: 3 ore")
      - Content warnings, safety tools, disclaimers (e.g. "Attenzione: gore, violenza", "X-Card: droghe", "Avviso: Effetti audio")
      - Genre / Themes (e.g. "Genere: Horror / Investigativo")
      Format them cleanly as short bulleted lines (using "• ") or concise text. If none of these exist in the message, output "".
    - "description": The synopsis or pitch of the event (focus on the story or game description; do not duplicate lines already extracted into extra_info).
    
    Return ONLY valid JSON.
    
    Message:
    {message_text}
    """
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
            
        data = json.loads(text)
        
        # Deterministic regex safety-net for "Posti [liberi]: X/Y"
        if isinstance(data, dict) and data.get("is_event", True):
            data['extra_info'] = str(data.get('extra_info') or '').strip()
            m = re.search(r'Posti(?:\s+liberi|\s+disponibili)?\s*:\s*(\d+)\s*/\s*(\d+)', message_text, re.IGNORECASE)
            if m:
                free = int(m.group(1))
                data['max_seats'] = free
                data['booked_seats'] = 0
                if free == 0:
                    data['seats'] = "0/0 Completo"
                else:
                    data['seats'] = f"{free}/{free}"
            else:
                m_single = re.search(r'Posti(?:\s+liberi|\s+disponibili)?\s*:\s*(\d+)(?!\s*/)', message_text, re.IGNORECASE)
                if m_single:
                    val = int(m_single.group(1))
                    data['max_seats'] = val
                    data['booked_seats'] = 0
                    if val == 0:
                        data['seats'] = "0/0 Completo"
                    else:
                        data['seats'] = f"{val}/{val}"
                        
        return data
    except Exception as e:
        logger.error(f"Error parsing message with AI: {e}")
        err_str = str(e)
        if "429" in err_str or "prepayment credits are depleted" in err_str.lower() or "quota" in err_str.lower() or "resourceexhausted" in err_str.lower():
            raise GeminiQuotaError(err_str) from e
        return None

def generate_wordpress_article(recap_text, event_list):
    events_details = ""
    for ev in event_list:
        link = ev.get('message_link') or 'Link non disponibile'
        img_url = ev.get('wp_media_url')
        img_info = f" | Image URL: {img_url}" if img_url else ""
        events_details += f"- {ev.get('title')}: {link}{img_info}\n"
        
    prompt = f"""
    You are an AI generating an engaging article for a tabletop games association's WordPress blog.
    Write an article in Italian summarizing the events for the upcoming game nights based on the recap text.
    Make it enthusiastic and welcoming.
    
    CRITICAL INSTRUCTIONS:
    - You must include the direct Telegram event link for each event in the article text, using the provided list below. Do not use placeholders like [Inserisci qui i link diretti agli eventi].
    - If you cite Destard or ManueleAbi, specify clearly that they are Telegram usernames. For example, use "l'utente Telegram @Destard (https://t.me/Destard)" and "l'utente Telegram @ManueleAbi (https://t.me/ManueleAbi)".
    - If an "Image URL" is provided for an event in the list below, you MUST embed it in the article body exactly where that event is described using an HTML <img> tag with a maximum size constraint (e.g., <img src="..." alt="..." style="max-width:400px; max-height:400px; width:auto; height:auto; margin-bottom:15px;">). Do not mention or include HTML tags for the daily collage, as the system will automatically attach it as the article's featured image (Immagine in evidenza).
    
    Recap Info:
    {recap_text}
    
    Event Links to include:
    {events_details}
    
    Return the response as HTML (just the content to put in the post body, no <html> or <body> tags).
    """
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Error generating WP article with AI: {e}")
        err_str = str(e)
        if "429" in err_str or "prepayment credits are depleted" in err_str.lower() or "quota" in err_str.lower() or "resourceexhausted" in err_str.lower():
            raise GeminiQuotaError(err_str) from e
        return None

