"""Клиент стандартного интерфейса OData 1С. Только чтение: выполняет исключительно GET-запросы."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import httpx

EMPTY_REF = "00000000-0000-0000-0000-000000000000"


class ODataError(RuntimeError):
    pass


def dt_literal(value: date | datetime | str) -> str:
    """Дата в формате литерала OData 1С: datetime'2026-01-31T00:00:00'."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    return f"datetime'{value:%Y-%m-%dT%H:%M:%S}'"


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
        return data.get("odata.error", {}).get("message", {}).get("value") or response.text[:500]
    except ValueError:
        return response.text[:500]


class ODataClient:
    def __init__(self, base_url: str, user: str, password: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/") + "/"
        self._http = httpx.Client(
            auth=(user, password),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    @classmethod
    def from_env(cls) -> "ODataClient":
        names = ("ONEC_ODATA_URL", "ONEC_USER", "ONEC_PASSWORD")
        missing = [n for n in names if not os.environ.get(n)]
        if missing:
            raise ODataError(f"Не заданы переменные: {', '.join(missing)}. Заполните файл .env (образец: .env.example).")
        return cls(
            os.environ["ONEC_ODATA_URL"],
            os.environ["ONEC_USER"],
            os.environ["ONEC_PASSWORD"],
            float(os.environ.get("ONEC_TIMEOUT", "120")),
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = {"$format": "json"}
        query.update({k: v for k, v in (params or {}).items() if v is not None})
        try:
            response = self._http.get(self.base_url + path, params=query)
        except httpx.HTTPError as e:
            raise ODataError(f"Нет связи с 1С ({self.base_url}): {e}") from e
        if response.status_code == 401:
            raise ODataError("1С отклонила логин или пароль (401). Проверьте ONEC_USER и ONEC_PASSWORD в .env.")
        if response.status_code >= 400:
            raise ODataError(f"1С вернула ошибку {response.status_code} на запрос {path}: {_error_text(response)}")
        return response.json()

    def entity_sets(self) -> list[str]:
        return [item["name"] for item in self.get("").get("value", [])]

    def query(
        self,
        entity: str,
        *,
        filter: str | None = None,
        select: str | None = None,
        orderby: str | None = None,
        expand: str | None = None,
        top: int | None = None,
        skip: int | None = None,
    ) -> list[dict]:
        params = {
            "$filter": filter,
            "$select": select,
            "$orderby": orderby,
            "$expand": expand,
            "$top": top,
            "$skip": skip,
        }
        return self.get(entity, params).get("value", [])

    def query_all(self, entity: str, *, page_size: int = 5000, orderby: str = "Ref_Key", **kwargs: Any) -> list[dict]:
        """Все записи набора постранично (для справочников и документов)."""
        rows: list[dict] = []
        skip = 0
        while True:
            page = self.query(entity, top=page_size, skip=skip, orderby=orderby, **kwargs)
            rows.extend(page)
            if len(page) < page_size:
                return rows
            skip += page_size

    def virtual_table(self, entity: str, function: str, args: dict[str, str | None] | None = None) -> list[dict]:
        """Виртуальная таблица регистра, например AccumulationRegister_ТоварыНаСкладах/Balance()."""
        arg_str = ",".join(f"{k}={v}" for k, v in (args or {}).items() if v is not None)
        return self.get(f"{entity}/{function}({arg_str})").get("value", [])
