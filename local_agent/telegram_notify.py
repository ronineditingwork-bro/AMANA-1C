"""Уведомления в Telegram о новых заказах клиентов в 1С.

Работает независимо от cloud_api/agent.py: сам, исходящим соединением, раз в несколько секунд
спрашивает у 1С «есть новые заказы с прошлого раза?» и, если есть, шлёт сообщение в Telegram —
тоже исходящим соединением (Telegram Bot API сам по себе в облаке). Ни один порт на офисном
роутере открывать не нужно.

Запуск:  python local_agent/telegram_notify.py
Остановить: Ctrl+C.

При первом запуске ничего не присылает (чтобы не завалить чат всей историей заказов), только
запоминает текущий момент как точку отсчёта. Уведомления придут по заказам, созданным после этого.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "local_agent" / ".env")
load_dotenv(ROOT / ".env")  # настройки самой 1С (ONEC_ODATA_URL и т.д.)

from onec_mcp import analytics  # noqa: E402
from onec_mcp.odata import ODataClient, ODataError  # noqa: E402

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
POLL_SECONDS = float(os.environ.get("NOTIFY_POLL_SECONDS", "60"))
STATE_PATH = ROOT / "local_agent" / "notify_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [notify] %(message)s")
log = logging.getLogger("notify")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def send_telegram(http: httpx.Client, text: str) -> None:
    resp = http.post(f"{API_BASE}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text})
    if resp.status_code != 200:
        log.warning("Telegram отклонил сообщение (%s): %s", resp.status_code, resp.text[:300])


def format_order(order: dict) -> str:
    sum_str = f"{order['Сумма']:,.2f}".replace(",", " ").replace(".", ",")
    return (
        f"Новый заказ клиента №{order['Номер']}\n"
        f"Дата: {order['Дата'][:16].replace('T', ' ')}\n"
        f"Клиент: {order['Клиент']}\n"
        f"Сумма: {sum_str} ₽\n"
        f"Статус: {order['Статус']}"
    )


def main() -> None:
    missing = [n for n in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(n)]
    if missing:
        raise SystemExit(
            f"Не заданы: {', '.join(missing)}. Заполните local_agent/.env "
            "(образец: local_agent/.env.example)."
        )

    state = load_state()
    with httpx.Client(timeout=30) as http:
        if "last_order_date" not in state:
            # Первый запуск: не шлём историю, просто запоминаем текущий момент.
            state["last_order_date"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            save_state(state)
            log.info("Первый запуск: беру за точку отсчёта текущий момент, старые заказы не шлю.")
            send_telegram(http, "Бот запущен. Буду присылать уведомления о новых заказах клиентов.")

        log.info("Слежу за новыми заказами, опрос раз в %.0f сек.", POLL_SECONDS)
        while True:
            try:
                client = ODataClient.from_env()
                directory = analytics.Directory(client)
                since = datetime.fromisoformat(state["last_order_date"])
                orders = analytics.orders_since(client, directory, since)
                for order in orders:
                    send_telegram(http, format_order(order))
                    log.info("Отправлено уведомление: заказ №%s", order["Номер"])
                    state["last_order_date"] = order["Дата"]
                    save_state(state)
            except ODataError as e:
                log.warning("Нет связи с 1С: %s", e)
            except httpx.HTTPError as e:
                log.warning("Нет связи с Telegram: %s", e)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
