import os
import glob
import zipfile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from datetime import datetime
from core.db import get_pending_events_for_recap, mark_events_as_recap
from utils.image_utils import create_collage
from utils.templates import recap_generate_text
from core.config import ADMIN_CHAT_ID, DATA_DIR
from bot.keyboards import get_recap_approval_keyboard
from core.ai_parser import generate_wordpress_article
from core.wordpress import publish_article, upload_media
import asyncio

logger = logging.getLogger(__name__)

async def generate_daily_recap(bot, manual_date=None, is_manual=False, reply_to_message_id=None):
    now = datetime.now()
    # Check if it's Monday(0), Wednesday(2), Friday(4), Saturday(5), Sunday(6)
    if not is_manual and now.weekday() not in [0, 2, 4, 5, 6]:
        return False
        
    date_str = manual_date if manual_date else now.strftime("%d-%m-%Y")
    
    days_it = {
        "Monday": "Lunedì",
        "Tuesday": "Martedì",
        "Wednesday": "Mercoledì",
        "Thursday": "Giovedì",
        "Friday": "Venerdì",
        "Saturday": "Sabato",
        "Sunday": "Domenica"
    }
    if manual_date:
        try:
            target_dt = datetime.strptime(date_str, "%d-%m-%Y")
            day_str = days_it.get(target_dt.strftime("%A"), target_dt.strftime("%A"))
        except Exception:
            day_str = days_it.get(now.strftime("%A"), now.strftime("%A"))
    else:
        day_str = days_it.get(now.strftime("%A"), now.strftime("%A"))
    
    events = get_pending_events_for_recap(date_str)
    if not events:
        logger.info(f"No events pending for recap on {date_str}.")
        if is_manual and bot:
            msg = f"Nessun evento in programma per la data {date_str}." if (manual_date and manual_date != now.strftime("%d-%m-%Y")) else "Nessun evento in programma per oggi."
            if reply_to_message_id:
                try:
                    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, reply_to_message_id=reply_to_message_id)
                    return False
                except Exception as e:
                    logger.warning(f"Failed to reply with reply_to_message_id {reply_to_message_id}: {e}")
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
        return False
        
    # generate text
    recap_text = recap_generate_text(day_str, date_str, events)
    
    # generate collage
    image_paths = [ev['image_path'] for ev in events if ev['image_path']]
    collage_path = create_collage(image_paths, DATA_DIR, date_str)
    
    # send to admin
    keyboard = get_recap_approval_keyboard(date_str)
    
    caption_text = recap_text[:1024] if len(recap_text) > 1024 else recap_text
    
    if collage_path:
        try:
            with open(collage_path, 'rb') as f:
                await bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=f, caption=caption_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending recap collage photo to admin: {e}")
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption_text, reply_markup=keyboard, parse_mode="HTML")
        
    # Mark as recap to avoid duplicate in next recaps (or wait for approval?)
    # For now, mark them so they don't get picked up again immediately.
    event_ids = [ev['id'] for ev in events]
    mark_events_as_recap(event_ids)
    return True

async def archive_today_images():
    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")

    target_dir = os.path.join(DATA_DIR, year, month, day)
    if not os.path.exists(target_dir):
        logger.info(f"Archive: No folder found for today ({target_dir}).")
        return

    image_extensions = ("*.jpg", "*.jpeg", "*.png", "*.webp")
    image_files = []
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(target_dir, ext)))

    if not image_files:
        logger.info(f"Archive: No image files found in {target_dir} to archive.")
        return

    zip_path = os.path.join(target_dir, "archive.zip")
    logger.info(f"Archive: Zipping {len(image_files)} images into {zip_path}")

    try:
        with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as zipf:
            for img in image_files:
                arcname = os.path.basename(img)
                zipf.write(img, arcname)

        for img in image_files:
            try:
                os.remove(img)
            except Exception as e:
                logger.warning(f"Archive: Failed to delete {img}: {e}")

        logger.info(f"Archive: Successfully archived and removed {len(image_files)} images in {target_dir}.")
    except Exception as e:
        logger.error(f"Archive: Error creating zip archive in {target_dir}: {e}")

async def archive_completed_month_logs():
    try:
        from core.config import LOGS_DIR
        from core.log_utils import zip_completed_months
        archived = zip_completed_months(LOGS_DIR)
        if archived:
            logger.info(f"Archive: Zipped monthly log files: {archived}")
    except Exception as e:
        logger.error(f"Archive: Error checking and zipping monthly logs: {e}")

scheduler_instance = None

def start_scheduler(bot):
    global scheduler_instance
    scheduler_instance = AsyncIOScheduler()
    # Schedule to run every day at a specific time (e.g., 18:00)
    scheduler_instance.add_job(generate_daily_recap, 'cron', hour=18, minute=0, args=[bot])
    # Schedule daily image archive at 23:59
    scheduler_instance.add_job(archive_today_images, 'cron', hour=23, minute=59)
    # Schedule check and zipping of ended month logs daily at 00:05
    scheduler_instance.add_job(archive_completed_month_logs, 'cron', hour=0, minute=5)
    scheduler_instance.start()

def stop_scheduler():
    global scheduler_instance
    if scheduler_instance:
        scheduler_instance.shutdown()


