"""The publish gate: decide whether a set of files is fit to become the live version.

Python projects must parse and run to a clean exit. Web projects must have every
local file they reference, pass a JavaScript syntax check, and load in a real
headless browser without throwing. Anything that fails stays a rejected draft
and the previous working version stays up.
"""
import html.parser
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

import runner
import store

BASE_URL = "http://127.0.0.1:7777"   # set by omni.py to the local listener
STAGED = {}                           # token -> files, served by server.py at /staged/<token>/
_lock = threading.Lock()

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

# Added right after <head> on the same line, so line numbers in the page's own scripts still
# match its source. static/probe.js records errors and, in check mode, uses every control.
TRAP = '<script src="/__omni/probe.js" data-mode="check"></script>'
PROBE = '<script src="/__omni/probe.js" data-mode="live"></script>'


def inject_trap(markup, tag=TRAP):
    m = re.search(r"<head[^>]*>", markup, re.I)
    if m:
        return markup[:m.end()] + tag + markup[m.end():]
    m = re.search(r"<html[^>]*>", markup, re.I)
    if m:
        return markup[:m.end()] + tag + markup[m.end():]
    return tag + markup


def browser_path():
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    return None


def node_path():
    return shutil.which("node")


# --- static analysis ---------------------------------------------------------

class _Refs(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs, self.scripts, self._in, self._buf, self._type = [], [], False, [], ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            if a.get("src"):
                self.refs.append(("script", a["src"]))
            else:
                self._in, self._buf, self._type = True, [], (a.get("type") or "").lower()
                self._line = self.getpos()[0]
        elif tag == "link" and a.get("href") and "stylesheet" in (a.get("rel") or "").lower():
            self.refs.append(("stylesheet", a["href"]))
        elif tag in ("img", "audio", "video", "source", "iframe") and a.get("src"):
            self.refs.append((tag, a["src"]))
        elif tag == "a" and a.get("href"):
            self.refs.append(("link", a["href"]))

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in:
            self._in = False
            self.scripts.append((self._type, "".join(self._buf), self._line))


def _resolve(page, ref):
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref:
        return None
    base = page.rsplit("/", 1)[0] + "/" if "/" in page else ""
    parts = []
    for part in ((base + ref) if not ref.startswith("/") else ref.lstrip("/")).split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _node_check(code, module, label, problems, offset=0):
    node = node_path()
    if not node or not code.strip():
        return
    fd, path = tempfile.mkstemp(suffix=".mjs" if module else ".cjs", prefix="omni-js-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        r = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            err = r.stderr.strip().splitlines()
            msg = next((l for l in err if "Error" in l), err[-1] if err else "syntax error")
            line = re.search(r":(\d+)\s*$", err[0]) if err else None
            where = " near line %d" % (int(line.group(1)) + offset) if line else ""
            problems.append("%s: JavaScript does not parse%s: %s" % (label, where, msg.strip()[:200]))
    except Exception:
        pass
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _static_web(files, problems):
    pages = [n for n in files if n.lower().endswith((".html", ".htm"))]
    if "index.html" not in files:
        problems.append("there is no index.html; a web project needs one as its front page")
    for name in pages:
        p = _Refs()
        try:
            p.feed(files[name])
        except Exception as e:
            problems.append("%s: HTML could not be parsed (%s)" % (name, e))
            continue
        for kind, ref in p.refs:
            low = ref.strip().lower()
            if low.startswith(("http://", "https://", "//")):
                if kind in ("script", "stylesheet"):
                    problems.append("%s loads %s from the internet (%s); projects must be self-contained"
                                    % (name, kind, ref[:80]))
                continue
            if low.startswith(("#", "data:", "javascript:", "mailto:", "blob:", "about:")) or not low:
                continue
            target = _resolve(name, ref.strip())
            if target and target not in files:
                problems.append("%s refers to %s, which does not exist in the project" % (name, ref[:80]))
        for typ, code, line in p.scripts:
            if typ in ("", "text/javascript", "application/javascript", "module"):
                _node_check(code, typ == "module", "%s (inline script)" % name, problems, offset=line - 1)
    for name, body in files.items():
        low = name.lower()
        if low.endswith((".js", ".mjs")):
            module = low.endswith(".mjs") or bool(re.search(r"^\s*(import|export)\s", body, re.M))
            _node_check(body, module, name, problems)
        elif low.endswith(".json"):
            try:
                json.loads(body)
            except ValueError as e:
                problems.append("%s is not valid JSON: %s" % (name, e))
    return pages


# --- real browser ------------------------------------------------------------

def _load_page(url, timeout=40, budget=4000):
    exe = browser_path()
    if not exe:
        return None, "no browser"
    profile = tempfile.mkdtemp(prefix="omni-chk-")
    proc = subprocess.Popen(
        [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-extensions", "--mute-audio", "--user-data-dir=" + profile,
         "--virtual-time-budget=%d" % budget, "--dump-dom", url],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        out, _ = proc.communicate(timeout=timeout)
        return out.decode("utf-8", "replace"), ""
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return None, "hung"
    finally:
        threading.Timer(3, shutil.rmtree, args=(profile,), kwargs={"ignore_errors": True}).start()


def _quote(labels, n=4):
    shown = ", ".join(labels[:n])
    return shown + (" and %d more" % (len(labels) - n) if len(labels) > n else "")


def _judge(name, res, problems, notes):
    """Turn what the click-through found into problems (block publishing) and notes (advice)."""
    ex = res.get("exercise") or {}
    tried = ex.get("controls") or []
    for c in tried:
        for e in (c.get("errors") or [])[:1]:
            problems.append('%s: using %s throws: %s' % (name, c.get("label", "a control"), _clean(e)))
    keys = ex.get("keys") or {}
    for e in (keys.get("errors") or [])[:1]:
        problems.append("%s: pressing arrow keys, Space or Enter throws: %s" % (name, _clean(e)))
    if not ex.get("done"):
        if tried:
            notes.append("%s: the click-through test did not get to the end (the page is very slow, or "
                         "stops responding after %s)" % (name, tried[-1].get("label")))
        return {"tried": len(tried), "responded": sum(1 for c in tried if c.get("changed")), "done": False}
    dead = [c.get("label") for c in tried if not c.get("changed") and not c.get("errors")]
    alive = len(tried) - len(dead)
    if ex.get("animated"):
        notes.append("%s animates by itself, so the test could only check that its controls do not throw"
                     % name)
    elif len(tried) >= 2 and alive == 0 and not keys.get("changed"):
        problems.append("%s: nothing happens when its controls are used. The test tried %s, and the page "
                        "did not change at all (no text, values, canvas or sound changed). Make sure the "
                        "event handlers are attached to the elements that exist on the page and that "
                        "they update what is shown." % (name, _quote(dead)))
    elif dead:
        notes.append("%s: %d of %d controls changed nothing visible when used: %s"
                     % (name, len(dead), len(tried), _quote(dead)))
    for line in (res.get("console") or [])[:30]:
        if line.startswith("error:"):
            notes.append("%s logged %s" % (name, _clean(line)[:240]))
            break
    return {"tried": len(tried), "responded": alive, "animated": bool(ex.get("animated")),
            "keys": bool(keys.get("changed")), "dead": dead[:12], "done": True}


def _clean(e):
    return re.sub(r"https?://127\.0\.0\.1:\d+/staged/[0-9a-f]+/", "", str(e))


def _browser_web(files, pages, problems, notes, deep=True):
    if not browser_path():
        notes.append("no browser found, so pages were not load-tested")
        return {}
    token = secrets.token_hex(8)
    with _lock:
        STAGED[token] = files
    summary = {}
    try:
        ordered = sorted(pages, key=lambda n: (n != "index.html", n))[:5]
        for name in ordered:
            deep_here = True
            dom, why = _load_page("%s/staged/%s/%s?__check=1" % (BASE_URL, token, name),
                                  budget=16000 if deep else 4000)
            if why == "hung" and deep:
                # Using every control can be too much for a heavy simulation; see whether the
                # page at least opens before calling it broken.
                dom, why = _load_page("%s/staged/%s/%s?__check=1" % (BASE_URL, token, name), budget=3000)
                if why != "hung":
                    notes.append("%s is too heavy for the click-through test to finish, so only "
                                 "opening it was checked" % name)
                    deep_here = False
            if why == "hung":
                problems.append("%s never finishes loading (a script loops forever or blocks the page)" % name)
                continue
            m = re.search(r'id="__omni_check__">(.*?)</script>', dom or "", re.S)
            if not m:
                notes.append("%s: the browser gave no result" % name)
                continue
            try:
                res = json.loads(html_unescape(m.group(1)))
            except ValueError:
                continue
            errs = res.get("errors", [])
            first = errs[:res["load_errors"]] if "load_errors" in res else errs
            for e in first:
                e = _clean(e)
                if "sandboxed and lacks" in e:
                    e += " -- storage (localStorage, cookies) is not available; keep state in memory"
                problems.append("%s throws when opened: %s" % (name, e))
            if not first and res.get("nodes", 0) == 0 and res.get("text", 0) == 0:
                problems.append("%s shows a completely empty page" % name)
            if deep and deep_here and not first:
                summary[name] = _judge(name, res, problems, notes)
    finally:
        with _lock:
            STAGED.pop(token, None)
    return summary


def html_unescape(s):
    import html
    return html.unescape(s)


# --- python ------------------------------------------------------------------

def _check_python(files, problems):
    for name, body in files.items():
        if name.endswith(".py"):
            try:
                compile(body, name, "exec")
            except SyntaxError as e:
                problems.append("%s line %s: %s" % (name, e.lineno, e.msg))
    entry = runner.entry_file(files)
    if not entry:
        problems.append("there is no main.py to run")
        return None
    if problems:
        return None
    tmp = tempfile.mkdtemp(prefix="omni-run-")
    try:
        store.write_tree(tmp, files)
        result = runner.run_dir(tmp, entry)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if result["exit_code"] == -1:
        problems.append("%s was still running after %ds; it must finish by itself in under 10 seconds "
                        "(no endless animation loops, no waiting for input)" % (entry, runner.TIMEOUT))
    elif result["exit_code"] != 0:
        tail = "\n".join(result["stderr"].strip().splitlines()[-12:])
        problems.append("%s exits with an error:\n%s" % (entry, tail[:1500]))
    elif not result["stdout"].strip():
        problems.append("%s runs but prints nothing" % entry)
    return result


# --- entry point -------------------------------------------------------------

def check(kind, files, deep=True):
    """Returns {ok, problems, notes, run, exercise, seconds}. `run` is set for Python projects;
    `exercise` says, per page, how many controls the click-through tried and how many responded."""
    started = time.time()
    problems, notes, run, exercise = [], [], None, None
    if not files:
        problems.append("the project has no files")
    for name, body in files.items():
        if not body.strip():
            problems.append("%s is empty" % name)
        if re.search(r"^\s*(//|#|<!--)?\s*\.\.\.\s*(rest|remaining|existing|unchanged)", body, re.I | re.M) \
                or re.search(r"(rest of (the )?(code|file)|code (stays|remains) (the same|unchanged))", body, re.I):
            problems.append("%s contains a placeholder instead of the full code" % name)
    if not problems:
        if kind == "python":
            run = _check_python(files, problems)
        else:
            pages = _static_web(files, problems)
            if not problems and pages:
                exercise = _browser_web(files, pages, problems, notes, deep)
    seen, uniq = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return {"ok": not uniq, "problems": uniq[:10], "notes": notes[:12], "run": run, "exercise": exercise,
            "seconds": round(time.time() - started, 2)}
