# Gogetlinks Task Parser - Makefile
# Автоматизация часто используемых команд

.PHONY: help install test run clean deploy setup-db lint format logs logs-errors deploy-check

# Путь к логам
LOG_FILE := logs/gogetlinks_parser.log

# Цвета для вывода
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m # No Color

help: ## Показать эту справку
	@echo "$(BLUE)Gogetlinks Task Parser - Доступные команды:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'

install: ## Установить зависимости
	@echo "$(BLUE)Создание виртуального окружения...$(NC)"
	python3 -m venv venv
	@echo "$(BLUE)Установка зависимостей...$(NC)"
	. venv/bin/activate && pip install --upgrade pip
	. venv/bin/activate && pip install -r requirements.txt
	@mkdir -p logs
	@echo "$(GREEN)✓ Зависимости установлены$(NC)"

install-dev: install ## Установить dev зависимости
	@echo "$(BLUE)Установка dev зависимостей...$(NC)"
	. venv/bin/activate && pip install pytest pytest-cov black flake8 mypy
	@echo "$(GREEN)✓ Dev зависимости установлены$(NC)"

setup-config: ## Создать config.ini из шаблона
	@if [ ! -f config.ini ]; then \
		cp config.ini.example config.ini; \
		chmod 600 config.ini; \
		echo "$(GREEN)✓ config.ini создан. Заполните credentials!$(NC)"; \
		echo "$(YELLOW)⚠ Отредактируйте config.ini перед запуском$(NC)"; \
	else \
		echo "$(YELLOW)config.ini уже существует$(NC)"; \
	fi

setup-db: ## Инициализировать базу данных
	@echo "$(BLUE)Применение схемы БД...$(NC)"
	@read -p "MySQL root password: " password; \
	mysql -u root -p$$password < schema.sql
	@echo "$(GREEN)✓ Схема БД применена$(NC)"

test: ## Запустить тесты
	@echo "$(BLUE)Запуск тестов...$(NC)"
	. venv/bin/activate && pytest tests/ -v

test-cov: ## Запустить тесты с покрытием
	@echo "$(BLUE)Запуск тестов с покрытием...$(NC)"
	. venv/bin/activate && pytest tests/ --cov=gogetlinks_parser --cov-report=html --cov-report=term

test-watch: ## Запустить тесты в watch режиме
	@echo "$(BLUE)Запуск тестов в watch режиме...$(NC)"
	. venv/bin/activate && pytest-watch tests/

lint: ## Проверить код линтером
	@echo "$(BLUE)Проверка кода...$(NC)"
	. venv/bin/activate && flake8 gogetlinks_parser.py tests/
	@echo "$(GREEN)✓ Линтер пройден$(NC)"

format: ## Форматировать код с black
	@echo "$(BLUE)Форматирование кода...$(NC)"
	. venv/bin/activate && black gogetlinks_parser.py tests/
	@echo "$(GREEN)✓ Код отформатирован$(NC)"

type-check: ## Проверить типы с mypy
	@echo "$(BLUE)Проверка типов...$(NC)"
	. venv/bin/activate && mypy gogetlinks_parser.py --ignore-missing-imports
	@echo "$(GREEN)✓ Типы проверены$(NC)"

run: ## Запустить парсер
	@echo "$(BLUE)Запуск парсера...$(NC)"
	. venv/bin/activate && python gogetlinks_parser.py

run-debug: ## Запустить парсер в debug режиме
	@echo "$(BLUE)Запуск парсера (DEBUG)...$(NC)"
	. venv/bin/activate && python -u gogetlinks_parser.py 2>&1 | tee debug.log

dry-run: ## Запустить в dry-run режиме (без записи в БД)
	@echo "$(BLUE)Запуск в dry-run режиме...$(NC)"
	@echo "$(YELLOW)TODO: Реализовать dry-run флаг$(NC)"

logs: ## Показать последние логи
	@if [ -f $(LOG_FILE) ]; then \
		tail -n 50 $(LOG_FILE); \
	else \
		echo "$(YELLOW)Лог файл не найден: $(LOG_FILE)$(NC)"; \
	fi

logs-errors: ## Показать только ошибки из логов
	@if [ -f $(LOG_FILE) ]; then \
		grep -i "error\|exception\|fail" $(LOG_FILE) | tail -n 20; \
	else \
		echo "$(YELLOW)Лог файл не найден: $(LOG_FILE)$(NC)"; \
	fi

db-tasks: ## Показать новые задачи из БД
	@echo "$(BLUE)Запрос новых задач...$(NC)"
	@read -p "MySQL user: " user; \
	read -s -p "MySQL password: " password; echo; \
	mysql -u $$user -p$$password -e "SELECT task_id, domain, price, customer, time_passed FROM ddl.ggl_tasks WHERE is_new=1 ORDER BY created_at DESC LIMIT 10;"

clean: ## Очистить временные файлы
	@echo "$(BLUE)Очистка...$(NC)"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf .pytest_cache .coverage htmlcov/ .mypy_cache/
	@echo "$(GREEN)✓ Очистка завершена$(NC)"

clean-all: clean ## Полная очистка (включая venv)
	@echo "$(BLUE)Полная очистка...$(NC)"
	rm -rf venv/
	@echo "$(GREEN)✓ Полная очистка завершена$(NC)"

deploy-check: ## Проверить готовность к деплою
	@echo "$(BLUE)Проверка готовности к деплою...$(NC)"
	@echo ""
	@echo "$(BLUE)--- Системные зависимости ---$(NC)"
	@which python3 > /dev/null 2>&1 && echo "$(GREEN)✓ Python3: $$(python3 --version 2>&1)$(NC)" || echo "$(YELLOW)✗ Python3 не найден$(NC)"
	@which google-chrome > /dev/null 2>&1 && echo "$(GREEN)✓ Chrome: $$(google-chrome --version 2>&1)$(NC)" || echo "$(YELLOW)✗ Google Chrome не найден$(NC)"
	@which mysql > /dev/null 2>&1 && echo "$(GREEN)✓ MySQL client установлен$(NC)" || echo "$(YELLOW)✗ MySQL client не найден$(NC)"
	@echo ""
	@echo "$(BLUE)--- Файлы проекта ---$(NC)"
	@if [ ! -f config.ini ]; then echo "$(YELLOW)✗ config.ini отсутствует$(NC)"; else echo "$(GREEN)✓ config.ini существует$(NC)"; fi
	@if [ ! -f venv/bin/python ]; then echo "$(YELLOW)✗ venv не создан$(NC)"; else echo "$(GREEN)✓ venv существует$(NC)"; fi
	@if [ ! -f requirements.txt ]; then echo "$(YELLOW)✗ requirements.txt отсутствует$(NC)"; else echo "$(GREEN)✓ requirements.txt существует$(NC)"; fi
	@if [ ! -d logs ]; then echo "$(YELLOW)✗ директория logs/ отсутствует (создайте: mkdir -p logs)$(NC)"; else echo "$(GREEN)✓ директория logs/ существует$(NC)"; fi
	@echo ""
	@echo "$(BLUE)--- Проверка MySQL подключения ---$(NC)"
	@read -p "MySQL user: " user; \
	read -s -p "MySQL password: " password; echo; \
	mysql -u $$user -p$$password -e "SHOW TABLES FROM ddl;" && echo "$(GREEN)✓ База данных доступна$(NC)" || echo "$(YELLOW)✗ Ошибка подключения к БД$(NC)"

setup-cron: ## Добавить задачу в crontab
	@echo "$(BLUE)Настройка cron...$(NC)"
	@echo "Добавьте следующие строки в crontab (crontab -e):"
	@echo "$(GREEN)CRON_TZ=Europe/Moscow$(NC)"
	@echo "$(GREEN)0 * * * * cd $(PWD) && venv/bin/python gogetlinks_parser.py --skip-sites >> /var/log/gogetlinks_cron.log 2>&1$(NC)"
	@echo "$(GREEN)15 7 * * * cd $(PWD) && venv/bin/python gogetlinks_parser.py --skip-tasks >> /var/log/gogetlinks_cron.log 2>&1$(NC)"

backup-db: ## Создать backup базы данных
	@echo "$(BLUE)Создание backup...$(NC)"
	@read -p "MySQL user: " user; \
	read -s -p "MySQL password: " password; echo; \
	mysqldump -u $$user -p$$password ddl ggl_tasks > backup_ddl_ggl_tasks_$$(date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)✓ Backup создан$(NC)"

all: install setup-config setup-db test ## Полная установка и проверка
	@echo "$(GREEN)✓ Все готово к работе!$(NC)"
