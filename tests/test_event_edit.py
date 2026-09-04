import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db


class TestEventEditImageAndDiscard(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self.test_db_path
        db.init_db()

        self.initial_event = {
            "title": "Old Event",
            "date": "Venerdì 04-09-2026 21:00",
            "normalized_date": "04-09-2026",
            "system": "D&D 5e",
            "host": "Old Host",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Old Desc",
            "status": "pending",
            "image_path": None,
        }
        self.event_id = db.insert_event(self.initial_event, None, "test text")

    def tearDown(self):
        self.temp_dir.cleanup()
        db.DB_PATH = self.orig_db_path

    async def test_delete_event_cleans_event_and_reservations(self):
        from core.db import delete_event, get_event, get_reservations_for_event, book_seat

        book_seat(self.event_id, 12345, "testuser")
        self.assertIsNotNone(get_event(self.event_id))
        self.assertEqual(len(get_reservations_for_event(self.event_id)), 1)

        res = delete_event(self.event_id)
        self.assertTrue(res)
        self.assertIsNone(get_event(self.event_id))
        self.assertEqual(len(get_reservations_for_event(self.event_id)), 0)

    async def test_discard_event_callback_deletes_event_and_file(self):
        from bot.callbacks import handle_approval
        from core.db import get_event

        img_file = os.path.join(self.temp_dir.name, "dummy_event.png")
        with open(img_file, "wb") as f:
            f.write(b"dummy")
        db.update_event_field(self.event_id, "image_path", img_file)

        update = MagicMock()
        query = MagicMock()
        query.data = f"discard_event_{self.event_id}"
        query.message.caption = "Event Review Message"
        query.message.photo = True
        query.answer = AsyncMock()
        query.edit_message_caption = AsyncMock()
        update.callback_query = query
        context = MagicMock()

        await handle_approval(update, context)

        self.assertFalse(os.path.exists(img_file))
        self.assertIsNone(get_event(self.event_id))
        query.edit_message_caption.assert_called_once()
        self.assertIn("❌ SCARTATO", query.edit_message_caption.call_args.kwargs.get("caption", ""))

    async def test_event_edit_image_single_photo_reply(self):
        from bot.handlers import event_edit_command
        from core.db import get_event

        old_img = os.path.join(self.temp_dir.name, "old_image.png")
        with open(old_img, "wb") as f:
            f.write(b"old")
        db.update_event_field(self.event_id, "image_path", old_img)

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = None
        update.message.caption = "/event_edit_image"
        update.message.media_group_id = None
        update.message.reply_text = AsyncMock()

        p = MagicMock()
        p.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"new_image_data"))))
        update.message.photo = [p]

        target_msg = MagicMock()
        target_msg.photo = True
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        target_msg.edit_media = AsyncMock()
        update.message.reply_to_message = target_msg

        context = MagicMock()
        new_saved_path = os.path.join(self.temp_dir.name, "new_saved.png")
        with open(new_saved_path, "wb") as f:
            f.write(b"new_image_data")

        with patch("bot.handlers.ADMIN_CHAT_ID", "999"),              patch("bot.handlers.save_image_locally", return_value=new_saved_path),              patch("bot.handlers.update_event_messages", AsyncMock()):

            await event_edit_command(update, context)

        self.assertFalse(os.path.exists(old_img))
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_saved_path)
        target_msg.edit_media.assert_called_once()
        update.message.reply_text.assert_called_once()
        self.assertIn("Campo 'image_path' aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_with_event_id_argument(self):
        from bot.handlers import event_edit_command
        from core.db import get_event

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = f"/event_edit_image {self.event_id}"
        update.message.caption = None
        update.message.media_group_id = None
        update.message.photo = None
        update.message.reply_text = AsyncMock()

        photo_msg = MagicMock()
        p = MagicMock()
        p.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"photo_from_reply"))))
        photo_msg.photo = [p]
        photo_msg.reply_markup = None
        update.message.reply_to_message = photo_msg

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "new_from_arg.png")
        with open(new_path, "wb") as f:
            f.write(b"photo_from_reply")

        with patch("bot.handlers.ADMIN_CHAT_ID", "999"),              patch("bot.handlers.save_image_locally", return_value=new_path),              patch("bot.handlers.update_event_messages", AsyncMock()):

            await event_edit_command(update, context)

        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)
        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_media_group_album(self):
        from bot.handlers import event_edit_command, admin_media_groups
        from core.db import get_event

        admin_media_groups["album_edit_test"] = {
            "images": {
                301: bytearray(b"img1"),
                302: bytearray(b"img2")
            },
            "captions": {},
            "last_received": 0.0,
            "pending_downloads": 0
        }

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.caption = "/event_edit_image"
        update.message.text = None
        update.message.media_group_id = "album_edit_test"
        update.message.photo = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.photo = True
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        target_msg.edit_media = AsyncMock()
        update.message.reply_to_message = target_msg

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "collage.png")
        with open(new_path, "wb") as f:
            f.write(b"collage")

        with patch("bot.handlers.ADMIN_CHAT_ID", "999"),              patch("bot.handlers.create_collage_from_bytes", return_value=b"stitched_bytes") as mock_collage,              patch("bot.handlers.save_image_locally", return_value=new_path),              patch("bot.handlers.update_event_messages", AsyncMock()):

            await event_edit_command(update, context)

        mock_collage.assert_called_once_with([bytearray(b"img1"), bytearray(b"img2")])
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)

    async def test_event_edit_image_media_group_concurrent_arrival_waits_for_all_photos(self):
        """
        Simulate an admin sending an album with 3 photos where the 1st photo carries
        /event_edit_image <event_id> as caption.
        As the edit command begins, photo 2 and photo 3 arrive with slight delays.
        The handler must wait for the album photos, stitch all 3 into a collage,
        and update the event's image.
        """
        from bot.handlers import cache_admin_media_group, event_edit_command, admin_media_groups
        from core.db import get_event

        admin_media_groups.clear()
        mg_id = "concurrent_album_edit_test"

        # Setup Update 1 (first photo in album, has caption /event_edit_image <id>)
        update1 = MagicMock()
        update1.effective_chat.id = 999
        msg1 = MagicMock()
        msg1.message_id = 1001
        msg1.media_group_id = mg_id
        msg1.caption = f"/event_edit_image {self.event_id}"
        msg1.text = None
        msg1.reply_to_message = None
        msg1.reply_text = AsyncMock()
        photo1_file = MagicMock()
        photo1_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"photo1_raw"))
        photo1_mock = MagicMock()
        photo1_mock.get_file = AsyncMock(return_value=photo1_file)
        msg1.photo = [photo1_mock]
        msg1.document = None
        update1.message = msg1
        update1.effective_message = msg1

        # Setup Update 2 (second photo in album, no caption)
        update2 = MagicMock()
        update2.effective_chat.id = 999
        msg2 = MagicMock()
        msg2.message_id = 1002
        msg2.media_group_id = mg_id
        msg2.caption = None
        msg2.text = None
        msg2.reply_to_message = None
        photo2_file = MagicMock()
        photo2_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"photo2_raw"))
        photo2_mock = MagicMock()
        photo2_mock.get_file = AsyncMock(return_value=photo2_file)
        msg2.photo = [photo2_mock]
        msg2.document = None
        update2.message = msg2
        update2.effective_message = msg2

        # Setup Update 3 (third photo as image document in album, no caption)
        update3 = MagicMock()
        update3.effective_chat.id = 999
        msg3 = MagicMock()
        msg3.message_id = 1003
        msg3.media_group_id = mg_id
        msg3.caption = None
        msg3.text = None
        msg3.reply_to_message = None
        doc3_file = MagicMock()
        doc3_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"photo3_raw"))
        msg3.photo = None
        msg3.document = MagicMock()
        msg3.document.mime_type = "image/png"
        msg3.document.get_file = AsyncMock(return_value=doc3_file)
        update3.message = msg3
        update3.effective_message = msg3

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "concurrent_collage.png")
        with open(new_path, "wb") as f:
            f.write(b"concurrent_collage")

        # Simulate concurrent arrival:
        # 1. Update 1 is cached in group -1
        await cache_admin_media_group(update1, context)

        # 2. Asynchronously run delayed arrival of update 2 and update 3
        async def arrive_subsequent_updates():
            await asyncio.sleep(0.15)
            await cache_admin_media_group(update2, context)
            await asyncio.sleep(0.15)
            await cache_admin_media_group(update3, context)

        with patch("bot.handlers.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.create_collage_from_bytes", return_value=b"stitched_3_images") as mock_collage, \
             patch("bot.handlers.save_image_locally", return_value=new_path), \
             patch("bot.handlers.update_event_messages", AsyncMock()):

            task_arrive = asyncio.create_task(arrive_subsequent_updates())
            task_cmd = asyncio.create_task(event_edit_command(update1, context))
            await asyncio.gather(task_arrive, task_cmd)

        mock_collage.assert_called_once_with([bytearray(b"photo1_raw"), bytearray(b"photo2_raw"), bytearray(b"photo3_raw")])
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)

    async def test_event_edit_image_waits_for_media_group_entry_if_called_early(self):
        """
        If event_edit_command starts before cache_admin_media_group registers the
        entry in admin_media_groups, _get_media_group_data_from_cache should wait
        until the entry is created rather than immediately returning None.
        """
        from bot.handlers import cache_admin_media_group, event_edit_command, admin_media_groups
        from core.db import get_event

        admin_media_groups.clear()
        mg_id = "early_entry_test"

        update1 = MagicMock()
        update1.effective_chat.id = 999
        msg1 = MagicMock()
        msg1.message_id = 2001
        msg1.media_group_id = mg_id
        msg1.caption = f"/event_edit_image {self.event_id}"
        msg1.text = None
        msg1.reply_to_message = None
        msg1.reply_text = AsyncMock()
        photo1_file = MagicMock()
        photo1_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"early_raw1"))
        photo1_mock = MagicMock()
        photo1_mock.get_file = AsyncMock(return_value=photo1_file)
        msg1.photo = [photo1_mock]
        msg1.document = None
        update1.message = msg1
        update1.effective_message = msg1

        update2 = MagicMock()
        update2.effective_chat.id = 999
        msg2 = MagicMock()
        msg2.message_id = 2002
        msg2.media_group_id = mg_id
        msg2.caption = None
        msg2.text = None
        msg2.reply_to_message = None
        photo2_file = MagicMock()
        photo2_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"early_raw2"))
        photo2_mock = MagicMock()
        photo2_mock.get_file = AsyncMock(return_value=photo2_file)
        msg2.photo = [photo2_mock]
        msg2.document = None
        update2.message = msg2
        update2.effective_message = msg2

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "early_collage.png")
        with open(new_path, "wb") as f:
            f.write(b"early_collage")

        # Note: we do NOT call cache_admin_media_group(update1) beforehand!
        # Both updates arrive slightly after event_edit_command starts.
        async def delayed_both_updates():
            await asyncio.sleep(0.1)
            await cache_admin_media_group(update1, context)
            await asyncio.sleep(0.15)
            await cache_admin_media_group(update2, context)

        with patch("bot.handlers.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.create_collage_from_bytes", return_value=b"early_stitched") as mock_collage, \
             patch("bot.handlers.save_image_locally", return_value=new_path), \
             patch("bot.handlers.update_event_messages", AsyncMock()):

            task_arrive = asyncio.create_task(delayed_both_updates())
            task_cmd = asyncio.create_task(event_edit_command(update1, context))
            await asyncio.gather(task_arrive, task_cmd)

        mock_collage.assert_called_once_with([bytearray(b"early_raw1"), bytearray(b"early_raw2")])
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)

    async def test_event_edit_image_missing_photo_shows_error(self):
        from bot.handlers import event_edit_command

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_edit_image"
        update.message.caption = None
        update.message.media_group_id = None
        update.message.photo = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.photo = False
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        update.message.reply_to_message = target_msg

        context = MagicMock()
        with patch("bot.handlers.ADMIN_CHAT_ID", "999"):
            await event_edit_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Devi allegare un'immagine", update.message.reply_text.call_args[0][0])

    async def test_event_edit_on_discarded_event_reports_not_found(self):
        from bot.handlers import event_edit_command
        from core.db import delete_event

        delete_event(self.event_id)

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_edit_title Nuovo Titolo"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        update.message.reply_to_message = target_msg
        context = MagicMock()

        with patch("bot.handlers.ADMIN_CHAT_ID", "999"):
            await event_edit_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("non trovato nel database", update.message.reply_text.call_args[0][0])
    def test_extract_event_id_from_reply_various_formats(self):
        from bot.handlers import extract_event_id_from_reply

        # 1. Button callback formats
        prefixes = ["publish_event_42", "cancel_event_42", "book_42", "unbook_42", "manage_subs_42", "sub_inc_42_1"]
        for p in prefixes:
            msg = MagicMock()
            btn = MagicMock(callback_data=p)
            msg.reply_markup.inline_keyboard = [[btn]]
            msg.caption = None
            msg.text = None
            msg.message_id = 9999
            self.assertEqual(extract_event_id_from_reply(msg), 42)

        # 2. Caption/text regex
        msg_text = MagicMock()
        msg_text.reply_markup = None
        msg_text.caption = None
        msg_text.text = "Modifica per evento #42"
        msg_text.message_id = 9999
        self.assertEqual(extract_event_id_from_reply(msg_text), 42)

        msg_hash = MagicMock()
        msg_hash.reply_markup = None
        msg_hash.caption = "#42 Dettagli tavolo"
        msg_hash.text = None
        msg_hash.message_id = 9999
        self.assertEqual(extract_event_id_from_reply(msg_hash), 42)

    async def test_extract_image_bytes_from_document_mime(self):
        from bot.handlers import _extract_image_bytes_from_update

        update = MagicMock()
        update.message.media_group_id = None
        update.message.photo = None
        doc = MagicMock()
        doc.mime_type = "image/png"
        doc.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"doc_img"))))
        update.message.document = doc
        update.message.reply_to_message = None

        res = await _extract_image_bytes_from_update(update)
        self.assertEqual(res, bytearray(b"doc_img"))

    def test_caption_command_matching_and_handler_registration(self):
        from telegram.ext import filters
        from telegram import Update, Message, Chat, User
        import datetime

        regex_filter = filters.CaptionRegex(r"^/event_edit_")
        m = Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=Chat(id=1, type="group"),
            from_user=User(id=1, is_bot=False, first_name="User"),
            caption="/event_edit_image"
        )
        u = Update(update_id=1, message=m)
        self.assertTrue(regex_filter.check_update(u))

        # CommandHandler must NOT match message captions (by design of PTB)
        from telegram.ext import CommandHandler
        ch = CommandHandler("event_edit_image", lambda u, c: None)
        self.assertFalse(ch.check_update(u))

    def test_main_admin_handlers_configured_block_false(self):
        from main import main
        from bot.handlers import event_edit_command, manual_trigger_command, cache_admin_media_group

        added_handlers = []
        mock_app = MagicMock()
        mock_app.add_handler.side_effect = lambda h, group=0: added_handlers.append((h, group))
        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.post_init.return_value = mock_builder
        mock_builder.post_shutdown.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch("main.init_db"), \
             patch("main.Application.builder", return_value=mock_builder), \
             patch("main.ADMIN_CHAT_ID", "999"), \
             patch("main.TELEGRAM_BOT_TOKEN", "fake_token"):
            try:
                main()
            except Exception:
                pass

        matched = 0
        for handler, group in added_handlers:
            cb = getattr(handler, "callback", None)
            if cb in (event_edit_command, manual_trigger_command, cache_admin_media_group):
                self.assertFalse(handler.block, f"Handler {handler} with callback {cb} should have block=False")
                matched += 1

        # We expect:
        # event_process (1), ep (1), 10 edit_cmds (10), CaptionRegex event_edit_ (1), CaptionRegex ep (1), cache_admin_media_group (1)
        self.assertGreaterEqual(matched, 15)



if __name__ == "__main__":
    unittest.main()
