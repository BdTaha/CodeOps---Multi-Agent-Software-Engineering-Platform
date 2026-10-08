"""Existing validation helper to reuse in registration."""
import re


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError('Email must be text')
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Invalid email')
    return email
