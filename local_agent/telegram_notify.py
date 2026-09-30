"""Уведомления в Telegram о новых заказах клиентов в 1С.

Работает независимо от cloud_api/agent.py: сам, исходящим соединением, раз в несколько секунд
спрашивает у 1С «какие заказы есть за последние NOTIFY_LOOKBACK_HOURS часов?» и шлёт сообщение
по каждому, которого ещё не видел. Ни один порт на офисном роутере открывать не нужно —
и к 1С, и к Telegram обращается сама, исходящим соединением.

Запуск:  python local_agent/telegram_notify.py
Остановить: Ctrl+C (или снять службу — см. README.md).

При первом запуске ничего не присылает (чтобы не завалить чат старыми заказами), только
запоминает уже существующие заказы за последнее окно как увиденные.

Почему по списку «увиденных», а не просто «дата больше последней увиденной»: дата документа
в 1С — это не всегда момент, когда заказ реально появился в базе (например, розничная продажа
может синхронизироваться в 1С с задержкой и получить дату из прошлого). Если сравнивать только
даты, такой запоздавший заказ никогда не пройдёт проверку. Поэтому вместо одной даты храним
список ID заказов, увиденных за последние NOTIFY_LOOKBACK_HOURS часов, и сравниваем по ним.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
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
LOOKBACK_HOURS = float(os.environ.get("NOTIFY_LOOKBACK_HOURS", "48"))
STATE_PATH = ROOT / "local_agent" / "notify_state.json"
LOG_PATH = ROOT / "local_agent" / "telegram_notify.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [notify] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("notify")


def load_state() -> dict:
    state: dict = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("notify_state.json повреждён, начинаю заново.")
    # Файл от старой версии программы (только last_order_date, без seen) — переходим на новый
    # формат, не считая это первым запуском и не теряя last_order_date как подсказку.
    if "seen" not in state:
        state["seen"] = {}
    return state


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def send_telegram(http: httpx.Client, text: str) -> None:
    resp = http.post(f"{API_BASE}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text})
    if resp.status_code != 200:
        log.warning("Telegram отклонил сообщение (%s): %s", resp.status_code, resp.text[:300])


MAX_ITEMS_SHOWN = 30


def format_order(order: dict) -> str:
    sum_str = f"{order['Сумма']:,.2f}".replace(",", " ").replace(".", ",")
    text = (
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


def main() -> None:
    missing = [n for n in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(n)]
    if missing:
        raise SystemExit(
            f"Не заданы: {', '.join(missing)}. Заполните local_agent/.env "
            "(образец: local_agent/.env.example)."
        )

    state = load_state()
    first_run = not state.get("seen")

    with httpx.Client(timeout=30) as http:
        if first_run:
            log.info("Первый запуск: запоминаю уже существующие заказы за окно, не отправляя их.")
            send_telegram(http, "Бот запущен. Буду присылать уведомления о новых заказах клиентов.")

        log.info(
            "Слежу за новыми заказами (окно %.0f ч.), опрос раз в %.0f сек.", LOOKBACK_HOURS, POLL_SECONDS
        )
        client = ODataClient.from_env()
        directory = analytics.Directory(client)
        directory_built_at = datetime.now()

        while True:
            try:
                # Directory кэширует справочник номенклатуры у себя — без этого он перекачивался бы
                # целиком на каждой проверке. Пересоздаём раз в несколько часов, чтобы видеть новые
                # товары, а не при каждом опросе.
                if datetime.now() - directory_built_at > timedelta(hours=6):
                    client = ODataClient.from_env()
                    directory = analytics.Directory(client)
                    directory_built_at = datetime.now()

                # Время местное (как и остальные даты в 1С), не UTC — иначе сравнение дат "поплывёт".
                since = datetime.now() - timedelta(hours=LOOKBACK_HOURS)
                orders = analytics.orders_since(client, directory, since, limit=500, with_items=True)

                for order in orders:
                    ref = order["Ref_Key"]
                    if ref in state["seen"]:
                        continue
                    if not first_run:
                        send_telegram(http, format_order(order))
                        log.info("Отправлено уведомление: заказ №%s", order["Номер"])
                    state["seen"][ref] = order["Дата"]

                # Не даём списку увиденных расти бесконечно: оставляем только то, что ещё в окне.
                cutoff = since.isoformat()
                state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
                save_state(state)
                first_run = False
            except ODataError as e:
                log.warning("Нет связи с 1С: %s", e)
            except httpx.HTTPError as e:
                log.warning("Нет связи с Telegram: %s", e)
            except Exception:
                # Любая другая неожиданная ошибка не должна останавливать программу насовсем —
                # раньше такая ошибка тихо убивала процесс, и уведомления пропадали без следа.
                log.exception("Неожиданная ошибка в цикле проверки, пробую снова через %.0f сек.", POLL_SECONDS)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
