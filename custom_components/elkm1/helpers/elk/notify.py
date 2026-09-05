"""Observer dispatch for decoded ELK-M1 messages and lifecycle events."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

NotifyHandler = Callable[..., None]
_LOGGER = logging.getLogger(__name__)


class Notifier:
    """Register handlers by message/event type and dispatch to them."""

    def __init__(self) -> None:
        self._observers: dict[str, list[NotifyHandler]] = {}

    def attach(self, notify_type: str, handler: NotifyHandler) -> None:
        """Add a handler for a message/event type."""
        handlers = self._observers.setdefault(notify_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def detach(self, notify_type: str, handler: NotifyHandler) -> None:
        """Remove a handler for a message/event type."""
        handlers = self._observers.get(notify_type)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def notify(self, notify_type: str, notify_parameters: dict[str, Any]) -> None:
        """Call every handler registered for this message/event type.

        The handler list is copied first since a handler may add/remove
        handlers of its own type while being called.
        """
        for observer in list(self._observers.get(notify_type, [])):
            try:
                observer(**notify_parameters)
            except Exception:
                _LOGGER.exception("Unhandled error in %s handler", notify_type)
