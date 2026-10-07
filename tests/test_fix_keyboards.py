import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from telegram.error import BadRequest
from scripts.fix_event_keyboards import fix_keyboards


class TestFixKeyboardsScript(unittest.IsolatedAsyncioTestCase):

    @patch("scripts.fix_event_keyboards.get_connection")
    @patch("scripts.fix_event_keyboards.Bot")
    async def test_fix_keyboards_dry_run(self, mock_bot_cls, mock_get_conn):
        mock_bot = MagicMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="GdG_Event_bot", id=12345))
        mock_bot.edit_message_reply_markup = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": 10,
                "title": "Catan",
                "status": "approved",
                "normalized_date": "25-12-2099",
                "telegram_message_id": 200,
                "discussion_message_id": 300,
                "discussion_chat_id": "-100111",
                "admin_message_id": 400,
                "max_seats": 4,
                "booked_seats": 1,
            }
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        await fix_keyboards(dry_run=True, delay=0)

        # In dry run, edit_message_reply_markup must not be called
        mock_bot.edit_message_reply_markup.assert_not_called()

    @patch("scripts.fix_event_keyboards.get_connection")
    @patch("scripts.fix_event_keyboards.Bot")
    async def test_fix_keyboards_filters_approved_status_by_default(self, mock_bot_cls, mock_get_conn):
        mock_bot = MagicMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="GdG_Event_bot", id=12345))
        mock_bot_cls.return_value = mock_bot

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        await fix_keyboards(dry_run=True, delay=0)

        query, params = mock_cursor.execute.call_args[0]
        self.assertIn("status = ?", query)
        self.assertEqual(params, ("approved",))


    @patch("scripts.fix_event_keyboards.get_connection")
    @patch("scripts.fix_event_keyboards.Bot")
    async def test_fix_keyboards_updates_all_targets(self, mock_bot_cls, mock_get_conn):
        mock_bot = MagicMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="GdG_Event_bot", id=12345))
        mock_bot.edit_message_reply_markup = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": 25,
                "title": "Wingspan",
                "status": "approved",
                "normalized_date": "25-12-2099",
                "telegram_message_id": 101,
                "discussion_message_id": 202,
                "discussion_chat_id": "-100222",
                "admin_message_id": 303,
                "max_seats": 5,
                "booked_seats": 0,
            }
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        with patch("scripts.fix_event_keyboards.PUBLIC_CHANNEL_ID", "-100999"), \
             patch("scripts.fix_event_keyboards.ADMIN_CHAT_ID", "-100888"):
            await fix_keyboards(dry_run=False, delay=0)

        # Expect 3 calls: channel, discussion, admin
        self.assertEqual(mock_bot.edit_message_reply_markup.call_count, 3)

        # Channel call
        call_channel = mock_bot.edit_message_reply_markup.call_args_list[0]
        self.assertEqual(call_channel.kwargs["chat_id"], "-100999")
        self.assertEqual(call_channel.kwargs["message_id"], 101)

        # Discussion call
        call_disc = mock_bot.edit_message_reply_markup.call_args_list[1]
        self.assertEqual(call_disc.kwargs["chat_id"], -100222)
        self.assertEqual(call_disc.kwargs["message_id"], 202)

        # Admin call
        call_admin = mock_bot.edit_message_reply_markup.call_args_list[2]
        self.assertEqual(call_admin.kwargs["chat_id"], -100888)
        self.assertEqual(call_admin.kwargs["message_id"], 303)

    @patch("scripts.fix_event_keyboards.get_connection")
    @patch("scripts.fix_event_keyboards.Bot")
    async def test_fix_keyboards_not_modified_ignored(self, mock_bot_cls, mock_get_conn):
        mock_bot = MagicMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="GdG_Event_bot", id=12345))
        mock_bot.edit_message_reply_markup = AsyncMock(
            side_effect=BadRequest("Message is not modified: specified new message content and reply markup are exactly the same")
        )
        mock_bot_cls.return_value = mock_bot

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": 5,
                "title": "Root",
                "status": "approved",
                "normalized_date": "25-12-2099",
                "telegram_message_id": 105,
                "discussion_message_id": None,
                "admin_message_id": None,
            }
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        with patch("scripts.fix_event_keyboards.PUBLIC_CHANNEL_ID", "-100999"):
            # Should not raise exception
            await fix_keyboards(dry_run=False, delay=0)

        mock_bot.edit_message_reply_markup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
