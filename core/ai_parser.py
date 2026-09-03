import google.generativeai as genai
import json
import logging
from core.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)

def parse_event_message(message_text):
    prompt = f"""
    You are an AI parser for a tabletop games association in Italy. 
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
    - "seats": The original string for available seats or "Posti liberi" status (e.g. "2/4", "no limit"). If the message indicates 0 free seats (e.g. "0/3" or "0/4"), output exactly "0/0 Completo".
    - "booked_seats": The number of already booked seats (integer, default 0). IMPORTANT: if the message says "Posti liberi: 2/4" it means 2 seats are FREE out of 4, so booked_seats is 2. If it says "3/3" it means 3 seats are FREE, so booked_seats is 0. If it says "0/3 Completo" it means 0 seats are free, so booked_seats is 3. Calculate this carefully.
    - "max_seats": The maximum number of available seats (integer, or null if there is no limit).
    - "description": The synopsis or description of the event.
    
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
        return data
    except Exception as e:
        logger.error(f"Error parsing message with AI: {e}")
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
        return None

