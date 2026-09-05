import unittest
from unittest.mock import MagicMock, patch
from telegram.error import NetworkError
from main import global_error_handler

class TestGlobalErrorHandler(unittest.IsolatedAsyncioTestCase):
    async def test_network_error_logged_as_warning(self):
        context = MagicMock()
        context.error = NetworkError("Bad Gateway")
        update = MagicMock()

        with patch("main.logger") as mock_logger:
            await global_error_handler(update, context)
            mock_logger.warning.assert_called_once()
            args, _ = mock_logger.warning.call_args
            self.assertIn("transiente", args[0])
            self.assertIn("si risolve automaticamente", args[0])
            self.assertEqual(args[1], context.error)
            mock_logger.error.assert_not_called()

    async def test_general_exception_logged_as_error(self):
        context = MagicMock()
        context.error = ValueError("Something unexpected")
        update = MagicMock()

        with patch("main.logger") as mock_logger:
            await global_error_handler(update, context)
            mock_logger.error.assert_called_once()
            mock_logger.warning.assert_not_called()
            _, kwargs = mock_logger.error.call_args
            self.assertEqual(kwargs.get("exc_info"), context.error)
