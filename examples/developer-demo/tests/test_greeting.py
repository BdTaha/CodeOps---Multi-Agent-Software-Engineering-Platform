"""Existing behavior checks for the trusted local development demo."""
import unittest

from greeting import greet


class GreetingTests(unittest.TestCase):
    def test_plain_name(self):
        self.assertEqual(greet("Ada"), "Hello Ada")

    def test_empty_name(self):
        self.assertEqual(greet(""), "Hello ")


if __name__ == "__main__":
    unittest.main()
