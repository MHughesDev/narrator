"""Speech-to-text (listen) track: WinRT recognition and text insertion."""

from __future__ import annotations

from .session import listen_worker_loop

__all__ = ["listen_worker_loop"]
