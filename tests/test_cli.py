import os
import unittest
from unittest.mock import patch

from pr_attention.cli import main


class CLITests(unittest.TestCase):
    def test_missing_token_is_bounded_error_for_snapshot(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main(["snapshot", "o/r", "1"]), 40)

    def test_missing_token_is_bounded_error_for_packet(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main(["review-packet", "o/r", "1", "--accepted-head", "a" * 40]), 70)


if __name__ == "__main__":
    unittest.main()
