"""Сводка в Telegram о деньгах, поступивших за день: банк + касса + эквайринг.

В отличие от telegram_notify.py, это не постоянно работающий процесс, а разовый запуск —
подводит итог за сегодня и завершается. Планировщик заданий Windows запускает его раз в день
в заданное время (см. scripts/install_daily_payments_service.ps1).

Один магазин (local_agent/.env):
  python local_agent/daily_payments.py
Несколько магазинов — так же, как в telegram_notify.py:
  python local_agent/daily_payments.py aerodromnaya
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STORE = sys.argv[1] if len(sys.argv) > 1 else None
if STORE:
    STORE_DIR = ROOT / "local_agent" / "stores" / STORE
    if not (STORE_DIR / ".env").exists():
        raise SystemExit(f"Не найден {STORE_DIR / '.env'}. Сначала настройте этот магазин (см. README.md).")
    load_dotenv(STORE_DIR / ".env", override=True)
    LOG_PATH = STORE_DIR / "daily_payments.log"
else:
    LOG_PATH = ROOT / "local_agent" / "daily_payments.log"
load_dotenv(ROOT / "local_agent" / ".env")
load_dotenv(ROOT / ".env")

from onec_mcp import analytics  # noqa: E402
from onec_mcp.odata import ODataClient, ODataError  # noqa: E402

STORE_NAME = os.environ.get("STORE_NAME")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
MAX_LINES_SHOWN = 25

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [daily] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("daily")


def fmt_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def format_summary(summary: dict) -> str:
    store_line = f"Магазин: {STORE_NAME}\n" if STORE_NAME else ""
    header = f"{store_line}Итоги дня {summary['день']} — поступления денег\n"

    if summary["итого"] <= 0:
        text = header + "Поступлений не зафиксировано."
    else:
        by_type = "\n".join(
            f"{label}: {v['документов']} шт., {fmt_money(v['сумма'])} ₽" for label, v in summary["по видам"].items()
        )
        text = header + f"Итого: {fmt_money(summary['итого'])} ₽\n\n{by_type}"

        lines = summary["строки"]
        if lines:
            detail = "\n".join(
                f"{i}. {r['Вид']} №{r['Номер']} — {fmt_money(r['Сумма'])} ₽ — {r['Плательщик']}"
                + (f" (заказ №{r['Заказ']})" if r["Заказ"] else "")
                for i, r in enumerate(lines[:MAX_LINES_SHOWN], 1)
            )
            if len(lines) > MAX_LINES_SHOWN:
                detail += f"\n... и ещё {len(lines) - MAX_LINES_SHOWN} платежей"
            text += f"\n\nСписок:\n{detail}"

    if summary["примечания"]:
        text += "\n\n" + "\n".join(summary["примечания"])
    return text


def send_telegram(http: httpx.Client, text: str) -> None:
    resp = http.post(f"{API_BASE}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text})
    if resp.status_code != 200:
        log.warning("Telegram отклонил сообщение (%s): %s", resp.status_code, resp.text[:300])
    else:
        log.info("Сводка за день отправлена.")


def main() -> None:
    missing = [n for n in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"Не заданы: {', '.join(missing)}. Заполните .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).")

    try:
        client = ODataClient.from_env()
        directory = analytics.Directory(client)
        summary = analytics.daily_payments(client, directory, date.today())
    except ODataError as e:
        log.error("Нет связи с 1С: %s", e)
        raise SystemExit(1)

    text = format_summary(summary)
    log.info(
        "Итого за %s: %.2f ₽ (%d платежей).", summary["день"], summary["итого"], len(summary["строки"])
    )
    with httpx.Client(timeout=30) as http:
        send_telegram(http, text)


if __name__ == "__main__":
    main()
