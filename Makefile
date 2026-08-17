.PHONY: help init generate-config generate-cookie up down restart destroy wipe logs status health shell plugins enable-plugin backup-definitions validate-json test-connection check-env start stop

# -----------------------------
# Help
# -----------------------------
help:
	@echo "RabbitMQ management commands:"
	@echo ""
	@echo "Basic:"
	@echo "  make init             - Prepare .env from template (one-time)"
	@echo "  make up               - Start RabbitMQ (uses existing configs)"
	@echo "  make down             - Stop RabbitMQ containers (data preserved)"
	@echo "  make restart          - Restart RabbitMQ"
	@echo "  make destroy          - Stop containers and remove Docker volumes"
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
	@echo "  make check-env        - Check if .env is properly configured"
	@echo "  make generate-cookie  - Generate unique Erlang cookie for .env"
	@echo "  make validate-json    - Validate definitions.json syntax"
	@echo "  make test-connection  - Test AMQP connection to RabbitMQ"
	@echo "  make backup-definitions - Export current definitions to backup"
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
check-env: init
	@echo "Checking .env configuration..."
	@ERRORS=0; \
	while IFS='=' read -r key value; do \
		case "$$key" in \
			""|\#*) continue ;; \
			ADMIN|MONITORING|STREAM_GAME|VALIDATION_WORKER|MC_GATEWAY) \
				if [ "$$value" = "change_me" ] || [ -z "$$value" ]; then \
					echo "⚠ Warning: $$key has default or empty value"; \
					ERRORS=1; \
				fi ;; \
			RABBITMQ_ERLANG_COOKIE) \
				if [ -z "$$value" ]; then \
					echo "⚠ Warning: $$key is empty. Run 'make generate-cookie'"; \
					ERRORS=1; \
				fi ;; \
		esac; \
	done < .env; \
	if [ $$ERRORS -eq 1 ]; then \
		echo "⚠ Please update .env with secure values before production use."; \
	else \
		echo "✓ .env looks good."; \
	fi

# -----------------------------
# Config generation
# -----------------------------
generate-config: check-env
	@echo "Generating definitions.json from template"
	@set -a; . ./.env; set +a; \
	envsubst < rabbitmq/definitions.template.json > rabbitmq/definitions.json

generate-cookie:
	@COOKIE=$$(head -c 32 /dev/urandom | base64 | head -c 32); \
	if [ -f .env ]; then \
		sed -i "s/^RABBITMQ_ERLANG_COOKIE=.*/RABBITMQ_ERLANG_COOKIE=$$COOKIE/" .env; \
	else \
		echo "RABBITMQ_ERLANG_COOKIE=$$COOKIE" > .env; \
	fi; \
	echo "Generated Erlang cookie: $$COOKIE"

# -----------------------------
# Lifecycle
# -----------------------------
up: generate-config
	docker compose up -d
	@echo "RabbitMQ started"
	@echo "Management UI: http://localhost:15672"
	@echo "User: admin (password from .env)"

down:
	docker compose down

restart:
	docker compose restart rabbitmq

destroy:
	docker compose down -v

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
	docker exec rabbitmq rabbitmq-diagnostics -q ping || echo "RabbitMQ is not healthy"

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
	@docker exec rabbitmq rabbitmqctl export_definitions /tmp/definitions_backup.json 2>/dev/null || \
		(echo "Note: export_definitions requires rabbitmq_management plugin" && exit 1)
	@docker cp rabbitmq:/tmp/definitions_backup.json backups/definitions-$$(date +%Y%m%d-%H%M%S).json
	@echo "Backup saved to backups/"

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

test-connection:
	@echo "Testing AMQP connection to RabbitMQ..."
	@docker exec rabbitmq rabbitmq-diagnostics -q check_port_connectivity || \
		(echo "✗ Cannot connect to RabbitMQ on port 5672" && exit 1)
	@echo "✓ Successfully connected to RabbitMQ"
