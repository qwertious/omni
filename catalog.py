"""Which models are worth downloading on this computer, and the downloads themselves.

The catalog is a hand-picked list. For every model it knows several builds (quantisations)
of different sizes; `recommend()` looks at the video card and system memory and picks, for
each model, the biggest build that runs well here, then ranks the models for this machine.
"""
import os
import re
import shutil
import sqlite3
import sys
import threading
import time

import bus
import gate
import providers

GB = 1e9   # sizes below are decimal gigabytes, as download pages show them

# quality: our judgement of how good the model is at writing small, complete projects (0-100).
# moe: a mixture-of-experts model only reads a few billion parameters per token, so it stays
# quick even when part of it has to live in system memory.
CATALOG = [
    {"id": "qwen3.8-27b", "name": "Qwen 3.8 27B", "maker": "Alibaba", "released": "2026-08",
     "quality": 88, "moe": False, "suits": "both",
     "blurb": "The newest Qwen. A dense model, so it is slower than Qwen 3.6, but it is the stronger "
              "coder of the two and is reported to rank above it on coding benchmarks.",
     "good_at": ["multi-file projects", "careful fixes", "python and web"],
     "builds": [("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_XXS", 10.9),
                ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL", 13.1),
                ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ4_XS", 14.4),
                ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL", 17.7),
                ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q5_K_XL", 21.0),
                ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q6_K_XL", 25.3)]},
    {"id": "qwen3.6-35b-a3b", "name": "Qwen 3.6 35B-A3B", "maker": "Alibaba", "released": "",
     "quality": 86, "moe": True, "suits": "both",
     "blurb": "Fast and very capable: 35B parameters, but only 3B are used per token, so it writes at "
              "around 100 tokens a second on a 16 GB card. It built every one of Omni's benchmark projects cleanly.",
     "good_at": ["speed", "multi-file projects", "interactive web pages"],
     "builds": [("hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ2_M", 11.5),
                ("hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS", 13.2),
                ("hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q3_K_XL", 16.8),
                ("hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS", 17.7),
                ("hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_XL", 22.4),
                ("hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q5_K_S", 24.9)],
     "aliases": ["qwen3.6:latest", "qwen3.6:35b"]},
    {"id": "glm-4.7-flash", "name": "GLM 4.7 Flash", "maker": "Z.ai", "released": "2026-01",
     "quality": 84, "moe": True, "suits": "create",
     "blurb": "A 30B mixture-of-experts model (3B active) with a reputation for good-looking front ends. "
              "A natural fit for visual, web-first makers. Quick for its size.",
     "good_at": ["web pages that look designed", "canvas and animation", "speed"],
     "builds": [("hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-IQ2_M", 11.0),
                ("hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-IQ3_XXS", 12.9),
                ("hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-Q3_K_XL", 13.8),
                ("hf.co/unsloth/GLM-4.7-Flash-GGUF:IQ4_XS", 16.3),
                ("hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-Q4_K_XL", 17.5),
                ("hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-Q5_K_XL", 21.7)],
     "aliases": ["glm-4.7-flash:latest"]},
    {"id": "devstral-small-2", "name": "Devstral Small 2 24B", "maker": "Mistral", "released": "2025-12",
     "quality": 80, "moe": False, "suits": "edit",
     "blurb": "Mistral's coding model, tuned for changing existing code (68% on SWE-bench Verified). "
              "Dense, so steady rather than quick. Good at edits and repairs.",
     "good_at": ["fixing bugs", "editing existing projects", "tidy code"],
     "builds": [("hf.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF:Q3_K_M", 11.5),
                ("hf.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF:IQ4_XS", 12.8),
                ("hf.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF:Q4_K_M", 14.3),
                ("hf.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF:Q5_K_M", 16.8),
                ("hf.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF:Q6_K", 19.3)],
     "aliases": ["devstral-small-2:24b", "devstral-small-2:latest"]},
    {"id": "gemma4-26b-a4b", "name": "Gemma 4 26B-A4B", "maker": "Google", "released": "2026-06",
     "quality": 78, "moe": True, "suits": "create",
     "blurb": "The big Gemma 4, in Google's quantisation-aware build. A large step up from the 8B Gemma 4 "
              "for both code and taste.",
     "good_at": ["visual ideas", "writing", "general knowledge"],
     "builds": [("hf.co/unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL", 14.2)],
     "aliases": ["gemma4:26b"]},
    {"id": "qwen3-coder-30b", "name": "Qwen3 Coder 30B-A3B", "maker": "Alibaba", "released": "2025-07",
     "quality": 76, "moe": True, "suits": "both",
     "blurb": "An older coding specialist. Fast like Qwen 3.6, but Qwen 3.6 has overtaken it.",
     "good_at": ["speed", "python"],
     "builds": [("hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:UD-IQ3_XXS", 12.8),
                ("hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:UD-Q3_K_XL", 13.8),
                ("hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:IQ4_XS", 16.4),
                ("hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:UD-Q4_K_XL", 17.7)],
     "aliases": ["qwen3-coder:30b"]},
    {"id": "nemotron-3.5-lightning", "name": "Nemotron 3.5 Lightning 30B-A3B", "maker": "NVIDIA",
     "released": "2026-09", "quality": 74, "moe": True, "suits": "both",
     "blurb": "NVIDIA's fast mixture-of-experts model. Its smallest build is about 20 GB, so it suits cards "
              "with 24 GB or more.",
     "good_at": ["speed", "long context"],
     "builds": [("hf.co/unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF:UD-IQ3_XXS", 19.8),
                ("hf.co/unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF:MXFP4_MOE", 23.2),
                ("hf.co/unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF:UD-Q4_K_XL", 25.5)]},
    {"id": "gpt-oss-20b", "name": "gpt-oss 20B", "maker": "OpenAI", "released": "2025-08",
     "quality": 72, "moe": True, "suits": "both",
     "blurb": "Good at reasoning and fast, but it always thinks before answering, which costs time, and "
              "its code is plainer than the Qwen models'.",
     "good_at": ["reasoning", "small tools"],
     "builds": [("gpt-oss:20b", 13.8)]},
    {"id": "lfm2.5-24b-a2b", "name": "LFM 2.5 24B-A2B", "maker": "Liquid AI", "released": "2026-10",
     "quality": 64, "moe": True, "suits": "both",
     "blurb": "Very fast (2B active parameters), even without a big video card. Weaker at long programs.",
     "good_at": ["speed", "computers without a big video card"],
     "builds": [("hf.co/unsloth/LFM2.5-24B-A2B-GGUF:UD-Q3_K_XL", 10.9),
                ("hf.co/unsloth/LFM2.5-24B-A2B-GGUF:UD-Q4_K_XL", 14.9),
                ("hf.co/unsloth/LFM2.5-24B-A2B-GGUF:UD-Q5_K_XL", 17.9)],
     "aliases": ["lfm2.5:24b"]},
    {"id": "qwen3.5-9b", "name": "Qwen 3.5 9B", "maker": "Alibaba", "released": "2026-02",
     "quality": 60, "moe": False, "suits": "both",
     "blurb": "The best small model for 8 GB cards. Single-file projects come out well; big ones less so.",
     "good_at": ["8 GB video cards", "single-file projects"],
     "builds": [("qwen3.5:9b", 6.6)]},
    {"id": "gemma4-12b", "name": "Gemma 4 12B", "maker": "Google", "released": "2026-08",
     "quality": 57, "moe": False, "suits": "create",
     "blurb": "A small Gemma with good taste for visual toys. Fits an 8-12 GB card.",
     "good_at": ["visual toys", "8-12 GB video cards"],
     "builds": [("gemma4:12b", 7.7)]},
    {"id": "gemma4-e4b", "name": "Gemma 4 E4B", "maker": "Google", "released": "2026-04",
     "quality": 48, "moe": False, "suits": "create",
     "blurb": "Light enough for laptops. Expect simple projects.",
     "good_at": ["laptops", "no video card"],
     "builds": [("gemma4:e4b", 6.6)], "aliases": ["gemma4:latest"]},
    {"id": "qwen3.5-4b", "name": "Qwen 3.5 4B", "maker": "Alibaba", "released": "2026-02",
     "quality": 42, "moe": False, "suits": "both",
     "blurb": "The smallest model that still writes working code. For machines with 8-16 GB of memory "
              "and no video card.",
     "good_at": ["low-memory computers"],
     "builds": [("qwen3.5:4b", 3.3)]},
]

BITS_RE = re.compile(r"(?:IQ|Q)(\d)|MXFP4|TQ1", re.I)


def bits(tag):
    m = BITS_RE.search(tag.split(":")[-1])
    if not m:
        return 4
    if m.group(1):
        return int(m.group(1))
    return 4 if "MXFP4" in m.group(0).upper() else 1


def quant_name(tag):
    q = tag.split(":")[-1] if ":" in tag else ""
    return q if q and q != "latest" and not q[0].isdigit() and not q.endswith("b") else "standard"


# --- the computer --------------------------------------------------------------

def _gpu_from_registry():
    """(name, bytes) of the largest display adapter, for cards nvidia-smi does not know."""
    if sys.platform != "win32":
        return "", 0
    import winreg
    best = ("", 0)
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    for i in range(16):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "%s\\%04d" % (base, i)) as k:
                try:
                    size = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                except OSError:
                    size = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                    if isinstance(size, bytes):
                        size = int.from_bytes(size[:8], "little")
                name = winreg.QueryValueEx(k, "DriverDesc")[0]
                if int(size) > best[1]:
                    best = (name, int(size))
        except OSError:
            continue
    return best


_hw = {"at": 0, "v": None}


def models_dir():
    """Where Ollama keeps its models (the desktop app's own setting wins over the variable)."""
    try:
        db = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Ollama", "db.sqlite")
        if os.path.exists(db):
            c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=2)
            row = c.execute("SELECT models FROM settings LIMIT 1").fetchone()
            c.close()
            if row and row[0] and os.path.isdir(row[0]):
                return row[0]
    except Exception:
        pass
    env = os.environ.get("OLLAMA_MODELS")
    if env and os.path.isdir(env):
        return env
    return os.path.join(os.path.expanduser("~"), ".ollama", "models")


def hardware(max_age=60):
    if _hw["v"] and time.time() - _hw["at"] < max_age:
        return _hw["v"]
    rt, _ = gate.ram()
    name, vt = gate.gpu_name(), gate.vram()[0]
    vendor = "nvidia" if vt else ""
    if not vt:
        name, vt = _gpu_from_registry()
        vendor = "other" if vt else ""
        if vt < 3.5 * 1024 ** 3:      # integrated graphics share system memory; treat as none
            name, vt, vendor = name, 0, ""
    path = models_dir()
    probe = path
    while probe and not os.path.exists(probe):
        probe = os.path.dirname(probe)
    try:
        free = shutil.disk_usage(probe or os.path.expanduser("~")).free
    except OSError:
        free = 0
    v = {"gpu": name, "vendor": vendor, "vram": vt, "ram": rt, "disk_free": free, "models_dir": path,
         "ollama": providers.version()}
    _hw.update(at=time.time(), v=v)
    return v


# --- choosing -------------------------------------------------------------------

def place(size_gb, moe, hw):
    """How a model of this size would run here: gpu, split (part in system memory), cpu, or None."""
    vram = hw["vram"] / 1024 ** 3
    ram = hw["ram"] / 1024 ** 3
    need = size_gb * GB / 1024 ** 3 + 1.5            # weights + working memory for a 16k context
    if vram >= 4 and need <= (vram - 0.6) * 1.06:     # a sliver over is fine: Ollama trims the context
        return "gpu"
    on_card = max(0.0, vram - 0.8) if vram >= 4 else 0.0
    spill = need - on_card
    if ram - spill < 10:                              # keep 10 GB for Windows and the person's apps
        return None
    if on_card == 0:
        return "cpu"
    if moe or spill <= 0.2 * need:
        return "split"
    return "cpu"


SPEED = {("gpu", True): "fast", ("gpu", False): "steady", ("split", True): "steady",
         ("split", False): "slow", ("cpu", True): "slow", ("cpu", False): "very slow"}
PENALTY = {"fast": 0, "steady": 2, "slow": 22, "very slow": 45}
WHERE_ORDER = {"gpu": 0, "split": 1, "cpu": 2}


def speed(where, moe, size_gb):
    if where == "gpu" and not moe and size_gb <= 9:
        return "fast"
    return SPEED[(where, moe)]


def _installed_names():
    return {m["name"] for m in providers.installed()}


def _which_installed(model, names):
    for tag, _ in model["builds"]:
        if tag in names or tag + ":latest" in names:
            return tag
    for a in model.get("aliases", []):
        if a in names:
            return a
    return None


def recommend(hw=None):
    hw = hw or hardware()
    names = _installed_names()
    bench = _bench()
    out = []
    for m in CATALOG:
        options = []
        for tag, size in m["builds"]:
            where = place(size, m["moe"], hw)
            if where:
                options.append((tag, size, where))
        have = _which_installed(m, names)
        pick = None
        good = [o for o in options if o[2] == "gpu" and bits(o[0]) >= 3]
        if good:
            pick = max(good, key=lambda o: o[1])
        else:
            ok = [o for o in options if bits(o[0]) >= 3]
            if ok:
                pick = min(ok, key=lambda o: (WHERE_ORDER[o[2]], -min(bits(o[0]), 4), o[1]))
        if not pick and not have:
            continue
        if pick:
            tag, size, where = pick
        else:
            tag, size = have, providers.model_size(have) / GB
            where = place(size, m["moe"], hw) or "cpu"
        pace = speed(where, m["moe"], size)
        score = m["quality"] - PENALTY[pace] - (4 if bits(tag) == 3 else 0) - (25 if bits(tag) < 3 else 0)
        sizes = {t: s for t, s in m["builds"]}
        builds = [{"tag": t, "size": s, "quant": quant_name(t), "where": place(s, m["moe"], hw),
                   "installed": t in names or t + ":latest" in names} for t, s in m["builds"]]
        out.append({
            "id": m["id"], "name": m["name"], "maker": m["maker"], "released": m["released"],
            "blurb": m["blurb"], "good_at": m["good_at"], "suits": m["suits"], "moe": m["moe"],
            "tag": tag, "size": sizes.get(tag, size), "quant": quant_name(tag), "where": where,
            "speed": pace, "score": score, "installed": have,
            "builds": builds, "bench": bench.get(have or tag),
        })
    out.sort(key=lambda r: -r["score"])
    for i, r in enumerate(out):
        r["rank"] = i + 1
        r["recommended"] = i < 3
    return out


def _bench():
    import store
    return store.get_setting("model_bench", {}) or {}


def save_bench(model, result):
    import store
    b = store.get_setting("model_bench", {}) or {}
    b[model] = result
    store.set_setting("model_bench", b)


# --- downloads ------------------------------------------------------------------

class Downloads:
    """Model downloads through Ollama, one at a time, with progress on the event bus."""

    def __init__(self):
        self.jobs = {}          # model -> state dict
        self._lock = threading.Lock()
        self._queue = []
        self._thread = None

    def list(self):
        with self._lock:
            return [dict(v) for v in self.jobs.values()]

    def start(self, model):
        model = (model or "").strip()
        if not re.match(r"^[\w.\-/:]+$", model) or len(model) > 200:
            raise ValueError("that is not a model name Ollama understands")
        with self._lock:
            cur = self.jobs.get(model)
            if cur and cur["state"] in ("queued", "downloading"):
                return cur
            self.jobs[model] = {"model": model, "state": "queued", "total": 0, "done": 0, "status": "",
                                "error": "", "started": time.time(), "speed": 0.0}
            self._queue.append(model)
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True, name="omni-pull")
                self._thread.start()
            return dict(self.jobs[model])

    def cancel(self, model):
        with self._lock:
            job = self.jobs.get(model)
            if not job:
                return
            if job["state"] == "queued":
                self._queue = [m for m in self._queue if m != model]
                job["state"] = "cancelled"
            elif job["state"] == "downloading":
                job["cancel"] = True
        self._publish(model, force=True)

    def clear(self, model):
        with self._lock:
            job = self.jobs.get(model)
            if job and job["state"] not in ("queued", "downloading"):
                self.jobs.pop(model, None)

    def _publish(self, model, force=False):
        job = self.jobs.get(model)
        if not job:
            return
        now = time.time()
        if force or now - job.get("_pub", 0) > 0.8:
            job["_pub"] = now
            bus.publish("pull", **{k: v for k, v in job.items() if not k.startswith("_") and k != "cancel"})

    def _run(self):
        while True:
            with self._lock:
                if not self._queue:
                    return
                model = self._queue.pop(0)
                job = self.jobs[model]
                job["state"] = "downloading"
            self._publish(model, force=True)
            samples = []

            def progress(status, total, done):
                job["status"], job["total"], job["done"] = status, total, done
                samples.append((time.time(), done))
                while len(samples) > 2 and samples[-1][0] - samples[0][0] > 8:
                    samples.pop(0)
                if len(samples) > 1 and samples[-1][0] > samples[0][0]:
                    job["speed"] = max(0.0, (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0]))
                self._publish(model)
                return not job.get("cancel")

            try:
                providers.pull(model, progress)
                job["state"] = "done"
                job["status"] = "installed"
            except providers.Cancelled:
                job["state"] = "cancelled"
                job["status"] = "stopped; Ollama keeps what was downloaded and continues from there next time"
            except Exception as e:
                job["state"] = "failed"
                job["error"] = str(e)[:400]
            job["finished"] = time.time()
            providers.installed(max_age=0)
            self._publish(model, force=True)
            bus.publish("models")


downloads = Downloads()
