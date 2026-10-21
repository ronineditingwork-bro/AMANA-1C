"""Разовая переотправка конкретного заказа клиента в Telegram — на случай, если уведомление
о нём уже ушло с ошибкой (например, с GUID вместо названия товара из-за старого кэша), и нужно
прислать его ещё раз с исправленными данными. Не трогает notify_state.json — telegram_notify.py
продолжит работать как ни в чём не бывало.

Один магазин (local_agent/.env):
  python local_agent/resend_order.py 00УТ-000482
Несколько магазинов:
  python local_agent/resend_order.py 00УТ-000482 aerodromnaya
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if len(sys.argv) < 2:
    raise SystemExit("Укажите номер заказа, например: python local_agent/resend_order.py 00УТ-000482")
ORDER_NUMBER = sys.argv[1]
STORE = sys.argv[2] if len(sys.argv) > 2 else None

if STORE:
    STORE_DIR = ROOT / "local_agent" / "stores" / STORE
    if not (STORE_DIR / ".env").exists():
        raise SystemExit(f"Не найден {STORE_DIR / '.env'}.")
    load_dotenv(STORE_DIR / ".env", override=True)
load_dotenv(ROOT / "local_agent" / ".env")
load_dotenv(ROOT / ".env")

from onec_mcp import analytics  # noqa: E402
from onec_mcp.odata import ODataClient, ODataError  # noqa: E402

# Не импортируем telegram_notify.py как модуль — у него есть собственная логика разбора
# sys.argv на верхнем уровне (номер магазина), которая перепутается с нашими аргументами.
# format_order/send_telegram здесь — копия того же форматирования сообщения.

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
STORE_NAME = os.environ.get("STORE_NAME")
MAX_ITEMS_SHOWN = 30


def send_telegram(http: httpx.Client, text: str) -> None:
    resp = http.post(f"{API_BASE}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text})
    if resp.status_code != 200:
        raise SystemExit(f"Telegram отклонил сообщение ({resp.status_code}): {resp.text[:300]}")


def format_order(order: dict) -> str:
    sum_str = f"{order['Сумма']:,.2f}".replace(",", " ").replace(".", ",")
    store_line = f"Магазин: {STORE_NAME}\n" if STORE_NAME else ""
    text = (
        f"{store_line}"
        f"Новый заказ клиента №{order['Номер']}\n"
        f"Дата: {order['Дата'][:16].replace('T', ' ')}\n"
        f"Клиент: {order['Клиент']}\n"
        f"Менеджер: {order['Менеджер']}\n"
        f"Сумма: {sum_str} ₽\n"
        f"Статус: {order['Статус']}"
    )
    items = order.get("Позиции") or []
    if items:

        def fmt_qty(q: float) -> str:
            return str(int(q)) if q == int(q) else f"{q:g}"

        lines = "\n".join(
            f"{i}. {it['Номенклатура']} — {fmt_qty(it['Количество'])} шт."
            for i, it in enumerate(items[:MAX_ITEMS_SHOWN], 1)
        )
        if len(items) > MAX_ITEMS_SHOWN:
            lines += f"\n... и ещё {len(items) - MAX_ITEMS_SHOWN} позиций"
        text += f"\n\nТовары:\n{lines}"
    return text

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("Не заданы TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID в .env.")

client = ODataClient.from_env()
directory = analytics.Directory(client)
try:
    order = analytics.order_by_number(client, directory, ORDER_NUMBER, with_items=True)
except ODataError as e:
    raise SystemExit(f"Нет связи с 1С: {e}")

if order is None:
    raise SystemExit(f"Заказ №{ORDER_NUMBER} не найден.")

with httpx.Client(timeout=30) as http:
    send_telegram(http, format_order(order))

print(f"Отправлено: заказ №{order['Номер']}.")
