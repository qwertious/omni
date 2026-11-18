"""SQLite store for Omni.

Projects are threads. Revisions are append-only snapshots of every file in the
project; a revision is either `published` (it passed its checks and became the
live version) or `rejected` (kept for the record, never shown as the project).
"""
import json
import os
import re
import sqlite3
import threading
import time

import bus

OMNI_HOME = os.environ.get("OMNI_HOME") or os.path.join(os.path.expanduser("~"), ".omni")
DB_PATH = os.path.join(OMNI_HOME, "omni.db")
PROGRAMS_DIR = os.path.join(OMNI_HOME, "programs")
CONFIG_PATH = os.path.join(OMNI_HOME, "config.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'python',
    tags TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    head_rev INTEGER
);
CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL,
    parent_id INTEGER,
    seq INTEGER NOT NULL,
    author TEXT NOT NULL,
    rationale TEXT NOT NULL,
    files TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    program_id INTEGER,
    type TEXT NOT NULL,
    author TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    program_id INTEGER,
    kind TEXT NOT NULL,
    prompt TEXT NOT NULL,
    requester TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    result TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    claimed_at REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL,
    revision_id INTEGER,
    exit_code INTEGER,
    stdout TEXT NOT NULL DEFAULT '',
    stderr TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY,
    handle TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    bio TEXT NOT NULL DEFAULT '',
    interests TEXT NOT NULL DEFAULT '[]',
    temperature REAL NOT NULL DEFAULT 0.8,
    num_ctx INTEGER NOT NULL DEFAULT 16384,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    seen_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_prog ON events(program_id, id);
CREATE INDEX IF NOT EXISTS idx_rev_prog ON revisions(program_id, seq);
CREATE INDEX IF NOT EXISTS idx_run_prog ON runs(program_id, id);
"""

# Columns added after v1. (table, column, declaration)
MIGRATIONS = [
    ("programs", "persona_id", "INTEGER"),
    ("programs", "status", "TEXT NOT NULL DEFAULT 'live'"),
    ("programs", "starred", "INTEGER NOT NULL DEFAULT 0"),
    ("programs", "archived", "INTEGER NOT NULL DEFAULT 0"),
    ("programs", "fail_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("programs", "cooldown_until", "REAL NOT NULL DEFAULT 0"),
    ("programs", "direction", "TEXT NOT NULL DEFAULT ''"),
    ("programs", "embedding", "TEXT NOT NULL DEFAULT ''"),
    ("programs", "health", "TEXT NOT NULL DEFAULT ''"),
    ("revisions", "status", "TEXT NOT NULL DEFAULT 'published'"),
    ("revisions", "report", "TEXT NOT NULL DEFAULT '{}'"),
    ("revisions", "stats", "TEXT NOT NULL DEFAULT '{}'"),
    ("tasks", "persona_id", "INTEGER"),
    ("tasks", "event_id", "INTEGER"),
    ("personas", "roles", "TEXT NOT NULL DEFAULT 'both'"),
]

ROLES = ("both", "create", "edit", "asked")   # what a persona does on its own

DEFAULT_SETTINGS = {
    "autonomy": "idle",        # off | idle | always
    "idle_minutes": 5,
    "interval": 240,           # seconds between autonomous jobs
    "batch": 4,                # jobs in a row before another persona gets a turn
    "ram_reserve_gb": 6,       # system RAM that must stay free while a model runs
    "vram_headroom_gb": 1.5,
    "similarity": 0.80,        # ideas at or above this cosine similarity are rejected
    "embed_model": "embeddinggemma",
    "max_files": 8,
    "kinds": "any",            # any | web | python: what they make (and improve) on their own
    "on_return": "finish",     # finish | stop: what happens to their own job when you come back
    "deep_check": True,        # click through web pages before publishing them
    "screensaver": "on",       # on | off: show what they are doing while you are away
    "saver_minutes": 6,        # minutes of no input before the screensaver appears
    "hotkey": "ctrl+alt+shift+o",  # step aside: stop, unload, carry on once you are away again
}

_local = threading.local()
_write_lock = threading.RLock()


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(OMNI_HOME, exist_ok=True)
        os.makedirs(PROGRAMS_DIR, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


def init():
    c = conn()
    with _write_lock:
        c.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            have = [r[1] for r in c.execute("PRAGMA table_info(%s)" % table)]
            if col not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
        # A task that was mid-flight when Omni last stopped goes back in the queue.
        c.execute("UPDATE tasks SET status='failed', result='interrupted when Omni was stopped' "
                  "WHERE status='running' AND claimed_at < ?", (time.time() - 86400,))
        c.execute("UPDATE tasks SET status='queued', claimed_at=NULL WHERE status='running'")
        c.commit()


def _row(r):
    return dict(r) if r is not None else None


def _write(sql, args=()):
    with _write_lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


# --- config (discord token etc. stay in the json file) -----------------------

def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(OMNI_HOME, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# --- settings ----------------------------------------------------------------

def get_settings():
    out = dict(DEFAULT_SETTINGS)
    for r in conn().execute("SELECT key, value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    return out


def set_setting(key, value):
    _write("INSERT INTO settings (key,value) VALUES (?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def get_setting(key, default=None):
    r = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if r is None:
        return DEFAULT_SETTINGS.get(key, default)
    try:
        return json.loads(r["value"])
    except ValueError:
        return default


# --- personas ----------------------------------------------------------------

def _persona(r):
    d = _row(r)
    if d:
        d["interests"] = json.loads(d["interests"] or "[]")
        d["enabled"] = bool(d["enabled"])
    return d


def list_personas(enabled_only=False):
    q = "SELECT * FROM personas" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
    return [_persona(r) for r in conn().execute(q)]


def get_persona(ident):
    if ident is None:
        return None
    if isinstance(ident, str):
        r = conn().execute("SELECT * FROM personas WHERE handle=?",
                           (ident.lstrip("@").lower(),)).fetchone()
    else:
        r = conn().execute("SELECT * FROM personas WHERE id=?", (ident,)).fetchone()
    return _persona(r)


def clean_handle(h):
    h = re.sub(r"[^a-z0-9_]", "", (h or "").lower().lstrip("@"))[:20]
    return h or "agent"


def save_persona(pid=None, **f):
    cols = {}
    if "handle" in f:
        cols["handle"] = clean_handle(f["handle"])
    for k in ("name", "model", "bio"):
        if k in f:
            cols[k] = str(f[k]).strip()[:2000]
    if "interests" in f:
        cols["interests"] = json.dumps([str(x).strip()[:200] for x in f["interests"] if str(x).strip()][:20])
    if "temperature" in f:
        cols["temperature"] = max(0.0, min(1.5, float(f["temperature"])))
    if "num_ctx" in f:
        cols["num_ctx"] = max(4096, min(131072, int(f["num_ctx"])))
    if "enabled" in f:
        cols["enabled"] = 1 if f["enabled"] else 0
    if "roles" in f:
        if f["roles"] not in ROLES:
            raise ValueError("roles must be one of " + ", ".join(ROLES))
        cols["roles"] = f["roles"]
    with _write_lock:
        c = conn()
        if pid is None:
            cols.setdefault("handle", "agent")
            cols.setdefault("name", cols["handle"].title())
            cols.setdefault("model", "")
            base, n = cols["handle"], 2
            while c.execute("SELECT 1 FROM personas WHERE handle=?", (cols["handle"],)).fetchone():
                cols["handle"] = "%s%d" % (base, n)
                n += 1
            cols["created_at"] = time.time()
            keys = list(cols)
            cur = c.execute("INSERT INTO personas (%s) VALUES (%s)" % (
                ",".join(keys), ",".join("?" * len(keys))), [cols[k] for k in keys])
            pid = cur.lastrowid
        elif cols:
            if "handle" in cols and c.execute("SELECT 1 FROM personas WHERE handle=? AND id<>?",
                                              (cols["handle"], pid)).fetchone():
                raise ValueError("that handle is taken")
            keys = list(cols)
            c.execute("UPDATE personas SET %s WHERE id=?" % ",".join(k + "=?" for k in keys),
                      [cols[k] for k in keys] + [pid])
        c.commit()
    return get_persona(pid)


# --- projects ----------------------------------------------------------------

def unique_slug(base):
    base = "".join(ch if (ch.isascii() and ch.isalnum()) or ch == "-" else "-"
                   for ch in base.lower()).strip("-")
    base = "-".join(p for p in base.split("-") if p)[:48] or "project"
    c = conn()
    slug, n = base, 2
    while c.execute("SELECT 1 FROM programs WHERE slug=?", (slug,)).fetchone():
        slug = "%s-%d" % (base, n)
        n += 1
    return slug


def _program(r):
    d = _row(r)
    if d:
        try:
            d["tags"] = json.loads(d["tags"]) if isinstance(d["tags"], str) else d["tags"]
        except ValueError:
            d["tags"] = []
        d.pop("embedding", None)
        d["starred"] = bool(d.get("starred"))
        d["archived"] = bool(d.get("archived"))
        try:
            d["health"] = json.loads(d["health"]) if d.get("health") else {}
        except ValueError:
            d["health"] = {}
    return d


def create_program(title, description, kind, tags, created_by, persona_id=None, status="live"):
    now = time.time()
    with _write_lock:
        slug = unique_slug(title)
        pid = _write(
            "INSERT INTO programs (slug,title,description,kind,tags,created_by,created_at,"
            "updated_at,persona_id,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (slug, title[:120], description[:1200], kind, json.dumps(tags or []), created_by,
             now, now, persona_id, status))
    return get_program(pid)


def get_program(ident):
    col = "slug" if isinstance(ident, str) else "id"
    return _program(conn().execute("SELECT * FROM programs WHERE %s=?" % col, (ident,)).fetchone())


LIST_SQL = """
SELECT p.id, p.slug, p.title, p.description, p.kind, p.tags, p.created_by, p.created_at,
       p.updated_at, p.head_rev, p.persona_id, p.status, p.starred, p.archived, p.fail_streak,
       p.cooldown_until, p.direction, p.health,
       (SELECT COUNT(*) FROM revisions r WHERE r.program_id=p.id AND r.status='published') AS rev_count,
       (SELECT COUNT(*) FROM events e WHERE e.program_id=p.id AND e.type='reply') AS reply_count
FROM programs p
"""


def list_programs(include_archived=True):
    q = LIST_SQL + ("" if include_archived else " WHERE p.archived=0") + " ORDER BY p.updated_at DESC"
    return [_program(r) for r in conn().execute(q)]


def update_program(pid, **f):
    allowed = {"title", "description", "tags", "status", "starred", "archived", "fail_streak",
               "cooldown_until", "direction", "persona_id", "embedding", "health", "kind"}
    cols = {k: v for k, v in f.items() if k in allowed}
    for k in ("tags", "health"):
        if k in cols and not isinstance(cols[k], str):
            cols[k] = json.dumps(cols[k])
    for k in ("starred", "archived"):
        if k in cols:
            cols[k] = 1 if cols[k] else 0
    if not cols:
        return
    if f.get("touch", False):
        cols["updated_at"] = time.time()
    keys = list(cols)
    _write("UPDATE programs SET %s WHERE id=?" % ",".join(k + "=?" for k in keys),
           [cols[k] for k in keys] + [pid])


def get_embedding(pid):
    r = conn().execute("SELECT embedding FROM programs WHERE id=?", (pid,)).fetchone()
    if not r or not r["embedding"]:
        return None
    try:
        return json.loads(r["embedding"])
    except ValueError:
        return None


def all_embeddings():
    out = []
    for r in conn().execute("SELECT id, slug, title, embedding FROM programs WHERE embedding<>''"):
        try:
            e = json.loads(r["embedding"])
        except ValueError:
            continue
        out.append((r["id"], r["slug"], r["title"], e))
    return out


# --- files -------------------------------------------------------------------

_SAFE_PART = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. \-]{0,63}$")


def clean_path(name):
    """Normalise a model-supplied file path, or return None if it is not safe."""
    name = (name or "").strip().strip("`'\"").replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    parts = [p for p in name.split("/") if p]
    if not parts or len(parts) > 4:
        return None
    for p in parts:
        if p in (".", "..") or not _SAFE_PART.match(p) or p.endswith("."):
            return None
    return "/".join(parts)


def program_dir(pid):
    p = get_program(pid)
    d = os.path.join(PROGRAMS_DIR, p["slug"])
    os.makedirs(d, exist_ok=True)
    return d


def write_tree(root, files, remove=()):
    os.makedirs(root, exist_ok=True)
    for name, content in files.items():
        safe = clean_path(name)
        if not safe:
            continue
        path = os.path.join(root, *safe.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    for name in remove:
        safe = clean_path(name)
        if safe and safe not in files:
            try:
                os.remove(os.path.join(root, *safe.split("/")))
            except OSError:
                pass


# --- revisions ---------------------------------------------------------------

def _rev(r, with_files=True):
    d = _row(r)
    if d:
        if with_files:
            d["files"] = json.loads(d["files"])
        else:
            d.pop("files", None)
        for k in ("report", "stats"):
            try:
                d[k] = json.loads(d.get(k) or "{}")
            except ValueError:
                d[k] = {}
    return d


def add_revision(pid, author, rationale, files, status="published", report=None, stats=None):
    """Record a snapshot. Only a published revision becomes the head and reaches disk."""
    now = time.time()
    with _write_lock:
        c = conn()
        row = c.execute("SELECT MAX(seq) s FROM revisions WHERE program_id=?", (pid,)).fetchone()
        seq = (row["s"] or 0) + 1
        parent = c.execute("SELECT head_rev FROM programs WHERE id=?", (pid,)).fetchone()["head_rev"]
        old = {}
        if parent:
            pr = c.execute("SELECT files FROM revisions WHERE id=?", (parent,)).fetchone()
            old = json.loads(pr["files"]) if pr else {}
        cur = c.execute(
            "INSERT INTO revisions (program_id,parent_id,seq,author,rationale,files,created_at,"
            "status,report,stats) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, parent, seq, author, rationale[:2000], json.dumps(files), now, status,
             json.dumps(report or {}), json.dumps(stats or {})))
        rid = cur.lastrowid
        if status == "published":
            c.execute("UPDATE programs SET head_rev=?, updated_at=? WHERE id=?", (rid, now, pid))
        c.commit()
    if status == "published":
        write_tree(program_dir(pid), files, remove=[n for n in old if n not in files])
    return get_revision(rid)


def get_revision(rid):
    if not rid:
        return None
    return _rev(conn().execute("SELECT * FROM revisions WHERE id=?", (rid,)).fetchone())


def head_files(pid):
    p = get_program(pid)
    if not p or not p["head_rev"]:
        return {}
    return get_revision(p["head_rev"])["files"]


def list_revisions(pid, with_files=False):
    rows = conn().execute(
        "SELECT * FROM revisions WHERE program_id=? ORDER BY seq", (pid,)).fetchall()
    return [_rev(r, with_files) for r in rows]


# --- events ------------------------------------------------------------------

FEED_TYPES = ("created", "revised", "post", "reply", "rejected", "note", "draft", "report")


def _event(r):
    d = dict(r)
    try:
        d["data"] = json.loads(d["data"])
    except ValueError:
        d["data"] = {}
    d["event"] = d["type"]
    return d


def add_event(pid, type_, author, body="", data=None):
    now = time.time()
    eid = _write(
        "INSERT INTO events (program_id,type,author,body,data,created_at) VALUES (?,?,?,?,?,?)",
        (pid, type_, author, body, json.dumps(data or {}), now))
    p = get_program(pid) if pid else None
    bus.publish("event", id=eid, program_id=pid, slug=(p or {}).get("slug"),
                title=(p or {}).get("title"), kind=(p or {}).get("kind"), event=type_,
                author=author, body=body, data=data or {}, created_at=now)
    return eid


def update_event_data(eid, **patch):
    with _write_lock:
        r = conn().execute("SELECT data FROM events WHERE id=?", (eid,)).fetchone()
        if not r:
            return
        d = json.loads(r["data"] or "{}")
        d.update(patch)
        conn().execute("UPDATE events SET data=? WHERE id=?", (json.dumps(d), eid))
        conn().commit()


def list_events(pid=None, limit=200, before=None, types=None):
    args, where = [], []
    if pid is not None:
        where.append("e.program_id=?")
        args.append(pid)
    if before:
        where.append("e.id<?")
        args.append(int(before))
    if types:
        where.append("e.type IN (%s)" % ",".join("?" * len(types)))
        args.extend(types)
    sql = ("SELECT e.*, p.slug, p.title, p.kind, p.status AS program_status, p.archived "
           "FROM events e LEFT JOIN programs p ON p.id=e.program_id"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY e.id DESC LIMIT ?")
    rows = conn().execute(sql, args + [limit]).fetchall()
    return [_event(r) for r in rows]


# --- tasks -------------------------------------------------------------------

def add_task(kind, prompt, requester, program_id=None, persona_id=None, event_id=None):
    return _write(
        "INSERT INTO tasks (program_id,kind,prompt,requester,created_at,persona_id,event_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (program_id, kind, prompt, requester, time.time(), persona_id, event_id))


def set_task_event(tid, eid):
    _write("UPDATE tasks SET event_id=? WHERE id=?", (eid, tid))


def queued_tasks():
    return [dict(r) for r in conn().execute(
        "SELECT * FROM tasks WHERE status='queued' ORDER BY id")]


def claim_task(tid):
    with _write_lock:
        c = conn()
        n = c.execute("UPDATE tasks SET status='running', claimed_at=? WHERE id=? AND status='queued'",
                      (time.time(), tid)).rowcount
        c.commit()
        return n == 1


def finish_task(tid, status, result=""):
    _write("UPDATE tasks SET status=?, result=? WHERE id=?", (status, result[:4000], tid))
    bus.publish("task", id=tid, status=status, result=result[:400])


def get_task(tid):
    return _row(conn().execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())


def tasks_by_ids(ids):
    ids = [i for i in ids if i]
    if not ids:
        return {}
    rows = conn().execute("SELECT id,status,result,persona_id,program_id FROM tasks WHERE id IN (%s)"
                          % ",".join("?" * len(ids)), ids).fetchall()
    return {r["id"]: dict(r) for r in rows}


def open_tasks(pid=None):
    q = "SELECT * FROM tasks WHERE status IN ('queued','running')"
    args = []
    if pid is not None:
        q += " AND program_id=?"
        args.append(pid)
    return [dict(r) for r in conn().execute(q + " ORDER BY id", args)]


def queued_count():
    return conn().execute("SELECT COUNT(*) FROM tasks WHERE status='queued'").fetchone()[0]


# --- runs --------------------------------------------------------------------

def add_run(pid, rid, exit_code, stdout, stderr, duration):
    return _write(
        "INSERT INTO runs (program_id,revision_id,exit_code,stdout,stderr,duration,created_at)"
        " VALUES (?,?,?,?,?,?,?)", (pid, rid, exit_code, stdout, stderr, duration, time.time()))


def get_run(rid):
    return _row(conn().execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone())


def last_run(pid):
    return _row(conn().execute(
        "SELECT * FROM runs WHERE program_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone())


def list_runs(pid, limit=20):
    return [dict(r) for r in conn().execute(
        "SELECT * FROM runs WHERE program_id=? ORDER BY id DESC LIMIT ?", (pid, limit))]


# --- remote sessions ---------------------------------------------------------

def add_session(token, label=""):
    now = time.time()
    _write("INSERT INTO sessions (token,label,created_at,seen_at) VALUES (?,?,?,?)",
           (token, label[:120], now, now))


def check_session(token):
    if not token:
        return False
    r = conn().execute("SELECT 1 FROM sessions WHERE token=?", (token,)).fetchone()
    return r is not None


def list_sessions():
    return [dict(r) for r in conn().execute(
        "SELECT substr(token,1,6) AS id, label, created_at, seen_at FROM sessions ORDER BY created_at DESC")]


def drop_sessions():
    _write("DELETE FROM sessions")
