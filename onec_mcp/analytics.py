"""Расчёты поверх OData УТ 11: остатки, продажи, заказы, предложение заявок поставщикам."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

from onec_mcp.odata import EMPTY_REF, ODataClient, ODataError, dt_literal

# Поля остатка в регистре ЗаказыПоставщикам, которые означают «ещё не поступило».
# Берётся первое найденное; какое именно использовано, возвращается в ответе.
INCOMING_FIELD_CANDIDATES = ("КПоступлениюBalance", "КОформлениюBalance", "ЗаказаноBalance")
NON_STOCK_TYPES = {"Услуга", "Работа"}


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _period_filter(date_from: date, date_to: date) -> str:
    return f"Date ge {dt_literal(date_from)} and Date lt {dt_literal(date_to + timedelta(days=1))}"


class Directory:
    """Кэш наименований справочников, чтобы отдавать названия вместо GUID."""

    def __init__(self, client: ODataClient):
        self.client = client
        self._cache: dict[str, dict[str, dict]] = {}

    def _load(self, entity: str, select: str) -> dict[str, dict]:
        if entity not in self._cache:
            try:
                rows = self.client.query_all(entity, select=select)
            except ODataError:
                rows = self.client.query_all(entity)
            self._cache[entity] = {r["Ref_Key"]: r for r in rows}
        return self._cache[entity]

    def items(self) -> dict[str, dict]:
        return self._load("Catalog_Номенклатура", "Ref_Key,Code,Description,Артикул,IsFolder,ТипНоменклатуры")

    def warehouses(self) -> dict[str, dict]:
        return self._load("Catalog_Склады", "Ref_Key,Description")

    def partners(self) -> dict[str, dict]:
        return self._load("Catalog_Партнеры", "Ref_Key,Description")

    def item_info(self, key: str) -> dict:
        row = self.items().get(key, {})
        return {
            "Код": row.get("Code"),
            "Артикул": row.get("Артикул"),
            "Номенклатура": row.get("Description") or key,
        }

    def partner_name(self, key: str | None) -> str:
        if not key or key == EMPTY_REF:
            return "(не указан)"
        return self.partners().get(key, {}).get("Description") or key

    def warehouse_name(self, key: str | None) -> str:
        if not key or key == EMPTY_REF:
            return "(не указан)"
        return self.warehouses().get(key, {}).get("Description") or key

    def find_warehouses(self, name_part: str) -> set[str]:
        part = name_part.lower()
        return {k for k, r in self.warehouses().items() if part in (r.get("Description") or "").lower()}

    def is_stock_item(self, key: str) -> bool:
        row = self.items().get(key)
        if row is None:
            return True
        return not row.get("IsFolder") and row.get("ТипНоменклатуры") not in NON_STOCK_TYPES


def documents(
    client: ODataClient,
    entity: str,
    date_from: date,
    date_to: date,
    header_fields: Iterable[str],
    posted_only: bool = True,
) -> list[dict]:
    """Документы за период вместе с табличной частью «Товары»."""
    flt = _period_filter(date_from, date_to) + " and DeletionMark eq false"
    if posted_only:
        flt += " and Posted eq true"
    select = ",".join(["Ref_Key", "Number", "Date", *header_fields, "Товары"])
    try:
        return client.query_all(entity, filter=flt, select=select, orderby="Date")
    except ODataError:
        # Не все версии конфигурации поддерживают $select табличной части — берём документ целиком.
        return client.query_all(entity, filter=flt, orderby="Date")


def _row_warehouse(doc: dict, row: dict) -> str | None:
    key = row.get("Склад_Key")
    if key and key != EMPTY_REF:
        return key
    return doc.get("Склад_Key")


def sales_by_item(
    client: ODataClient,
    date_from: date,
    date_to: date,
    warehouses: set[str] | None = None,
    subtract_returns: bool = True,
) -> dict[str, dict[str, float]]:
    """Продажи по номенклатуре: реализации минус возвраты от клиентов."""
    result: dict[str, dict[str, float]] = defaultdict(lambda: {"qty": 0.0, "sum": 0.0})
    sources = [("Document_РеализацияТоваровУслуг", 1)]
    if subtract_returns:
        sources.append(("Document_ВозвратТоваровОтКлиента", -1))
    for entity, sign in sources:
        try:
            docs = documents(client, entity, date_from, date_to, ["Склад_Key"])
        except ODataError:
            if sign < 0:
                continue  # возвраты не опубликованы — считаем без них
            raise
        for doc in docs:
            for row in doc.get("Товары") or []:
                if warehouses is not None and _row_warehouse(doc, row) not in warehouses:
                    continue
                key = row.get("Номенклатура_Key")
                result[key]["qty"] += sign * _num(row.get("Количество"))
                result[key]["sum"] += sign * _num(row.get("Сумма"))
    return result


def register_balance(
    client: ODataClient,
    register: str,
    group_by: Iterable[str],
    as_of: date | None = None,
) -> tuple[list[dict], list[str]]:
    """Остатки регистра накопления, сгруппированные по полям; суммируются все числовые поля."""
    entity = register if register.startswith("AccumulationRegister_") else f"AccumulationRegister_{register}"
    args = {"Period": dt_literal(as_of + timedelta(days=1))} if as_of else None
    rows = client.virtual_table(entity, "Balance", args)
    group_by = list(group_by)
    totals: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    numeric_fields: set[str] = set()
    for row in rows:
        group = tuple(row.get(f) for f in group_by)
        for field, value in row.items():
            if field not in group_by and isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[group][field] += value
                numeric_fields.add(field)
    result = [dict(zip(group_by, g)) | dict(v) for g, v in totals.items()]
    return result, sorted(numeric_fields)


def stock_by_item(client: ODataClient, warehouses: set[str] | None = None) -> dict[str, dict[str, float]]:
    rows = client.virtual_table("AccumulationRegister_ТоварыНаСкладах", "Balance")
    result: dict[str, dict[str, float]] = defaultdict(lambda: {"in_stock": 0.0, "reserved": 0.0})
    for row in rows:
        if warehouses is not None and row.get("Склад_Key") not in warehouses:
            continue
        key = row.get("Номенклатура_Key")
        result[key]["in_stock"] += _num(row.get("ВНаличииBalance"))
        result[key]["reserved"] += _num(row.get("ВРезервеСоСкладаBalance")) + _num(row.get("ВРезервеПодЗаказBalance"))
    return result


def incoming_by_item(client: ODataClient) -> tuple[dict[str, float], str | None, list[str]]:
    """Заказано у поставщиков, но ещё не поступило. Возвращает (кол-во по товарам, использованное поле, все поля)."""
    rows = client.virtual_table("AccumulationRegister_ЗаказыПоставщикам", "Balance")
    fields = sorted({f for r in rows for f, v in r.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
    field = next((f for f in INCOMING_FIELD_CANDIDATES if f in fields), None)
    result: dict[str, float] = defaultdict(float)
    if field:
        for row in rows:
            result[row.get("Номенклатура_Key")] += _num(row.get(field))
    return result, field, fields


def last_purchases(client: ODataClient, date_from: date, date_to: date) -> dict[str, dict]:
    """Последнее поступление по каждому товару: поставщик, дата, цена."""
    docs = documents(client, "Document_ПриобретениеТоваровУслуг", date_from, date_to, ["Партнер_Key"])
    result: dict[str, dict] = {}
    for doc in docs:  # отсортированы по дате, поздние перезаписывают ранние
        for row in doc.get("Товары") or []:
            # Цена в документе — за упаковку, а Количество и Сумма — в базовой единице,
            # поэтому настоящую цену за единицу берём как Сумма / Количество.
            qty = _num(row.get("Количество"))
            price = _num(row.get("Сумма")) / qty if qty else _num(row.get("Цена"))
            result[row.get("Номенклатура_Key")] = {
                "partner": doc.get("Партнер_Key"),
                "date": (doc.get("Date") or "")[:10],
                "price": round(price, 2),
            }
    return result


def reorder_suggestion(
    client: ODataClient,
    directory: Directory,
    today: date,
    sales_days: int,
    lead_days: int,
    cover_days: int,
    warehouse: str | None = None,
    supplier: str | None = None,
    purchase_history_days: int = 365,
) -> dict:
    """Сколько заказать: средние продажи × (срок поставки + запас дней) − (свободный остаток + в пути)."""
    warehouses = directory.find_warehouses(warehouse) if warehouse else None
    if warehouses is not None and not warehouses:
        raise ODataError(f"Склад, содержащий «{warehouse}», не найден.")

    date_from = today - timedelta(days=sales_days)
    sales = sales_by_item(client, date_from, today - timedelta(days=1), warehouses)
    stock = stock_by_item(client, warehouses)
    notes = []
    try:
        incoming, incoming_field, incoming_fields = incoming_by_item(client)
        if incoming_field is None:
            notes.append(f"В регистре ЗаказыПоставщикам не найдено поле остатка к поступлению; поля: {incoming_fields}. «В пути» не учтено.")
        else:
            notes.append(f"«В пути» взято из ЗаказыПоставщикам.{incoming_field} по всем складам.")
    except ODataError as e:
        incoming, incoming_field = {}, None
        notes.append(f"Регистр ЗаказыПоставщикам недоступен ({e}). «В пути» не учтено.")
    purchases = last_purchases(client, today - timedelta(days=purchase_history_days), today)

    lines = []
    for key, s in sales.items():
        if s["qty"] <= 0 or not directory.is_stock_item(key):
            continue
        avg_daily = s["qty"] / sales_days
        st = stock.get(key, {"in_stock": 0.0, "reserved": 0.0})
        free = st["in_stock"] - st["reserved"]
        in_transit = incoming.get(key, 0.0)
        target = avg_daily * (lead_days + cover_days)
        need = target - free - in_transit
        if need <= 0:
            continue
        last = purchases.get(key, {})
        supplier_name = directory.partner_name(last.get("partner"))
        if supplier and supplier.lower() not in supplier_name.lower():
            continue
        qty = math.ceil(need)
        lines.append({
            "Поставщик": supplier_name,
            **directory.item_info(key),
            "Продано за период": round(s["qty"], 3),
            "Продаж в день": round(avg_daily, 3),
            "В наличии": round(st["in_stock"], 3),
            "В резерве": round(st["reserved"], 3),
            "В пути": round(in_transit, 3),
            "Дней хватит": round(max(free + in_transit, 0) / avg_daily, 1),
            "Заказать": qty,
            "Последняя цена закупки": last.get("price"),
            "Сумма (по посл. цене)": round(qty * last["price"], 2) if last.get("price") else None,
            "Последнее поступление": last.get("date"),
        })

    lines.sort(key=lambda r: (r["Поставщик"], r["Дней хватит"]))
    by_supplier: dict[str, dict] = defaultdict(lambda: {"позиций": 0, "сумма": 0.0})
    for line in lines:
        agg = by_supplier[line["Поставщик"]]
        agg["позиций"] += 1
        agg["сумма"] += line["Сумма (по посл. цене)"] or 0.0
    return {
        "параметры": {
            "период продаж": f"{date_from} — {today - timedelta(days=1)} ({sales_days} дн.)",
            "срок поставки, дн.": lead_days,
            "запас, дн.": cover_days,
            "склад": [directory.warehouse_name(k) for k in warehouses] if warehouses else "все склады",
        },
        "примечания": notes,
        "итого по поставщикам": {k: {"позиций": v["позиций"], "сумма": round(v["сумма"], 2)} for k, v in by_supplier.items()},
        "строки": lines,
    }


def customer_orders_summary(client: ODataClient, directory: Directory, date_from: date, date_to: date, top: int = 20) -> dict:
    docs = documents(
        client, "Document_ЗаказКлиента", date_from, date_to,
        ["Партнер_Key", "Статус", "СуммаДокумента", "Posted"], posted_only=False,
    )
    by_status: dict[str, dict] = defaultdict(lambda: {"заказов": 0, "сумма": 0.0})
    by_partner: dict[str, dict] = defaultdict(lambda: {"заказов": 0, "сумма": 0.0})
    by_item: dict[str, dict] = defaultdict(lambda: {"количество": 0.0, "сумма": 0.0, "заказов": 0})
    total = 0.0
    for doc in docs:
        amount = _num(doc.get("СуммаДокумента"))
        total += amount
        status = doc.get("Статус") or ("Проведён" if doc.get("Posted") else "Не проведён")
        by_status[status]["заказов"] += 1
        by_status[status]["сумма"] += amount
        partner = directory.partner_name(doc.get("Партнер_Key"))
        by_partner[partner]["заказов"] += 1
        by_partner[partner]["сумма"] += amount
        for row in doc.get("Товары") or []:
            item = by_item[row.get("Номенклатура_Key")]
            item["количество"] += _num(row.get("Количество"))
            item["сумма"] += _num(row.get("Сумма"))
            item["заказов"] += 1

    def _top(d: dict, key: str) -> list:
        return sorted(d.items(), key=lambda kv: kv[1][key], reverse=True)[:top]

    return {
        "период": f"{date_from} — {date_to}",
        "заказов": len(docs),
        "сумма": round(total, 2),
        "по статусам": {k: {"заказов": v["заказов"], "сумма": round(v["сумма"], 2)} for k, v in by_status.items()},
        "топ клиентов": [{"Клиент": k, "заказов": v["заказов"], "сумма": round(v["сумма"], 2)} for k, v in _top(by_partner, "сумма")],
        "топ товаров": [
            {**directory.item_info(k), "количество": round(v["количество"], 3), "сумма": round(v["сумма"], 2), "заказов": v["заказов"]}
            for k, v in _top(by_item, "сумма")
        ],
    }


def supplier_letters(lines: list[dict], sender: str | None = None) -> dict[str, str]:
    """Черновики писем поставщикам по строкам заявки (analytics.reorder_suggestion(...)['строки']).
    Только текст — ничего не отправляет. Ключ — имя поставщика, значение — текст письма."""
    by_supplier: dict[str, list[dict]] = defaultdict(list)
    for line in lines:
        by_supplier[line["Поставщик"]].append(line)

    letters: dict[str, str] = {}
    for supplier, items in by_supplier.items():
        rows = "\n".join(
            f"{i:>2}. {r['Номенклатура']}"
            + (f" (арт. {r['Артикул']})" if r.get("Артикул") else "")
            + f" — {r['Заказать']} шт."
            for i, r in enumerate(items, 1)
        )
        total = sum(r["Сумма (по посл. цене)"] or 0 for r in items)
        total_str = f"{total:,.2f}".replace(",", " ").replace(".", ",")
        total_line = f"\n\nОриентировочная сумма (по последней цене закупки): {total_str} ₽." if total else ""
        letters[supplier] = (
            f"Тема: Заявка на поставку\n\n"
            f"Здравствуйте!\n\n"
            f"Просим сообщить наличие и подготовить счёт на следующие позиции:\n\n"
            f"{rows}"
            f"{total_line}\n\n"
            f"Просим уточнить сроки поставки.\n\n"
            f"С уважением,\n{sender or '[укажите имя и контакты]'}"
        )
    return letters
