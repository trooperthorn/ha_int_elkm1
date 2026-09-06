"""Local web application: the GUI is a browser page served by this process.

The server owns the open account, the account files on disk, and at most one
panel session. It never stores the RP access code or the database password;
both are supplied per request and used once.

Two modes, chosen by the ``ELK_PROGRAMMER_MODE`` environment variable:

- ``standalone`` (default): bound to localhost on a workstation; no
  authentication of its own beyond that bind.
- ``app``: behind Home Assistant ingress. Every request must carry an
  allow-listed ``X-Remote-User-Id`` header, every API call needs a session
  opened with the app passphrase, writes need a stepped-up session, and the
  service stops itself when idle. See docs/app.md.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..hass import HomeAssistant, HomeAssistantError, IntegrationRelease
from ..model import specs
from ..model.account import Account
from ..model.records import decode_record, encode_record, explain_flags
from ..protocol import messages as m
from ..protocol.framing import encode_frame
from ..protocol.panel import UNMAPPED_REASON, WIRE, wire_for
from ..protocol.session import SerialTransport, Session, SessionError, TcpTransport, TraceEntry
from ..protocol.sync import RECEIVE_ORDER, ReceiveReport, receive_all, send_record, verify_record
from ..security import AccessControl, AuthError, LockedOut, NotSetUp, Session as AuthSession

_LOGGER = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
SESSION_COOKIE = "elk_session"
LOCAL_USER = "local"


class Settings:
    """Everything that comes from the environment; nothing secret."""

    def __init__(self) -> None:
        env = os.environ
        self.mode = env.get("ELK_PROGRAMMER_MODE", "standalone")
        self.data_dir = Path(
            env.get(
                "ELK_PROGRAMMER_DATA", str(Path.home() / "workspace" / "elk-programmer-accounts")
            )
        )
        users = env.get("ELK_PROGRAMMER_ALLOWED_USERS", "")
        self.allowed_users = frozenset(u.strip() for u in users.split(",") if u.strip())
        self.idle_minutes = int(env.get("ELK_PROGRAMMER_IDLE_MINUTES", "0") or 0)
        self.read_only = env.get("ELK_PROGRAMMER_READ_ONLY", "false").lower() in (
            "1",
            "true",
            "yes",
        )
        self.default_method = env.get("ELK_PROGRAMMER_CONNECTION", "network")
        self.default_host = env.get("ELK_PROGRAMMER_HOST", "")
        self.default_port = int(env.get("ELK_PROGRAMMER_PORT", "2101") or 2101)
        self.default_serial_port = env.get("ELK_PROGRAMMER_SERIAL_PORT", "")
        self.default_baud = int(env.get("ELK_PROGRAMMER_BAUD", "115200") or 115200)
        self.release_integration = env.get(
            "ELK_PROGRAMMER_RELEASE_INTEGRATION", "false"
        ).lower() in ("1", "true", "yes")
        self.supervisor_token = env.get("SUPERVISOR_TOKEN", "")

    @property
    def app_mode(self) -> bool:
        return self.mode == "app"

    @property
    def accounts_dir(self) -> Path:
        return self.data_dir / "accounts" if self.app_mode else self.data_dir


class State:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.account: Account = Account.blank()
        self.path: Path | None = None
        self.session: Session | None = None
        self.trace_clients: set[WebSocket] = set()
        self.receive_task: asyncio.Task[ReceiveReport] | None = None
        self.receive_progress: dict[str, Any] = {}
        self.receive_report: ReceiveReport | None = None
        self.access = AccessControl(settings.data_dir, settings.allowed_users)
        self.idle_task: asyncio.Task[None] | None = None
        self._sends: set[asyncio.Future[None]] = set()
        self.release: IntegrationRelease | None = None
        if settings.app_mode and settings.release_integration and settings.supervisor_token:
            self.release = IntegrationRelease(
                HomeAssistant(settings.supervisor_token), settings.data_dir / "session_open.json"
            )

    def broadcast(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload)
        for ws in list(self.trace_clients):
            task = asyncio.ensure_future(_safe_send(ws, text, self))
            self._sends.add(task)
            task.add_done_callback(self._sends.discard)

    def on_trace(self, entry: TraceEntry) -> None:
        shown = entry.body
        if entry.note.startswith("login"):
            # The login frame carries the RP access code; never show or log it.
            shown = entry.body[:4] + b"?" * (len(entry.body) - 4)
        self.broadcast(
            {
                "when": entry.when.isoformat(),
                "direction": entry.direction,
                "hex": shown.hex(" "),
                "note": entry.note,
            }
        )


async def _safe_send(ws: WebSocket, payload: str, state: State) -> None:
    try:
        await ws.send_text(payload)
    except Exception:
        state.trace_clients.discard(ws)


settings = Settings()
state = State(settings)


async def _idle_watch() -> None:
    limit = settings.idle_minutes * 60
    while True:
        await asyncio.sleep(30)
        receiving = bool(state.receive_task and not state.receive_task.done())
        if receiving or state.access.idle_seconds() < limit:
            continue
        state.access.audit.record("idle_stop", "", "", after_seconds=limit)
        if state.session is not None:
            await state.session.close()
            state.session = None
        await _restore_integration("", "")
        if settings.supervisor_token:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    "http://supervisor/addons/self/stop",
                    headers={"Authorization": f"Bearer {settings.supervisor_token}"},
                )
        return


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    if state.release and state.release.pending():
        # A previous run disabled the integration and did not get to restore it.
        try:
            restored = await state.release.restore()
            state.access.audit.record(
                "integration_restored_after_restart", "", "", entries=restored
            )
        except HomeAssistantError as err:
            _LOGGER.error("integration still released: %s", err)
    if settings.app_mode and settings.idle_minutes > 0:
        state.idle_task = asyncio.create_task(_idle_watch())
    yield
    if state.idle_task:
        state.idle_task.cancel()


app = FastAPI(title="Elk Programmer", version=__version__, lifespan=_lifespan)


def _remote_user(request: Request) -> tuple[str, str]:
    if not settings.app_mode:
        return LOCAL_USER, "local operator"
    return (
        request.headers.get("x-remote-user-id", ""),
        request.headers.get(
            "x-remote-user-name", request.headers.get("x-remote-user-display-name", "")
        ),
    )


def _auth_session(request: Request) -> AuthSession | None:
    user_id, _ = _remote_user(request)
    return state.access.resolve(request.cookies.get(SESSION_COOKIE), user_id)


OPEN_PATHS = ("/api/auth/", "/api/version")


@app.middleware("http")
async def access_gate(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """App mode: allow-list on every request, session on every API call."""
    if settings.app_mode:
        user_id, _ = _remote_user(request)
        if not state.access.user_allowed(user_id):
            state.access.audit.record("refused", user_id, "", path=request.url.path)
            return JSONResponse(
                {"detail": "this Home Assistant user is not allowed to use the programmer"}, 403
            )
        path = request.url.path
        if (
            path.startswith("/api/")
            and not path.startswith(OPEN_PATHS)
            and _auth_session(request) is None
        ):
            return JSONResponse({"detail": "log in with the app passphrase first"}, 401)
    return await call_next(request)


def _require_session(request: Request) -> AuthSession:
    if not settings.app_mode:
        return AuthSession(
            "local", LOCAL_USER, "local operator", 0.0, 0.0, write_until=float("inf")
        )
    session = _auth_session(request)
    if session is None:
        raise HTTPException(401, "log in with the app passphrase first")
    return session


def _require_write(request: Request) -> AuthSession:
    session = _require_session(request)
    if settings.read_only:
        raise HTTPException(403, "the app is configured read only")
    if settings.app_mode and not session.can_write(state.access.clock()):
        raise HTTPException(403, "enable writes with the passphrase first")
    return session


def _audit(request: Request, event: str, **details: Any) -> None:
    user_id, user_name = _remote_user(request)
    state.access.audit.record(event, user_id, user_name, **details)


def _set_cookie(response: Response, request: Request, token: str) -> None:
    base = request.headers.get("x-ingress-path", "") or "/"
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path=base)


class Passphrase(BaseModel):
    passphrase: str


class Rotation(BaseModel):
    current: str
    new: str


@app.get("/api/auth/status")
def auth_status(request: Request) -> dict[str, Any]:
    user_id, user_name = _remote_user(request)
    session = _auth_session(request) if settings.app_mode else None
    return {
        "mode": settings.mode,
        "user_id": user_id,
        "user_name": user_name,
        "set_up": state.access.passphrase.is_set() if settings.app_mode else True,
        "logged_in": (session is not None) if settings.app_mode else True,
        "can_write": (session.can_write(state.access.clock()) if session else False)
        if settings.app_mode
        else not settings.read_only,
        "read_only": settings.read_only,
        "audit_intact": state.access.audit.verify()[0],
    }


@app.post("/api/auth/setup")
def auth_setup(body: Passphrase, request: Request, response: Response) -> dict[str, Any]:
    if not settings.app_mode:
        raise HTTPException(400, "not in app mode")
    user_id, user_name = _remote_user(request)
    try:
        state.access.setup(user_id, user_name, body.passphrase)
    except (AuthError, ValueError) as err:
        raise HTTPException(400, str(err)) from err
    session = state.access.login(user_id, user_name, body.passphrase)
    _set_cookie(response, request, session.token)
    return {"ok": True}


@app.post("/api/auth/login")
def auth_login(body: Passphrase, request: Request, response: Response) -> dict[str, Any]:
    if not settings.app_mode:
        raise HTTPException(400, "not in app mode")
    user_id, user_name = _remote_user(request)
    try:
        session = state.access.login(user_id, user_name, body.passphrase)
    except NotSetUp as err:
        raise HTTPException(409, str(err)) from err
    except LockedOut as err:
        raise HTTPException(429, str(err)) from err
    except AuthError as err:
        raise HTTPException(401, str(err)) from err
    _set_cookie(response, request, session.token)
    return {"ok": True}


@app.post("/api/auth/step_up")
def auth_step_up(body: Passphrase, request: Request) -> dict[str, Any]:
    session = _require_session(request)
    if settings.read_only:
        raise HTTPException(403, "the app is configured read only")
    if settings.app_mode:
        try:
            state.access.step_up(session, body.passphrase)
        except LockedOut as err:
            raise HTTPException(429, str(err)) from err
        except AuthError as err:
            raise HTTPException(401, str(err)) from err
    return {"ok": True}


@app.post("/api/auth/rotate")
def auth_rotate(body: Rotation, request: Request) -> dict[str, Any]:
    session = _require_session(request)
    if not settings.app_mode:
        raise HTTPException(400, "not in app mode")
    try:
        state.access.rotate(session, body.current, body.new)
    except (AuthError, ValueError) as err:
        raise HTTPException(400, str(err)) from err
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict[str, Any]:
    if settings.app_mode:
        session = _auth_session(request)
        if session:
            state.access.logout(session)
        response.delete_cookie(
            SESSION_COOKIE, path=request.headers.get("x-ingress-path", "") or "/"
        )
    return {"ok": True}


def _spec_json(spec: specs.RecordSpec) -> dict[str, Any]:
    def fld(f: specs.Field) -> dict[str, Any]:
        return {
            "name": f.name,
            "kind": f.kind.value,
            "length": f.length,
            "label": f.label or f.name,
            "hidden": f.hidden,
            "choices": list(f.choices),
            "minimum": f.minimum,
            "maximum": f.maximum,
            "bits": [asdict(b) for b in f.bits],
        }

    return {
        "name": spec.name,
        "label": spec.label,
        "table": spec.table,
        "count": spec.count,
        "first": spec.first,
        "size": spec.size,
        "fields": [fld(f) for f in spec.fields],
        "extra": [fld(f) for f in spec.extra],
        "wire": (
            {"opcode": WIRE[spec.name].record.value, "size": WIRE[spec.name].size}
            if spec.name in WIRE
            else None
        ),
        "unmapped_reason": UNMAPPED_REASON.get(spec.name),
    }


@app.get("/api/specs")
def get_specs() -> list[dict[str, Any]]:
    return [_spec_json(s) for s in specs.ALL_SPECS]


def _csv(name: str) -> list[dict[str, str]]:
    text = resources.files("elk_programmer.data").joinpath(name).read_text(encoding="utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


@app.get("/api/vocab/words")
def words() -> list[dict[str, Any]]:
    return [{"id": int(r["Value"]), "text": r["Description"]} for r in _csv("voice_words.csv")]


@app.get("/api/vocab/events")
def events() -> list[dict[str, Any]]:
    out = []
    for r in _csv("events.csv"):
        code, _, text = r["Description"].partition(" = ")
        out.append({"code": int(code), "text": text})
    return out


class NewAccount(BaseModel):
    name: str


@app.get("/api/accounts")
def list_accounts() -> dict[str, Any]:
    settings.accounts_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in settings.accounts_dir.glob("*.json"))
    return {
        "directory": str(settings.accounts_dir),
        "files": files,
        "open": state.path.name if state.path else None,
    }


@app.post("/api/accounts/new")
def new_account(body: NewAccount, request: Request) -> dict[str, Any]:
    state.account = Account.blank(body.name)
    state.path = None
    _audit(request, "account_new", name=body.name)
    return account_summary()


@app.get("/api/accounts/open/{name}")
def open_account(name: str, request: Request) -> dict[str, Any]:
    path = settings.accounts_dir / name
    if not path.is_file() or path.suffix != ".json" or path.parent != settings.accounts_dir:
        raise HTTPException(404, "no such account file")
    state.account = Account.load(path)
    state.path = path
    _audit(request, "account_open", file=name)
    return account_summary()


class SaveAs(BaseModel):
    name: str | None = None


@app.post("/api/accounts/save")
def save_account(body: SaveAs, request: Request) -> dict[str, Any]:
    settings.accounts_dir.mkdir(parents=True, exist_ok=True)
    if body.name:
        safe = "".join(c for c in body.name if c.isalnum() or c in "-_ .").strip() or "account"
        state.path = settings.accounts_dir / (safe if safe.endswith(".json") else f"{safe}.json")
    if state.path is None:
        raise HTTPException(400, "choose a file name first")
    state.account.save(state.path)
    _audit(request, "account_save", file=state.path.name)
    return account_summary()


@app.get("/api/account")
def account_summary() -> dict[str, Any]:
    a = state.account
    return {
        "name": a.name,
        "notes": a.notes,
        "identity": asdict(a.identity),
        "connection": asdict(a.connection),
        "file": state.path.name if state.path else None,
        "counts": {s.name: len(a.tables.get(s.name, {})) for s in specs.ALL_SPECS},
    }


class AccountHead(BaseModel):
    name: str
    notes: str = ""
    connection: dict[str, Any]


@app.put("/api/account")
def update_account(body: AccountHead) -> dict[str, Any]:
    state.account.name = body.name
    state.account.notes = body.notes
    for k, v in body.connection.items():
        if hasattr(state.account.connection, k):
            setattr(state.account.connection, k, v)
    return account_summary()


@app.get("/api/records/{spec_name}")
def list_records(spec_name: str) -> dict[str, Any]:
    spec = specs.SPECS_BY_NAME.get(spec_name)
    if spec is None:
        raise HTTPException(404, "unknown table")
    table = state.account.tables.get(spec_name, {})
    title_field = next((f.name for f in spec.fields if f.kind is specs.Kind.TEXT), None)
    items = []
    for n in sorted(table):
        rec = table[n]
        items.append({"number": n, "title": rec.get(title_field, "") if title_field else ""})
    return {"items": items}


@app.get("/api/records/{spec_name}/{number}")
def get_record(spec_name: str, number: int) -> dict[str, Any]:
    spec = specs.SPECS_BY_NAME.get(spec_name)
    if spec is None:
        raise HTTPException(404, "unknown table")
    rec = state.account.record(spec_name, number)
    return {"number": number, "record": _jsonable(rec), "hex": encode_record(spec, rec).hex(" ")}


@app.put("/api/records/{spec_name}/{number}")
def put_record(spec_name: str, number: int, body: dict[str, Any]) -> dict[str, Any]:
    spec = specs.SPECS_BY_NAME.get(spec_name)
    if spec is None:
        raise HTTPException(404, "unknown table")
    rec = state.account.record(spec_name, number)
    for f in (*spec.fields, *spec.extra):
        if f.name in body:
            rec[f.name] = (
                bytes.fromhex(body[f.name]) if f.kind is specs.Kind.BYTES else body[f.name]
            )
        show = f.name + "Show"
        if f.kind is specs.Kind.TEXT and show in body:
            rec[show] = bool(body[show])
    return get_record(spec_name, number)


@app.delete("/api/records/{spec_name}/{number}")
def delete_record(spec_name: str, number: int) -> dict[str, Any]:
    state.account.tables.get(spec_name, {}).pop(number, None)
    return {"ok": True}


def _jsonable(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.hex() if isinstance(v, bytes) else v) for k, v in rec.items()}


class MdbRequest(BaseModel):
    path: str
    password: str
    account_id: str | None = None


@app.post("/api/import/mdb")
def import_mdb(body: MdbRequest, request: Request) -> dict[str, Any]:
    try:
        from ..storage.mdb_import import OdbcSource, import_account, list_accounts
    except ImportError as err:
        _LOGGER.error("ElkRP import unavailable: %s", err)
        raise HTTPException(500, "the Access ODBC support (pyodbc) is not installed") from err
    try:
        source = OdbcSource(body.path, body.password)
    except Exception as err:
        # Driver messages can carry file paths and internals; keep them server side.
        _LOGGER.error("could not open ElkRP database %s: %s", body.path, err)
        raise HTTPException(
            400,
            "could not open the database: check the path, the password, and that ElkRP is closed",
        ) from err
    try:
        if body.account_id is None:
            return {"accounts": list_accounts(source)}
        state.account = import_account(source, body.account_id)
        state.path = None
        _audit(request, "account_import", account=body.account_id)
        return account_summary()
    finally:
        source.close()


async def _release_integration(user_id: str, user_name: str) -> None:
    if state.release is None:
        return
    try:
        entries = await state.release.release()
    except HomeAssistantError as err:
        state.access.audit.record("integration_release_failed", user_id, user_name, error=str(err))
        raise HTTPException(502, f"could not release the integration: {err}") from err
    state.access.audit.record("integration_released", user_id, user_name, entries=entries)


async def _restore_integration(user_id: str, user_name: str) -> None:
    if state.release is None or not state.release.pending():
        return
    try:
        entries = await state.release.restore()
    except HomeAssistantError as err:
        state.access.audit.record("integration_restore_failed", user_id, user_name, error=str(err))
        _LOGGER.error("%s", err)
        return
    state.access.audit.record("integration_restored", user_id, user_name, entries=entries)


@app.get("/api/defaults")
def connection_defaults() -> dict[str, Any]:
    """What the connect dialog should start with; app options win over the account."""
    return {
        "from_app": settings.app_mode,
        "method": settings.default_method,
        "host": settings.default_host,
        "port": settings.default_port,
        "serial_port": settings.default_serial_port,
        "baud": settings.default_baud,
        "release_integration": state.release is not None,
    }


class ConnectRequest(BaseModel):
    method: str = "network"
    host: str = ""
    port: int = 2101
    serial_port: str = ""
    baud: int = 115200
    rp_code: str


@app.post("/api/panel/connect")
async def panel_connect(body: ConnectRequest, request: Request) -> dict[str, Any]:
    _require_session(request)
    if state.session is not None:
        raise HTTPException(409, "already connected")
    host = body.host or settings.default_host
    port = body.port or settings.default_port
    serial_port = body.serial_port or settings.default_serial_port
    baud = body.baud or settings.default_baud
    user_id, user_name = _remote_user(request)
    await _release_integration(user_id, user_name)
    try:
        if body.method == "serial":
            transport: TcpTransport = await SerialTransport.open(serial_port, baud)
        else:
            transport = await TcpTransport.connect(host, port)
    except OSError as err:
        _LOGGER.error("could not open panel transport (%s): %s", body.method, err)
        await _restore_integration(user_id, user_name)
        raise HTTPException(400, "could not open the connection to the panel") from err
    session = Session(transport, on_trace=state.on_trace)
    try:
        info = await session.login(body.rp_code)
    except SessionError as err:
        await transport.close()
        await _restore_integration(user_id, user_name)
        _audit(
            request,
            "panel_login_failed",
            method=body.method,
            target=host if body.method != "serial" else body.serial_port,
        )
        raise HTTPException(400, f"login failed: {err}") from err
    state.session = session
    _audit(
        request,
        "panel_connect",
        method=body.method,
        firmware=info.firmware,
        serial=info.serial_number,
    )
    return {"login": asdict(info)}


@app.post("/api/panel/disconnect")
async def panel_disconnect(request: Request) -> dict[str, Any]:
    if state.session is not None:
        await state.session.close()
        state.session = None
        _audit(request, "panel_disconnect")
    await _restore_integration(*_remote_user(request))
    return {"ok": True}


@app.get("/api/panel/status")
def panel_status() -> dict[str, Any]:
    s = state.session
    return {
        "connected": s is not None,
        "login": asdict(s.login_reply) if s and s.login_reply else None,
        "trace_length": len(s.trace) if s else 0,
    }


class RecordRef(BaseModel):
    spec: str
    number: int


@app.post("/api/panel/read")
async def panel_read(body: RecordRef, request: Request) -> dict[str, Any]:
    _require_session(request)
    if state.session is None:
        raise HTTPException(409, "not connected")
    spec = specs.SPECS_BY_NAME[body.spec]
    try:
        wire = wire_for(body.spec)
    except LookupError as err:
        raise HTTPException(400, str(err)) from err
    try:
        raw = await state.session.read_record(
            wire.record, wire.item(body.number), wire.size, wire.sub
        )
    except SessionError as err:
        raise HTTPException(502, str(err)) from err
    rec = decode_record(spec, raw)
    local = state.account.record(body.spec, body.number)
    diff = {
        k: {"panel": v, "local": local.get(k)}
        for k, v in _jsonable(rec).items()
        if local.get(k) != v
    }
    _audit(request, "record_read", table=body.spec, number=body.number, differs=sorted(diff))
    return {"record": _jsonable(rec), "hex": raw.hex(" "), "diff": diff}


class WriteRequest(RecordRef):
    dry_run: bool = True


@app.post("/api/panel/write")
async def panel_write(body: WriteRequest, request: Request) -> dict[str, Any]:
    spec = specs.SPECS_BY_NAME[body.spec]
    try:
        wire = wire_for(body.spec)
    except LookupError as err:
        raise HTTPException(400, str(err)) from err
    payload = encode_record(spec, state.account.record(body.spec, body.number))
    req = m.write_record(wire.record, wire.item(body.number), payload, wire.sub)
    frame = encode_frame(req.body)
    if body.dry_run:
        _require_session(request)
        return {"dry_run": True, "body": req.body.hex(" "), "frame": frame.hex(" ")}
    _require_write(request)
    if state.session is None:
        raise HTTPException(409, "not connected")
    try:
        reply = await send_record(state.session, state.account, body.spec, body.number)
    except SessionError as err:
        _audit(request, "record_send_failed", table=body.spec, number=body.number, error=str(err))
        raise HTTPException(502, str(err)) from err
    _audit(
        request,
        "record_sent",
        table=body.spec,
        number=body.number,
        frame=frame.hex(" "),
        reply=reply.hex(" "),
    )
    return {"dry_run": False, "frame": frame.hex(" "), "reply": reply.hex(" ")}


class ReceiveRequest(BaseModel):
    tables: list[str] | None = None


@app.post("/api/panel/receive")
async def panel_receive(body: ReceiveRequest, request: Request) -> dict[str, Any]:
    """Start a background receive of every mapped table into the open account."""
    _require_session(request)
    if state.session is None:
        raise HTTPException(409, "not connected")
    if state.receive_task and not state.receive_task.done():
        raise HTTPException(409, "a receive is already running")
    tables = tuple(body.tables) if body.tables else RECEIVE_ORDER
    for t in tables:
        if t not in WIRE:
            raise HTTPException(400, f"{t} is not sendable or receivable")
    user_id, user_name = _remote_user(request)

    def progress(table: str, i: int, n: int, msg: str) -> None:
        state.receive_progress = {"table": table, "item": i, "total": n, "message": msg}
        state.broadcast({"kind": "progress", **state.receive_progress})

    async def run() -> ReceiveReport:
        assert state.session is not None
        report = await receive_all(state.session, state.account, progress, tables)
        state.receive_report = report
        state.access.audit.record(
            "receive_finished",
            user_id,
            user_name,
            read=report.read,
            changed=report.changed,
            errors=report.errors,
        )
        state.broadcast({"kind": "receive_done", **asdict(report)})
        return report

    state.receive_report = None
    state.access.audit.record("receive_started", user_id, user_name, tables=list(tables))
    state.receive_task = asyncio.create_task(run())
    return {"started": True, "tables": list(tables)}


@app.get("/api/panel/receive")
def panel_receive_status() -> dict[str, Any]:
    running = bool(state.receive_task and not state.receive_task.done())
    return {
        "running": running,
        "progress": state.receive_progress,
        "report": asdict(state.receive_report) if state.receive_report else None,
    }


@app.post("/api/panel/verify")
async def panel_verify(body: RecordRef, request: Request) -> dict[str, Any]:
    """Compare the panel's stored CRC for a record with the CRC of the local copy."""
    _require_session(request)
    if state.session is None:
        raise HTTPException(409, "not connected")
    if body.spec not in WIRE:
        raise HTTPException(400, "table has no wire mapping")
    try:
        panel_crc, local_crc = await verify_record(
            state.session, state.account, body.spec, body.number
        )
    except SessionError as err:
        raise HTTPException(502, str(err)) from err
    _audit(
        request, "record_verify", table=body.spec, number=body.number, match=panel_crc == local_crc
    )
    return {
        "panel_crc": f"{panel_crc:04X}",
        "local_crc": f"{local_crc:04X}",
        "match": panel_crc == local_crc,
    }


@app.get("/api/panel/trace")
def panel_trace() -> list[dict[str, Any]]:
    if state.session is None:
        return []
    out = []
    for t in state.session.trace:
        body = t.body
        if t.note.startswith("login"):
            body = body[:4] + b"?" * (len(body) - 4)
        out.append(
            {
                "when": t.when.isoformat(),
                "direction": t.direction,
                "hex": body.hex(" "),
                "note": t.note,
            }
        )
    return out


@app.get("/api/explain/{spec_name}/{field_name}/{value}")
def explain(spec_name: str, field_name: str, value: int) -> dict[str, int]:
    spec = specs.SPECS_BY_NAME[spec_name]
    return explain_flags(spec.field_by_name(field_name), value)


@app.get("/api/audit")
def audit_tail(request: Request, limit: int = 200) -> dict[str, Any]:
    _require_session(request)
    path = state.access.audit.path
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    intact, count = state.access.audit.verify()
    return {
        "intact": intact,
        "count": count,
        "entries": [json.loads(line) for line in lines[-limit:]],
    }


@app.websocket("/ws/trace")
async def ws_trace(ws: WebSocket) -> None:
    if settings.app_mode:
        user_id = ws.headers.get("x-remote-user-id", "")
        if (
            not state.access.user_allowed(user_id)
            or state.access.resolve(ws.cookies.get(SESSION_COOKIE), user_id) is None
        ):
            await ws.close(code=4401)
            return
    await ws.accept()
    state.trace_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        state.trace_clients.discard(ws)


@app.get("/")
def index(request: Request) -> Response:
    if settings.app_mode and not state.access.user_allowed(_remote_user(request)[0]):
        return JSONResponse(
            {"detail": "this Home Assistant user is not allowed to use the programmer"}, 403
        )
    return FileResponse(STATIC / "index.html")


@app.get("/api/version")
def version() -> JSONResponse:
    return JSONResponse({"version": __version__, "mode": settings.mode})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    host = "0.0.0.0" if settings.app_mode else "127.0.0.1"
    uvicorn.run(
        app, host=host, port=8099 if settings.app_mode else 8765, proxy_headers=settings.app_mode
    )


if __name__ == "__main__":
    main()
