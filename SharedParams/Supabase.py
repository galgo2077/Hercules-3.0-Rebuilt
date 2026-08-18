"""Supabase client singleton — reads URL and anon key from environment."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


@lru_cache(maxsize=1)
def get_client() -> "Client":
    """Return a cached Supabase client.

    Requires env vars SUPABASE_URL and SUPABASE_ANON_KEY.
    """
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_ANON_KEY"]
    return create_client(url, key)


@lru_cache(maxsize=1)
def get_service_client() -> "Client":
    """Service-role client — elevated permissions for server-side ops."""
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)
