.DEFAULT_GOAL := help
COMPOSE := docker compose

help:  ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-9s\033[0m %s\n",$$1,$$2}'

up:  ## start every docker stack (console, pattern, worker, mlflow)
	$(COMPOSE) up -d --build
	@echo "\n  console  http://localhost:7100\n  pattern  http://localhost:7110/designs\n  worker   http://localhost:7120/health\n  mlflow   http://localhost:5060\n"

full:  ## same as up, plus MinIO
	$(COMPOSE) --profile full up -d --build

gateway:  ## start the host-native model gateway (MLX, :8090). Downloads ~20 GB on first run
	./host/model-gateway/run.sh

ps:  ## show running stacks
	$(COMPOSE) --profile full ps

logs:  ## tail logs
	$(COMPOSE) --profile full logs -f

down:  ## stop (keeps data)
	$(COMPOSE) --profile full down

.PHONY: help up full gateway ps logs down
