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
pip install -e ".[login]"
playwright install chromium

cp .env.example .env
# заполните VOYAH_PHONE и позже TELEGRAM_BOT_TOKEN
```

### 1. Авторизация

После login сессия сохраняется в `data/session.json`. Access token живёт ~10 минут,
но клиент автоматически обновляет его через `refreshToken` (~90 дней).
SMS-login нужен только при первой настройке или когда refresh token истечёт.

**Рекомендуется** (ПК с браузером):

```bash
./scripts/local-login.sh        # Linux / macOS
# scripts\local-login.bat       # Windows
```

Или вручную:

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

Команды бота: кнопки в меню или `/start`, `/status`, `/collect`.

Фоновый сбор — примерно раз в 4 часа с разбросом (`TELEGRAM_POLL_INTERVAL`, `TELEGRAM_POLL_JITTER`).

## Docker (локально)

```bash
cp .env.example .env
# Сначала scripts/local-login.sh — session.json в ./data

docker compose build
docker compose up -d voyah-monitor
```

Профиль `login` в compose — только для разработки (`Dockerfile.login` с Playwright).
На **VPS** login в Docker не используйте.

```bash
docker compose --profile fetch run --rm voyah-fetch
```

Данные сессии и SQLite хранятся в `./data`.

## Production (VPS)

Пошаговое развёртывание: **[docs/DEPLOY.md](docs/DEPLOY.md)**.

```bash
# на VPS: install.sh (sudo) или install_nosudo.sh (Docker уже есть)
sudo ./install.sh
# scp .env и data/session.json с ПК
cd /opt/voyah-monitor && ./first_start.sh
```

Prod-образ без Playwright (быстрая сборка).

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
scripts/             # local-login, vps/install.sh, prod/*
docs/DEPLOY.md       # VPS deployment
```

Конфиг Cursor (`.cursor/`, `AGENTS.md`) в репозиторий не попадает — только локально.

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
- Если refresh token истёк, повторите `./scripts/local-login.sh` и загрузите новый `session.json` на сервер.
