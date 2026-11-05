"""Provide process-local application secrets for tests without committing them."""

import os
from secrets import token_urlsafe

os.environ.setdefault("NOVAYIELD_CSRF_SECRET", token_urlsafe(32))
os.environ.setdefault("NOVAYIELD_LOCATION_HASH_SECRET", token_urlsafe(32))
