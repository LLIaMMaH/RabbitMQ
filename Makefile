.PHONY: help init check-env ensure-cookie generate-config generate-cookie up down restart reload-definitions clean wipe logs status health shell plugins enable-plugin backup-definitions validate-json test test-connection start stop

BACKUP_KEEP := 10

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
	@echo "  make enable-plugin    - Enable a specific plugin (NAME=<plugin>)"
	@echo ""
	@echo "Validation & Backup:"
	@echo "  make check-env        - Sync .env with .env.template (cookie auto-generated)"
	@echo "  make generate-cookie  - Rotate Erlang cookie (auto on first up if empty)"
	@echo "  make validate-json    - Validate definitions.json syntax"
	@echo "  make test-connection  - Test AMQP connection to RabbitMQ"
	@echo "  make backup-definitions - Export definitions to backups/ (keep last 10)"
	@echo "  make test             - Run unit tests (check_env + permissions invariant)"
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
	docker exec rabbitmq rabbitmq-plugins enable $(NAME)
	@echo "Plugin '$(NAME)' enabled. Restart may be required."

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
	@echo "Testing AMQP connection to RabbitMQ..."
	@docker exec rabbitmq gosu rabbitmq rabbitmq-diagnostics -q check_port_connectivity || \
		(echo "✗ Cannot connect to RabbitMQ on port 5672" && exit 1)
	@echo "✓ Successfully connected to RabbitMQ"
