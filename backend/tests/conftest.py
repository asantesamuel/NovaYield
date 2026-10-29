"""Provide a process-local CSRF signing key for HTTP tests without committing secrets."""

import os
from secrets import token_urlsafe

os.environ.setdefault("NOVAYIELD_CSRF_SECRET", token_urlsafe(32))
