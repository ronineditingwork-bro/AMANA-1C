"""Local Agent — служба на офисном компьютере.

Сам, исходящим соединением, раз в несколько секунд спрашивает у Cloud API: «есть задача?»
Входящие подключения в офисную сеть не нужны и не используются — с роутером ничего делать не надо.

Полученную задачу выполняет через 1С (используя тот же код, что и обычный чат с Claude,
из onec_mcp/) и отправляет результат обратно в Cloud API.

Запуск:  python local_agent/agent.py
Остановить: Ctrl+C.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # чтобы `import onec_mcp` работал при запуске из любой папки
load_dotenv(ROOT / "local_agent" / ".env")
load_dotenv(ROOT / ".env")  # тут лежат настройки самой 1С (ONEC_ODATA_URL и т.д.)

from onec_mcp import analytics  # noqa: E402  (после load_dotenv, чтобы .env уже был прочитан)
from onec_mcp.odata import ODataClient, ODataError  # noqa: E402

CLOUD_API_URL = os.environ.get("CLOUD_API_URL", "http://127.0.0.1:8000")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN")
POLL_SECONDS = float(os.environ.get("AGENT_POLL_SECONDS", "5"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [agent] %(message)s")
log = logging.getLogger("agent")


def run_task(task_type: str, params: dict, dry_run: bool) -> dict:
    """Выполняет одну задачу через 1С. Пишущие команды пока не реализованы — только читают."""
    client = ODataClient.from_env()
    directory = analytics.Directory(client)

    if task_type == "GET_ORDERS":
        limit = int(params.get("limit", 10))
        orders = analytics.recent_customer_orders(client, directory, limit)
        return {"заказов": len(orders), "value": orders}

    if task_type == "CHECK_STOCK":
        warehouse = params.get("warehouse")
        warehouses = directory.find_warehouses(warehouse) if warehouse else None
        stock = analytics.stock_by_item(client, warehouses)
        rows = [
            {**directory.item_info(k), "в наличии": round(v["in_stock"], 3), "в резерве": round(v["reserved"], 3)}
            for k, v in stock.items()
        ]
        return {"позиций": len(rows), "value": rows[: int(params.get("limit", 50))]}

    if task_type in ("CHECK_RECEIPTS", "CREATE_SUPPLIER_ORDER"):
        return {"пропущено": f"Команда {task_type} появится на следующем этапе, сейчас не реализована."}

    raise ValueError(f"Неизвестный тип задачи: {task_type}")


def main() -> None:
    if not AGENT_TOKEN:
        raise SystemExit("Не задан AGENT_TOKEN. Скопируйте local_agent/.env.example в local_agent/.env и заполните.")
    headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
    log.info("Local Agent запущен. Cloud API: %s. Опрос раз в %.0f сек.", CLOUD_API_URL, POLL_SECONDS)

    with httpx.Client(base_url=CLOUD_API_URL, headers=headers, timeout=30) as http:
        while True:
            try:
                resp = http.get("/agent/next")
                resp.raise_for_status()
                task = resp.json().get("task")
                if task is None:
                    time.sleep(POLL_SECONDS)
                    continue

                log.info("Задача %s: %s %s", task["id"][:8], task["type"], task.get("params") or "")
                try:
                    result = run_task(task["type"], task.get("params") or {}, task.get("dry_run", True))
                    http.post(f"/agent/result/{task['id']}", json={"status": "done", "result": result})
                    log.info("Задача %s выполнена.", task["id"][:8])
                except (ODataError, ValueError) as e:
                    http.post(f"/agent/result/{task['id']}", json={"status": "error", "error": str(e)})
                    log.warning("Задача %s: ошибка — %s", task["id"][:8], e)
            except httpx.HTTPError as e:
                log.warning("Нет связи с Cloud API (%s), повтор через %.0f сек.", e, POLL_SECONDS)
                time.sleep(POLL_SECONDS)
                continue
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
