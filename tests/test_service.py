import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from telegram.error import BadRequest, RetryAfter
from bot.service import _execute_with_retry, update_event_messages

class TestService(unittest.IsolatedAsyncioTestCase):
    async def test_execute_with_retry_success(self):
        mock_coro = AsyncMock(return_value="done")
        result = await _execute_with_retry(lambda: mock_coro())
        self.assertEqual(result, "done")
        mock_coro.assert_called_once()

    async def test_execute_with_retry_handles_retry_after(self):
        mock_coro = AsyncMock(side_effect=[RetryAfter(0.01), "success"])
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await _execute_with_retry(lambda: mock_coro(), max_retries=2)
            self.assertEqual(result, "success")
            self.assertEqual(mock_coro.call_count, 2)
            mock_sleep.assert_called_once_with(0.01)

    async def test_execute_with_retry_exceeds_max_retries(self):
        mock_coro = AsyncMock(side_effect=RetryAfter(0.01))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(RetryAfter):
                await _execute_with_retry(lambda: mock_coro(), max_retries=2)
        self.assertEqual(mock_coro.call_count, 3)

    async def test_execute_with_retry_raises_other_exception_immediately(self):
        mock_coro = AsyncMock(side_effect=ValueError("other error"))
        with self.assertRaises(ValueError):
            await _execute_with_retry(lambda: mock_coro(), max_retries=2)
        self.assertEqual(mock_coro.call_count, 1)

    async def test_update_event_messages_caption_success(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": 123,
            "image_path": "path/to/img.png",
            "discussion_message_id": None,
            "discussion_chat_id": None
        }
        context = MagicMock()
        context.bot.edit_message_caption = AsyncMock()
        context.bot.edit_message_text = AsyncMock()

        with patch("bot.service.PUBLIC_CHANNEL_ID", "-100123"):
            await update_event_messages(context, event_id=1, event=event)

        context.bot.edit_message_caption.assert_called_once()
        context.bot.edit_message_text.assert_not_called()
    async def test_update_event_messages_caption_not_modified_ignored(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": 123,
            "image_path": "path/to/img.png",
        }
        context = MagicMock()
        context.bot.edit_message_caption = AsyncMock(
            side_effect=BadRequest("Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message")
        )
        context.bot.edit_message_text = AsyncMock()

        with patch("bot.service.PUBLIC_CHANNEL_ID", "-100123"), \
             patch("bot.service.logger") as mock_logger:
            await update_event_messages(context, event_id=1, event=event)

        context.bot.edit_message_caption.assert_called_once()
        context.bot.edit_message_text.assert_not_called()
        mock_logger.error.assert_not_called()

    async def test_update_event_messages_caption_fallback_to_text(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": 123,
            "image_path": "path/to/img.png",
        }
        context = MagicMock()
        context.bot.edit_message_caption = AsyncMock(
            side_effect=BadRequest("Bad Request: there is no caption in the message to edit")
        )
        context.bot.edit_message_text = AsyncMock()

        with patch("bot.service.PUBLIC_CHANNEL_ID", "-100123"):
            await update_event_messages(context, event_id=1, event=event)

        context.bot.edit_message_caption.assert_called_once()
        context.bot.edit_message_text.assert_called_once()

    async def test_update_event_messages_caption_does_not_fallback_on_unrelated_error(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": 123,
            "image_path": "path/to/img.png",
        }
        context = MagicMock()
        context.bot.edit_message_caption = AsyncMock(
            side_effect=BadRequest("Bad Request: chat not found")
        )
        context.bot.edit_message_text = AsyncMock()

        with patch("bot.service.PUBLIC_CHANNEL_ID", "-100123"), \
             patch("bot.service.logger") as mock_logger:
            await update_event_messages(context, event_id=1, event=event)

        context.bot.edit_message_caption.assert_called_once()
        context.bot.edit_message_text.assert_not_called()
        mock_logger.error.assert_called_once()
        self.assertIn("chat not found", str(mock_logger.error.call_args).lower())

    async def test_update_event_messages_text_fallback_to_caption(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": 123,
            "image_path": None,
        }
        context = MagicMock()
        context.bot.edit_message_text = AsyncMock(
            side_effect=BadRequest("Bad Request: there is no text in the message to edit")
        )
        context.bot.edit_message_caption = AsyncMock()

        with patch("bot.service.PUBLIC_CHANNEL_ID", "-100123"):
            await update_event_messages(context, event_id=1, event=event)

        context.bot.edit_message_text.assert_called_once()
        context.bot.edit_message_caption.assert_called_once()

    async def test_update_event_messages_text_does_not_fallback_on_unrelated_error(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": 123,
            "image_path": None,
        }
        context = MagicMock()
        context.bot.edit_message_text = AsyncMock(
            side_effect=BadRequest("Bad Request: chat not found")
        )
        context.bot.edit_message_caption = AsyncMock()

        with patch("bot.service.PUBLIC_CHANNEL_ID", "-100123"), \
             patch("bot.service.logger") as mock_logger:
            await update_event_messages(context, event_id=1, event=event)

        context.bot.edit_message_text.assert_called_once()
        context.bot.edit_message_caption.assert_not_called()
        mock_logger.error.assert_called_once()

    async def test_update_event_messages_retries_channel_caption_on_flood_control(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": 123,
            "image_path": "path/to/img.png",
        }
        context = MagicMock()
        context.bot.edit_message_caption = AsyncMock(
            side_effect=[RetryAfter(0.01), MagicMock()]
        )
        context.bot.edit_message_text = AsyncMock()

        with patch("bot.service.PUBLIC_CHANNEL_ID", "-100123"), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await update_event_messages(context, event_id=1, event=event)

        self.assertEqual(context.bot.edit_message_caption.call_count, 2)
        mock_sleep.assert_called_once_with(0.01)
        context.bot.edit_message_text.assert_not_called()

    async def test_update_event_messages_discussion_retries_on_flood_control(self):
        event = {
            "id": 1,
            "title": "Test Event",
            "date": "2026-10-10",
            "status": "approved",
            "telegram_message_id": None,
            "discussion_message_id": 999,
            "discussion_chat_id": -100456,
        }
        context = MagicMock()
        context.bot.edit_message_reply_markup = AsyncMock(
            side_effect=[RetryAfter(0.01), MagicMock()]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await update_event_messages(context, event_id=1, event=event)

        self.assertEqual(context.bot.edit_message_reply_markup.call_count, 2)
        mock_sleep.assert_called_once_with(0.01)

