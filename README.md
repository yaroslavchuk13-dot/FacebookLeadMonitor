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
│   │   ├── models.py          моделі даних: допис, рівень скаму, алерт
│   │   └── state.py           спільний стан: пауза, зв'язок із розширенням
│   ├── filters/
│   │   ├── keywords.py        фільтр: групи слів ([trade] І [offer] І [location]) + [exclude]
│   │   └── pay.py             оплата з тексту: £/год, £/день, оцінка за день
│   ├── storage/
│   │   ├── database.py        SQLite: дописи, дублікати, ліди
│   │   └── __main__.py        статистика й останні ліди
│   ├── notifications/
│   │   ├── telegram.py        бот: ліди, алерти, /status /pause /resume
│   │   └── formatting.py      тексти повідомлень
│   ├── server/
│   │   └── extension_api.py   API для розширення (127.0.0.1, токен)
│   ├── pipeline.py            обробка: ключові слова → база → ліди
│   ├── app.py                 запуск усього разом: сервер + бот
│   └── __main__.py            python -m lead_monitor
├── extension/                 Chrome-розширення (Manifest V3)
│   ├── manifest.json
│   ├── background/            фоновий цикл: по черзі відкриває групи, надсилає дописи
│   ├── popup/                 вікно: Старт/Стоп, стан, налаштування, тест розбору
│   ├── content/               код, що працює на сторінці групи (дописи, checkpoint)
│   └── lib/                   спільні JS-функції (групи, паузи, сховище)
├── config/
│   └── keywords.txt           ключові слова: вакансії fire stopping у Лондоні (перечитується автоматично)
├── scripts/
│   ├── setup.ps1              встановлення на новому ПК
│   ├── start_server.ps1       запуск програми (сервер + Telegram-бот)
│   └── show_leads.ps1         статистика й останні ліди
├── tests/
│   ├── python/                тести pytest
│   └── js/                    тести node --test
├── .env.example               шаблон налаштувань (копіюється в .env)
├── pyproject.toml             налаштування pytest
└── requirements.txt           залежності Python
```

Кожен наступний етап отримує власну папку в `lead_monitor/`
(`scam/`, `ai/`, `dashboard/`) і створюється лише тоді, коли до нього доходимо.

Не потрапляють у Git: `.env` (секрети), `data/` (база), `logs/` (логи), `.venv/`.

## Встановлення (на новому ПК)

1. Встановити **Python 3.12+** з https://www.python.org/downloads/ (галочка «Add python.exe to PATH»)
   і **Git** з https://git-scm.com/.
2. Отримати код: `git clone <адреса репозиторію> C:\FacebookLeadMonitor`
   (або у Visual Studio: **Git → Clone Repository**).
3. Запустити скрипт — він створить `.venv`, встановить залежності, створить `.env` і прожене тести:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\FacebookLeadMonitor\scripts\setup.ps1
   ```
4. Заповнити `.env` (токени Git не переносить — скопіюйте старий `.env` або створіть нові).
5. Завантажити розширення в Chrome (розділ нижче) і вставити токен у popup.

**Що Git НЕ переносить:** `.env` (секрети), `data/` (база з історією лідів — скопіюйте папку вручну,
якщо потрібна історія), `logs/`, `.venv/` (створюється скриптом), розширення в Chrome (завантажується заново).

Відкрити у Visual Studio: **File → Open → Folder…** → `C:\FacebookLeadMonitor`.

## Команди

| Що | Команда |
|---|---|
| Запустити програму (сервер + бот) | `powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1` |
| Статистика й останні ліди | `powershell -ExecutionPolicy Bypass -File scripts\show_leads.ps1` |
| Показати налаштування (без секретів) | `.\.venv\Scripts\python.exe -m lead_monitor.core.config` |
| Python-тести | `python -m pytest` |
| JS-тести | `node --test tests/js/` |

## Chrome-розширення

1. `chrome://extensions` → увімкнути **Режим розробника**.
2. **Завантажити розпаковане** → вибрати папку `extension`.
3. Відкрити popup розширення → вставити `EXTENSION_TOKEN` з `.env` → **Перевірити з'єднання**.
