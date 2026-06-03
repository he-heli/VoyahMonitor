# Развёртывание на VPS (production)

Бот на сервере работает **без браузера**. SMS-логин — только на вашем ПК (`scripts/local-login.sh`).

## Схема (автоматизированная)

```text
[ПК]  local-login.sh + inspect  →  .env + session.json
[VPS] один install.sh          →  Docker + git clone
[ПК]  scp                      →  .env + session.json на VPS
[VPS] ./first_start.sh         →  docker build + бот
```

---

## Шаг 0. Локально (один раз)

```bash
./scripts/local-login.sh
source .venv/bin/activate && voyah-monitor inspect
# скопируйте VOYAH_ALLOWED_* в .env
```

В `.env` должны быть `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, пути API.

---

## Шаг 1. Один скрипт на VPS

Два варианта (файлы в `scripts/vps/`):

| Скрипт | Когда использовать |
|--------|-------------------|
| **`install.sh`** | Чистый сервер: ставит Docker через **sudo**, клон в `/opt/voyah-monitor` |
| **`install_nosudo.sh`** | Docker, git и `docker compose` уже есть, **sudo не нужен**; клон в `~/voyah-monitor` |

### A. С sudo (по умолчанию)

```bash
curl -fsSL https://raw.githubusercontent.com/he-heli/VoyahMonitor/main/scripts/vps/install.sh -o install.sh
chmod +x install.sh
sudo ./install.sh
```

### B. Без sudo

```bash
curl -fsSL https://raw.githubusercontent.com/he-heli/VoyahMonitor/main/scripts/vps/install_nosudo.sh -o install_nosudo.sh
chmod +x install_nosudo.sh
./install_nosudo.sh
```

`install_nosudo.sh` — один самодостаточный файл (без `lib.sh`).

Проверьте до запуска: `docker info` и `docker compose version` работают **от вашего пользователя**.

Другой каталог (если есть права на `/opt`):

```bash
VOYAH_INSTALL_DIR=/opt/voyah-monitor ./install_nosudo.sh
```

Переменные для `install.sh` (опционально):

```bash
sudo VOYAH_REPO_URL=https://github.com/he-heli/VoyahMonitor.git \
     VOYAH_INSTALL_DIR=/opt/voyah-monitor \
     ./install.sh
```

`install.sh`: apt-пакеты, Docker при необходимости, git clone, `data/`, шаблон `.env`.

После `install.sh` с добавлением в группу `docker` может понадобиться **повторный SSH**.

---

## Шаг 2. Секреты на VPS

С **вашего ПК**:

```bash
export VPS_USER=deploy
export VPS_HOST=203.0.113.10
export REMOTE_DIR=/opt/voyah-monitor   # или ~/voyah-monitor после install_nosudo.sh

scp .env "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/.env"
scp data/session.json "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/data/session.json"

ssh "${VPS_USER}@${VPS_HOST}" \
  "chmod 600 ${REMOTE_DIR}/.env ${REMOTE_DIR}/data/session.json"
```

Шаблон: `scripts/prod/upload-secrets.example.sh`.

---

## Шаг 3. Первый запуск бота

На VPS:

```bash
cd /opt/voyah-monitor
./first_start.sh
```

Проверка в Telegram: `/start`.

Повторный запуск после остановки: `./scripts/prod/up.sh` (то же, что `first_start.sh`).

---

## Управление на VPS

| Скрипт | Назначение |
|--------|------------|
| `./first_start.sh` | Первая сборка и запуск (нужны `.env` + `session.json`) |
| `./scripts/prod/up.sh` | То же |
| `./scripts/prod/down.sh` | Остановка |
| `./scripts/prod/restart.sh` | Перезапуск |
| `./scripts/prod/rebuild.sh` | Пересборка + запуск |
| `./scripts/prod/logs.sh` | Логи |
| `./scripts/prod/ps.sh` | Статус |
| `./scripts/prod/update.sh` | `git pull` |
| `./scripts/prod/backup-data.sh` | Бэкап `data/` |

Обновление кода:

```bash
cd /opt/voyah-monitor
./scripts/prod/update.sh
./scripts/prod/rebuild.sh
```

---

## Обновление сессии (~90 дней)

1. ПК: `./scripts/local-login.sh`
2. `scp data/session.json` на VPS
3. `./scripts/prod/restart.sh`

---

## Важно

- **Не запускайте** бота на ПК и VPS с **одним** `TELEGRAM_BOT_TOKEN`.
- Prod-образ **без Playwright** — login только локально.
- Входящие порты на VPS не нужны (достаточно SSH).

## Firewall (пример)

```bash
sudo ufw allow OpenSSH
sudo ufw enable
```
