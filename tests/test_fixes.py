from datetime import date, datetime
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from bot.handlers import (
    event_next_command,
    event_edit_command,
    handle_event_extraction,
    extract_event_id_from_reply,
)
from core.scheduler import archive_today_images
from utils.templates import format_public_event_message


class TestPastEventsBookingDisable(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    async def test_archive_today_images_disables_booking_for_today_events(self):
        today_str = datetime.now().strftime("%d-%m-%Y")
        tomorrow_str = "30-12-2099"

        # Today's approved event with channel and discussion messages
        ev1_id = db.insert_event({
            "title": "Evento Oggi",
            "date": f"Oggi {today_str}",
            "normalized_date": today_str,
            "system": "D&D",
            "host": "Master",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Descrizione",
        }, None, "raw 1")
        db.update_event_status(ev1_id, "approved")
        db.update_telegram_message_info(ev1_id, 1001, "https://t.me/c/123/1001")
        db.update_discussion_message_info(ev1_id, 2001, "-100999999")

        # Tomorrow's approved event
        ev2_id = db.insert_event({
            "title": "Evento Futuro",
            "date": f"Domani {tomorrow_str}",
            "normalized_date": tomorrow_str,
            "system": "Pathfinder",
            "host": "Master 2",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Descrizione",
        }, None, "raw 2")
        db.update_event_status(ev2_id, "approved")
        db.update_telegram_message_info(ev2_id, 1002, "https://t.me/c/123/1002")
        db.update_discussion_message_info(ev2_id, 2002, "-100999999")

        bot = MagicMock()
        bot.edit_message_reply_markup = AsyncMock()

        with patch("core.scheduler.PUBLIC_CHANNEL_ID", "-100123456"), \
             patch("core.scheduler.DISCUSSION_GROUP_ID", "-100999999"):
            await archive_today_images(bot=bot)

        calls = bot.edit_message_reply_markup.call_args_list
        edited_msgs = [c.kwargs.get("message_id") for c in calls]
        self.assertIn(1001, edited_msgs)
        self.assertIn(2001, edited_msgs)
        self.assertNotIn(1002, edited_msgs)
        self.assertNotIn(2002, edited_msgs)

        for c in calls:
            self.assertIsNone(c.kwargs.get("reply_markup"))

    async def test_archive_today_images_without_bot_succeeds(self):
        await archive_today_images(bot=None)


class TestAdminEventPreviewAndLimits(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    async def test_handle_event_extraction_uses_final_form_with_emojis(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        sent_mock = MagicMock()
        sent_mock.message_id = 777
        context.bot.send_message.return_value = sent_mock

        parsed_data = {
            "is_event": True,
            "title": "Avventura Stellare",
            "date": "Venerdì 25-12-2026 21:00",
            "normalized_date": "25-12-2026",
            "system": "Starfinder",
            "host": "Capitano",
            "seats": "5/5",
            "booked_seats": 0,
            "max_seats": 5,
            "description": "Viaggio nello spazio profondo.",
            "is_roleplay": True,
        }

        with patch("bot.handlers.parse_event_message", return_value=parsed_data), \
             patch("bot.handlers.ADMIN_CHAT_ID", "999"):
            success = await handle_event_extraction(
                text="Evento Starfinder",
                image_bytes=None,
                context=context,
                is_manual_trigger=True,
            )

        self.assertTrue(success)
        context.bot.send_message.assert_called_once()
        sent_kwargs = context.bot.send_message.call_args.kwargs
        text = sent_kwargs.get("text", "")

        self.assertIn("📣 <b>Avventura Stellare</b>", text)
        self.assertIn("🎲 Sistema: Starfinder", text)
        self.assertIn("👑 Master: Capitano", text)
        self.assertIn("🪑 Posti: 5/5", text)
        self.assertEqual(sent_kwargs.get("parse_mode"), "HTML")

        ev = db.get_event(1)
        self.assertEqual(ev.get("admin_message_id"), 777)
    async def test_handle_event_extraction_warns_on_caption_over_1024_chars(self):
        context = MagicMock()
        sent_mock = MagicMock()
        sent_mock.message_id = 888
        context.bot.send_photo = AsyncMock(return_value=sent_mock)

        long_desc = "X" * 1100
        parsed_data = {
            "is_event": True,
            "title": "Evento Lunghissimo",
            "date": "Venerdì 25-12-2026 21:00",
            "normalized_date": "25-12-2026",
            "system": "D&D",
            "host": "Master",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": long_desc,
        }

        with patch("bot.handlers.parse_event_message", return_value=parsed_data), \
             patch("bot.handlers.ADMIN_CHAT_ID", "999"):
            success = await handle_event_extraction(
                text="Evento con testo lunghissimo",
                image_bytes=b"dummy_image_data",
                context=context,
                is_manual_trigger=True,
            )

        self.assertTrue(success)
        context.bot.send_photo.assert_called_once()
        caption = context.bot.send_photo.call_args.kwargs.get("caption", "")

        self.assertIn("🚨 ATTENZIONE LIMITE CARATTERI:", caption)
        self.assertIn("IL TESTO DELL'EVENTO SUPERA I 1024 CARATTERI", caption)
        self.assertLessEqual(len(caption), 1024)

    async def test_extract_event_id_from_reply_matches_admin_message_id(self):
        ev_id = db.insert_event({
            "title": "Test Admin Id Match",
            "date": "25-12-2026",
            "normalized_date": "25-12-2026",
        }, None, "raw")
        db.update_event_field(ev_id, "admin_message_id", 5555)

        reply_msg = MagicMock()
        reply_msg.reply_markup = None
        reply_msg.text = "Messaggio senza tag"
        reply_msg.caption = None
        reply_msg.message_id = 5555

        found_id = extract_event_id_from_reply(reply_msg)
        self.assertEqual(found_id, ev_id)
    def test_get_approval_keyboard_does_not_have_cancel_button(self):
        from bot.keyboards import get_approval_keyboard, get_approved_event_keyboard
        kb = get_approval_keyboard(42)
        all_callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("publish_event_42", all_callbacks)
        self.assertIn("discard_event_42", all_callbacks)
        self.assertNotIn("cancel_event_42", all_callbacks)

        # Approved keyboard must have cancel button
        approved_kb = get_approved_event_keyboard(42)
        approved_callbacks = [btn.callback_data for row in approved_kb.inline_keyboard for btn in row]
        self.assertIn("cancel_event_42", approved_callbacks)



class TestEventNextCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    async def test_event_next_command_non_admin_ignored(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.ADMIN_CHAT_ID", "-100999999"):
            await event_next_command(update, context)

        update.message.reply_text.assert_not_called()

    async def test_event_next_command_no_events(self):
        update = MagicMock()
        update.effective_chat.id = -100999999
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.ADMIN_CHAT_ID", "-100999999"):
            await event_next_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Nessun evento in programma", update.message.reply_text.call_args[0][0])

    async def test_event_next_command_lists_today_and_future_events(self):
        today_str = datetime.now().strftime("%d-%m-%Y")

        # 1. Past event (should NOT be included)
        ev_past_id = db.insert_event({
            "title": "Evento Passato",
            "date": "01-01-2020",
            "normalized_date": "01-01-2020",
        }, None, "raw past")
        db.update_event_status(ev_past_id, "approved")

        # 2. Today's event (SHOULD be included)
        ev_today_id = db.insert_event({
            "title": "Evento Di Oggi",
            "date": f"Oggi {today_str} ore 21:00",
            "normalized_date": today_str,
        }, None, "raw today")
        db.update_event_status(ev_today_id, "approved")
        db.update_event_field(ev_today_id, "admin_message_id", 301)
        db.update_discussion_message_info(ev_today_id, 401, "-100888888")

        # 3. Future pending event (SHOULD be included)
        ev_future_id = db.insert_event({
            "title": "Evento Futuro",
            "date": "Venerdì 25-12-2099",
            "normalized_date": "25-12-2099",
        }, None, "raw future")
        db.update_event_field(ev_future_id, "admin_message_id", 302)

        update = MagicMock()
        update.effective_chat.id = -100999999
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.ADMIN_CHAT_ID", "-100999999"), \
             patch("bot.handlers.DISCUSSION_GROUP_ID", "-100888888"):
            await event_next_command(update, context)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]

        self.assertNotIn("Evento Passato", reply_text)
        self.assertIn("Evento Di Oggi", reply_text)
        self.assertIn("Evento Futuro", reply_text)
        self.assertIn("[In attesa di approvazione]", reply_text)
        self.assertIn('https://t.me/c/999999/301', reply_text)
        self.assertIn('https://t.me/c/999999/302', reply_text)
        self.assertIn('https://t.me/c/888888/401', reply_text)

