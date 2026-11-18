"""The makers: personas that pitch, build, check and revise projects.

One worker thread runs one job at a time (the video card holds one model). A job
is either something the person asked for or something a persona chose to do while
the computer was idle. Nothing replaces a working project unless it passes the
publish gate in checker.py.
"""
import difflib
import json
import random
import re
import threading
import time
import traceback

import bus
import catalog
import checker
import gate
import providers
import runner
import store

# --- prompts -----------------------------------------------------------------

SYSTEM = """You are {name} (@{handle}), one of several AI makers living in Omni, a workshop on one \
person's computer. You invent, build and improve small self-contained software projects and post \
them for that person to enjoy.

About you: {bio}

Rules for everything you build:
- Real, complete, working code. Never placeholders, never TODO, never "rest of the code unchanged".
- Python projects: standard library only. The entry point is main.py. It must finish by itself in \
under 10 seconds and print something worth reading as plain text. No input(), no endless loops, no \
sleeping, no clearing the screen, no ANSI animation.
- Web projects: the entry point is index.html. Plain HTML, CSS and JavaScript with no frameworks \
and nothing loaded from the internet. A web project may have several pages and separate .css and \
.js files that refer to each other with relative paths. localStorage and cookies are not available; \
keep state in memory.
- Keep every file under about 300 lines. If something grows larger, split it into more files.
- Follow the reply format you are given exactly. No markdown fences, no commentary outside the format."""

PITCH = """PITCH A NEW PROJECT.

{origin}

Projects that already exist in the workshop. Yours must be clearly different from every one of \
them, in subject and in what it shows. Not a variation, not the same idea with a new name:
{existing}
{avoid}
Decide what to build. It can be one file, or up to {max_files} files when several pages or modules \
make it better. In a web project every page is its own .html file, linked to the others with \
ordinary links; if several pages were asked for, plan one .html file for each.

Reply in exactly this form and nothing else:
TITLE: two to five words
KIND: python or web
SUMMARY: two or three sentences on what it does and why it is worth a look
TAGS: three, short, tags
FILES:
- main.py: what this file is responsible for"""

WRITE = """WRITE FILE: {path}

Project: {title} ({kind})
{summary}

The plan for the whole project:
{plan}
{written}
Now write `{path}`. Its job: {purpose}
It must work together with the other files in the plan. Use exactly the planned file names when \
one file refers to another.

Reply with only this:
=== FILE: {path} ===
(the complete contents of the file)
=== END FILE ==="""

REVISE = """REVISE PROJECT.

Project: {title} ({kind})
{summary}
{direction}
Recent history:
{history}
{thread}
State of the live version: {health}

What to do now:
{request}

Current files:
{files}

Make the change. Keep what works. Reply in exactly this form:
RATIONALE: one or two sentences on what you changed and why
SUMMARY: the project's summary, updated only if what it does has changed
Then every file you changed or added, each one complete:
=== FILE: path ===
(the complete contents of the file)
=== END FILE ===
Leave out files you did not change. To remove a file, write a line: === DELETE: path ==="""

REPAIR = """FIX THESE PROBLEMS.

Your version of "{title}" ({kind}) was tested before publishing and it failed:
{problems}

The files as you wrote them:
{files}

Fix every problem listed. Reply in exactly this form:
RATIONALE: one sentence on what was wrong
Then the complete contents of each file you change:
=== FILE: path ===
(the complete contents of the file)
=== END FILE ==="""

SELF_DIRECTED = [
    "Add one genuinely useful or delightful feature that fits what this project is for.",
    "Make the result more interesting to look at, without making it slower.",
    "Find the weakest part of this project and make it properly good.",
    "Make it explain itself: someone seeing it for the first time should understand what is going on.",
    "Simplify the implementation without losing any behaviour, then use the room to polish one detail.",
    "Add a second mode or variation that shows the same idea from a different angle.",
]
SELF_DIRECTED_WEB = [
    "Add a new page that goes deeper into one part of this, and link the pages to each other.",
    "Add controls so the viewer can change the important parameters while it runs.",
    "Split the code into separate .css and .js files and tidy the structure, keeping behaviour identical.",
]
SPARKS = [
    "make it something you could show a curious friend in thirty seconds",
    "make it reveal a pattern most people have never seen",
    "make it useful for a small everyday task",
    "make it playful, with something to tinker with",
    "make it teach one idea so clearly it sticks",
    "make it beautiful first and clever second",
    "make it about something from nature",
    "make it about language or text",
    "make it about sound, rhythm or time",
    "make it about maps, space or geometry",
]

DEFAULT_PERSONAS = [
    {"handle": "qwen", "name": "Qwen",
     "prefer": ["hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS", "qwen3.6:latest",
                "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ4_XS", "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL",
                "qwen3.5:9b"],
     "bio": "A systems tinkerer. You like things with moving parts that fit together: simulations, "
            "small engines, interpreters, multi-page explainers. You care that it actually works.",
     "interests": ["simulations of simple physical systems", "tiny interpreters, parsers and state machines",
                   "puzzle solvers and search algorithms", "data structures built from scratch, with a demo",
                   "multi-page interactive explainers of one idea"]},
    {"handle": "gemma", "name": "Gemma",
     "prefer": ["hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-Q3_K_XL", "hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-IQ3_XXS",
                "hf.co/unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL", "gemma4:latest", "gemma4:12b"],
     "bio": "A visual artist who thinks in code. You make things people want to keep watching: "
            "generative drawings, living patterns, colour and motion. You favour elegance over features.",
     "interests": ["generative art on a canvas", "cellular automata and emergent patterns",
                   "procedural generation of maps, names or music", "visualisations of a mathematical idea",
                   "typography and colour toys"]},
    {"handle": "gpt", "name": "Otto",
     "prefer": ["hf.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF:Q4_K_M",
                "hf.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF:IQ4_XS", "gpt-oss:20b"],
     "bio": "A practical toolmaker with a playful streak. You build small things people can use or "
            "play: converters, calculators, text tools, original mini-games. Clear and tidy.",
     "interests": ["small useful tools that do one thing well", "original playable browser mini-games",
                   "number theory curiosities you can watch", "explorers for small data sets",
                   "text-processing utilities"]},
]

FILE_RE = re.compile(r"^[ \t]*={2,}[ \t]*FILE:[ \t]*(.+?)[ \t]*={2,}[ \t]*$", re.M)
END_RE = re.compile(r"^[ \t]*={2,}[ \t]*END(?:[ \t]+FILE)?[ \t]*={2,}[ \t]*$", re.M)
DEL_RE = re.compile(r"^[ \t]*={2,}[ \t]*DELETE:[ \t]*(.+?)[ \t]*={2,}[ \t]*$", re.M)
FIELD_RE = re.compile(r"^[ \t*#]*(TITLE|KIND|SUMMARY|TAGS|RATIONALE|FILES)[ \t*]*:[ \t*]*(.*)$", re.M)
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{2,20})")

MAX_FILE_CHARS = 60000
MAX_TOTAL_CHARS = 300000


class Skip(Exception):
    """The job ended without producing anything, for an ordinary reason."""


# --- parsing -----------------------------------------------------------------

def _unfence(body):
    lines = body.strip("\n").split("\n")
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
    return "\n".join(lines).rstrip() + "\n"


def parse_reply(text, expect=None):
    """Pull the header fields and file blocks out of a model reply."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    heads = list(FILE_RE.finditer(text))
    head_text = text[:heads[0].start()] if heads else text
    fields, order = {}, list(FIELD_RE.finditer(head_text))
    for i, m in enumerate(order):
        end = order[i + 1].start() if i + 1 < len(order) else len(head_text)
        key = m.group(1).upper()
        val = (m.group(2) + head_text[m.end():end]).strip()
        if key == "FILES":
            fields["FILES"] = val
        else:
            fields.setdefault(key, " ".join(val.split()))
    files, complete = {}, True
    for i, m in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        chunk = text[m.end():stop]
        e = END_RE.search(chunk)
        if e:
            chunk = chunk[:e.start()]
        else:
            d = DEL_RE.search(chunk)
            if d:
                chunk = chunk[:d.start()]
            if i + 1 == len(heads):
                complete = False
        path = store.clean_path(m.group(1))
        if path:
            files[path] = _unfence(chunk)
    if not files and expect:
        # Weaker models sometimes answer with a bare fenced block. Accept it for single files.
        blocks = re.findall(r"```[\w+-]*\n(.*?)```", text, flags=re.S)
        if blocks:
            files[expect] = max(blocks, key=len).rstrip() + "\n"
    deleted = [p for p in (store.clean_path(x) for x in DEL_RE.findall(text)) if p]
    return {"fields": fields, "files": files, "deleted": deleted, "complete": complete}


def parse_plan(raw, kind, max_files):
    plan = []
    for line in (raw or "").splitlines():
        m = re.match(r"^\s*[-*\d.)]+\s*`?([\w./ \-]+?\.\w{1,5})`?\s*[:\-–—]+\s*(.+)$", line)
        if not m:
            continue
        path = store.clean_path(m.group(1))
        if path and path not in [p for p, _ in plan]:
            plan.append((path, m.group(2).strip()[:300]))
    entry = "main.py" if kind == "python" else "index.html"
    good = (".py", ".txt", ".json", ".csv", ".md") if kind == "python" else \
        (".html", ".css", ".js", ".json", ".svg", ".txt", ".md")
    plan = [(p, why) for p, why in plan if p.lower().endswith(good)]
    if entry not in [p for p, _ in plan]:
        plan.insert(0, (entry, "the entry point; ties the project together"))
    plan = plan[:max(1, max_files)]
    if entry not in [p for p, _ in plan]:
        plan[-1] = (entry, "the entry point; ties the project together")

    def rank(item):
        p = item[0].lower()
        if kind == "python":
            return (p == entry, p)                       # helpers first, main.py last
        return (0 if p == entry else 1 if p.endswith(".html") else 2 if p.endswith(".css") else 3, p)
    return sorted(plan, key=rank)


def find_mention(body):
    for h in MENTION_RE.findall(body or ""):
        p = store.get_persona(h)
        if p:
            return p
    return None


def diff_stats(old, new):
    adds = dels = 0
    changed = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        changed.append(name)
        for line in difflib.ndiff((a or "").splitlines(), (b or "").splitlines()):
            if line.startswith("+ "):
                adds += 1
            elif line.startswith("- "):
                dels += 1
    return {"adds": adds, "dels": dels, "files": changed}


def files_block(files, budget, focus=()):
    """Render files for a prompt, trimming the least important ones if they will not fit."""
    names = sorted(files, key=lambda n: (n not in focus, n not in ("main.py", "index.html"), len(files[n])))
    out, used = [], 0
    for n in names:
        body = files[n]
        if used + len(body) > budget and out:
            head = "\n".join(body.splitlines()[:25])
            out.append("=== FILE: %s === (long file: only the first lines are shown, %d lines in all)\n%s\n=== END FILE ==="
                       % (n, body.count("\n") + 1, head))
            used += len(head)
        else:
            out.append("=== FILE: %s ===\n%s=== END FILE ===" % (n, body if body.endswith("\n") else body + "\n"))
            used += len(body)
    return "\n\n".join(out)


# --- setup -------------------------------------------------------------------

def seed_personas():
    """Create the starting personas on first run and adopt projects made before personas existed."""
    names = [m["name"] for m in providers.installed(max_age=0)]
    if not store.list_personas():
        for d in DEFAULT_PERSONAS:
            model = next((m for m in d["prefer"] if m in names), None)
            store.save_persona(handle=d["handle"], name=d["name"], model=model or d["prefer"][0],
                               bio=d["bio"], interests=d["interests"], enabled=bool(model),
                               num_ctx=16384)
    c = store.conn()
    if c.execute("SELECT COUNT(*) FROM programs WHERE persona_id IS NULL").fetchone()[0]:
        for p in store.list_personas():
            like = "ollama:%s%%" % p["handle"]
            tag = "@" + p["handle"]
            with store._write_lock:
                c.execute("UPDATE programs SET persona_id=?, created_by=? WHERE persona_id IS NULL "
                          "AND created_by LIKE ?", (p["id"], tag, like))
                c.execute("UPDATE revisions SET author=? WHERE author LIKE ?", (tag, like))
                c.execute("UPDATE events SET author=? WHERE author LIKE ?", (tag, like))
                c.commit()
        first = store.list_personas()[0]
        with store._write_lock:
            c.execute("UPDATE programs SET persona_id=? WHERE persona_id IS NULL", (first["id"],))
            c.commit()


# --- the worker --------------------------------------------------------------

class Worker(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="omni-worker")
        self._stop_evt = threading.Event()
        self._wake = threading.Event()
        self.cancel = threading.Event()
        self.held = False              # set by Stop; nothing runs until Resume
        self.force_once = False        # "run one now": skip the idle and memory gates once
        self.job = None                # what is being worked on right now
        self.gate_state = {"state": "starting", "reason": ""}
        self.last_persona = None
        self.streak = 0
        self.next_auto_at = 0.0
        self.our_model = None          # the chat model Omni last put in memory
        self._last_pub = 0.0
        self._audit_at = 0.0
        self.aside = False             # stepped aside: nothing runs until the person is away again
        self.aside_why = ""
        self.benches = []              # models the person asked to try out
        self._tok = []                 # text generated since the last "tokens" event
        self._tok_at = 0.0
        self._settings = ({}, 0.0)
        self._forced = False

    # -- status ------------------------------------------------------------

    def status(self):
        snap = gate.snapshot()
        job = None
        if self.job:
            job = {k: v for k, v in self.job.items() if k != "tail"}
            job["tail"] = self.job.get("tail", "")[-1500:]
        return {"job": job, "gate": self.gate_state, "held": self.held, "aside": self.aside,
                "queued": store.queued_count(), "idle": round(snap["idle"]),
                "ram_free": snap["ram_free"], "ram_total": snap["ram_total"],
                "vram_free": snap["vram_free"], "vram_total": snap["vram_total"],
                "next_auto_at": self.next_auto_at, "now": time.time()}

    def publish(self, force=False):
        if force or time.time() - self._last_pub > 1.0:
            self._last_pub = time.time()
            bus.publish("status", **self.status())

    def nudge(self):
        self._wake.set()

    def stop(self):
        self._stop_evt.set()
        self.cancel.set()
        self._wake.set()

    def halt(self):
        """Stop button: abandon the current job and hold until resumed."""
        self.held = True
        self.cancel.set()
        self._wake.set()

    def resume(self):
        self.held = False
        self.aside = False
        self.cancel.clear()
        self._wake.set()

    def step_aside(self, why="you asked"):
        """Stop what is running, free the video card, and carry on once the person is away again.
        A request of theirs that was cut off goes back to the front of the queue."""
        self.aside, self.aside_why = True, why
        self.cancel.set()
        self._free_memory()
        self._wake.set()
        self.publish(force=True)

    def _free_memory(self):
        ours = {p["model"] for p in store.list_personas()} | {self.our_model}
        for name in providers.loaded():
            if name in ours or name.split(":latest")[0] in ours:
                providers.unload(name)
        self.our_model = None

    def settings(self):
        """Settings, read at most once a second (the watch loop asks often)."""
        val, at = self._settings
        if time.time() - at > 1.0:
            self._settings = (store.get_settings(), time.time())
        return self._settings[0]

    def _watch(self):
        """While one of their own jobs runs: if the person comes back and wants the machine
        back at once, step aside without waiting for the job to finish."""
        while not self._stop_evt.is_set():
            time.sleep(0.5)
            job = self.job
            if not job or not job.get("auto") or self.aside:
                continue
            st = self.settings()
            if st.get("on_return") == "stop" and st.get("autonomy") == "idle" and gate.idle_seconds() < 2:
                self.step_aside("you came back")

    # -- loop --------------------------------------------------------------

    def run(self):
        threading.Thread(target=self._watch, daemon=True, name="omni-watch").start()
        while not self._stop_evt.is_set():
            did = False
            try:
                did = self.tick()
            except Exception:
                traceback.print_exc()
            finally:
                self.job = None
                self.publish(force=True)
            self._wake.wait(1.0 if did else 5.0)
            self._wake.clear()

    def _set_gate(self, state, reason=""):
        new = {"state": state, "reason": reason}
        if new != self.gate_state:
            self.gate_state = new
            self.publish(force=True)

    def _memory_gate(self, persona, settings):
        model = persona["model"]
        if not providers.is_installed(model):
            return False, "@%s's model (%s) is not installed" % (persona["handle"], model)
        if model == "scripted":
            return True, ""
        loaded = providers.loaded()
        is_loaded = model in loaded or (model + ":latest") in loaded
        ours = {p["model"] for p in store.list_personas()} | {settings.get("embed_model")}
        reclaim = sum(v for k, v in loaded.items()
                      if k != model and (k in ours or k.split(":latest")[0] in ours))
        return gate.memory_ok(providers.model_size(model), is_loaded, reclaim, settings)

    def _yield_memory(self, settings):
        """The person is back: hand the video card back by unloading our model."""
        if self.our_model and settings.get("autonomy") != "always" and gate.idle_seconds() < 20:
            if not store.queued_count():
                # Small models are left alone: they cost little and other apps may share them.
                held = providers.loaded()
                if max(held.get(self.our_model, 0), held.get(self.our_model + ":latest", 0)) > 6 * gate.GB:
                    providers.unload(self.our_model)
                self.our_model = None

    def tick(self):
        settings = store.get_settings()
        if self.held:
            self._set_gate("held", "stopped by you")
            return False
        force, self.force_once = self.force_once, False
        need = float(settings.get("idle_minutes", 5)) * 60
        if self.aside and (force or gate.idle_seconds() >= need):
            self.aside = False
        if self.aside:
            left = need - gate.idle_seconds()
            self._set_gate("aside", "stepped aside (%s); carries on after %s away from the computer"
                           % (self.aside_why, span(left)))
            return False

        # 0. models the person asked to try
        if self.benches:
            self._bench(self.benches.pop(0))
            return True

        # 1. things the person asked for
        blocked = ""
        for task in store.queued_tasks():
            persona = self._persona_for(task)
            if not persona:
                store.finish_task(task["id"], "failed", "no persona is available")
                continue
            ok, why = (True, "") if force else self._memory_gate(persona, settings)
            if not ok:
                blocked = blocked or "@%s is waiting for memory: %s" % (persona["handle"], why)
                continue
            if store.claim_task(task["id"]):
                self._work_task(task, persona, settings)
                return True
        if blocked:
            self._set_gate("waiting", blocked)
            return False

        # 2. their own work
        mode = settings.get("autonomy", "idle")
        if mode == "off" and not force:
            self._set_gate("off", "autonomy is off")
            self._yield_memory(settings)
            self._audit(settings)
            return False
        idle = gate.idle_seconds()
        if mode == "idle" and idle < need and not force:
            left = need - idle
            self._set_gate("waiting", "you are using the computer (starts after %s of quiet)" % span(left))
            self._yield_memory(settings)
            self._audit(settings)
            return False
        if time.time() < self.next_auto_at and not force:
            self._set_gate("resting", "between jobs")
            self._audit(settings)
            return False
        persona, why = self._pick_persona(settings, force)
        if not persona:
            self._set_gate("waiting", why or "no persona can run right now")
            self._audit(settings)
            return False
        self._forced = force
        try:
            self._autonomous(persona, settings)
        finally:
            self.next_auto_at = max(self.next_auto_at,
                                    time.time() + max(5, int(settings.get("interval", 240))))
        return True

    # -- choosing ----------------------------------------------------------

    def _persona_for(self, task):
        if task.get("persona_id"):
            p = store.get_persona(task["persona_id"])
            if p:
                return p
        role = "create" if task["kind"] == "new" else "edit"
        if task.get("program_id"):
            prog = store.get_program(task["program_id"])
            p = store.get_persona(prog.get("persona_id")) if prog else None
            if p and p["enabled"] and providers.is_installed(p["model"]) and p["roles"] in ("both", role):
                return p
        live = [p for p in store.list_personas(True) if providers.is_installed(p["model"])]
        fit = [p for p in live if p["roles"] in ("both", role)]
        live = fit or [p for p in live if p["roles"] != "asked"] or live
        if not live:
            return None
        loaded = providers.loaded()
        for p in live:  # whoever is already in memory answers fastest
            if p["model"] in loaded or p["model"] + ":latest" in loaded:
                return p
        return live[0]

    def _pick_persona(self, settings, force):
        live = [p for p in store.list_personas(True) if providers.is_installed(p["model"])
                and p["roles"] != "asked"]
        if not live:
            return None, "no persona that works on its own has an installed model"
        ids = [p["id"] for p in live]
        batch = max(1, int(settings.get("batch", 3)))
        if self.last_persona in ids and self.streak < batch:
            start = ids.index(self.last_persona)
        elif self.last_persona in ids:
            start = (ids.index(self.last_persona) + 1) % len(ids)
        else:
            start = random.randrange(len(ids))
        first_why = ""
        for i in range(len(live)):
            p = live[(start + i) % len(live)]
            ok, why = (True, "") if force else self._memory_gate(p, settings)
            if ok:
                return p, ""
            first_why = first_why or "@%s is waiting for memory: %s" % (p["handle"], why)
        return None, first_why

    def _pick_target(self, persona, programs, kinds="any"):
        now = time.time()
        cands = [p for p in programs if not p["archived"] and p["cooldown_until"] < now
                 and kind_allowed(p["kind"], kinds)]
        if not cands:
            return None
        cands.sort(key=lambda p: p["updated_at"])
        weights = []
        for i, p in enumerate(cands):
            w = 1.0 + (1.0 - i / max(1, len(cands)))          # stale projects get a turn
            if p["starred"]:
                w *= 4
            if p["direction"]:
                w *= 2
            if p["persona_id"] == persona["id"]:
                w *= 2.5
            if p["status"] == "draft" or (p["health"] and p["health"].get("ok") is False):
                w *= 2.5
            weights.append(w)
        return random.choices(cands, weights=weights, k=1)[0]

    def _autonomous(self, persona, settings):
        programs = store.list_programs()
        kinds = settings.get("kinds", "any")
        mine = [p for p in programs if p["persona_id"] == persona["id"] and p["status"] == "live"
                and not p["archived"] and kind_allowed(p["kind"], kinds)]
        role = persona["roles"]
        target = None
        if role == "edit" or (role == "both" and len(mine) >= 2 and random.random() > 0.35):
            target = self._pick_target(persona, programs, kinds)   # mostly improve, sometimes invent
            if not target and role == "edit":
                raise_skip = "nothing to improve right now"
                bus.publish("log", persona=persona["handle"], body=raise_skip, created_at=time.time())
                return
        if self.last_persona == persona["id"]:
            self.streak += 1
        else:
            self.last_persona, self.streak = persona["id"], 1
        try:
            if target:
                self._revise(persona, target, self._self_request(target), "self", settings)
            else:
                self._create(persona, None, settings)
        except Skip as e:
            bus.publish("log", persona=persona["handle"], body=str(e), created_at=time.time())
        except providers.Cancelled:
            pass
        except providers.ProviderError as e:
            bus.publish("log", persona=persona["handle"], body="model error: %s" % e,
                        created_at=time.time())
            self.next_auto_at = time.time() + 120

    def _self_request(self, p):
        h = p["health"] or {}
        if p["status"] == "draft" or h.get("ok") is False:
            probs = h.get("problems") or ["it does not pass its checks"]
            return "The current version does not work. Fix it:\n" + "\n".join("- " + x for x in probs[:6])
        if p["direction"] and random.random() < 0.75:
            return ("Continue in the direction the owner of the workshop set for this project:\n\"%s\"\n"
                    "Pick the next concrete step in that direction and do it." % p["direction"])
        pool = SELF_DIRECTED + (SELF_DIRECTED_WEB if p["kind"] != "python" else [])
        return random.choice(pool)

    # -- model calls -------------------------------------------------------

    def _llm(self, persona, prompt, phase, max_tokens=9000):
        self.job.update(phase=phase, chars=0, tps=0.0, phase_at=time.time())
        self.publish(force=True)

        self.job["tail"] = ""

        def progress(n, tps, text=""):
            self.job["chars"] += n
            self.job["tps"] = round(tps, 1)
            self.job["tail"] = (self.job.get("tail", "") + text)[-4000:]
            self._tok.append(text)
            now = time.time()
            if now - self._tok_at > 0.12:
                bus.publish("tokens", text="".join(self._tok), persona=persona["handle"])
                self._tok, self._tok_at = [], now
            self.publish()

        system = SYSTEM.format(name=persona["name"], handle=persona["handle"],
                               bio=persona["bio"] or "A curious maker.")
        if persona["model"] != "scripted":
            self.our_model = persona["model"]
        text, stats = providers.chat(
            persona["model"], system, prompt, temperature=persona["temperature"],
            num_ctx=persona["num_ctx"], max_tokens=max_tokens, on_progress=progress,
            cancel=self.cancel)
        self.job.setdefault("stats", []).append(
            {"phase": phase, "tokens": stats.get("tokens"), "tps": round(stats.get("tps") or 0, 1),
             "seconds": round(stats.get("seconds") or 0, 1)})
        return text, stats

    def _begin(self, persona, what, slug=None, title=None, task=None):
        self.cancel.clear()
        self.job = {"persona": persona["handle"], "persona_name": persona["name"], "what": what,
                    "slug": slug, "title": title, "task_id": task["id"] if task else None,
                    "auto": task is None and not self._forced, "model": persona["model"],
                    "phase": "starting", "chars": 0, "tps": 0.0, "started_at": time.time(),
                    "phase_at": time.time(), "plan": [], "file_i": -1}
        self._set_gate("working", "")
        self.publish(force=True)

    def _budget(self, persona, reserve_out=9000):
        return max(6000, int((persona["num_ctx"] - reserve_out - 2000) * 3.0))

    # -- similarity --------------------------------------------------------

    def _embed_missing(self, settings):
        model = settings.get("embed_model")
        if not model or not providers.is_installed(model):
            return False
        rows = store.conn().execute(
            "SELECT id, title, description FROM programs WHERE embedding='' LIMIT 64").fetchall()
        if rows:
            vecs = providers.embed(["%s. %s" % (r["title"], r["description"]) for r in rows], model)
            if vecs is None:
                return False
            for r, v in zip(rows, vecs):
                store.update_program(r["id"], embedding=json.dumps(v))
        return True

    def similar(self, text, settings, exclude=None):
        """([(score, title, slug)], vector) of existing projects closest to `text`, best first."""
        out = []
        if self._embed_missing(settings):
            vec = providers.embed([text], settings.get("embed_model"))
            if vec:
                for pid, slug, title, e in store.all_embeddings():
                    if pid != exclude:
                        out.append((providers.cosine(vec[0], e), title, slug))
                out.sort(reverse=True)
                return out[:5], vec[0]
        words = set(re.findall(r"[a-z]{4,}", text.lower()))
        for p in store.list_programs():
            if p["id"] == exclude:
                continue
            w = set(re.findall(r"[a-z]{4,}", (p["title"] + " " + p["description"]).lower()))
            if words and w:
                out.append((len(words & w) / len(words | w) * 1.6, p["title"], p["slug"]))
        out.sort(reverse=True)
        return out[:5], None

    # -- checking ----------------------------------------------------------

    def _check_and_repair(self, persona, kind, title, files, rounds=2):
        """Check, and give the persona a couple of tries to fix what the check finds."""
        report = None
        for attempt in range(rounds + 1):
            self.job.update(phase="testing before publishing", chars=0, tps=0.0, phase_at=time.time())
            self.publish(force=True)
            report = checker.check("python" if kind == "python" else "html", files,
                                   deep=bool(self.settings().get("deep_check", True)))
            report["repairs"] = attempt
            if report["ok"] or attempt == rounds:
                break
            raw, stats = self._llm(persona, REPAIR.format(
                title=title, kind="python" if kind == "python" else "web",
                problems="\n".join("- " + p for p in report["problems"]),
                files=files_block(files, self._budget(persona))),
                "fixing what the test found (try %d)" % (attempt + 1))
            fix = parse_reply(raw)
            changed = {k: v for k, v in fix["files"].items() if v.strip() and files.get(k) != v}
            if not changed or stats.get("truncated") or not fix["complete"]:
                break
            files.update(changed)
            for name in fix["deleted"]:
                if name not in changed:
                    files.pop(name, None)
        return report

    # -- jobs --------------------------------------------------------------

    def _work_task(self, task, persona, settings):
        prog = store.get_program(task["program_id"]) if task.get("program_id") else None
        tag = "@" + persona["handle"]
        try:
            if task["kind"] == "new":
                p = self._create(persona, task["prompt"], settings, task)
                store.finish_task(task["id"], "done", p["slug"])
            else:
                if not prog:
                    raise Skip("that project no longer exists")
                request = task["prompt"]
                if task["kind"] == "report":
                    request = self._with_test_results(persona, prog, task, request)
                rev = self._revise(persona, prog, request, "you", settings, task)
                store.finish_task(task["id"], "done" if rev["status"] == "published" else "rejected",
                                  prog["slug"])
        except providers.Cancelled:
            store._write("UPDATE tasks SET status='queued', claimed_at=NULL WHERE id=?", (task["id"],))
            bus.publish("task", id=task["id"], status="queued", result="")
        except Skip as e:
            store.finish_task(task["id"], "failed", str(e))
            store.add_event(prog["id"] if prog else None, "note", tag, str(e), {"task_id": task["id"]})
        except Exception as e:
            store.finish_task(task["id"], "failed", "%s: %s" % (type(e).__name__, e))
            store.add_event(prog["id"] if prog else None, "note", tag,
                            "Could not finish this: %s" % e, {"task_id": task["id"]})
            if not isinstance(e, providers.ProviderError):
                traceback.print_exc()

    def _create(self, persona, prompt, settings, task=None):
        self._begin(persona, "new project", task=task)
        author = "@" + persona["handle"]
        programs = store.list_programs()
        existing = "\n".join("- %s: %s" % (p["title"], p["description"][:70]) for p in programs[:70]) \
            or "- (nothing yet)"
        kinds = settings.get("kinds", "any")
        must = {"web": "web", "python": "python"}.get(kinds)
        if prompt:
            origin = ("The person who runs this workshop asked you for this:\n\"%s\"\n"
                      "Build what they asked for. If it is close to an existing project, make it your "
                      "own take rather than a copy." % prompt)
            if must:
                origin += "\nIf they did not say which kind of project they want, make it a %s project." % must
        else:
            interest = random.choice(persona["interests"] or ["something you find fascinating"])
            origin = ("Nobody asked for this one; it is yours. Follow this interest of yours: %s.\n"
                      "A direction to push it in: %s." % (interest, random.choice(SPARKS)))
            if must:
                origin += "\nIt must be a %s project (KIND: %s)." % (must, must)
        avoid, pitch, vec = "", None, None
        limit = float(settings.get("similarity", 0.8))
        max_files = int(settings.get("max_files", 8))
        for attempt in range(3):
            raw, _ = self._llm(persona, PITCH.format(origin=origin, existing=existing, avoid=avoid,
                                                     max_files=max_files),
                               "thinking of an idea", max_tokens=700)
            f = parse_reply(raw)["fields"]
            title = (f.get("TITLE") or "").strip(" \"'*#")[:80]
            summary = (f.get("SUMMARY") or "").strip()[:900]
            if not title or not summary:
                avoid = "\nYour last reply did not follow the form. Use the exact form below.\n"
                continue
            kind = "python" if "python" in (f.get("KIND") or "").lower() else "html"
            if must and not prompt and kind_label(kind) != must:
                avoid = "\nYour last idea was a %s project, but it must be a %s project.\n" % (kind_label(kind), must)
                continue
            near, vec = self.similar("%s. %s" % (title, summary), settings)
            pitch = {"title": title, "summary": summary, "kind": kind,
                     "tags": [t.strip(" #.").lower()[:24] for t in re.split(r"[,;]", f.get("TAGS") or "")
                              if t.strip(" #.")][:4],
                     "plan": parse_plan(f.get("FILES"), kind, max_files)}
            if prompt or not near or near[0][0] < limit:
                break
            close = ", ".join('"%s"' % t for s, t, _ in near[:3] if s >= limit - 0.05)
            bus.publish("log", persona=persona["handle"], created_at=time.time(),
                        body="Dropped the idea \"%s\": too similar to %s." % (title, close))
            avoid = ("\nYour last idea, \"%s\", was turned down because it is too close to %s. "
                     "Go somewhere clearly different: another subject entirely.\n" % (title, close))
            pitch = None
        if not pitch:
            raise Skip("could not come up with an idea different enough from what already exists")

        self.job.update(title=pitch["title"], plan=[p for p, _ in pitch["plan"]], kind=kind_label(pitch["kind"]))
        plan = pitch["plan"]
        plan_text = "\n".join("- %s: %s" % (p, why) for p, why in plan)
        kind_word = "python" if pitch["kind"] == "python" else "web"
        files = {}
        for i, (path, purpose) in enumerate(plan):
            self.job["file_i"] = i
            written = ""
            if files:
                written = "\nFiles already written:\n%s\n" % files_block(files, self._budget(persona))
            raw, stats = self._llm(persona, WRITE.format(
                path=path, title=pitch["title"], kind=kind_word, summary=pitch["summary"],
                plan=plan_text, written=written, purpose=purpose),
                "writing %s (%d of %d)" % (path, i + 1, len(plan)))
            got = parse_reply(raw, expect=path)["files"]
            body = got.get(path) or (next(iter(got.values())) if len(got) == 1 else "")
            if stats.get("truncated") or not body.strip():
                raise Skip("%s came out incomplete, so \"%s\" was abandoned" % (path, pitch["title"]))
            files[path] = body[:MAX_FILE_CHARS]

        self.job["file_i"] = len(plan)
        report = self._check_and_repair(persona, pitch["kind"], pitch["title"], files)
        ok = report["ok"]
        run = report.pop("run", None)
        p = store.create_program(pitch["title"], pitch["summary"], pitch["kind"], pitch["tags"], author,
                                 persona_id=persona["id"], status="live" if ok else "draft")
        rev = store.add_revision(p["id"], author, "First version.", files, "published", report,
                                 {"adds": sum(v.count("\n") for v in files.values()), "dels": 0,
                                  "files": sorted(files)})
        store.update_program(p["id"], health=health_of(report), embedding=json.dumps(vec) if vec else "")
        data = {"revision": rev["id"], "files": sorted(files), "task_id": task["id"] if task else None,
                "request": prompt or "", "stats": self.job.get("stats", [])}
        if run and run.get("stdout"):
            data["output"] = run["stdout"][:700]
        if ok:
            store.add_event(p["id"], "created", author, pitch["summary"], data)
        else:
            data["problems"] = report["problems"]
            store.add_event(p["id"], "draft", author,
                            "Built \"%s\", but it does not pass its checks yet, so it is kept as a draft."
                            % pitch["title"], data)
        if run:
            runner.record(p["id"], rev["id"], run)
        return store.get_program(p["id"])

    def _revise(self, persona, program, request, requester, settings, task=None):
        pid = program["id"]
        self._begin(persona, "revision", program["slug"], program["title"], task)
        author = "@" + persona["handle"]
        files = store.head_files(pid)
        kind = program["kind"]
        self.job.update(plan=sorted(files), kind=kind_label(kind))
        revs = [r for r in store.list_revisions(pid) if r["status"] == "published"]
        history = "\n".join("  r%d by %s: %s" % (r["seq"], r["author"], r["rationale"][:120])
                            for r in revs[-5:]) or "  (none)"
        talk = [e for e in store.list_events(pid, 12, types=("reply", "request", "report")) if e["author"] == "you"]
        thread = ""
        if talk:
            thread = "What the owner has said on this project, oldest first:\n%s\n" % "\n".join(
                "  - %s" % e["body"][:300] for e in reversed(talk[:5]))
        h = program["health"] or {}
        if kind == "python":
            run = store.last_run(pid)
            health = "never run" if not run else "exit code %s\nstdout:\n%s\nstderr:\n%s" % (
                run["exit_code"], (run["stdout"] or "")[:1500], (run["stderr"] or "")[:1500])
        elif h.get("ok"):
            health = "the pages load without errors"
        elif h:
            health = "problems:\n" + "\n".join("- " + x for x in h.get("problems", []))
        else:
            health = "not tested yet"
        if kind != "python" and h.get("notes"):
            health += "\nFrom the automatic click-through test:\n" + "\n".join("- " + x for x in h["notes"][:6])
        direction = ""
        if program["direction"]:
            direction = "Standing direction from the owner: \"%s\"\n" % program["direction"][:500]
        focus = [n for n in files if n.lower() in (request or "").lower()]
        raw, stats = self._llm(persona, REVISE.format(
            title=program["title"], kind="python" if kind == "python" else "web",
            summary=program["description"], direction=direction, history=history, thread=thread,
            health=health, request=request, files=files_block(files, self._budget(persona), focus)),
            "revising")
        got = parse_reply(raw)
        rationale = (got["fields"].get("RATIONALE") or "Revised.")[:600]
        if stats.get("truncated") or not got["complete"]:
            raise Skip("the reply was cut off before the files were complete; nothing was changed")
        new_files = dict(files)
        for name, body in got["files"].items():
            if body.strip():
                new_files[name] = body[:MAX_FILE_CHARS]
        for name in got["deleted"]:
            if name not in got["files"]:
                new_files.pop(name, None)
        if new_files == files:
            raise Skip("looked at \"%s\" and made no changes" % program["title"])
        if len(new_files) > int(settings.get("max_files", 8)) + 4 or \
                sum(len(v) for v in new_files.values()) > MAX_TOTAL_CHARS:
            raise Skip("the change made the project too large; nothing was changed")

        report = self._check_and_repair(persona, kind, program["title"], new_files)
        run = report.pop("run", None)
        stats_d = diff_stats(files, new_files)
        data = {"request": request, "requester": requester, "task_id": task["id"] if task else None,
                "adds": stats_d["adds"], "dels": stats_d["dels"], "files": stats_d["files"],
                "stats": self.job.get("stats", [])}
        if run and run.get("stdout"):
            data["output"] = run["stdout"][:700]
        if report["ok"]:
            rev = store.add_revision(pid, author, rationale, new_files, "published", report, stats_d)
            data.update(revision=rev["id"], seq=rev["seq"])
            summary = (got["fields"].get("SUMMARY") or "").strip()[:900]
            patch = {"health": health_of(report), "fail_streak": 0, "cooldown_until": 0}
            was_draft = program["status"] == "draft"
            if was_draft:
                patch["status"] = "live"
            if summary and summary != program["description"] and len(summary) > 20:
                patch.update(description=summary, embedding="")
            store.update_program(pid, **patch)
            store.add_event(pid, "created" if was_draft else "revised", author,
                            program["description"] if was_draft else rationale, data)
            if run:
                runner.record(pid, rev["id"], run)
        else:
            rev = store.add_revision(pid, author, rationale, new_files, "rejected", report, stats_d)
            streak = program["fail_streak"] + 1
            store.update_program(pid, fail_streak=streak,
                                 cooldown_until=time.time() + 12 * 3600 if streak >= 3 else 0)
            data.update(revision=rev["id"], seq=rev["seq"], problems=report["problems"])
            store.add_event(pid, "rejected", author, rationale, data)
        return rev

    # -- housekeeping ------------------------------------------------------

    def _audit(self, settings):
        """While resting, test one project that has never been through the publish gate."""
        if time.time() < self._audit_at or gate.idle_seconds() < 60:
            return      # testing opens a headless browser; only do that while nobody is at the keyboard
        self._audit_at = time.time() + 4
        r = store.conn().execute(
            "SELECT id FROM programs WHERE health='' AND archived=0 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if not r:
            self._audit_at = time.time() + 600
            self._embed_missing(settings)
            return
        p = store.get_program(r["id"])
        report = checker.check("python" if p["kind"] == "python" else "html", store.head_files(p["id"]),
                               deep=bool(settings.get("deep_check", True)))
        store.update_program(p["id"], health=health_of(report))
        bus.publish("program", slug=p["slug"])

    # -- trying models -----------------------------------------------------

    def _bench(self, model):
        """A short, real job for a model the person just downloaded: does it load, and how fast is it?"""
        fake = {"handle": "omni", "name": "Omni"}
        self._begin(dict(fake, model=model), "model test", title=providers_short(model))
        self.job["auto"] = False
        result = {"at": time.time(), "ok": False}
        try:
            self.our_model = model
            started = time.time()
            text, stats = providers.chat(
                model, "You write small, correct programs.",
                "Write a complete single-file HTML page with a button that counts clicks. "
                "Reply with only the code.", temperature=0.4, num_ctx=8192, max_tokens=600,
                on_progress=lambda n, tps, t="": (self.job.update(chars=self.job["chars"] + n, tps=round(tps, 1),
                                                                   tail=(self.job.get("tail", "") + t)[-4000:]),
                                                  self.publish()),
                cancel=self.cancel)
            result.update(ok="<" in text, tps=round(stats.get("tps") or 0, 1),
                          load=round(stats.get("load") or 0, 1), seconds=round(time.time() - started, 1),
                          tokens=stats.get("tokens"))
            if not result["ok"]:
                result["error"] = "it answered, but not with code"
        except providers.Cancelled:
            return
        except providers.ProviderError as e:
            result["error"] = str(e)[:300]
        catalog.save_bench(model, result)
        bus.publish("models")

    def _with_test_results(self, persona, prog, task, request):
        """For a problem report: click through the live version first and add what that finds."""
        self._begin(persona, "revision", prog["slug"], prog["title"], task)
        self.job.update(phase="trying the project the way you did")
        self.publish(force=True)
        if prog["kind"] == "python":
            run = runner.run_program(prog["id"])
            return request + "\n\nWhen Omni ran it just now: exit code %s\nstdout:\n%s\nstderr:\n%s" % (
                run.get("exit_code"), (run.get("stdout") or "")[:1500], (run.get("stderr") or "")[:1500])
        rep = checker.check("html", store.head_files(prog["id"]), deep=True)
        store.update_program(prog["id"], health=health_of(rep))
        found = rep["problems"] + rep["notes"]
        if not found:
            found = ["it found nothing wrong by itself, so go by the description and the log above"]
        return request + "\n\nAn automatic test then opened the pages and used every control. It found:\n" + \
            "\n".join("- " + x for x in found[:12])


def span(seconds):
    s = max(0, int(seconds))
    return "%dh %02dm" % (s // 3600, s % 3600 // 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def kind_label(kind):
    return "python" if kind == "python" else "web"


def kind_allowed(kind, kinds):
    return kinds not in ("web", "python") or kind_label(kind) == kinds


def providers_short(model):
    return re.sub(r"^hf\.co/[^/]+/", "", model or "").replace("-GGUF", "")


def health_of(report):
    return {"ok": report["ok"], "problems": report["problems"], "notes": report.get("notes", [])[:10],
            "exercise": report.get("exercise"), "at": time.time()}
