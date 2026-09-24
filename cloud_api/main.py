"""Cloud API — брокер задач между вами (телефон/веб) и Local Agent на офисном компьютере.

Как это работает:
  1. Вы (или веб-страница/бот) создаёте задачу: POST /tasks {"type": "GET_ORDERS"}.
  2. Local Agent, находясь в офисе, сам раз в несколько секунд спрашивает: GET /agent/next.
     Входящих подключений в офисную сеть не требуется — агент всегда сам стучится наружу.
  3. Агент выполняет задачу через 1С и присылает результат: POST /agent/result/{id}.
  4. Вы забираете результат: GET /tasks/{id}.

Два разных токена, чтобы телефон не мог притвориться агентом и наоборот:
  CLIENT_TOKEN — для создания задач и чтения результатов (телефон, веб-панель, бот).
  AGENT_TOKEN  — только для Local Agent на офисном компьютере.

Хранилище — один файл SQLite (tasks.db) рядом с этим скриптом; для начала этого достаточно.
Все задачи и их результаты остаются в базе — это и есть журнал действий.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DB_PATH = ROOT / "tasks.db"
CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN")

KNOWN_TASK_TYPES = {"GET_ORDERS", "CHECK_STOCK", "CHECK_RECEIPTS", "CREATE_SUPPLIER_ORDER"}

app = FastAPI(title="Amana 1C Cloud API")
security = HTTPBearer()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                params TEXT NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )"""
        )


@app.on_event("startup")
def on_startup() -> None:
    if not CLIENT_TOKEN or not AGENT_TOKEN:
        raise RuntimeError(
            "Не заданы CLIENT_TOKEN и/или AGENT_TOKEN. Скопируйте cloud_api/.env.example в cloud_api/.env "
            "и впишите два разных случайных значения."
        )
    init_db()


def _check_token(creds: HTTPAuthorizationCredentials, expected: str, who: str) -> None:
    if creds.credentials != expected:
        raise HTTPException(401, f"Неверный токен для {who}")


def require_client(creds: HTTPAuthorizationCredentials = Depends(security)) -> None:
    _check_token(creds, CLIENT_TOKEN, "клиента (телефон/веб)")


def require_agent(creds: HTTPAuthorizationCredentials = Depends(security)) -> None:
    _check_token(creds, AGENT_TOKEN, "Local Agent")


class NewTask(BaseModel):
    type: Literal["GET_ORDERS", "CHECK_STOCK", "CHECK_RECEIPTS", "CREATE_SUPPLIER_ORDER"]
    params: dict[str, Any] = {}
    dry_run: bool = True


class TaskResult(BaseModel):
    status: Literal["done", "error"]
    result: dict[str, Any] | None = None
    error: str | None = None


@app.get("/health")
def health() -> dict:
    """Без токена: просто проверить, что сервис живой."""
    return {"status": "ok", "time": _now()}


@app.post("/tasks", dependencies=[Depends(require_client)])
def create_task(task: NewTask) -> dict:
    task_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "INSERT INTO tasks (id, type, params, dry_run, status, created_at) VALUES (?,?,?,?,?,?)",
            (task_id, task.type, json.dumps(task.params, ensure_ascii=False), int(task.dry_run), "pending", _now()),
        )
    return {"id": task_id, "status": "pending"}


@app.get("/tasks/{task_id}", dependencies=[Depends(require_client)])
def get_task(task_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Задача не найдена")
    return {
        "id": row["id"],
        "type": row["type"],
        "status": row["status"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


@app.get("/tasks", dependencies=[Depends(require_client)])
def list_tasks(limit: int = 20) -> dict:
    with db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"tasks": [dict(r) for r in rows]}


@app.get("/agent/next", dependencies=[Depends(require_agent)])
def agent_next_task() -> dict:
    """Local Agent вызывает это раз в несколько секунд. Возвращает самую старую задачу в очереди."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return {"task": None}
        conn.execute("UPDATE tasks SET status = 'in_progress', started_at = ? WHERE id = ?", (_now(), row["id"]))
    return {"task": {"id": row["id"], "type": row["type"], "params": json.loads(row["params"]), "dry_run": bool(row["dry_run"])}}


@app.post("/agent/result/{task_id}", dependencies=[Depends(require_agent)])
def agent_submit_result(task_id: str, payload: TaskResult) -> dict:
    with db() as conn:
        row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Задача не найдена")
        conn.execute(
            "UPDATE tasks SET status = ?, result = ?, error = ?, finished_at = ? WHERE id = ?",
            (
                payload.status,
                json.dumps(payload.result, ensure_ascii=False) if payload.result is not None else None,
                payload.error,
                _now(),
                task_id,
            ),
        )
    return {"ok": True}
