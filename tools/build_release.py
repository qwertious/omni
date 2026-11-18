"""Build the Windows installer zip: dist/omni-setup-<version>.zip

    python tools/build_release.py          # package what is there
    python tools/build_release.py --ui     # rebuild the interface first (needs Node)

The zip holds "Install Omni.cmd", the PowerShell installer and an `app` folder with the
program itself. No data, settings or tokens are ever included: those live in ~/.omni.
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_FILES = ["agent.py", "bus.py", "catalog.py", "checker.py", "discord_relay.py", "gate.py", "omni.py",
             "providers.py", "runner.py", "saver.py", "server.py", "store.py", "README.md", "LICENSE"]
APP_DIRS = ["static", os.path.join("ui", "dist")]
INSTALLER = ["Install Omni.cmd", "install.ps1", "uninstall.ps1", "README.txt"]


def version():
    with open(os.path.join(ROOT, "omni.py"), encoding="utf-8") as f:
        return re.search(r'__version__ = "([^"]+)"', f.read()).group(1)


def main():
    if "--ui" in sys.argv:
        subprocess.run("npx vite build", cwd=os.path.join(ROOT, "web"), shell=True, check=True)
    if not os.path.isfile(os.path.join(ROOT, "ui", "dist", "index.html")):
        sys.exit("ui/dist is missing: run with --ui (needs Node) first")
    ver = version()
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "omni-setup-%s.zip" % ver)
    top = "omni-setup-%s" % ver
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in INSTALLER:
            z.write(os.path.join(ROOT, "installer", name), "%s/%s" % (top, name))
        for name in APP_FILES:
            p = os.path.join(ROOT, name)
            if os.path.isfile(p):
                z.write(p, "%s/app/%s" % (top, name))
        for d in APP_DIRS:
            for base, _, files in os.walk(os.path.join(ROOT, d)):
                for f in files:
                    if f.endswith((".pyc", ".map")):
                        continue
                    full = os.path.join(base, f)
                    rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                    z.write(full, "%s/app/%s" % (top, rel))
    size = os.path.getsize(out)
    print("%s  (%.0f KB)" % (out, size / 1024))
    return out


if __name__ == "__main__":
    main()
