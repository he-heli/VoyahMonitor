# Развёртывание на VPS (production)

Бот на сервере работает **без браузера**. SMS-логин и SmartCaptcha — только на вашем компьютере.

## Требования

| Где | Что нужно |
|-----|-----------|
| **Локальный ПК** | Python 3.11+, Chromium (через Playwright) |
| **VPS** | Docker + Docker Compose plugin, SSH, исходящий интернет |

Входящие порты на VPS для бота **не нужны** (Telegram long polling). Достаточно SSH.

## Обзор

```text
[ПК]  local-login.sh  →  data/session.json
[ПК]  inspect         →  VOYAH_ALLOWED_* в .env
[ПК]  scp             →  .env + session.json на VPS
[VPS] bootstrap.sh    →  git clone, data/
[VPS] up.sh           →  docker compose (slim image, без Playwright)
```

Access token обновляется автоматически (~10 мин). Refresh token — ~90 дней. После истечения refresh снова запустите **local-login** на ПК и загрузите новый `session.json`.

---

## 1. Локально: сессия и конфиг

### Linux / macOS

```bash
./scripts/local-login.sh
```

### Windows

```cmd
scripts\local-login.bat
```

В браузере: телефон, капча, SMS. Результат:

- `data/session.json` — **обязательно на VPS**
- `data/network_capture.json` — только для inspect на ПК

### Allow-list API

```bash
source .venv/bin/activate
voyah-monitor inspect
```

Скопируйте предложенные пути в `.env`:

```env
VOYAH_ALLOWED_GET_PATHS=...
VOYAH_ALLOWED_POST_PATHS=...
```

На VPS `network_capture.json` **не нужен**, если пути уже в `.env`.

### `.env` для прода

Скопируйте `.env.example` → `.env` и заполните минимум:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS`
- `VOYAH_ALLOWED_GET_PATHS` / `VOYAH_ALLOWED_POST_PATHS`

`VOYAH_PHONE` на VPS не используется (только при login на ПК).

---

## 2. VPS: установка Docker и кода

На сервере (Ubuntu/Debian пример):

```bash
# Docker — официальная инструкция: https://docs.docker.com/engine/install/

sudo mkdir -p /opt/voyah-monitor
sudo chown "$USER:$USER" /opt/voyah-monitor
cd /opt/voyah-monitor

# Клонирование (подставьте свой URL)
export VOYAH_REPO_URL=https://github.com/YOUR_USER/VoyahMonitor.git
git clone "$VOYAH_REPO_URL" .

chmod +x scripts/prod/*.sh scripts/local-login.sh
./scripts/prod/bootstrap.sh
```

Если репозиторий уже склонирован вручную, достаточно:

```bash
cd /opt/voyah-monitor
./scripts/prod/bootstrap.sh
```

---

## 3. Перенос секретов на VPS

С **локального ПК** (отредактируйте хост и путь):

```bash
export VPS_USER=deploy
export VPS_HOST=203.0.113.10
export REMOTE_DIR=/opt/voyah-monitor

scp .env "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/.env"
scp data/session.json "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/data/session.json"

# Опционально: история и настройки бота
# scp data/voyah_monitor.db data/bot_settings.json \
#   "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/data/"

ssh "${VPS_USER}@${VPS_HOST}" \
  "chmod 600 ${REMOTE_DIR}/.env ${REMOTE_DIR}/data/session.json"
```

Шаблон: `scripts/prod/upload-secrets.example.sh`.

**Никогда** не коммитьте `.env` и `data/session.json` в git.

---

## 4. Запуск бота на VPS

```bash
cd /opt/voyah-monitor
./scripts/prod/up.sh
```

| Скрипт | Назначение |
|--------|------------|
| `./scripts/prod/up.sh` | Сборка (slim) + запуск |
| `./scripts/prod/down.sh` | Остановка |
| `./scripts/prod/restart.sh` | Перезапуск |
| `./scripts/prod/rebuild.sh` | Пересборка образа + запуск |
| `./scripts/prod/logs.sh` | Логи |
| `./scripts/prod/ps.sh` | Статус контейнеров |
| `./scripts/prod/update.sh` | `git pull` |
| `./scripts/prod/backup-data.sh` | Архив `data/*` |

Проверка в Telegram: `/start`.

---

## Обновление кода

```bash
cd /opt/voyah-monitor
./scripts/prod/update.sh
./scripts/prod/rebuild.sh
```

---

## Обновление сессии (~90 дней)

1. На ПК: `./scripts/local-login.sh`
2. `scp data/session.json` на VPS
3. `./scripts/prod/restart.sh`

---

## Важно

- **Не запускайте** бота локально и на VPS с **одним** `TELEGRAM_BOT_TOKEN`.
- **Не используйте** `docker compose --profile login` на VPS — только local-login на ПК.
- Prod-образ (`Dockerfile`) **без Playwright** — быстрая сборка и меньший размер.
- Profile `login` в compose — только для разработки (`Dockerfile.login`).

## Firewall (пример)

```bash
sudo ufw allow OpenSSH
sudo ufw enable
```

Дополнительные порты для Voyah Monitor не открывайте.
