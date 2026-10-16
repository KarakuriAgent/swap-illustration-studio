"""履歴（SQLite）。

1 回の「生成」= 1 ジョブ。入力（A・A_marked・B 群・枠）、指示文、設定、結果（複数枚）を保存し、
履歴から設定を再利用できるようにする。ファイルの実体は data/jobs/<id>/ に置き、DB にはファイル名だけ。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import data_dir

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_path: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,          -- queued / running / done / error / cancelled
    message TEXT,                  -- 状態の説明（再試行中など）
    error TEXT,
    progress REAL NOT NULL DEFAULT 0,
    prompt TEXT NOT NULL,
    request TEXT NOT NULL,         -- 生成リクエスト（枠・服装・設定など、再利用用）
    settings TEXT NOT NULL,        -- 実際に使った設定（seed・強さ・LoRA 名・実行先など）
    inputs TEXT NOT NULL,          -- 送ったファイル（A / A_marked / B1…）
    results TEXT NOT NULL DEFAULT '[]',   -- [{"file", "seed", "elapsed"}]
    parent_id TEXT                 -- 再生成の元
);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at DESC);
"""

JSON_FIELDS = ("request", "settings", "inputs", "results")


def connect(path: Path | None = None) -> sqlite3.Connection:
    global _conn, _path
    target = path or data_dir() / "swap.db"
    with _lock:
        if _conn is None or _path != target:
            if _conn is not None:
                _conn.close()
            _conn = sqlite3.connect(target, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.execute("PRAGMA journal_mode=WAL")
            _path = target
        return _conn


def close() -> None:
    global _conn, _path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, _path = None, None


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_FIELDS:
        d[k] = json.loads(d[k]) if d.get(k) else ([] if k == "results" else {})
    return d


def insert_job(job: dict[str, Any]) -> None:
    c = connect()
    with _lock:
        c.execute(
            "INSERT INTO jobs (id, created_at, status, message, progress, prompt, request, settings, inputs, results, parent_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (job["id"], job.get("created_at", time.time()), job.get("status", "queued"), job.get("message"),
             0.0, job["prompt"], json.dumps(job["request"], ensure_ascii=False),
             json.dumps(job["settings"], ensure_ascii=False), json.dumps(job["inputs"], ensure_ascii=False),
             json.dumps(job.get("results", []), ensure_ascii=False), job.get("parent_id")),
        )
        c.commit()


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k} = ?")
        vals.append(json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else v)
    c = connect()
    with _lock:
        c.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", (*vals, job_id))
        c.commit()


def get_job(job_id: str) -> dict[str, Any] | None:
    c = connect()
    with _lock:
        return _row(c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def list_jobs(limit: int = 50, before: float | None = None) -> list[dict[str, Any]]:
    c = connect()
    with _lock:
        if before is None:
            rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM jobs WHERE created_at < ? ORDER BY created_at DESC LIMIT ?",
                             (before, limit)).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def delete_job(job_id: str) -> None:
    c = connect()
    with _lock:
        c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        c.commit()


def mark_stale_running() -> int:
    """起動時: 前回の実行中・待ち中のジョブを「中断」にする（プロセスが落ちて続きが無いため）。"""
    c = connect()
    with _lock:
        cur = c.execute(
            "UPDATE jobs SET status = 'error', error = ?, finished_at = ? WHERE status IN ('queued', 'running')",
            ("アプリが再起動したため中断しました。履歴から再生成できます。", time.time()))
        c.commit()
        return cur.rowcount
