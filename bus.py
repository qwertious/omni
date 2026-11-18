"""Tiny in-process pub/sub so SSE clients see activity the moment it happens."""
import json
import queue
import threading

_subs = []
_lock = threading.Lock()


def subscribe():
    q = queue.Queue(maxsize=200)
    with _lock:
        _subs.append(q)
    return q


def unsubscribe(q):
    with _lock:
        if q in _subs:
            _subs.remove(q)


def publish(type_, **payload):
    msg = json.dumps(dict(payload, type=type_))
    with _lock:
        targets = list(_subs)
    for q in targets:
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass
