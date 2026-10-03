import os
import re
import json
import logging
import urllib.parse
from datetime import datetime
import requests
import google.generativeai as genai
from telegram import Update
from telegram.ext import ContextTypes

from core.config import DATA_DIR, ADMIN_CHAT_ID, GEMINI_API_KEY, GEMINI_MODEL
from core.ai_parser import GeminiQuotaError, GEMINI_DEPLETED_ALERT
from core.db import insert_event, update_event_field
from utils.image_utils import create_collage_from_bytes, save_image_locally
from utils.templates import format_public_event_message
from utils.date_utils import validate_event_date_anomalies, DAYS_IT
from bot.keyboards import get_approval_keyboard

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "GdG-Event-Bot/1.0 (+https://github.com/destard/GdG-Event-Bot)"
BGG_SEARCH_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&search="
BGG_DETAIL_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&objectid="

ACCESSORY_RE = re.compile(
    r"\b(\d+\s*x\s*\d+\s*mm|sleeves?|enamel|coins?|tokens?|insert|organizer|playmat|dice bag|promo pack|promo card|upgrade kit|goodie|neoprene|custom dice)\b",
    re.I,
)


def fetch_bgg_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """
    Searches BoardGameGeek via api.geekdo.com and fetches box image bytes.
    Filters out accessories and prefers exact name matches.
    """
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
    search_url = f"{BGG_SEARCH_URL}{urllib.parse.quote(q)}"

    try:
        resp = requests.get(search_url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"BGG search for '{q}' returned status {resp.status_code}")
            return None

        data = resp.json()
        items = data.get("items", [])
        if not items:
            logger.info(f"No BGG search items found for '{q}'")
            return None

        # Best item selection:
        best_item = None
        q_norm = q.lower()
        for it in items:
            if it.get("name", "").strip().lower() == q_norm:
                best_item = it
                break

        if not best_item:
            for it in items:
                name = it.get("name", "").strip()
                if not ACCESSORY_RE.search(name) and (name.lower().startswith(q_norm) or q_norm in name.lower()):
                    best_item = it
                    break

        if not best_item:
            for it in items:
                name = it.get("name", "").strip()
                if not ACCESSORY_RE.search(name):
                    best_item = it
                    break

        if not best_item:
            best_item = items[0]

        object_id = best_item.get("objectid")
        if not object_id:
            return None

        # Fetch item details for image URL
        detail_url = f"{BGG_DETAIL_URL}{object_id}"
        det_resp = requests.get(detail_url, headers=headers, timeout=timeout)
        if det_resp.status_code != 200:
            logger.warning(f"BGG item detail fetch for ID {object_id} returned {det_resp.status_code}")
            return None

        item_data = det_resp.json().get("item", {})

        # Prefer high-resolution 'original' image, fallback to 'imageurl'
        image_url = None
        images_dict = item_data.get("images")
        if isinstance(images_dict, dict) and images_dict.get("original"):
            image_url = images_dict.get("original")
        if not image_url:
            image_url = item_data.get("imageurl")

        if not image_url:
            logger.info(f"No image URL found in BGG item for '{q}' (ID: {object_id})")
            return None

        if image_url.startswith("//"):
            image_url = "https:" + image_url

        img_resp = requests.get(image_url, headers=headers, timeout=timeout + 5)
        if img_resp.status_code == 200:
            return img_resp.content

        logger.warning(f"Failed to download image from {image_url}: status {img_resp.status_code}")
        return None

    except Exception as e:
        logger.error(f"Error fetching BGG image for '{q}': {e}")
        return None


def generate_event_data_with_ai(prompt_text: str) -> dict | None:
    """
    Calls Gemini AI to interpret the user's instructions and generate
    standardized event fields plus an array of board games / systems to query BGG.
    """
    now = datetime.now()
    weekday_it = DAYS_IT[now.weekday()]
    today_context = f"{weekday_it} {now.strftime('%d-%m-%Y')} (Year: 2026)"

    prompt = f"""
You are an AI assistant for a tabletop games association.
The user provides informal instructions to create a new gaming event (e.g., game title(s), date, host, seats, etc.).
Analyze the user's message and generate a structured JSON object.

Context:
- Current date reference: {today_context}.
- Standard default start time: 21:00 (if no time specified).

Required JSON structure:
{{
  "title": "Title of the event or game(s). E.g. 'Catan', 'Catan & Carcassonne', or 'D&D 5e: Il Tesoro della Regina'",
  "games": ["List of individual game titles to search on BoardGameGeek for box art, e.g. ['Catan'] or ['Catan', 'Carcassonne']"],
  "date": "Italian date string, e.g. 'Venerdì 10-10-2026 21:00' or 'Domenica 04 Ottobre 2026 21:00'",
  "normalized_date": "Strict DD-MM-YYYY format, e.g. '10-10-2026'",
  "system": "Game system or category, e.g. 'Board Game', 'Giochi da Tavolo', 'D&D 5e', 'Call of Cthulhu'",
  "host": "Master or Host name/handle (e.g. '@Destard' or 'Destard'). If unknown, 'N/A'",
  "seats": "Display string for seats, e.g. '4/4', '6/6', or 'no limit'",
  "booked_seats": 0,
  "max_seats": 4,
  "extra_info": "Additional metadata (difficulty, beginner friendly, duration, tags) if mentioned, or empty string",
  "is_roleplay": false,
  "description": "Engaging, captivating synopsis/pitch for the game(s) in Italian (theme, objective, vibe)."
}}

CRITICAL RULES:
1. "description" MUST BE CONCISE: maximum 350-400 characters!
   The entire Telegram post (including title, host, date, seats, and description) MUST fit within Telegram's strict 1024-character caption limit.
2. "games" must contain only clean game names without dates, hosts, or extra words (e.g. ["Root", "Wingspan"]).
3. Return ONLY valid JSON, with no markdown outside ```json blocks.

User Instructions:
{prompt_text}
"""
    try:
        logger.info("Event Generator: Sending prompt to Gemini for event generation...")
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()

        data = json.loads(text)
        if not isinstance(data, dict):
            return None

        # Clean types
        data["extra_info"] = str(data.get("extra_info") or "").strip()
        data["description"] = str(data.get("description") or "").strip()
        data["booked_seats"] = 0

        raw_rp = data.get("is_roleplay")
        if isinstance(raw_rp, str):
            data["is_roleplay"] = raw_rp.strip().lower() in ["true", "1", "yes", "si", "sì"]
        else:
            data["is_roleplay"] = bool(raw_rp)

        # Ensure games list exists
        games = data.get("games")
        if not isinstance(games, list):
            if isinstance(games, str) and games.strip():
                data["games"] = [games.strip()]
            elif data.get("title"):
                data["games"] = [data["title"]]
            else:
                data["games"] = []

        return data

    except Exception as e:
        logger.error(f"Error generating event with Gemini: {e}")
        err_str = str(e)
        if "429" in err_str or "prepayment credits are depleted" in err_str.lower() or "quota" in err_str.lower() or "resourceexhausted" in err_str.lower():
            raise GeminiQuotaError(err_str) from e
        return None


def enforce_caption_limit(event_data: dict, max_length: int = 1024) -> str:
    """
    Formats the public event message and dynamically trims event_data['description']
    if the resulting message exceeds max_length (1024 for Telegram photo captions).
    """
    formatted = format_public_event_message(event_data)
    if len(formatted) <= max_length:
        return formatted

    # Need to trim description
    desc = event_data.get("description", "")
    overflow = len(formatted) - max_length

    # Give a safety buffer of 5 characters for ellipsis
    trim_amount = overflow + 5
    if len(desc) > trim_amount:
        event_data["description"] = desc[:-trim_amount].rstrip() + "..."
    else:
        event_data["description"] = ""

    formatted = format_public_event_message(event_data)

    if len(formatted) > max_length:
        event_data["description"] = ""
        formatted = format_public_event_message(event_data)

    return formatted



async def process_event_generation(
    prompt_text: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[bool, str]:
    """
    Full pipeline to generate event from text:
    1. AI generates structured fields & game names.
    2. Box image(s) fetched from BoardGameGeek.
    3. Stitches collage if multiple games were requested.
    4. Guarantees message <= 1024 characters.
    5. Saves event in DB as pending and sends approval card to ADMIN_CHAT_ID.
    """
    try:
        event_data = generate_event_data_with_ai(prompt_text)
    except GeminiQuotaError as e:
        logger.error(f"Gemini quota depleted during /event_generate: {e}")
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=GEMINI_DEPLETED_ALERT)
        except Exception as send_err:
            logger.error(f"Failed to send quota alert to admin: {send_err}")
        return False, "Crediti Gemini AI esauriti. Impossibile generare l'evento."

    if not event_data:
        return False, "Impossibile interpretare l'evento con l'AI. Verifica il messaggio fornito."

    games = event_data.get("games", [])
    downloaded_images = []

    # Fetch box art from BGG
    for game in games:
        img_bytes = fetch_bgg_game_image(game)
        if img_bytes:
            downloaded_images.append(img_bytes)

    image_path = None
    if downloaded_images:
        norm_date = event_data.get("normalized_date")
        # Collage ONLY when multiple games were requested AND multiple images retrieved
        if len(games) > 1 and len(downloaded_images) > 1:
            collage_bytes = create_collage_from_bytes(downloaded_images)
            if collage_bytes:
                image_path = save_image_locally(collage_bytes, DATA_DIR, norm_date)
        else:
            # Single game or single retrieved image
            image_path = save_image_locally(downloaded_images[0], DATA_DIR, norm_date)

    # Enforce caption limit (1024 characters)
    final_text = enforce_caption_limit(event_data, max_length=1024)

    # Insert event into SQLite
    event_id = insert_event(event_data, image_path, original_text=prompt_text)
    if not event_id:
        logger.error("Failed to insert generated event into DB.")
        return False, "Errore durante il salvataggio dell'evento nel database."

    # Validate date anomalies
    warnings = validate_event_date_anomalies(event_data, raw_text=prompt_text)
    warning_block = ""
    if warnings:
        warning_block = "🚨 ATTENZIONE ANOMALIE DATA:\n" + "\n".join(warnings) + "\n👉 Usa /event_edit_date per correggere prima di approvare.\n\n"

    display_text = warning_block + final_text
    keyboard = get_approval_keyboard(event_id)

    admin_msg = None
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            if len(display_text) <= 1024:
                try:
                    admin_msg = await context.bot.send_photo(
                        chat_id=ADMIN_CHAT_ID,
                        photo=f,
                        caption=display_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"Error sending admin preview with HTML: {e}")
                    admin_msg = await context.bot.send_photo(
                        chat_id=ADMIN_CHAT_ID,
                        photo=f,
                        caption=display_text,
                        reply_markup=keyboard
                    )
            else:
                if warning_block:
                    try:
                        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=warning_block.strip())
                    except Exception as e:
                        logger.error(f"Error sending date warning message: {e}")
                photo_caption = final_text[:1024]
                try:
                    admin_msg = await context.bot.send_photo(
                        chat_id=ADMIN_CHAT_ID,
                        photo=f,
                        caption=photo_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"Error sending admin preview with HTML: {e}")
                    admin_msg = await context.bot.send_photo(
                        chat_id=ADMIN_CHAT_ID,
                        photo=f,
                        caption=photo_caption,
                        reply_markup=keyboard
                    )
    else:
        try:
            admin_msg = await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=display_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception:
            admin_msg = await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=display_text,
                reply_markup=keyboard
            )

    if admin_msg:
        update_event_field(event_id, "admin_message_id", admin_msg.message_id)

    return True, "Evento generato con successo e inviato in revisione."



async def event_generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles /event_generate and /eg commands in ADMIN_CHAT_ID.
    """
    msg = update.message if update.message is not None else (update.effective_message or update.channel_post)
    if not msg:
        return

    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        await msg.reply_text("Non sei autorizzato.")
        return

    admin_user = update.effective_user
    admin_identifier = (
        f"Admin {admin_user.id} (@{admin_user.username})"
        if getattr(admin_user, "username", None)
        else f"Admin {getattr(admin_user, 'id', 'unknown')}"
    )
    logger.info(f"{admin_identifier} triggered event generation (/event_generate).")

    # Extract text from command parameters or replied-to message
    prompt_text = None
    cmd_raw = msg.text or msg.caption or ""
    text_parts = cmd_raw.split(maxsplit=1)
    if len(text_parts) > 1 and text_parts[1].strip():
        prompt_text = text_parts[1].strip()

    if not prompt_text and msg.reply_to_message:
        replied = msg.reply_to_message
        prompt_text = replied.text or replied.caption

    if not prompt_text:
        await msg.reply_text(
            "ℹ️ **Uso del comando /event_generate:**\n"
            "Invia il comando seguito dai dettagli dell'evento, oppure rispondi a un messaggio.\n\n"
            "**Esempi:**\n"
            "`/event_generate Catan e Carcassonne, venerdì 10 ottobre ore 21, Host Destard, 4 posti`\n"
            "`/eg Root, domani alle 20:45, Host Marco`",
            parse_mode="Markdown",
        )
        return

    status_msg = await msg.reply_text("⏳ Generazione evento in corso con AI e BoardGameGeek...")

    success, msg_text = await process_event_generation(prompt_text, context)

    try:
        await status_msg.edit_text(f"{'✅' if success else '❌'} {msg_text}")
    except Exception:
        await msg.reply_text(f"{'✅' if success else '❌'} {msg_text}")

