# RabbitMQ Infrastructure (Docker Compose)

![License](https://img.shields.io/badge/license-MIT-green)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![RabbitMQ](https://img.shields.io/badge/rabbitmq-3.13-orange)

---

## 📌 Назначение репозитория

Этот репозиторий содержит **декларативную и воспроизводимую конфигурацию RabbitMQ**, предназначенную для локальной разработки и продакшн-окружений.

Цели:
- полностью автоматизированный старт брокера;
- отсутствие ручных post-start скриптов;
- хранение *безопасных* секретов вне репозитория (`.env`);
- воспроизводимость окружения через `docker-compose` + `Makefile`.

---

## 📖 Содержание

- [Архитектура](#-архитектура)
- [Структура репозитория](#-структура-репозитория)
- [Как это работает](#-как-это-работает)
- [Быстрый старт](#-быстрый-старт)
- [Makefile](#-makefile)
- [Безопасность](#-безопасность)
- [Очистка и сброс данных](#-очистка-и-сброс-данных)

---

## 🧱 Архитектура

- **RabbitMQ 3.13 + Management Plugin**
- Конфигурация загружается **декларативно при старте**:
  - пользователи
  - vhost'ы
  - permissions
  - очереди
- Пароли **не хранятся в репозитории**
- Все секреты подставляются через `envsubst`

❗ Никаких `rabbitmqctl` из других контейнеров
❗ Никакой runtime-магии после старта брокера

---

## 📂 Структура репозитория

```
.
├── docker-compose.yml
├── Makefile
├── .env.template
├── data/                # volume RabbitMQ (persistent)
├── logs/                # логи RabbitMQ
├── backups/             # экспорт definitions (последние 10, не в git)
├── scripts/
│   └── check_env.py     # сверка .env с .env.template (make check-env)
└── rabbitmq/
    ├── rabbitmq.conf
    ├── definitions.template.json
    └── definitions.json   # генерируется, НЕ коммитится
```

---

## ⚙️ Как это работает

1. Пароли описываются в `.env` (локально, не в git)
2. `definitions.template.json` содержит плейсхолдеры `$ADMIN`, `$STREAM_GAME`, и т.д.
3. `make generate-config`:
   - подгружает `.env`
   - выполняет `envsubst`
   - генерирует `definitions.json`
4. RabbitMQ при старте:
   - читает `rabbitmq.conf`
   - загружает `definitions.json`
   - создаёт пользователей, vhost'ы, очереди

📌 Всё происходит **один раз при старте**, без ожиданий и race-condition'ов.

---

## 🚀 Быстрый старт

```bash
make init            # создать .env из шаблона
nano .env            # заполнить реальные пароли
make up              # сгенерировать cookie и конфиг, проверить JSON и запустить RabbitMQ
```

> `RABBITMQ_ERLANG_COOKIE` можно не заполнять вручную: `make up` сгенерирует его
> автоматически, если он пуст. При прямом `docker compose up` без cookie compose
> упадёт с ошибкой — дефолтного значения больше нет.

После старта:
- Management UI: http://localhost:15672
- Логин: `admin`
- Пароль: из `.env`

---

## 🛠 Makefile

### Основные команды

| Команда | Описание |
|---------|----------|
| `make init` | Создать `.env` из шаблона (первый запуск) |
| `make up` | Запустить RabbitMQ |
| `make down` | Остановить контейнер (данные сохраняются) |
| `make restart` | Перезапустить контейнер (definitions **не** переимпортируются) |
| `make reload-definitions` | `down` + `up` с повторным импортом — после правок прав/топологии |
| `make clean` | Удалить контейнеры, volumes и образы |
| `make wipe` | **Опасно**: удалить локальные `data/` и `logs/` |

> 💡 **Алиасы:** `make start` = `make up`, `make stop` = `make down` (для совместимости).
> `make generate-cookie` перегенерирует cookie; `make up` делает это сам, если он пуст.

### Диагностика

| Команда | Описание |
|---------|----------|
| `make logs` | Вывод логов в реальном времени |
| `make status` | Статус контейнеров |
| `make health` | Проверка здоровья RabbitMQ |
| `make shell` | Войти в контейнер (bash) |
| `make plugins` | Список доступных плагинов |
| `make enable-plugin NAME=<plugin>` | Включить плагин |
| `make test-connection` | Проверка подключения к порту 5672 |

### Валидация и бэкапы

| Команда | Описание |
|---------|----------|
| `make check-env` | Сверка `.env` с `.env.template` (добавляет недостающие, убирает лишние; бэкап при изменении) |
| `make validate-json` | Валидация JSON-файлов (вызывается автоматически при `make up`) |
| `make backup-definitions` | Экспорт определений в `backups/`; хранятся последние 10 копий |
| `make generate-config` | Сгенерировать `definitions.json` из шаблона и проверить JSON |

---

## 🔐 Безопасность

- `.env` **не коммитится**
- Пароли не хранятся в `definitions.json` в репозитории
- `definitions.json` генерируется локально
- `RABBITMQ_ERLANG_COOKIE` генерируется локально; compose не запустится без него
- `backups/` не коммитится (экспорт definitions содержит метаданные брокера)
- Management API не используется для инициализации

Это исключает:
- временные уязвимые окна
- проблемы синхронизации
- ошибки с `rabbitmqctl` и Erlang cookie

---

## 🧨 Очистка и сброс данных

⚠️ **ВНИМАНИЕ**: команда ниже удаляет все данные RabbitMQ:

```bash
make wipe
```

* * *

### Как можно отблагодарить:
* Оформить удобную для вас подписку на [Boosty.to](https://boosty.to/lliammah/ref)  
* Разово поддержать через [DonationAlerts](https://www.donationalerts.com/r/lliammah)  