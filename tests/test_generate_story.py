import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.generate_story import (
    list_events,
    generate_event_story,
    send_story_to_telegram,
    publish_story_to_instagram,
)


class TestGenerateStoryScript(unittest.IsolatedAsyncioTestCase):

    @patch("scripts.generate_story.get_connection")
    def test_list_events(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "title": "Dungeons & Dragons",
                "date": "Lunedì 7 Settembre",
                "normalized_date": "07-09-2026",
                "status": "approved",
                "booked_seats": 3,
                "max_seats": 5,
                "image_path": None,
            }
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        with patch("builtins.print") as mock_print:
            list_events()
            printed_text = " ".join([str(call.args[0]) for call in mock_print.call_args_list if call.args])
            self.assertIn("Dungeons & Dragons", printed_text)
            self.assertIn("approved", printed_text)

    @patch("scripts.generate_story.get_event")
    @patch("scripts.generate_story.create_story_image")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_generate_event_story_success(self, mock_size, mock_exists, mock_create, mock_get_event):
        mock_get_event.return_value = {
            "id": 42,
            "title": "Call of Cthulhu",
            "date": "Venerdì 11 Settembre ore 21:00",
            "normalized_date": "11-09-2026",
            "system": "CoC 7th",
            "booked_seats": 2,
            "max_seats": 4,
            "status": "approved",
            "image_path": "/fake/path/event.jpg",
        }
        mock_exists.return_value = True
        mock_size.return_value = 102400
        mock_create.return_value = "/fake/path/story_42.jpg"

        story_path, event = generate_event_story(42)
        self.assertEqual(story_path, "/fake/path/story_42.jpg")
        self.assertEqual(event["title"], "Call of Cthulhu")
        mock_create.assert_called_once()

    @patch("scripts.generate_story.get_event")
    def test_generate_event_story_not_found(self, mock_get_event):
        mock_get_event.return_value = None

        story_path, event = generate_event_story(9999)
        self.assertIsNone(story_path)
        self.assertIsNone(event)

    @patch("scripts.generate_story.TELEGRAM_BOT_TOKEN", "fake_token")
    @patch("scripts.generate_story.ADMIN_CHAT_ID", "-100999")
    @patch("telegram.Bot")
    @patch("builtins.open")
    async def test_send_story_to_telegram(self, mock_open, mock_bot_cls):
        mock_bot = MagicMock()
        mock_bot.send_photo = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        event = {"id": 1, "title": "Test Event", "date": "Oggi", "system": "GURPS"}
        ok = await send_story_to_telegram("/fake/story.jpg", event)
        self.assertTrue(ok)
        mock_bot.send_photo.assert_called_once()

    @patch("scripts.generate_story.WP_URL", "https://example.com")
    @patch("scripts.generate_story.WP_USERNAME", "admin")
    @patch("scripts.generate_story.WP_APP_PASSWORD", "secret")
    @patch("scripts.generate_story.IG_ACCESS_TOKEN", "token")
    @patch("scripts.generate_story.IG_ACCOUNT_ID", "12345")
    @patch("core.wordpress.upload_media")
    @patch("core.instagram.publish_instagram_story", new_callable=AsyncMock)
    async def test_publish_story_to_instagram(self, mock_ig, mock_wp):
        mock_wp.return_value = {"id": 10, "source_url": "https://example.com/wp-content/story.jpg"}
        mock_ig.return_value = (True, "Storia pubblicata con successo!")

        ok = await publish_story_to_instagram("/fake/story.jpg")
        self.assertTrue(ok)
        mock_wp.assert_called_once_with("/fake/story.jpg")
        mock_ig.assert_called_once_with("https://example.com/wp-content/story.jpg")
