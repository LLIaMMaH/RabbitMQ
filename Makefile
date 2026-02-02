.PHONY: help init generate-config start stop restart destroy wipe logs status

# -----------------------------
# Help
# -----------------------------
help:
	@echo "RabbitMQ management commands:"
	@echo ""
	@echo "  make init             - Prepare .env from template (one-time)"
	@echo "  make generate-config  - Generate rabbitmq.conf and definitions.json"
	@echo "  make start            - Start RabbitMQ (uses existing configs)"
	@echo "  make stop             - Stop RabbitMQ containers (data preserved)"
	@echo "  make restart          - Restart RabbitMQ"
	@echo "  make destroy          - Stop containers and remove Docker volumes"
	@echo "  make wipe             - REMOVE local data/logs directories (DANGEROUS)"
	@echo "  make logs             - Follow RabbitMQ logs"
	@echo "  make status           - Show container status"
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
# Config generation
# -----------------------------
generate-config: init
	@echo "Generating definitions.json from template"
	@set -a; . ./.env; set +a; \
	envsubst < rabbitmq/definitions.template.json > rabbitmq/definitions.json

# -----------------------------
# Lifecycle
# -----------------------------
start: generate-config
	docker compose up -d
	@echo "RabbitMQ started"
	@echo "Management UI: http://localhost:15672"
	@echo "User: admin (password from .env)"

stop:
	docker compose down

restart:
	docker compose restart rabbitmq

destroy:
	docker compose down -v

# -----------------------------
# Dangerous operations
# -----------------------------
wipe:
	@echo "WARNING: This will permanently delete local RabbitMQ data and logs."
	@echo "Press Ctrl+C to abort."
	@sleep 5
	sudo rm -rf data logs

# -----------------------------
# Diagnostics
# -----------------------------
logs:
	docker compose logs -f rabbitmq

status:
	docker compose ps
