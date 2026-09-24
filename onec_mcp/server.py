"""MCP-сервер: инструменты для чтения и анализа данных 1С:УТ 11 через OData."""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from onec_mcp import analytics
from onec_mcp.odata import ODataClient, ODataError

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "exports"
load_dotenv(ROOT / ".env")
logging.getLogger("httpx").setLevel(logging.WARNING)

KEY_ENTITY_SETS = [
    "Catalog_Номенклатура",
    "Catalog_Склады",
    "Catalog_Партнеры",
    "Catalog_Контрагенты",
    "Document_ЗаказКлиента",
    "Document_ЗаказПоставщику",
    "Document_ПриобретениеТоваровУслуг",
    "Document_РеализацияТоваровУслуг",
    "Document_ВозвратТоваровОтКлиента",
    "AccumulationRegister_ТоварыНаСкладах",
    "AccumulationRegister_СвободныеОстатки",
    "AccumulationRegister_ЗаказыКлиентов",
    "AccumulationRegister_ЗаказыПоставщикам",
]

mcp = _Server(
    "1c",
    instructions=(
        "Доступ к 1С:Управление торговлей 11 (база Amana) через OData, только чтение. "
        "Готовые отчёты: sales_report, customer_orders_summary, reorder_suggestion. "
        "Для произвольных вопросов: list_entity_sets → describe_entity → odata_query."
    ),
)


def _client() -> ODataClient:
    return ODataClient.from_env()


def _date(value: str | None, default: date) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else default


def _save_csv(rows: list[dict], name: str) -> str | None:
    if not rows:
        return None
    EXPORT_DIR.mkdir(exist_ok=True)
    path = EXPORT_DIR / f"{name}_{datetime.now():%Y%m%d_%H%M}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig и «;» — чтобы Excel открыл без мастера
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def _error(e: Exception) -> dict[str, str]:
    return {"ошибка": str(e)}


@mcp.tool()
def check_connection() -> dict[str, Any]:
    """Проверить подключение к 1С и какие ключевые объекты опубликованы в OData."""
    try:
        sets = set(_client().entity_sets())
    except ODataError as e:
        return _error(e)
    return {
        "подключение": "ok",
        "всего объектов в OData": len(sets),
        "опубликованы": [s for s in KEY_ENTITY_SETS if s in sets],
        "не опубликованы": [s for s in KEY_ENTITY_SETS if s not in sets],
    }


@mcp.tool()
def list_entity_sets(contains: str | None = None) -> list[str] | dict:
    """Список наборов OData (Catalog_…, Document_…, AccumulationRegister_… и т.д.), с фильтром по подстроке."""
    try:
        sets = _client().entity_sets()
    except ODataError as e:
        return _error(e)
    if contains:
        sets = [s for s in sets if contains.lower() in s.lower()]
    return sorted(sets)


@mcp.tool()
def describe_entity(entity: str) -> dict[str, Any]:
    """Поля набора OData по первой записи (имена полей и пример значений). Для регистров укажите, например,
    'AccumulationRegister_ТоварыНаСкладах/Balance()'."""
    try:
        client = _client()
        if "/" in entity:
            rows = client.get(entity, {"$top": 1}).get("value", [])
        else:
            rows = client.query(entity, top=1)
    except ODataError as e:
        return _error(e)
    if not rows:
        return {"entity": entity, "записей": 0}
    return {"entity": entity, "пример": rows[0]}


@mcp.tool()
def odata_query(
    entity: str,
    filter: str | None = None,
    select: str | None = None,
    orderby: str | None = None,
    expand: str | None = None,
    top: int = 50,
    skip: int | None = None,
) -> dict[str, Any]:
    """Произвольный запрос на чтение к OData 1С.
    Примеры filter: "Posted eq true and Date ge datetime'2026-01-01T00:00:00'", "Description eq 'Смеситель'",
    "substringof('Grohe', Description)". Ссылки — поля с суффиксом _Key (GUID, сравнивать как guid'...').
    top ограничен 1000."""
    try:
        rows = _client().query(
            entity, filter=filter, select=select, orderby=orderby, expand=expand, top=min(top, 1000), skip=skip
        )
    except ODataError as e:
        return _error(e)
    return {"записей": len(rows), "value": rows}


@mcp.tool()
def register_balance(
    register: str,
    group_by: str = "Номенклатура_Key,Склад_Key",
    as_of: str | None = None,
    top: int = 200,
) -> dict[str, Any]:
    """Остатки регистра накопления (например ТоварыНаСкладах, СвободныеОстатки, ЗаказыПоставщикам),
    сгруппированные по полям group_by. as_of — дата ГГГГ-ММ-ДД (по умолчанию текущие остатки)."""
    try:
        client = _client()
        rows, fields = analytics.register_balance(
            client, register, [g.strip() for g in group_by.split(",") if g.strip()], _date(as_of, None) if as_of else None
        )
        directory = analytics.Directory(client)
        for row in rows:
            if "Номенклатура_Key" in row:
                row.update(directory.item_info(row["Номенклатура_Key"]))
            if "Склад_Key" in row:
                row["Склад"] = directory.warehouse_name(row["Склад_Key"])
            if "Партнер_Key" in row:
                row["Партнер"] = directory.partner_name(row["Партнер_Key"])
    except (ODataError, ValueError) as e:
        return _error(e)
    return {"числовые поля": fields, "строк": len(rows), "value": rows[:top]}


@mcp.tool()
def sales_report(
    date_from: str,
    date_to: str | None = None,
    warehouse: str | None = None,
    top: int = 50,
    save_csv: bool = False,
) -> dict[str, Any]:
    """Продажи по номенклатуре за период (реализации минус возвраты), сортировка по сумме.
    Даты ГГГГ-ММ-ДД; warehouse — часть названия склада."""
    try:
        client = _client()
        directory = analytics.Directory(client)
        start, end = _date(date_from, date.today()), _date(date_to, date.today())
        warehouses = directory.find_warehouses(warehouse) if warehouse else None
        sales = analytics.sales_by_item(client, start, end, warehouses)
    except (ODataError, ValueError) as e:
        return _error(e)
    rows = sorted(
        ({**directory.item_info(k), "Количество": round(v["qty"], 3), "Сумма": round(v["sum"], 2)} for k, v in sales.items()),
        key=lambda r: r["Сумма"],
        reverse=True,
    )
    result = {
        "период": f"{start} — {end}",
        "позиций": len(rows),
        "итого сумма": round(sum(r["Сумма"] for r in rows), 2),
        "value": rows[:top],
    }
    if save_csv:
        result["файл"] = _save_csv(rows, "продажи")
    return result


@mcp.tool()
def customer_orders_summary(date_from: str, date_to: str | None = None, top: int = 20) -> dict[str, Any]:
    """Анализ заказов клиентов за период: количество, сумма, статусы, топ клиентов и товаров. Даты ГГГГ-ММ-ДД."""
    try:
        client = _client()
        return analytics.customer_orders_summary(
            client, analytics.Directory(client), _date(date_from, date.today()), _date(date_to, date.today()), top
        )
    except (ODataError, ValueError) as e:
        return _error(e)


@mcp.tool()
def reorder_suggestion(
    sales_days: int = 90,
    lead_days: int = 14,
    cover_days: int = 30,
    warehouse: str | None = None,
    supplier: str | None = None,
    max_lines: int = 200,
    save_csv: bool = True,
) -> dict[str, Any]:
    """Черновик заявок поставщикам. Для каждого товара: средние продажи в день за sales_days,
    нужно = продажи_в_день × (lead_days + cover_days) − (в наличии − резерв) − в пути.
    Поставщик — из последнего поступления товара. Ничего в 1С не создаёт, только считает и сохраняет CSV."""
    try:
        client = _client()
        result = analytics.reorder_suggestion(
            client, analytics.Directory(client), date.today(), sales_days, lead_days, cover_days, warehouse, supplier
        )
    except (ODataError, ValueError) as e:
        return _error(e)
    lines = result["строки"]
    if save_csv:
        result["файл"] = _save_csv(lines, "заявка_поставщикам")
    result["строк всего"] = len(lines)
    result["строки"] = lines[:max_lines]
    return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
