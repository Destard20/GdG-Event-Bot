import os
import glob
import zipfile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from datetime import datetime
from core.db import get_pending_events_for_recap, mark_events_as_recap
from utils.image_utils import create_collage
from utils.templates import recap_generate_text
from core.config import ADMIN_CHAT_ID, DATA_DIR, PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID
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
    
    logger.info(f"Scheduler: Generating daily recap (manual={is_manual}, date={date_str})...")
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
            err_str = str(e).lower()
            sent_retry = False
            if "photo_invalid_dimensions" in err_str or "dimensions" in err_str or "too large" in err_str:
                try:
                    logger.info("Attempting emergency recompression of recap collage...")
                    from utils.image_utils import compress_existing_image_file
                    fallback_path = compress_existing_image_file(collage_path, max_dim_sum=5000, max_single_dim=3000, target_max_bytes=1_000_000)
                    if fallback_path:
                        with open(fallback_path, 'rb') as f:
                            await bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=f, caption=caption_text, reply_markup=keyboard, parse_mode="HTML")
                        sent_retry = True
                except Exception as retry_err:
                    logger.error(f"Error sending emergency re-compressed recap collage photo: {retry_err}")

            if not sent_retry:
                await bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption_text, reply_markup=keyboard, parse_mode="HTML")
        
    # Mark as recap to avoid duplicate in next recaps (or wait for approval?)
    # For now, mark them so they don't get picked up again immediately.
    event_ids = [ev['id'] for ev in events]
    mark_events_as_recap(event_ids)
    logger.info(f"Scheduler: Daily recap successfully generated and sent to admin for date {date_str} ({len(events)} events).")
    return True

async def archive_today_images(bot=None):
    logger.info("Scheduler: Starting archive_today_images job...")
    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")

    target_dir = os.path.join(DATA_DIR, year, month, day)
    if not os.path.exists(target_dir):
        logger.info(f"Archive: No folder found for today ({target_dir}).")
    else:
        image_extensions = ("*.jpg", "*.jpeg", "*.png", "*.webp")
        image_files = []
        for ext in image_extensions:
            image_files.extend(glob.glob(os.path.join(target_dir, ext)))

        if not image_files:
            logger.info(f"Archive: No image files found in {target_dir} to archive.")
        else:
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

    # Disable booking for today's events at 23:59
    if bot:
        logger.info("Scheduler: Disabling bookings for today's events...")
        try:
            from core.db import get_approved_events_for_date

            today_str = now.strftime("%d-%m-%Y")
            today_events = get_approved_events_for_date(today_str)
            for ev in today_events:
                ev_id = ev['id']
                # 1. Update public channel message
                if PUBLIC_CHANNEL_ID and ev.get('telegram_message_id'):
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=PUBLIC_CHANNEL_ID,
                            message_id=ev['telegram_message_id'],
                            reply_markup=None
                        )
                        logger.info(f"Scheduler: Removed booking keyboard from public channel for event #{ev_id}.")
                    except Exception as e:
                        if "not modified" not in str(e).lower() and "message to edit not found" not in str(e).lower():
                            logger.error(f"Scheduler: Error removing booking keyboard in public channel for event #{ev_id}: {e}")

                # 2. Update discussion group message
                disc_chat_id = ev.get('discussion_chat_id') or DISCUSSION_GROUP_ID
                if disc_chat_id and ev.get('discussion_message_id'):
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=int(disc_chat_id),
                            message_id=ev['discussion_message_id'],
                            reply_markup=None
                        )
                        logger.info(f"Scheduler: Removed booking keyboard from discussion group for event #{ev_id}.")
                    except Exception as e:
                        if "not modified" not in str(e).lower() and "message to edit not found" not in str(e).lower():
                            logger.error(f"Scheduler: Error removing booking keyboard in discussion group for event #{ev_id}: {e}")
        except Exception as e:
            logger.error(f"Scheduler: Error disabling bookings for today's events: {e}")

async def archive_completed_month_logs():
    logger.info("Scheduler: Starting archive_completed_month_logs job...")
    try:
        from core.config import LOGS_DIR
        from core.log_utils import zip_completed_months
        archived = zip_completed_months(LOGS_DIR)
        if archived:
            logger.info(f"Archive: Zipped monthly log files: {archived}")
        else:
            logger.info("Archive: No completed month logs needed archiving.")
    except Exception as e:
        logger.error(f"Archive: Error checking and zipping monthly logs: {e}")

async def send_daily_scheduled_reposts(bot):
    """
    Runs daily at 10:00 AM.
    Checks DB for scheduled events matching today (by recurring day or specific date),
    and sends a summary notification to ADMIN_CHAT_ID with invoke commands.
    """
    if not bot or not ADMIN_CHAT_ID:
        return

    now = datetime.now()
    days_it = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    weekday_it = days_it[now.weekday()]
    today_str = now.strftime("%d-%m-%Y")

    logger.info(f"Scheduler: Checking scheduled reposts for today ({weekday_it} {today_str})...")
    from core.db import get_scheduled_events_for_date
    events = get_scheduled_events_for_date(today_str, weekday_it)

    if not events:
        logger.info(f"Scheduler: No events scheduled for reposting on {today_str}.")
        return

    lines = [
        f"📅 <b>Eventi programmati per il reposting di oggi ({weekday_it} {today_str}):</b>\n"
    ]
    for ev in events:
        sched_id = ev['id']
        title = ev.get('title') or "Evento"
        lines.append(
            f"• <b>{title}</b> (ID #{sched_id})\n"
            f"  👉 Invia per preparare il post: <code>/event_repost_invoke {sched_id}</code>\n"
        )

    lines.append(
        "💡 <i>Promemoria:</i> Puoi aggiornare il contenuto di un evento programmato rispondendo a un messaggio con il nuovo testo/locandina e usando:\n"
        "<code>/event_repost_update ID</code>"
    )

    msg_text = "\n".join(lines)
    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg_text, parse_mode="HTML")
        logger.info(f"Scheduler: Sent today's scheduled reposts notification ({len(events)} events) to admin chat.")
    except Exception as e:
        logger.error(f"Scheduler: Failed to send scheduled reposts notification to admin chat: {e}")

scheduler_instance = None

def start_scheduler(bot):
    global scheduler_instance
    scheduler_instance = AsyncIOScheduler()
    # Schedule check and notification of today's scheduled reposts at 10:00 AM
    scheduler_instance.add_job(send_daily_scheduled_reposts, 'cron', hour=10, minute=0, args=[bot])
    # Schedule to run every day at a specific time (e.g., 16:00)
    scheduler_instance.add_job(generate_daily_recap, 'cron', hour=16, minute=0, args=[bot])
    # Schedule daily image archive at 23:59 and disable booking for today's events
    scheduler_instance.add_job(archive_today_images, 'cron', hour=23, minute=59, args=[bot])
    # Schedule check and zipping of ended month logs daily at 00:05
    scheduler_instance.add_job(archive_completed_month_logs, 'cron', hour=0, minute=5)
    scheduler_instance.start()

def stop_scheduler():
    global scheduler_instance
    if scheduler_instance:
        scheduler_instance.shutdown()


