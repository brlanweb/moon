"""Explicitly isolated settings for retirement and migration regression tests."""
from spug.settings import *  # noqa: F401,F403

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': ':memory:',
    'TEST': {'NAME': ':memory:'},
}}
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'retirement-tests',
}}
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
