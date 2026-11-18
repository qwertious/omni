"""HTTP + SSE server for Omni.

Two listeners share one handler. The local one (127.0.0.1) is trusted. The
remote one is what Tailscale forwards to, and it demands a paired session
cookie before it serves anything but the pairing page.
"""
import difflib
import json
import mimetypes
import os
import queue
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent
import bus
import catalog
import checker
import providers
import runner
import store

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "dist")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
worker = None        # set by omni.py
relay = None         # optional discord relay
saver = None         # optional screensaver controller
hotkey = None        # optional global hotkey
remote_info = {"enabled": False, "url": "", "port": 0}
local_port = 7777

TYPES = {".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8",
         ".md": "text/plain; charset=utf-8", ".py": "text/plain; charset=utf-8",
         ".csv": "text/plain; charset=utf-8", ".ico": "image/x-icon", ".png": "image/png",
         ".woff2": "font/woff2", ".map": "application/json"}

# Project pages are other people's code as far as the browser is concerned: this header gives
# them an origin of their own, so they cannot call Omni's API or read its cookies.
SANDBOX = "sandbox allow-scripts allow-pointer-lock allow-modals allow-forms allow-popups"

SETTING_KEYS = {"autonomy": str, "idle_minutes": float, "interval": int, "batch": int,
                "ram_reserve_gb": float, "vram_headroom_gb": float, "similarity": float,
                "embed_model": str, "max_files": int, "kinds": str, "on_return": str,
                "deep_check": bool, "screensaver": str, "saver_minutes": float, "hotkey": str}
CHOICES = {"autonomy": ("off", "idle", "always"), "kinds": ("any", "web", "python"),
           "on_return": ("finish", "stop"), "screensaver": ("on", "off")}

# Pages inside the preview frame have an opaque origin, so the browser does not send them the
# remote session cookie when they load their own scripts and styles. On the remote listener the
# frame is pointed at /v/<VIEW>/p/... instead, which carries the permission in the path.
VIEW = {"token": secrets.token_urlsafe(18)}

_pair = {"code": "", "at": 0.0, "fails": []}

PAIR_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Omni</title>
<style>body{margin:0;background:#000;color:#f2f2f2;font:15px/1.7 ui-monospace,Consolas,monospace;
display:grid;place-items:center;min-height:100vh}main{width:min(22rem,88vw)}h1{font-size:1.1rem;
letter-spacing:.3em;margin:0 0 1.5rem}p{color:#8a8a8a;margin:0 0 1.2rem}input{width:100%;
box-sizing:border-box;background:#000;border:1px solid #333;color:#f2f2f2;font:inherit;
font-size:1.6rem;letter-spacing:.4em;text-align:center;padding:.6rem}button{margin-top:.8rem;
width:100%;background:#f2f2f2;color:#000;border:0;font:inherit;padding:.7rem;cursor:pointer}
#e{color:#ff2d2d;min-height:1.7em;margin-top:.6rem}</style></head><body><main><h1>OMNI</h1>
<p>This device is not paired yet. Open Omni on the computer it runs on, go to Settings, and
type the six-digit code shown under Remote access.</p>
<form id="f"><input id="c" inputmode="numeric" autocomplete="one-time-code" maxlength="6" autofocus>
<button>Pair this device</button><div id="e"></div></form>
<script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();
const r=await fetch('/api/pair',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({code:document.getElementById('c').value.trim()})});
if(r.ok)location.href='/';else document.getElementById('e').textContent=(await r.json()).error;};
</script></main></body></html>"""


def pair_code():
    if not _pair["code"] or time.time() - _pair["at"] > 900:
        _pair["code"] = "%06d" % secrets.randbelow(1000000)
        _pair["at"] = time.time()
    return _pair["code"]


def unified(old, new):
    """Per-file diff between two snapshots, as lines the UI can colour."""
    out = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        lines = list(difflib.unified_diff((a or "").splitlines(), (b or "").splitlines(),
                                          lineterm="", n=3))[2:]
        out.append({"file": name, "state": "added" if a is None else "removed" if b is None else "changed",
                    "lines": lines[:1500]})
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Omni"
    remote = False

    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError):
            self.close_connection = True

    # -- helpers -----------------------------------------------------------

    def _send(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n or n > 2_000_000:
            return {}
        try:
            v = json.loads(self.rfile.read(n).decode("utf-8"))
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}

    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def _authed(self):
        return (not self.remote) or store.check_session(self._cookie("omni_s"))

    def _host_ok(self):
        """Refuse requests aimed at us through some other name (DNS rebinding)."""
        if self.remote:
            return True
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("localhost", "127.0.0.1", "[::1]")

    def _origin_ok(self):
        """State-changing requests must come from Omni's own pages, not another site."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        try:
            o = urllib.parse.urlparse(origin)
        except ValueError:
            return False
        return bool(o.netloc) and o.netloc.lower() == (self.headers.get("Host") or "").lower()

    # -- GET ---------------------------------------------------------------

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        url = urllib.parse.urlparse(self.path)
        path, q = urllib.parse.unquote(url.path), urllib.parse.parse_qs(url.query, keep_blank_values=True)

        if path.startswith("/staged/"):
            return self._staged(path, q)
        if path == "/__omni/probe.js":
            return self._probe_js()
        if path.startswith("/v/"):
            parts = path.split("/", 3)
            if len(parts) < 4 or not secrets.compare_digest(parts[2], VIEW["token"]):
                return self._send(403, "this link has expired; reload Omni", "text/plain; charset=utf-8")
            return self._project_file("/" + parts[3], q)
        if not self._authed():
            if path.startswith("/api/"):
                return self._send(401, {"error": "this device is not paired"})
            return self._send(200, PAIR_PAGE, "text/html; charset=utf-8")
        if path.startswith("/p/"):
            return self._project_file(path, q)
        if path == "/api/state":
            return self._send(200, self._state())
        if path == "/api/feed":
            return self._send(200, self._feed(q))
        if path == "/api/projects":
            return self._send(200, {"projects": store.list_programs()})
        if path.startswith("/api/projects/"):
            return self._project(path.split("/")[3])
        if path.startswith("/api/revisions/"):
            return self._revision(path.split("/"))
        if path == "/api/stream":
            return self._stream()
        if path == "/api/models":
            return self._send(200, self._models())
        if path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        return self._static(path)

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(UI_DIR, rel))
        if not full.startswith(UI_DIR) or not os.path.isfile(full):
            full = os.path.join(UI_DIR, "index.html")
        if not os.path.isfile(full):
            return self._send(503, "The interface has not been built yet. Run: npm run build (in omni/web)",
                              "text/plain; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        hdr = {"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in path else {}
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(ext) or mimetypes.guess_type(full)[0]
                         or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", hdr.get("Cache-Control", "no-store"))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _probe_js(self):
        try:
            with open(os.path.join(STATIC_DIR, "probe.js"), "rb") as f:
                data = f.read()
        except OSError:
            data = b""
        self._send(200, data, "text/javascript; charset=utf-8", {"Access-Control-Allow-Origin": "*"})

    def _serve_file(self, files, rel, trap=False, probe=False):
        rel = rel.strip("/") or "index.html"
        body = files.get(rel)
        if body is None:
            return self._send(404, "not found: " + rel, "text/plain; charset=utf-8",
                              {"Access-Control-Allow-Origin": "*"})
        ext = os.path.splitext(rel)[1].lower()
        if trap and ext in (".html", ".htm"):
            body = checker.inject_trap(body)
        elif probe and ext in (".html", ".htm"):
            body = checker.inject_trap(body, checker.PROBE)
        self._send(200, body, TYPES.get(ext, "text/plain; charset=utf-8"),
                   {"Content-Security-Policy": SANDBOX, "Access-Control-Allow-Origin": "*"})

    def _staged(self, path, q):
        parts = path.split("/", 3)
        files = checker.STAGED.get(parts[2] if len(parts) > 2 else "")
        if files is None:
            return self._send(404, "gone", "text/plain")
        self._serve_file(files, parts[3] if len(parts) > 3 else "", trap="__check" in q)

    def _project_file(self, path, q):
        parts = path.split("/", 3)
        p = store.get_program(parts[2]) if len(parts) > 2 else None
        if not p:
            return self._send(404, "no such project", "text/plain")
        if len(parts) < 4:   # /p/slug -> /p/slug/ so relative links resolve
            self.send_response(302)
            self.send_header("Location", "/p/%s/" % p["slug"] + ("?rev=" + q["rev"][0] if "rev" in q else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        files = None
        if "rev" in q:
            try:
                rev = store.get_revision(int(q["rev"][0]))
            except ValueError:
                rev = None
            if rev and rev["program_id"] == p["id"]:
                files = rev["files"]
        if files is None:
            files = store.head_files(p["id"])
        self._serve_file(files, parts[3], probe="raw" not in q)

    def _state(self):
        models = [m for m in providers.installed() if not m["embedding"]]
        counts = store.conn().execute(
            "SELECT SUM(status='live' AND archived=0) live, SUM(status='draft' AND archived=0) drafts, "
            "SUM(archived) archived FROM programs").fetchone()
        rem = dict(remote_info)
        if not self.remote:
            rem["code"] = pair_code()
            rem["devices"] = store.list_sessions()
        else:
            rem["view"] = VIEW["token"]
        return {
            "status": worker.status(),
            "personas": store.list_personas(),
            "settings": store.get_settings(),
            "models": models + [{"name": "scripted", "size": 0, "params": "", "embedding": False}],
            "loaded": sorted(providers.loaded()),
            "discord": relay.status() if relay else {"state": "off"},
            "remote": rem,
            "is_remote": self.remote,
            "counts": {k: counts[k] or 0 for k in ("live", "drafts", "archived")},
            "saver": saver.status() if saver else {"state": "off"},
            "hotkey": hotkey.status() if hotkey else {"ok": False, "error": "not started"},
        }

    def _models(self):
        used = {}
        for p in store.list_personas():
            used.setdefault(p["model"], []).append(p["handle"])
        inst = []
        for m in providers.installed(max_age=5):
            inst.append(dict(m, used_by=used.get(m["name"], []) + used.get(m["name"].replace(":latest", ""), [])))
        return {"hardware": catalog.hardware(), "catalog": catalog.recommend(), "installed": inst,
                "downloads": catalog.downloads.list(), "loaded": sorted(providers.loaded()),
                "bench": catalog._bench()}

    def _feed(self, q):
        before = (q.get("before") or [None])[0]
        limit = min(60, int((q.get("limit") or ["30"])[0]))
        evs = store.list_events(None, limit, before, store.FEED_TYPES)
        tasks = store.tasks_by_ids([e["data"].get("task_id") for e in evs])
        for e in evs:
            t = tasks.get(e["data"].get("task_id"))
            if t:
                e["task"] = t
        return {"events": evs, "more": len(evs) == limit}

    def _project(self, slug):
        p = store.get_program(slug)
        if not p:
            return self._send(404, {"error": "no such project"})
        events = list(reversed(store.list_events(p["id"], 250)))
        tasks = store.tasks_by_ids([e["data"].get("task_id") for e in events])
        for e in events:
            t = tasks.get(e["data"].get("task_id"))
            if t:
                e["task"] = t
        return self._send(200, {
            "project": p,
            "files": store.head_files(p["id"]),
            "revisions": store.list_revisions(p["id"]),
            "events": events,
            "runs": store.list_runs(p["id"], 3),
            "open_tasks": store.open_tasks(p["id"]),
        })

    def _revision(self, parts):
        try:
            rev = store.get_revision(int(parts[3]))
        except (ValueError, IndexError):
            rev = None
        if not rev:
            return self._send(404, {"error": "no such revision"})
        if len(parts) > 4 and parts[4] == "diff":
            base = store.get_revision(rev["parent_id"]) if rev["parent_id"] else None
            return self._send(200, {"diff": unified(base["files"] if base else {}, rev["files"])})
        return self._send(200, {"revision": rev})

    def _stream(self):
        q = bus.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(("data: %s\n\n" % msg).encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass
        finally:
            bus.unsubscribe(q)
        self.close_connection = True

    # -- POST --------------------------------------------------------------

    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._send(403, {"error": "request refused"})
        path = urllib.parse.urlparse(self.path).path
        body = self._body()

        if path == "/api/pair":
            return self._do_pair(body)
        if not self._authed():
            return self._send(401, {"error": "this device is not paired"})

        if path == "/api/posts":
            text = (body.get("body") or "").strip()[:4000]
            if not text:
                return self._send(400, {"error": "say what you would like made"})
            persona = agent.find_mention(text)
            tid = store.add_task("new", text, "you", None, persona["id"] if persona else None)
            eid = store.add_event(None, "post", "you", text,
                                  {"persona": persona["handle"] if persona else None, "task_id": tid})
            store.set_task_event(tid, eid)
            worker.nudge()
            return self._send(200, {"event_id": eid, "task_id": tid})

        if path.startswith("/api/projects/"):
            parts = path.split("/")
            p = store.get_program(parts[3])
            if not p or len(parts) < 5:
                return self._send(404, {"error": "no such project"})
            return self._project_action(p, parts[4], body)

        if path.startswith("/api/models/"):
            return self._model_action(path.split("/")[3], body)

        if path == "/api/saver":
            if not saver:
                return self._send(400, {"error": "the screensaver is not available here"})
            if body.get("action") == "show" and not self.remote:
                saver.show(preview=True)
            else:
                saver.hide()
            return self._send(200, {"ok": True})

        if path == "/api/personas" or path.startswith("/api/personas/"):
            parts = path.split("/")
            pid = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
            if pid is None and not (body.get("handle") or "").strip():
                return self._send(400, {"error": "a persona needs a handle"})
            try:
                persona = store.save_persona(pid, **{k: body[k] for k in (
                    "handle", "name", "model", "bio", "interests", "temperature", "num_ctx", "enabled",
                    "roles")
                    if k in body})
            except (ValueError, TypeError) as e:
                return self._send(400, {"error": str(e)})
            bus.publish("personas")
            worker.nudge()
            return self._send(200, {"persona": persona})

        if path == "/api/settings":
            for k, cast in SETTING_KEYS.items():
                if k in body:
                    try:
                        v = cast(body[k])
                    except (ValueError, TypeError):
                        continue
                    if k in CHOICES and v not in CHOICES[k]:
                        continue
                    if k == "hotkey" and hotkey and not hotkey.parse(v):
                        return self._send(400, {"error": "use something like ctrl+alt+shift+o or ctrl+f9"})
                    store.set_setting(k, v)
                    if k == "hotkey" and hotkey:
                        hotkey.reload()
            bus.publish("settings")
            worker.nudge()
            return self._send(200, {"settings": store.get_settings()})

        if path == "/api/control":
            action = body.get("action")
            if action == "stop":
                worker.halt()
            elif action == "resume":
                worker.resume()
            elif action == "run_now":
                worker.held = False
                worker.force_once = True
                worker.next_auto_at = 0
                worker.nudge()
            elif action == "unload":
                for name in providers.loaded():
                    providers.unload(name)
            elif action == "step_aside":
                worker.step_aside("you asked")
                if saver:
                    saver.hide()
            elif action == "forget_devices" and not self.remote:
                store.drop_sessions()
                VIEW["token"] = secrets.token_urlsafe(18)
            else:
                return self._send(400, {"error": "unknown action"})
            worker.publish(force=True)
            return self._send(200, {"ok": True})

        if path.startswith("/api/tasks/") and path.endswith("/cancel"):
            try:
                tid = int(path.split("/")[3])
            except ValueError:
                return self._send(404, {"error": "no such task"})
            t = store.get_task(tid)
            if t and t["status"] == "queued":
                store.finish_task(tid, "cancelled", "cancelled by you")
            elif t and t["status"] == "running" and worker.job and worker.job.get("task_id") == tid:
                store.finish_task(tid, "cancelled", "cancelled by you")
                worker.cancel.set()
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def _project_action(self, p, action, body):
        pid = p["id"]
        if action == "reply":
            text = (body.get("body") or "").strip()[:4000]
            if not text:
                return self._send(400, {"error": "say where this should go next"})
            persona = agent.find_mention(text)
            tid = store.add_task("fix", text, "you", pid, persona["id"] if persona else None)
            eid = store.add_event(pid, "reply", "you", text,
                                  {"persona": persona["handle"] if persona else None, "task_id": tid})
            store.set_task_event(tid, eid)
            store.update_program(pid, direction=text[:600], cooldown_until=0, fail_streak=0)
            worker.nudge()
            return self._send(200, {"event_id": eid, "task_id": tid})
        if action == "report":
            text = (body.get("body") or "").strip()[:3000]
            if not text:
                return self._send(400, {"error": "say what is wrong"})
            log = body.get("log") if isinstance(body.get("log"), list) else []
            lines = []
            for e in log[-80:]:
                if isinstance(e, dict):
                    lines.append("[%s] %s%s: %s" % (str(e.get("page", ""))[:40], str(e.get("kind", ""))[:10],
                                                    "/" + str(e["level"])[:8] if e.get("level") else "",
                                                    " ".join(str(e.get("text", "")).split())[:300]))
            prompt = ('The owner opened this project in Omni, tried it, and says it does not work properly:\n'
                      '"%s"\n' % text)
            if lines:
                prompt += "\nWhat the page recorded while they used it, oldest first:\n" + \
                    "\n".join(lines)[-5000:] + "\n"
            prompt += "\nFind the cause and fix it, so that it works the way they expect."
            persona = agent.find_mention(text)
            tid = store.add_task("report", prompt, "you", pid, persona["id"] if persona else None)
            errs = sum(1 for e in log if isinstance(e, dict) and e.get("kind") == "error")
            eid = store.add_event(pid, "report", "you", text,
                                  {"persona": persona["handle"] if persona else None, "task_id": tid,
                                   "log": lines[-40:], "errors": errs})
            store.set_task_event(tid, eid)
            store.update_program(pid, cooldown_until=0, fail_streak=0)
            worker.nudge()
            return self._send(200, {"event_id": eid, "task_id": tid})
        if action == "run":
            return self._send(200, runner.run_program(pid))
        if action == "star":
            store.update_program(pid, starred=bool(body.get("on")))
        elif action == "archive":
            store.update_program(pid, archived=bool(body.get("on")))
        elif action == "direction":
            store.update_program(pid, direction=(body.get("text") or "").strip()[:600])
        elif action == "check":
            rep = checker.check("python" if p["kind"] == "python" else "html", store.head_files(pid),
                                deep=bool(store.get_setting("deep_check", True)))
            store.update_program(pid, health=agent.health_of(rep))
        elif action == "revert":
            rev = store.get_revision(body.get("revision_id"))
            if not rev or rev["program_id"] != pid:
                return self._send(404, {"error": "no such revision"})
            head = store.head_files(pid)
            word = "Restored" if rev["status"] == "published" else "Published the rejected draft"
            note = "%s r%d by hand." % (word, rev["seq"])
            new = store.add_revision(pid, "you", note, rev["files"], "published", {},
                                     agent.diff_stats(head, rev["files"]))
            store.update_program(pid, health="", status="live")
            store.add_event(pid, "revised", "you", note,
                            {"revision": new["id"], "seq": new["seq"], "manual": True})
        else:
            return self._send(404, {"error": "unknown action"})
        bus.publish("program", slug=p["slug"])
        return self._send(200, {"project": store.get_program(pid)})

    def _model_action(self, action, body):
        model = str(body.get("model") or "").strip()
        try:
            if action == "pull":
                return self._send(200, {"download": catalog.downloads.start(model)})
            if action == "cancel":
                catalog.downloads.cancel(model)
            elif action == "clear":
                catalog.downloads.clear(model)
            elif action == "try":
                if not providers.is_installed(model):
                    return self._send(400, {"error": "that model is not installed"})
                if model not in worker.benches:
                    worker.benches.append(model)
                worker.nudge()
            elif action == "delete":
                if self.remote:
                    return self._send(403, {"error": "delete models from the computer Omni runs on"})
                if worker.job and worker.job.get("model") == model:
                    return self._send(409, {"error": "that model is working right now"})
                providers.delete(model)
                bus.publish("models")
            else:
                return self._send(404, {"error": "unknown action"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except providers.ProviderError as e:
            return self._send(502, {"error": str(e)})
        return self._send(200, {"ok": True})

    def _do_pair(self, body):
        now = time.time()
        _pair["fails"] = [t for t in _pair["fails"] if now - t < 600]
        if len(_pair["fails"]) >= 6:
            return self._send(429, {"error": "too many tries; wait ten minutes"})
        if str(body.get("code") or "").strip() != pair_code():
            _pair["fails"].append(now)
            return self._send(403, {"error": "that code is not right"})
        token = secrets.token_urlsafe(32)
        store.add_session(token, (self.headers.get("User-Agent") or "")[:120])
        _pair["code"] = ""        # one code, one device
        bus.publish("settings")
        return self._send(200, {"ok": True}, headers={
            "Set-Cookie": "omni_s=%s; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax" % token})


class RemoteHandler(Handler):
    remote = True


def serve(host, port, handler=Handler):
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd
