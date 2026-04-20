"""Cursor CLI chat store path (same rules as pragma-agent session_capture)."""

from __future__ import annotations

import os
from pathlib import Path


def get_cursor_cli_chats_path() -> Path:
    """Return the Cursor CLI chats directory.

    Override with ``CLI_CHATS_PATH`` (absolute or ``~``); default ``~/.cursor/chats``.
    """
    env_path = os.environ.get("CLI_CHATS_PATH", "").strip()
    if env_path:
        return Path(os.path.expanduser(env_path))
    return Path.home() / ".cursor" / "chats"
