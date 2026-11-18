"""Omni -- a workshop of local AI makers.

    python omni.py                  # http://localhost:7777
    python omni.py --port 7790      # somewhere else
    python omni.py --no-browser     # do not open a tab

Personas, their models, autonomy and everything else are set in the interface.
Data lives in ~/.omni (or $OMNI_HOME).
"""
__version__ = "2.1.0"

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if "--home" in sys.argv[1:-1]:      # must be decided before the store module is imported
    os.environ["OMNI_HOME"] = sys.argv[sys.argv.index("--home") + 1]
if sys.stdout is None or sys.stderr is None:   # started with pythonw (no console): keep a log file
    _home = os.environ.get("OMNI_HOME") or os.path.join(os.path.expanduser("~"), ".omni")
    os.makedirs(_home, exist_ok=True)
    _log = os.path.join(_home, "omni.log")
    if os.path.exists(_log) and os.path.getsize(_log) > 2_000_000:
        os.replace(_log, _log + ".1")
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)

import agent
import checker
import discord_relay
import saver as saver_mod
import server
import store


def tailnet_name():
    """This machine's Tailscale DNS name, or '' if Tailscale is not running."""
    try:
        out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True,
                             timeout=6, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (json.loads(out.stdout).get("Self", {}).get("DNSName") or "").rstrip(".")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(prog="omni")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--remote-port", type=int, default=None,
                    help="second local port for Tailscale to forward to (default: port + 1); 0 = off")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--home", default=None, help="data directory (default: ~/.omni)")
    ap.add_argument("--discord-token", default=None,
                    help="bot token; saved to ~/.omni/config.json so you only pass it once")
    ap.add_argument("--discord-channel", default=None, help="channel name (default: omni)")
    ap.add_argument("--no-discord", action="store_true")
    ap.add_argument("--autonomy", choices=["off", "idle", "always"], default=None,
                    help="override the saved autonomy setting")
    ap.add_argument("--no-saver", action="store_true",
                    help="no screensaver and no step-aside hotkey (for test copies)")
    args = ap.parse_args()

    store.init()
    agent.seed_personas()
    if args.autonomy:
        store.set_setting("autonomy", args.autonomy)

    cfg = store.load_config()
    token = args.discord_token or os.environ.get("OMNI_DISCORD_TOKEN") or cfg.get("discord_token")
    channel = args.discord_channel or cfg.get("discord_channel") or "omni"
    if args.discord_token or args.discord_channel:
        cfg.update(discord_token=token, discord_channel=channel)
        store.save_config(cfg)

    httpd = server.serve(args.host, args.port)
    server.local_port = args.port
    checker.BASE_URL = "http://127.0.0.1:%d" % args.port
    url = "http://%s:%d" % ("localhost" if args.host == "127.0.0.1" else args.host, args.port)

    remote_port = args.port + 1 if args.remote_port is None else args.remote_port
    remote_httpd = None
    if remote_port:
        try:
            remote_httpd = server.serve("127.0.0.1", remote_port, server.RemoteHandler)
            threading.Thread(target=remote_httpd.serve_forever, daemon=True, name="omni-remote").start()
            name = tailnet_name()
            server.remote_info.update(enabled=True, port=remote_port,
                                      url="http://%s:%d" % (name, args.port) if name else "")
        except OSError as e:
            print("  remote   : could not open port %d (%s)" % (remote_port, e))

    worker = agent.Worker()
    server.worker = worker
    worker.start()

    if sys.platform == "win32" and not args.no_saver:
        saver = saver_mod.Saver(worker, "http://127.0.0.1:%d/#/saver" % args.port)
        server.saver = saver
        saver.start()

        def step_aside():
            worker.step_aside("hotkey")
            saver.hide()
        hk = saver_mod.Hotkey(step_aside)
        server.hotkey = hk
        hk.start()

    relay = None
    if token and not args.no_discord:
        relay = discord_relay.Relay(token, channel, url)
        server.relay = relay
        relay.start()

    print("Omni %s is running at %s" % (__version__, url))
    print("  personas : %s" % ", ".join("@%s (%s)" % (p["handle"], p["model"])
                                         for p in store.list_personas(True)))
    print("  autonomy : %s" % store.get_setting("autonomy"))
    print("  remote   : %s" % (server.remote_info["url"] or "off"))
    print("  discord  : %s" % ("relaying to #%s" % channel if relay else "off"))
    print("  data     : %s" % store.OMNI_HOME)
    sys.stdout.flush()

    if not args.no_browser:
        first = url
        if not any(p["model"] and agent.providers.is_installed(p["model"]) for p in store.list_personas(True)):
            first += "/#/models"          # nothing can run yet: start where the models are
        threading.Timer(0.6, lambda: webbrowser.open(first)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        worker.stop()
        if relay:
            relay.stop()
        if remote_httpd:
            remote_httpd.shutdown()
        httpd.shutdown()


if __name__ == "__main__":
    main()
