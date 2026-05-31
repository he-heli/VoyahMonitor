# VOYAH Monitor

Read-only клиент для [VOYAH Assist](https://app.voyahassist.ru/): интерактивная SMS-авторизация, сбор телеметрии, локальная история и Telegram-бот.

## Принципы безопасности

- После авторизации выполняются **только read-only** запросы.
- `PUT`, `PATCH`, `DELETE` заблокированы.
- `POST` разрешен только для endpoint-ов из явного allow-list.
- Пути с признаками изменения данных (`delete`, `unbind`, `control`, `update` и т.д.) блокируются автоматически.
- Сессия, cookies, SMS-коды и токены **не попадают в git**.

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium

cp .env.example .env
# заполните VOYAH_PHONE и позже TELEGRAM_BOT_TOKEN
```

### 1. Авторизация

После login сессия сохраняется в `data/session.json`. Access token живёт ~10 минут,
но клиент автоматически обновляет его через `refreshToken` (~90 дней).
SMS-login нужен только при первой настройке или когда refresh token истечёт.

```bash
voyah-monitor login
```

Скрипт откроет браузер. Дальше:

1. Введите номер телефона (или используйте `VOYAH_PHONE` из `.env`).
2. Пройдите SmartCaptcha вручную, если появится.
3. Получите SMS и введите код в терминал.
4. Дождитесь сохранения `data/session.json` и `data/network_capture.json`.

### 2. Проверка API

```bash
voyah-monitor inspect
```

Скопируйте предложенные `VOYAH_ALLOWED_GET_PATHS` / `VOYAH_ALLOWED_POST_PATHS` в `.env`.

### 3. Статус автомобиля (как на сайте)

```bash
voyah-monitor status
```

Команда read-only: забирает поля из таблицы и карточки автомобиля с сайта VOYAH.
Не использует блок «Управление», не меняет владельца и не добавляет автомобили.

### 4. Сбор телеметрии в локальную базу

```bash
voyah-monitor fetch
voyah-monitor status
```

### 5. Telegram-бот

```bash
# .env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=123456789

voyah-monitor bot
```

Команды бота: `/status`, `/collect`, `/mileage`, `/battery`, `/history`.

Фоновый сбор — раз в 4 часа (`TELEGRAM_POLL_INTERVAL=14400`). `/status` и `/collect` запрашивают данные сразу по запросу.

## Docker

```bash
cp .env.example .env
docker compose build

# интерактивный login
docker compose --profile login run --rm voyah-login

# разовый fetch
docker compose --profile fetch run --rm voyah-fetch

# постоянный бот
docker compose up -d voyah-monitor
```

Данные сессии и SQLite хранятся в `./data`.

## Структура

```text
src/voyah_monitor/
  auth_login.py      # Playwright SMS login
  network_inspector.py
  session.py
  client.py          # read-only HTTP client
  telemetry.py
  storage.py         # SQLite snapshots + daily mileage
  bot.py
  cli.py
```

## Переменные окружения

См. [.env.example](.env.example).

## GitHub

Перед публикацией убедитесь, что в репозитории нет:

- `.env`
- `data/session.json`
- `data/*.db`

```bash
git init
git add .
git status
git commit -m "Initial VOYAH monitor prototype"
gh repo create VoyahMonitor --public --source=. --remote=origin --push
```

## Ограничения

- SmartCaptcha проходится только вручную.
- Точные API endpoint-ы зависят от версии кабинета VOYAH и определяются после login через network capture.
- Если refresh token истёк, повторите `voyah-monitor login`.
