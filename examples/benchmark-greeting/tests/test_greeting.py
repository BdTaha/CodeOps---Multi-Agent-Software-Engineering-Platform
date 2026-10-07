import unittest
from greeting import greet


class GreetingTests(unittest.TestCase):
    def test_trim_surrounding_spaces(self):
        self.assertEqual(greet(' Ada '), 'Hello Ada')

    def test_empty(self):
        self.assertEqual(greet(''), 'Hello ')

    def test_plain_name(self):
        self.assertEqual(greet('Ada'), 'Hello Ada')
