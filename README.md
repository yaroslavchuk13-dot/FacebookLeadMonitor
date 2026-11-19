# Facebook Lead Monitor

Стежить за вибраними Facebook-групами, знаходить дописи потенційних клієнтів
і надсилає їх у Telegram з перевіркою автора на скам (🟢🟡🔴).

## Структура

```
FacebookLeadMonitor/
├── lead_monitor/              Python-програма (пакет)
│   ├── core/                  основа, яку використовують усі частини
│   │   ├── config.py          налаштування з .env
│   │   ├── log_setup.py       логи з ротацією та приховуванням токенів
│   │   └── models.py          моделі даних: допис, рівень скаму
│   └── server/                локальний сервер для Chrome-розширення
│       ├── __main__.py        запуск: python -m lead_monitor.server
│       └── extension_api.py   приймання дописів (127.0.0.1, токен)
├── extension/                 Chrome-розширення (Manifest V3)
│   ├── manifest.json
│   ├── popup/                 вікно налаштувань (токен, порт, групи)
│   └── lib/                   спільні JS-функції
├── tests/
│   ├── python/                тести pytest
│   └── js/                    тести node --test
├── .env.example               шаблон налаштувань (копіюється в .env)
├── pyproject.toml             налаштування pytest
└── requirements.txt           залежності Python
```

Кожен наступний етап отримує власну папку в `lead_monitor/`
(`storage/`, `monitoring/`, `filters/`, `notifications/`, `ai/`, `scam/`, `dashboard/`)
і створюється лише тоді, коли до нього доходимо.

Не потрапляють у Git: `.env` (секрети), `data/` (база), `logs/` (логи), `.venv/`.

## Встановлення

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # і заповнити значення
```

## Команди

| Що | Команда |
|---|---|
| Показати налаштування (без секретів) | `python -m lead_monitor.core.config` |
| Запустити сервер для розширення | `python -m lead_monitor.server` |
| Python-тести | `python -m pytest` |
| JS-тести | `node --test tests/js/` |

## Chrome-розширення

1. `chrome://extensions` → увімкнути **Режим розробника**.
2. **Завантажити розпаковане** → вибрати папку `extension`.
3. Відкрити popup розширення → вставити `EXTENSION_TOKEN` з `.env` → **Перевірити з'єднання**.
