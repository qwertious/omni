"""Runs Python projects in a contained subprocess.

Containment, not security: a wall-clock limit, capped output, a stripped
environment and a pinned working directory. Programs can still read files and
reach the network, which is the current, deliberate policy.
"""
import os
import subprocess
import sys
import time

import store

TIMEOUT = 15
MAX_OUTPUT = 12000


def entry_file(files):
    for candidate in ("main.py", "run.py", "app.py"):
        if candidate in files:
            return candidate
    for name in sorted(files):
        if name.endswith(".py") and "/" not in name:
            return name
    return None


def run_dir(cwd, entry, timeout=TIMEOUT):
    """Run `entry` inside `cwd`. Returns {exit_code, stdout, stderr, duration, entry}."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMNI_SANDBOX": "1",
    }
    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-E", "-s", entry], cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        code = -1
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        err = "TimeoutExpired: still running after %ds. Programs must finish on their own." % timeout
    except Exception as e:
        code, out, err = -2, "", "%s: %s" % (type(e).__name__, e)
    return {"exit_code": code, "stdout": (out or "")[:MAX_OUTPUT], "stderr": (err or "")[:MAX_OUTPUT],
            "duration": time.time() - start, "entry": entry}


def record(pid, revision_id, result):
    """Store a run that already happened (for example the one done by the publish check)."""
    rid = store.add_run(pid, revision_id, result["exit_code"], result["stdout"], result["stderr"],
                        result["duration"])
    store.add_event(pid, "run", "sandbox",
                    "exit %s in %.2fs" % (result["exit_code"], result["duration"]),
                    {"run_id": rid, "exit_code": result["exit_code"], "entry": result.get("entry")})
    return rid


def run_program(pid):
    """Run the live version of a project on request."""
    program = store.get_program(pid)
    files = store.head_files(pid)
    if program["kind"] != "python":
        return {"skipped": "web projects render in the browser"}
    entry = entry_file(files)
    if not entry:
        return {"skipped": "no python entry file found"}
    cwd = store.program_dir(pid)
    store.write_tree(cwd, files)
    result = run_dir(cwd, entry)
    result["run_id"] = record(pid, program["head_rev"], result)
    return result
