"""Mirror Omni activity into a Discord channel.

Outbound only, and REST only -- no gateway connection, no dependencies. The
relay subscribes to the internal bus and posts one embed per event to the first
text channel named `#omni` it can find.
"""
import json
import queue
import threading
import time
import urllib.error
import urllib.request

import bus
import store

API = "https://discord.com/api/v10"

COLORS = {
    "created": 0x7EE787,
    "revised": 0x7AA2F7,
    "request": 0xC99CF5,
    "run_ok": 0x3D4455,
    "run_bad": 0xFF7B72,
    "note": 0xE3B341,
    "failed": 0xFF7B72,
    "post": 0xC99CF5,
    "reply": 0xC99CF5,
    "draft": 0xE3B341,
}

# Discord is for watching, so only the events worth reading are mirrored.
RELAYED = {"created", "revised", "post", "reply", "draft"}

ICONS = {"created": "🌱", "revised": "⟳", "request": "✎", "run": "▶",
         "note": "⚠", "failed": "⚠", "post": "✎", "reply": "↳", "draft": "◌"}


def _clip(s, n):
    s = s or ""
    return s if len(s) <= n else s[:n - 1] + "…"


def _block(text, lines=10, chars=900):
    text = (text or "").strip()
    if not text:
        return ""
    kept = text.splitlines()[:lines]
    out = "\n".join(kept)
    if len(out) > chars:
        out = out[:chars] + "\n…"
    elif len(text.splitlines()) > lines:
        out += "\n…"
    return "```\n%s\n```" % out


class Relay(threading.Thread):
    """Background poster. Never raises into the worker; failures degrade to off."""
    daemon = True

    def __init__(self, token, channel_name="omni", base_url="http://localhost:7777"):
        super().__init__(name="omni-discord")
        self.token = token
        self.channel_name = channel_name
        self.base_url = base_url
        self.channel_id = None
        self.guild_name = None
        self.state = "connecting"
        self.last_error = ""
        self.sent = 0
        self.failed = 0
        self._stop = threading.Event()

    # -- status ------------------------------------------------------------

    def status(self):
        return {
            "state": self.state,
            "channel": ("#" + self.channel_name) if self.channel_name else None,
            "guild": self.guild_name,
            "error": self.last_error,
            "sent": self.sent,
            "failed": self.failed,
        }

    def stop(self):
        self._stop.set()

    # -- http --------------------------------------------------------------

    def _req(self, method, path, body=None):
        req = urllib.request.Request(
            API + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": "Bot " + self.token,
                "Content-Type": "application/json",
                "User-Agent": "Omni (local playground, 0.1)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode())
            except Exception:
                return e.code, {}
        except urllib.error.URLError as e:
            return 0, {"message": str(e.reason)}

    def _post_message(self, payload):
        """POST with one 429 retry, honouring Discord's retry_after."""
        for _ in range(2):
            code, body = self._req("POST", "/channels/%s/messages" % self.channel_id, payload)
            if code in (200, 201):
                self.sent += 1
                bus.publish("discord", **self.status())
                return True
            if code == 429:
                time.sleep(float(body.get("retry_after", 1)) + 0.25)
                continue
            self.failed += 1
            self.last_error = "POST %s: %s" % (code, body.get("message", ""))
            bus.publish("discord", **self.status())
            return False
        self.failed += 1
        return False

    # -- channel discovery -------------------------------------------------

    def resolve_channel(self):
        code, me = self._req("GET", "/users/@me")
        if code != 200:
            self.state = "bad token"
            self.last_error = me.get("message", "auth failed (HTTP %s)" % code)
            return False

        code, guilds = self._req("GET", "/users/@me/guilds")
        if code != 200:
            self.state = "error"
            self.last_error = guilds.get("message", "could not list servers")
            return False
        if not guilds:
            self.state = "not invited"
            self.last_error = "the bot is not in any server yet"
            return False

        for g in guilds:
            code, chans = self._req("GET", "/guilds/%s/channels" % g["id"])
            if code != 200:
                continue
            for c in chans:
                if c.get("type") == 0 and c.get("name") == self.channel_name:
                    self.channel_id = c["id"]
                    self.guild_name = g.get("name")
                    self.state = "connected"
                    self.last_error = ""
                    return True

        self.state = "no channel"
        self.last_error = "no text channel named #%s in %s" % (
            self.channel_name, ", ".join(g.get("name", "?") for g in guilds))
        return False

    # -- formatting --------------------------------------------------------

    def _embed(self, m):
        kind = m.get("event") or ""
        data = m.get("data") or {}
        title = m.get("title") or "Omni"
        slug = m.get("slug")
        icon = ICONS.get(kind, "•")
        url = "%s/#%s" % (self.base_url, slug) if slug else None

        e = {
            "title": "%s %s · %s" % (icon, kind.capitalize(), _clip(title, 200)),
            "color": COLORS.get(kind, 0x8B93A7),
            "footer": {"text": m.get("author") or "omni"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(
                m.get("created_at") or time.time())),
        }
        if url:
            e["url"] = url

        if kind == "run":
            run = store.get_run(data.get("run_id")) if data.get("run_id") else None
            ok = data.get("exit_code") == 0
            e["color"] = COLORS["run_ok" if ok else "run_bad"]
            e["title"] = "%s Ran · %s" % ("▶" if ok else "❌", _clip(title, 200))
            parts = [m.get("body") or ""]
            if run:
                if run["stdout"]:
                    parts.append(_block(run["stdout"]))
                if run["stderr"]:
                    parts.append("**stderr**\n" + _block(run["stderr"], lines=8))
            e["description"] = _clip("\n".join(p for p in parts if p), 3800)
            return e

        e["description"] = _clip(m.get("body") or "", 3800)

        if kind == "revised" and data.get("seq"):
            e["fields"] = [{"name": "revision", "value": "r%d" % data["seq"], "inline": True}]
            if data.get("files"):
                e["fields"].append({"name": "changed", "inline": True,
                                    "value": _clip(", ".join(data["files"]), 200)})
        if kind == "created" and slug:
            p = store.get_program(slug)
            if p:
                e["fields"] = [{"name": "kind", "value": "python" if p["kind"] == "python" else "web", "inline": True}]
        return e

    # -- loop --------------------------------------------------------------

    def run(self):
        q = bus.subscribe()
        backoff = 15
        while not self._stop.is_set():
            if not self.channel_id:
                bus.publish("discord", **self.status())
                if not self.resolve_channel():
                    bus.publish("discord", **self.status())
                    # Keep retrying: the channel usually appears once the user
                    # invites the bot, and we want that to just start working.
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 120)
                    continue
                backoff = 15
                bus.publish("discord", **self.status())
                self._post_message({"content":
                    "**Omni** is online — relaying activity here. <%s>" % self.base_url})

            try:
                msg = q.get(timeout=5)
            except queue.Empty:
                continue
            m = json.loads(msg)
            if m.get("type") != "event" or m.get("event") not in RELAYED:
                continue
            try:
                self._post_message({"embeds": [self._embed(m)]})
            except Exception as e:
                self.last_error = "%s: %s" % (type(e).__name__, e)
            time.sleep(0.4)  # stay well under the per-channel rate limit
        bus.unsubscribe(q)
