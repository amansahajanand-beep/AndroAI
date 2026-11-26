"""DEV-ONLY routes for the live preview (see ``services/emulator_dev.py``).

Enabled with ``AGENT_DEV_BRIDGE=1`` next to the agent bridge, under ``/api/v1/agent``:

* ``POST   /projects/{id}/preview``              start (contract: ``preview.start``) -> EmulatorStreamSession
* ``DELETE /projects/{id}/preview/{sessionId}``  stop  (contract: ``preview.stop``)
* ``GET    /preview-viewer/{token}``             the page the Preview tab embeds in an iframe
* ``GET    /preview-viewer/{token}/status|frame.png`` and ``POST .../input``  used by that page

The viewer routes are authorised by the unguessable session token in the URL alone, because an
iframe cannot carry the app's login. The token is created for the logged-in owner by the start call
and dies with the session.
"""

from __future__ import annotations

from typing import Literal

from androai_storage import ObjectStorage
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from ...config import get_settings
from ...db import get_db
from ...db.session import get_session_factory
from ...deps import AuthContext, get_owned_project, get_storage, require_permission
from ...errors import AppError
from ...models import Project
from ...services import emulator_dev as emu
from ...services import projects as svc

router = APIRouter(tags=["preview-dev"])
manage = require_permission("projects:manage")


def _error(exc: emu.PreviewError) -> AppError:
    return AppError(exc.status, exc.code, exc.message)


def _session(token: str) -> emu.Session:
    session = emu.MANAGER.by_token(token)
    if session is None:
        raise AppError(404, "not_found", "This preview does not exist or has ended")
    return session


class StartIn(BaseModel):
    device: dict | None = None


class InputIn(BaseModel):
    type: Literal["tap", "swipe", "key", "text"]
    x: float = 0
    y: float = 0
    x2: float = 0
    y2: float = 0
    ms: int = Field(default=250, ge=0, le=5000)
    key: str = Field(default="", max_length=20)
    text: str = Field(default="", max_length=200)


@router.post("/projects/{project_id}/preview", status_code=201)
def start_preview(
    project_id: str,
    request: Request,
    body: StartIn | None = None,
    ctx: AuthContext = Depends(manage),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    factory: sessionmaker = Depends(get_session_factory),
):
    project = get_owned_project(db, ctx, project_id)
    pid = project.id

    def files():
        # Read in the worker thread with its own database session.
        with factory() as session:
            row = session.get(Project, pid)
            if row is None:
                raise emu.PreviewError("unsupported_project", "The project no longer exists.", 404)
            for item in svc.list_files(session, row):
                _, data = svc.read_file(session, storage, row, item.path)
                yield item.path, data

    try:
        started = emu.MANAGER.start(project_id=pid, tenant_id=ctx.tenant_id, files=lambda: list(files()))
    except emu.PreviewError as exc:
        raise _error(exc) from exc
    base = str(request.base_url).rstrip("/")
    return {
        "sessionId": started.id,
        "viewerUrl": f"{base}/api/v1/agent/preview-viewer/{started.token}",
        **started.public(),
    }


@router.delete("/projects/{project_id}/preview/{session_id}", status_code=204)
def stop_preview(project_id: str, session_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    project = get_owned_project(db, ctx, project_id)
    session = emu.MANAGER.by_id(project.id, session_id)
    if session is None or session.tenant_id != ctx.tenant_id:
        raise AppError(404, "not_found", "Preview session not found")
    emu.MANAGER.stop(session)
    return Response(status_code=204)


# ---------------------------------------------------------------------------- viewer (token only)


def _frame_headers() -> dict[str, str]:
    allowed = " ".join(["'self'", "http://localhost:*", "http://127.0.0.1:*", *sorted(get_settings().trusted_origins)])
    return {
        "Content-Security-Policy": (
            "default-src 'none'; img-src 'self' blob:; connect-src 'self'; style-src 'unsafe-inline'; "
            f"script-src 'unsafe-inline'; frame-ancestors {allowed}"
        ),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


@router.get("/preview-viewer/{token}", response_class=HTMLResponse)
def viewer(token: str):
    _session(token)
    return HTMLResponse(VIEWER_HTML, headers=_frame_headers())


@router.get("/preview-viewer/{token}/status")
def status(token: str):
    return JSONResponse(_session(token).status(), headers={"Cache-Control": "no-store"})


@router.get("/preview-viewer/{token}/frame.png")
def frame(token: str):
    session = _session(token)
    try:
        data = emu.MANAGER.frame(session)
    except emu.PreviewError as exc:
        raise _error(exc) from exc
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/preview-viewer/{token}/input", status_code=204)
def send_input(token: str, body: InputIn):
    session = _session(token)
    try:
        if body.type == "tap":
            emu.MANAGER.tap(session, body.x, body.y)
        elif body.type == "swipe":
            emu.MANAGER.swipe(session, body.x, body.y, body.x2, body.y2, body.ms)
        elif body.type == "key":
            emu.MANAGER.key(session, body.key)
        else:
            emu.MANAGER.text(session, body.text)
    except emu.PreviewError as exc:
        raise _error(exc) from exc
    return Response(status_code=204)


VIEWER_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live preview</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; background: #0e0f12; color: #e6e8ee; font: 13px system-ui, sans-serif; }
  #wrap { height: 100%; display: flex; flex-direction: column; }
  #stage { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 6px; }
  #screen { max-width: 100%; max-height: 100%; border-radius: 10px; background: #000; touch-action: none; cursor: pointer; user-select: none; -webkit-user-drag: none; display: none; }
  #state { text-align: center; max-width: 320px; padding: 16px; }
  #state .t { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
  #state .m { color: #9aa0ae; line-height: 1.4; word-break: break-word; }
  #state pre { text-align: left; margin: 10px 0 0; padding: 8px; max-height: 120px; overflow: auto; background: #181a20; border-radius: 6px; color: #9aa0ae; font-size: 11px; white-space: pre-wrap; word-break: break-all; }
  .spin { width: 22px; height: 22px; margin: 0 auto 10px; border: 3px solid #2a2d36; border-top-color: #8b7cff; border-radius: 50%; animation: s 0.9s linear infinite; }
  @keyframes s { to { transform: rotate(360deg); } }
  .err .t { color: #ff8a8a; } .err .spin { display: none; }
  #bar { display: none; gap: 6px; padding: 6px; border-top: 1px solid #23252d; align-items: center; }
  #bar button { background: #1b1d24; color: #e6e8ee; border: 1px solid #2a2d36; border-radius: 6px; padding: 5px 9px; cursor: pointer; font: inherit; }
  #bar button:hover { background: #242732; }
  #bar input { flex: 1; min-width: 0; background: #14161b; color: inherit; border: 1px solid #2a2d36; border-radius: 6px; padding: 5px 8px; font: inherit; }
  #left { color: #6c7280; font-size: 11px; white-space: nowrap; }
</style></head>
<body><div id="wrap">
  <div id="stage">
    <div id="state"><div class="spin"></div><div class="t" id="t">Starting…</div><div class="m" id="m"></div><pre id="log" hidden></pre></div>
    <img id="screen" alt="Live app screen" draggable="false">
  </div>
  <div id="bar">
    <button data-key="back" title="Back">&#9664;</button>
    <button data-key="home" title="Home">&#9679;</button>
    <button data-key="recents" title="Recent apps">&#9632;</button>
    <input id="txt" placeholder="Type text, press Enter to send" maxlength="200" autocomplete="off">
    <span id="left"></span>
  </div>
</div>
<script>
(function () {
  var base = location.pathname.replace(/\\/$/, "");
  var img = document.getElementById("screen"), st = document.getElementById("state");
  var tEl = document.getElementById("t"), mEl = document.getElementById("m"), logEl = document.getElementById("log");
  var bar = document.getElementById("bar"), left = document.getElementById("left"), txt = document.getElementById("txt");
  var dev = { w: 1080, h: 2400 }, live = false, stopped = false, lastUrl = null, expires = 0;

  var TITLES = { building: "Building your app", booting: "Starting the emulator", installing: "Installing your app", failed: "Preview unavailable", stopped: "Preview ended" };

  function status() {
    fetch(base + "/status", { cache: "no-store" }).then(function (r) { if (!r.ok) throw 0; return r.json(); }).then(function (s) {
      dev.w = s.width; dev.h = s.height; expires = Date.parse(s.expiresAt);
      if (s.phase === "ready") {
        if (!live) { live = true; st.style.display = "none"; img.style.display = "block"; bar.style.display = "flex"; frames(); }
      } else {
        live = false; img.style.display = "none"; bar.style.display = "none"; st.style.display = "";
        st.className = s.phase === "failed" || s.phase === "stopped" ? "err" : "";
        tEl.textContent = TITLES[s.phase] || "Starting…";
        mEl.textContent = s.phase === "failed" || s.phase === "stopped" ? s.message : s.message;
        logEl.hidden = !s.log.length; logEl.textContent = s.log.join("\\n");
        if (s.phase === "failed" || s.phase === "stopped") { stopped = true; return; }
      }
      setTimeout(status, live ? 5000 : 1500);
    }).catch(function () { setTimeout(status, 3000); });
  }

  function frames() {
    if (!live || stopped) return;
    fetch(base + "/frame.png", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw r.status; return r.blob();
    }).then(function (b) {
      var url = URL.createObjectURL(b);
      img.onload = function () { if (lastUrl) URL.revokeObjectURL(lastUrl); lastUrl = url; };
      img.src = url;
      setTimeout(frames, 110);
    }).catch(function (code) {
      if (code === 404 || code === 409) { live = false; status(); return; }
      setTimeout(frames, 700);
    });
    var sec = Math.max(0, Math.round((expires - Date.now()) / 1000));
    left.textContent = sec ? Math.floor(sec / 60) + " min left" : "";
  }

  function send(body) {
    fetch(base + "/input", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }
  function toDevice(e) {
    var r = img.getBoundingClientRect();
    return { x: (e.clientX - r.left) * dev.w / r.width, y: (e.clientY - r.top) * dev.h / r.height };
  }
  var down = null;
  img.addEventListener("pointerdown", function (e) { img.setPointerCapture(e.pointerId); down = { p: toDevice(e), t: Date.now(), cx: e.clientX, cy: e.clientY }; });
  img.addEventListener("pointerup", function (e) {
    if (!down) return;
    var up = toDevice(e), moved = Math.hypot(e.clientX - down.cx, e.clientY - down.cy), ms = Date.now() - down.t;
    if (moved < 8) send({ type: "tap", x: up.x, y: up.y });
    else send({ type: "swipe", x: down.p.x, y: down.p.y, x2: up.x, y2: up.y, ms: Math.max(80, Math.min(ms, 1500)) });
    down = null;
  });
  img.addEventListener("pointercancel", function () { down = null; });
  Array.prototype.forEach.call(document.querySelectorAll("[data-key]"), function (b) {
    b.addEventListener("click", function () { send({ type: "key", key: b.getAttribute("data-key") }); });
  });
  txt.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { if (txt.value) send({ type: "text", text: txt.value }); txt.value = ""; send({ type: "key", key: "enter" }); }
  });
  status();
})();
</script></body></html>
"""
