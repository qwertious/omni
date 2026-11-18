"""Talking to Ollama: streamed chat, embeddings, and what is installed or loaded."""
import json
import math
import random
import time
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"


class ProviderError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def _post(path, payload, timeout=30):
    req = urllib.request.Request(OLLAMA_URL + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(path, timeout=4):
    with urllib.request.urlopen(OLLAMA_URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


# --- inventory ---------------------------------------------------------------

_tags_cache = {"at": 0, "v": []}


def installed(max_age=20):
    """[{name, size, params, family}] for every local model. Cached briefly."""
    if time.time() - _tags_cache["at"] < max_age:
        return _tags_cache["v"]
    try:
        out = []
        for m in _get("/api/tags").get("models", []):
            det = m.get("details") or {}
            fam = (det.get("family") or "").lower()
            name = m["name"]
            out.append({"name": name, "size": m.get("size", 0),
                        "params": det.get("parameter_size", ""),
                        "embedding": "embed" in name.lower() or "bert" in fam})
        _tags_cache.update(at=time.time(), v=out)
    except Exception:
        _tags_cache.update(at=time.time() - max_age + 5)
    return _tags_cache["v"]


def model_size(name):
    for m in installed():
        if m["name"] == name or m["name"] == name + ":latest":
            return m["size"]
    return 0


def is_installed(name):
    return name == "scripted" or any(m["name"] in (name, name + ":latest") for m in installed())


def loaded():
    """{model name: bytes held in video memory} for models Ollama has in memory now."""
    try:
        return {m["name"]: m.get("size_vram", 0) for m in _get("/api/ps").get("models", [])}
    except Exception:
        return {}


def unload(model):
    if not model or model == "scripted":
        return
    try:
        _post("/api/generate", {"model": model, "keep_alive": 0}, timeout=20)
    except Exception:
        pass


def version():
    try:
        return _get("/api/version").get("version", "")
    except Exception:
        return ""


def pull(model, on_progress):
    """Download a model. `on_progress(status, total, done)` returns False to stop."""
    req = urllib.request.Request(OLLAMA_URL + "/api/pull",
                                 data=json.dumps({"model": model, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    layers = {}
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            for raw in r:
                if not raw.strip():
                    continue
                msg = json.loads(raw.decode("utf-8", "replace"))
                if msg.get("error"):
                    err = str(msg["error"])
                    if "file does not exist" in err or "not found" in err:
                        err = "there is no model by that name (check the spelling and the part after the colon)"
                    raise ProviderError(err[:300])
                if msg.get("digest") and msg.get("total"):
                    layers[msg["digest"]] = (msg["total"], msg.get("completed", 0))
                total = sum(t for t, _ in layers.values())
                done = sum(c for _, c in layers.values())
                if on_progress(msg.get("status", ""), total, done) is False:
                    raise Cancelled()
                if msg.get("status") == "success":
                    return True
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("error", "")
        except Exception:
            detail = ""
        raise ProviderError(detail or "Ollama refused the download (HTTP %s)" % e.code)
    except urllib.error.URLError as e:
        raise ProviderError("Ollama is not running (%s)" % e.reason)
    raise ProviderError("the download ended before Ollama said it was complete")


def delete(model):
    req = urllib.request.Request(OLLAMA_URL + "/api/delete", data=json.dumps({"model": model}).encode(),
                                 headers={"Content-Type": "application/json"}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=60):
            pass
    except urllib.error.HTTPError as e:
        raise ProviderError("Ollama could not delete it (HTTP %s)" % e.code)
    installed(max_age=0)


# --- chat --------------------------------------------------------------------

def _think_value(model):
    # gpt-oss cannot switch reasoning off, only down.
    return "low" if "gpt-oss" in model.lower() else False


def chat(model, system, prompt, temperature=0.8, num_ctx=16384, max_tokens=9000,
         on_progress=None, cancel=None, keep_alive="10m", timeout=900):
    """Stream one reply. `on_progress(chars, tokens_per_sec, new_text)` is called as text arrives;
    setting the `cancel` event aborts the generation. Returns (text, stats)."""
    if model == "scripted":
        return scripted(prompt), {"tokens": 0, "seconds": 0.0, "tps": 0.0}

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "stream": True,
        "think": _think_value(model),
        "keep_alive": keep_alive,
        "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": max_tokens},
    }
    last_err = None
    for attempt in range(3):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        parts, started, stats = [], time.time(), {}
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                first = None
                for raw in r:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    if not raw.strip():
                        continue
                    msg = json.loads(raw.decode("utf-8", "replace"))
                    if msg.get("error"):
                        raise ProviderError(str(msg["error"])[:300])
                    piece = (msg.get("message") or {}).get("content") or ""
                    if piece:
                        if first is None:
                            first = time.time()
                        parts.append(piece)
                        if on_progress and len(parts) % 4 == 0:
                            n = len(parts)
                            new = "".join(parts[-4:])
                            on_progress(len(new), n / max(0.5, time.time() - first), new)
                    if msg.get("done"):
                        stats = msg
            text = "".join(parts)
            ev, dur = stats.get("eval_count", len(parts)), stats.get("eval_duration", 0) / 1e9
            return text, {"tokens": ev, "seconds": time.time() - started,
                          "tps": (ev / dur) if dur else 0.0,
                          "load": stats.get("load_duration", 0) / 1e9,
                          "truncated": stats.get("done_reason") == "length"}
        except Cancelled:
            raise
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:
                pass
            last_err = "HTTP %s from ollama: %s" % (e.code, detail)
            if e.code == 400 and "think" in detail.lower() and "think" in payload:
                payload.pop("think")
                continue
            if e.code == 404:
                break
        except urllib.error.URLError as e:
            last_err = "ollama unreachable (%s)" % e.reason
        except (TimeoutError, OSError) as e:
            last_err = "ollama connection failed (%s)" % e
        time.sleep(2 * (attempt + 1))
    raise ProviderError(last_err or "ollama call failed")


# --- embeddings --------------------------------------------------------------

def embed(texts, model="embeddinggemma"):
    """Unit-length vectors for each text, or None if the embedding model is not usable."""
    if not texts:
        return []
    try:
        body = _post("/api/embed", {
            "model": model, "keep_alive": "30m",
            "input": ["task: sentence similarity | query: " + t for t in texts]}, timeout=120)
        vecs = body.get("embeddings") or []
        if len(vecs) != len(texts):
            return None
        out = []
        for v in vecs:
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([round(x / n, 5) for x in v])
        return out
    except Exception:
        return None


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


# --- scripted model (tests, and a demo with no GPU) --------------------------

_IDEAS = [
    ("Collatz Basin Explorer", "python", "Walks Collatz orbits and ranks the longest.",
     {"main.py": 'def steps(n):\n    s = 0\n    while n != 1:\n        n = n // 2 if n % 2 == 0 else 3 * n + 1\n        s += 1\n    return s\n\nbest = sorted(((steps(n), n) for n in range(1, 3000)), reverse=True)[:8]\nfor s, n in best:\n    print("%5d  %d steps" % (n, s))\n'}),
    ("Lissajous Weaver", "web", "Drifting Lissajous figures across two pages with a shared script.",
     {"index.html": '<!doctype html>\n<html><head><meta charset="utf-8"><title>Weaver</title>\n<link rel="stylesheet" href="style.css"></head>\n<body><nav><a href="about.html">about</a></nav><canvas id="c" width="500" height="500"></canvas>\n<script src="weave.js"></script></body></html>\n',
      "about.html": '<!doctype html>\n<html><head><meta charset="utf-8"><title>About</title>\n<link rel="stylesheet" href="style.css"></head>\n<body><nav><a href="index.html">back</a></nav><p>Two sine waves, one curve.</p></body></html>\n',
      "style.css": "body{margin:0;background:#000;color:#eee;font-family:monospace}canvas{display:block;margin:auto}nav{padding:8px}a{color:#eee}\n",
      "weave.js": "const c=document.getElementById('c'),x=c.getContext('2d');let t=0;\nfunction f(){x.fillStyle='rgba(0,0,0,.08)';x.fillRect(0,0,500,500);x.strokeStyle='#fff';x.beginPath();\nfor(let i=0;i<600;i++){const u=i/600*Math.PI*2;const px=250+200*Math.sin(3*u+t),py=250+200*Math.sin(4*u);i?x.lineTo(px,py):x.moveTo(px,py);}\nx.stroke();t+=.01;requestAnimationFrame(f);}f();\n"}),
]


def scripted(prompt):
    """Deterministic stand-in so the whole pipeline can be exercised without a model."""
    idea = random.choice(_IDEAS)
    for cand in _IDEAS:
        if cand[0] in prompt:
            idea = cand
    title, kind, summary, files = idea
    if "PITCH" in prompt.split("\n", 1)[0]:
        n = random.randint(100, 999)
        return ("TITLE: %s %d\nKIND: %s\nSUMMARY: %s\nTAGS: demo, scripted\nFILES:\n%s\n"
                % (title, n, kind, summary,
                   "\n".join("- %s: part of the demo" % f for f in files)))
    if "WRITE FILE" in prompt.split("\n", 1)[0]:
        want = prompt.split("\n", 1)[0].split("WRITE FILE", 1)[1].strip().strip(":").strip()
        body = files.get(want) or "# %s\nprint('hello from %s')\n" % (want, want)
        return "=== FILE: %s ===\n%s=== END FILE ===\n" % (want, body)
    if "BROKEN" in prompt:
        return ("RATIONALE: Deliberately broken edit for testing the publish gate.\n"
                "=== FILE: main.py ===\nprint('oops'\n=== END FILE ===\n"
                "=== FILE: index.html ===\n<!doctype html><html><body><script>nope.nope();</script></body></html>\n=== END FILE ===\n")
    stamp = time.strftime("%H:%M:%S")
    if "main.py" in prompt and "index.html" not in prompt:
        return ("RATIONALE: Added a timestamp line to the output.\n"
                "=== FILE: notes.py ===\nSTAMP = '%s'\n=== END FILE ===\n" % stamp)
    return ("RATIONALE: Added a small notes page.\n"
            "=== FILE: notes.html ===\n<!doctype html><html><body><p>revised %s</p></body></html>\n=== END FILE ===\n" % stamp)
