import unittest
from validation import normalize_email


class Validation(unittest.TestCase):
    def test_normalizes(self):
        self.assertEqual(normalize_email(' Ada@Example.com '), 'ada@example.com')

    def test_rejects(self):
        for value in [None, '', 'bad', 'a b@example.com']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_email(value)
