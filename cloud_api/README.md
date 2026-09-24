# Cloud API

Небольшой сервис-посредник между вами (телефон/веб) и Local Agent на офисном компьютере.
Как это работает целиком, включая Local Agent, — см. `README.md` в корне проекта, раздел
«Дистанционное управление».

## Запуск для проверки (на любом компьютере, без облака)

```powershell
cd cloud_api
copy .env.example .env
notepad .env
```
Впишите `CLIENT_TOKEN` и `AGENT_TOKEN` — два разных случайных набора символов. Затем:
```powershell
pip install -r requirements.txt
uvicorn main:app --port 8000
```
Проверка: `http://127.0.0.1:8000/health` должен ответить `{"status": "ok", ...}`.

## Эндпоинты

| Метод | Путь | Кто вызывает | Токен |
|---|---|---|---|
| GET | `/health` | кто угодно | не нужен |
| POST | `/tasks` | телефон/веб | CLIENT_TOKEN |
| GET | `/tasks` | телефон/веб | CLIENT_TOKEN |
| GET | `/tasks/{id}` | телефон/веб | CLIENT_TOKEN |
| GET | `/agent/next` | Local Agent | AGENT_TOKEN |
| POST | `/agent/result/{id}` | Local Agent | AGENT_TOKEN |

Хранилище — файл `tasks.db` (SQLite) рядом со скриптом; он же служит журналом всех задач
и их результатов. В git не попадает.
