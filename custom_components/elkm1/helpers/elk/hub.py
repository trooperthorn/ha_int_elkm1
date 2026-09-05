"""The `Elk` hub: ties the connection, notifier, and every element collection
together, and drives the post-connect login/sync handshake.

The actual transport open/reconnect/read loop is owned by
`helpers/transport.py` (`ElkConnectionManager`/`_entry_connect`), not by
this class or `Connection` - see `helpers/elk/connection.py`'s docstring.
This class's `connect()` is unused by this repo for that reason and exists
only for parity/API completeness.
"""

from __future__ import annotations

import logging
from typing import Any

from .areas import Areas
from .connection import Connection
from .counters import Counters
from .keypads import Keypads
from .lights import Lights
from .message import MessageEncode, MsgHandler, ua_encode
from .notify import Notifier
from .outputs import Outputs
from .panel import Panel
from .settings import Settings
from .tasks import Tasks
from .thermostats import Thermostats
from .users import Users
from .util import url_scheme_is_secure
from .zones import Zones

_LOGGER = logging.getLogger(__name__)


class Elk:
    """Every element collection for one panel, plus its login/sync handshake."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._notifier = Notifier()
        self._connection = Connection(config["url"], self._notifier)
        self._logged_in = False

        self.element_list = config.get(
            "element_list",
            [
                "panel",
                "zones",
                "lights",
                "areas",
                "tasks",
                "keypads",
                "outputs",
                "thermostats",
                "counters",
                "settings",
                "users",
            ],
        )

        self._notifier.attach("connected", self._connected)
        self._notifier.attach("disconnected", self._disconnected)
        self._notifier.attach("login", self._login_status)
        self._notifier.attach("IE", self._call_sync_handlers)
        self._notifier.attach("VN", self._got_first_message)

        self.areas = Areas(self._connection, self._notifier)
        self.counters = Counters(self._connection, self._notifier)
        self.keypads = Keypads(self._connection, self._notifier)
        self.lights = Lights(self._connection, self._notifier)
        self.outputs = Outputs(self._connection, self._notifier)
        self.panel = Panel(self._connection, self._notifier)
        self.settings = Settings(self._connection, self._notifier)
        self.tasks = Tasks(self._connection, self._notifier)
        self.thermostats = Thermostats(self._connection, self._notifier)
        self.users = Users(self._connection, self._notifier)
        self.zones = Zones(self._connection, self._notifier)

    def _login_status(self, succeeded: bool) -> None:
        self._logged_in = succeeded
        if not succeeded:
            self._connection.disconnect()
            _LOGGER.error("Invalid username or password.")

    def _got_first_message(self, **kwargs: Any) -> None:
        if not self._logged_in:
            self._notifier.notify("login", {"succeeded": True})

    def _connected(self) -> None:
        if url_scheme_is_secure(self._config["url"]):
            self._connection.send_raw(self._config["userid"])
            self._connection.send_raw(self._config["password"])
        self._call_sync_handlers()

    def _disconnected(self) -> None:
        self._logged_in = False

    def _sync_complete(self, **_: Any) -> None:
        self._notifier.notify("sync_complete", {})
        # Detach so a later, unrelated UA request doesn't re-fire sync_complete.
        self._notifier.detach("UA", self._sync_complete)

    def _call_sync_handlers(self) -> None:
        """Ask every element collection to (re-)sync, and mark the end with a UA request."""
        _LOGGER.debug("Synchronizing panel...")
        self.add_handler("UA", self._sync_complete)
        for element in self.element_list:
            getattr(self, element).sync()
        self.send(ua_encode(0))

    @property
    def connection(self) -> Connection:
        """The underlying `Connection` (state + write queue owned here; the
        actual transport lifecycle owned by `helpers/transport.py`)."""
        return self._connection

    def add_handler(self, msg_type: str, handler: MsgHandler) -> None:
        """Register a handler for a message/event type."""
        self._notifier.attach(msg_type, handler)

    def remove_handler(self, msg_type: str, handler: MsgHandler) -> None:
        """Remove a previously registered handler."""
        self._notifier.detach(msg_type, handler)

    async def connect(self) -> None:
        """Unused by this repo - see this module's docstring. Kept for parity."""
        raise NotImplementedError(
            "Elk.connect() is not used; helpers/transport.py drives the connection directly."
        )

    def disconnect(self) -> None:
        """Disconnect the transport."""
        self._connection.disconnect()

    def is_connected(self) -> bool:
        """Whether a transport is currently open."""
        return self._connection.is_connected()

    def is_paused(self) -> bool:
        """Whether ElkRP currently owns the panel."""
        return self._connection.is_paused()

    def send(self, msg: MessageEncode) -> None:
        """Send a message to the panel."""
        self._connection.send(msg)
