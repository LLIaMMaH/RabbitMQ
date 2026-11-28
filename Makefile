.PHONY: help init check-env ensure-cookie generate-config generate-cookie up down restart reload-definitions clean wipe logs status health shell plugins enable-plugin backup-definitions validate-json test test-connection release-preview start stop

BACKUP_KEEP := 10

# Smoke-проверка идёт с хоста, на котором запущен make, а не из контейнера.
RABBITMQ_HOST ?= localhost
RABBITMQ_PORT ?= 5672
AMQP_TIMEOUT ?= 5

# Предпросмотр релиза: те же параметры, что у workflow_dispatch.
BUMP ?= auto
VERSION ?=

# -----------------------------
# Help
# -----------------------------
help:
	@echo "RabbitMQ management commands:"
	@echo ""
	@echo "Basic:"
	@echo "  make init             - Prepare .env from template (one-time)"
	@echo "  make up               - Generate config, validate JSON, start RabbitMQ"
	@echo "  make down             - Stop RabbitMQ containers (data preserved)"
	@echo "  make restart          - Restart container (definitions are NOT re-imported)"
	@echo "  make reload-definitions - down + up to re-import definitions after edits"
	@echo "  make clean            - Stop containers, remove volumes and images"
	@echo ""
	@echo "Diagnostics:"
	@echo "  make logs             - Follow RabbitMQ logs"
	@echo "  make status           - Show container status"
	@echo "  make health           - Check RabbitMQ health status"
	@echo "  make shell            - Open shell inside RabbitMQ container"
	@echo "  make plugins          - List all available plugins"
	@echo "  make enable-plugin    - Проверить описание плагина в rabbitmq/enabled_plugins (NAME=<plugin>)"
	@echo ""
	@echo "Validation & Backup:"
	@echo "  make check-env        - Sync .env with .env.template (cookie auto-generated)"
	@echo "  make generate-cookie  - Rotate Erlang cookie (auto on first up if empty)"
	@echo "  make validate-json    - Validate definitions.json syntax"
	@echo "  make test-connection  - AMQP smoke с хоста (RABBITMQ_HOST/PORT, AMQP_TIMEOUT)"
	@echo "  make backup-definitions - Export definitions to backups/ (keep last 10)"
	@echo "  make test             - Run unit tests (check_env + permissions invariant)"
	@echo "  make release-preview  - Показать версию и коммиты будущего релиза (BUMP/VERSION)"
	@echo ""
	@echo "Dangerous:"
	@echo "  make wipe             - REMOVE local data/logs directories"
	@echo ""

# -----------------------------
# Initial setup
# -----------------------------
init:
	@if [ ! -f .env ]; then \
		cp .env.template .env; \
		echo ".env created from template. Fill in real passwords."; \
	else \
		echo ".env already exists."; \
	fi

# -----------------------------
# Environment validation
# -----------------------------
check-env: ensure-cookie
	@python3 scripts/check_env.py

# Шаблон оставляет cookie пустым: без этой проверки compose подставит
# дефолтное значение, одинаковое на всех инсталляциях.
ensure-cookie: init
	@if ! grep -Eq '^RABBITMQ_ERLANG_COOKIE=.+' .env || \
		grep -Eiq '^RABBITMQ_ERLANG_COOKIE=(change_me|default_cookie_change_me)[[:space:]]*$$' .env; then \
		echo "Erlang cookie не задан — генерирую..."; \
		$(MAKE) --no-print-directory generate-cookie; \
	fi

# -----------------------------
# Config generation
# -----------------------------
# ensure-cookie готовит cookie; sync + subst выполняются в один проход скриптом
generate-config: ensure-cookie
	@echo "Generating definitions.json from template"
	@python3 scripts/check_env.py --subst rabbitmq/definitions.template.json rabbitmq/definitions.json
	@# definitions.json монтируется в контейнер: владелец читает как 600, а
	@# RabbitMQ внутри контейнера работает под uid/gid 999. Даём группе 999
	@# read-only доступ, не открывая файл для остальных пользователей хоста.
	@if getent group 999 >/dev/null 2>&1; then \
		if [ "$$(id -u)" -eq 0 ]; then \
			chgrp 999 rabbitmq/definitions.json; \
		elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then \
			sudo chgrp 999 rabbitmq/definitions.json; \
		else \
			echo "ВНИМАНИЕ: sudo без пароля недоступен — chgrp пропущен" >&2; \
		fi; \
	else \
		echo "Группа 999 не найдена: chgrp пропущен, файл останется в текущей группе" >&2; \
	fi
	@chmod 640 rabbitmq/definitions.json
	@$(MAKE) --no-print-directory validate-json

generate-cookie: init
	@COOKIE=$$(python3 -c 'import secrets; print(secrets.token_hex(32))'); \
	if grep -q '^RABBITMQ_ERLANG_COOKIE=' .env; then \
		sed -i "s|^RABBITMQ_ERLANG_COOKIE=.*|RABBITMQ_ERLANG_COOKIE=$$COOKIE|" .env; \
	else \
		printf 'RABBITMQ_ERLANG_COOKIE=%s\n' "$$COOKIE" >> .env; \
	fi; \
	echo "Erlang cookie сгенерирован (значение не выводится)."

# -----------------------------
# Lifecycle
# -----------------------------
up: generate-config
	@mkdir -p data logs
	@# RabbitMQ внутри контейнера работает под uid 999, поэтому каталоги
	@# должны принадлежать ему, а не быть world-writable.
	@if [ "$$(id -u)" -eq 0 ]; then \
		chown -R 999:999 data logs; \
	else \
		sudo chown -R 999:999 data logs; \
	fi
	docker compose up -d
	@echo "RabbitMQ started"
	@echo "Management UI: http://localhost:15672"
	@echo "User: admin (password from .env)"

down:
	docker compose down

restart:
	@echo "ВНИМАНИЕ: docker compose restart НЕ переимпортирует definitions.json."
	@echo "Если менялись пользователи/права/очереди — используйте make reload-definitions."
	docker compose restart rabbitmq

# Именно этот рестарт применяет правки definitions (короткий даунтайм).
reload-definitions: validate-json
	@echo "Перезапуск с повторным импортом definitions.json..."
	docker compose down
	$(MAKE) up

clean:
	docker compose down -v --rmi all

# Алиасы для совместимости
start: up
stop: down

# -----------------------------
# Dangerous operations
# -----------------------------
wipe:
	@echo "=== Будут удалены следующие папки ==="
	@ls -la data/ logs/ 2>/dev/null || true
	@echo ""
	@read -p "Введите 'DELETE' для подтверждения: " confirm; \
	if [ "$$confirm" = "DELETE" ]; then \
		sudo rm -rf data logs; \
		echo "Удалено."; \
	else \
		echo "Отмена."; \
	fi

# -----------------------------
# Diagnostics
# -----------------------------
logs:
	docker compose logs -f rabbitmq

status:
	docker compose ps

health:
	@echo "Checking RabbitMQ health..."
	@docker exec rabbitmq gosu rabbitmq sh -c 'rabbitmq-diagnostics -q check_running && rabbitmq-diagnostics -q check_port_connectivity' || { echo "RabbitMQ is not healthy" >&2; exit 1; }

shell:
	docker exec -it rabbitmq bash

plugins:
	docker exec rabbitmq rabbitmq-plugins list

enable-plugin:
ifndef NAME
	$(error NAME is required. Usage: make enable-plugin NAME=<plugin_name>)
endif
	@# Рантайм-enable теряется при пересоздании контейнера: плагины описаны
	@# в rabbitmq/enabled_plugins и монтируются в контейнер.
	@grep -q -- "$(NAME)" rabbitmq/enabled_plugins || { \
		echo "Плагин $(NAME) не описан в rabbitmq/enabled_plugins" >&2; \
		exit 1; \
	}
	@echo "Плагин $(NAME) описан декларативно; примените: make reload-definitions"

# -----------------------------
# Backup & Validation
# -----------------------------
backup-definitions:
	@echo "Exporting current definitions to backup..."
	@mkdir -p backups
	@docker exec rabbitmq gosu rabbitmq rabbitmqctl export_definitions /tmp/definitions_backup.json 2>/dev/null || \
		(echo "Note: export_definitions requires rabbitmq_management plugin" && exit 1)
	@docker cp rabbitmq:/tmp/definitions_backup.json backups/definitions-$$(date +%Y%m%d-%H%M%S).json
	@docker exec rabbitmq rm -f /tmp/definitions_backup.json
	@ls -1t backups/definitions-*.json 2>/dev/null | tail -n +$$(( $(BACKUP_KEEP) + 1 )) | xargs -r rm --
	@echo "Backup saved to backups/ (хранятся последние $(BACKUP_KEEP))"

validate-json:
	@echo "Validating definitions.template.json syntax..."
	@python3 -c "import json; json.load(open('rabbitmq/definitions.template.json'))" && \
		echo "✓ definitions.template.json is valid JSON" || \
		(echo "✗ Invalid JSON in definitions.template.json" && exit 1)
	@if [ -f rabbitmq/definitions.json ]; then \
		python3 -c "import json; json.load(open('rabbitmq/definitions.json'))" && \
		echo "✓ definitions.json is valid JSON" || \
		(echo "✗ Invalid JSON in definitions.json" && exit 1); \
	fi

test:
	@echo "Running unit tests..."
	@python3 -m unittest discover -s tests -v

test-connection:
	@echo "AMQP smoke: $(RABBITMQ_HOST):$(RABBITMQ_PORT) со стороны хоста..."
	@python3 scripts/smoke_amqp.py "$(RABBITMQ_HOST)" "$(RABBITMQ_PORT)" --timeout "$(AMQP_TIMEOUT)"

release-preview:
	@# Только чтение git: тег не создаётся и GitHub не дёргается.
	@python3 scripts/release_version.py --bump "$(BUMP)" $(if $(VERSION),--version "$(VERSION)",)
