from __future__ import annotations

import inspect
import unittest

import local_exchange
from local_exchange import (
    MAX_LOCAL_MESSAGES,
    MAX_LOCAL_MESSAGE_CHARS,
    RECEIVED_STATUS,
    SENT_STATUS,
    append_local_message,
)


class LocalExchangeTests(unittest.TestCase):
    def test_message_is_a_local_echo_with_both_explicit_statuses(self):
        original = []
        updated = append_local_message(original, "teaching-only text")
        self.assertEqual(original, [])  # The helper returns a new session-state value.
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["sent_status"], "Sent (local simulation)")
        self.assertEqual(updated[0]["received_status"], "Received (local simulation)")
        self.assertEqual(updated[0]["sent_status"], SENT_STATUS)
        self.assertEqual(updated[0]["received_status"], RECEIVED_STATUS)
        self.assertEqual(updated[0]["sent_message"], "teaching-only text")
        self.assertEqual(updated[0]["received_message"], "teaching-only text")

    def test_session_log_is_capped_at_ten_messages_and_rejects_an_eleventh(self):
        self.assertEqual(MAX_LOCAL_MESSAGES, 10)
        messages = []
        for index in range(MAX_LOCAL_MESSAGES):
            messages = append_local_message(messages, f"demo message {index + 1}")
        self.assertEqual(len(messages), 10)
        with self.assertRaisesRegex(ValueError, "capped at 10"):
            append_local_message(messages, "eleventh demo message")
        self.assertEqual(len(messages), 10)

    def test_message_validation_is_bounded(self):
        for invalid in ("", "  ", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                append_local_message([], invalid)
        with self.assertRaisesRegex(ValueError, "at most 240"):
            append_local_message([], "x" * (MAX_LOCAL_MESSAGE_CHARS + 1))

    def test_helper_has_no_network_logging_or_persistence_path(self):
        source = inspect.getsource(local_exchange)
        for forbidden in ("requests.", "urllib.request", "logging.", "open(", "Path(", "print("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
