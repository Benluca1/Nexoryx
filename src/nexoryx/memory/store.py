"""SQLite-basierter Multi-Layer-Speicher (zero-dependency, stdlib sqlite3).

Layer über die Spalte `scope`: long (user-global) | project (pro Pfad) |
preference (Key-Value). Short-Term hält der Aufrufer in-process.
Recall = hybrid: Keyword-Overlap + Recency-Decay + Importance + Trefferzähler.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ..platform.config import CONFIG_DIR, ensure_dir

DB_PATH = CONFIG_DIR / "memory.db"
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Memory:
    id: int
    scope: str
    project: str
    text: str
    importance: float
    ts: float
    hits: int


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if len(w) > 2}


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        ensure_dir()
        self.db = sqlite3.connect(str(path or DB_PATH))
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS memories(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 scope TEXT NOT NULL,
                 project TEXT NOT NULL DEFAULT '',
                 text TEXT NOT NULL,
                 importance REAL NOT NULL DEFAULT 1.0,
                 ts REAL NOT NULL,
                 hits INTEGER NOT NULL DEFAULT 0)"""
        )
        self.db.commit()

    # --- Schreiben ---
    def remember(self, text: str, scope: str = "long", project: str = "",
                 importance: float = 1.0) -> int:
        cur = self.db.execute(
            "INSERT INTO memories(scope,project,text,importance,ts) VALUES(?,?,?,?,?)",
            (scope, project, text.strip(), importance, time.time()),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def set_preference(self, key: str, value: str) -> None:
        self.db.execute("DELETE FROM memories WHERE scope='preference' AND text LIKE ?",
                        (f"{key}=%",))
        self.remember(f"{key}={value}", scope="preference", importance=2.0)

    # --- Lesen ---
    def recall(self, query: str, project: str = "", limit: int = 5) -> list[Memory]:
        q_tokens = _tokens(query)
        rows = self.db.execute(
            "SELECT * FROM memories WHERE scope!='preference' AND (project='' OR project=?)",
            (project,),
        ).fetchall()
        now = time.time()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            overlap = len(q_tokens & _tokens(row["text"]))
            if overlap == 0 and q_tokens:
                continue
            age_days = (now - row["ts"]) / 86400.0
            recency = 1.0 / (1.0 + age_days)
            score = overlap * 2.0 + row["importance"] + recency + 0.1 * row["hits"]
            scored.append((score, row))
        scored.sort(key=lambda s: s[0], reverse=True)
        out = []
        for _, row in scored[:limit]:
            self.db.execute("UPDATE memories SET hits=hits+1 WHERE id=?", (row["id"],))
            out.append(self._row(row))
        self.db.commit()
        return out

    def preferences(self) -> dict[str, str]:
        rows = self.db.execute("SELECT text FROM memories WHERE scope='preference'").fetchall()
        out = {}
        for r in rows:
            if "=" in r["text"]:
                k, v = r["text"].split("=", 1)
                out[k] = v
        return out

    def recent(self, limit: int = 10, project: str = "") -> list[Memory]:
        rows = self.db.execute(
            "SELECT * FROM memories WHERE scope!='preference' AND (project='' OR project=?) "
            "ORDER BY ts DESC LIMIT ?",
            (project, limit),
        ).fetchall()
        return [self._row(r) for r in rows]

    # --- Löschen ---
    def forget(self, query: str) -> int:
        q_tokens = _tokens(query)
        ids = [
            r["id"] for r in self.db.execute("SELECT id,text FROM memories").fetchall()
            if q_tokens & _tokens(r["text"])
        ]
        for i in ids:
            self.db.execute("DELETE FROM memories WHERE id=?", (i,))
        self.db.commit()
        return len(ids)

    def _row(self, r: sqlite3.Row) -> Memory:
        return Memory(r["id"], r["scope"], r["project"], r["text"],
                      r["importance"], r["ts"], r["hits"])

    def close(self) -> None:
        self.db.close()
