"""Barramento de eventos thread-safe + histórico em SQLite.

O core publica; a GUI assina (e repassa para a thread do Qt por conta própria).
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import paths
from .logsetup import scrub

log = logging.getLogger(__name__)

SEVERITIES = ("info", "aviso", "critico")


@dataclass
class Event:
    kind: str  # estado | alerta | info | erro | nivel | acao
    message: str
    slot: int | None = None
    severity: str = "info"
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class EventBus:
    """Tópicos simples: 'event' (vai para o histórico), 'snapshot', 'alerts', etc."""

    def __init__(self, store: EventStore | None = None):
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.Lock()
        self.store = store

    def subscribe(self, topic: str, cb: Callable[[Any], None]) -> None:
        with self._lock:
            self._subs[topic].append(cb)

    def publish(self, topic: str, payload: Any) -> None:
        if topic == "event" and self.store is not None:
            try:
                self.store.add(payload)
            except Exception:
                log.exception("falha ao gravar evento")
        with self._lock:
            subs = list(self._subs.get(topic, ()))
        for cb in subs:
            try:
                cb(payload)
            except Exception:
                log.exception("assinante de %s falhou", topic)

    def emit(self, kind: str, message: str, slot: int | None = None, severity: str = "info", **data) -> Event:
        ev = Event(kind, message, slot, severity, data)
        log.log(logging.WARNING if severity != "info" else logging.INFO, "[%s] %s%s", kind,
                f"slot {slot}: " if slot else "", message)
        self.publish("event", ev)
        return ev


class EventStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "events.db")
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, slot INTEGER,"
            " severity TEXT, message TEXT, data TEXT)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts)")
        self._db.commit()

    def add(self, ev: Event) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO events (ts, kind, slot, severity, message, data) VALUES (?,?,?,?,?,?)",
                (ev.ts, ev.kind, ev.slot, ev.severity, scrub(ev.message), scrub(json.dumps(ev.data, default=str))),
            )
            self._db.commit()

    def query(self, limit: int = 500, slot: int | None = None, severity: str | None = None,
              text: str | None = None, since: float | None = None) -> list[Event]:
        sql = "SELECT ts, kind, slot, severity, message, data FROM events WHERE 1=1"
        args: list[Any] = []
        if slot is not None:
            sql += " AND slot = ?"
            args.append(slot)
        if severity:
            sql += " AND severity = ?"
            args.append(severity)
        if text:
            sql += " AND message LIKE ?"
            args.append(f"%{text}%")
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [Event(kind=k, message=m, slot=s, severity=sv, data=json.loads(d or "{}"), ts=t)
                for t, k, s, sv, m, d in rows]

    def export_csv(self, dest: Path, **filters) -> int:
        evs = self.query(limit=1_000_000, **filters)
        with dest.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["data_hora", "tipo", "slot", "severidade", "mensagem"])
            for e in reversed(evs):
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.ts)), e.kind,
                            e.slot or "", e.severity, e.message])
        return len(evs)

    def close(self) -> None:
        with self._lock:
            self._db.close()


def event_to_dict(ev: Event) -> dict:
    return asdict(ev)
