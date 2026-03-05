# Завершение: Парсер задач Gogetlinks

## План развертывания

### Контрольный список перед развертыванием

#### Готовность кода
- [ ] Все функции MVP реализованы
- [ ] Модульные тесты проходят (покрытие >80%)
- [ ] Интеграционные тесты проходят
- [ ] Код проверен
- [ ] Документация завершена

#### Готовность инфраструктуры
- [ ] VPS предоставлен (Ubuntu 20.04+)
- [ ] Python 3.8+ установлен
- [ ] MySQL 8.0+ установлен и защищен
- [ ] Браузер Chrome установлен
- [ ] Git репозиторий доступен

#### Готовность конфигурации
- [ ] Создан шаблон config.ini
- [ ] .gitignore включает config.ini
- [ ] Создана учетная запись Anti-captcha.com с кредитами
- [ ] Созданы пользователь и база данных MySQL
- [ ] Проверены права доступа к файлам (config.ini chmod 600)

### Шаги развертывания

#### Шаг 1: Настройка VPS (15 минут)
```bash
# SSH подключение к VPS
ssh user@vps-ip

# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка зависимостей
sudo apt install -y python3 python3-pip python3-venv git

# Установка Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb || sudo apt install -f -y

# Проверка версии Chrome
google-chrome --version

# Установка MySQL
sudo apt install -y mysql-server
sudo mysql_secure_installation
```

#### Шаг 2: Настройка MySQL (5 минут)
```bash
# Создание базы данных и пользователя
sudo mysql -u root -p << 'SQL'
CREATE DATABASE ddl CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'gogetlinks_parser'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT SELECT, INSERT, UPDATE ON ddl.* TO 'gogetlinks_parser'@'localhost';
FLUSH PRIVILEGES;
SQL

# Создание схемы
mysql -u gogetlinks_parser -p ddl < schema.sql
```

#### Шаг 3: Развертывание кода (5 минут)
```bash
# Клонирование репозитория
cd ~
git clone https://github.com/abukreev-dev/gogetlinks-api.git
cd gogetlinks-api

# Установка (venv + зависимости + директория logs/)
make install
```

#### Шаг 4: Конфигурация (5 минут)
```bash
# Создание config.ini из шаблона (chmod 600 автоматически)
make setup-config

# Редактирование конфигурации (вставка учетных данных)
nano config.ini
```

**Пример config.ini:**
```ini
[gogetlinks]
username = your_email@example.com
password = your_password

[anticaptcha]
api_key = your_anticaptcha_key

[database]
host = localhost
port = 3306
database = ddl
user = gogetlinks_parser
password = STRONG_PASSWORD

[telegram]
# Уведомления о новых задачах и статусах сайтов (опционально)
enabled = true
bot_token = 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
chat_id = -100123456789
# Кого тегать в уведомлениях о новых задачах (через пробел)
mention = @user1 @user2

[output]
print_to_console = false

[logging]
log_level = INFO
log_file = logs/gogetlinks_parser.log
```

#### Шаг 5: Проверка и тестовый запуск (5 минут)
```bash
# Проверить готовность к деплою (Python, Chrome, MySQL, файлы)
make deploy-check

# Запуск парсера вручную
make run

# Проверка логов
make logs

# Проверка новых задач в базе данных
make db-tasks
```

**Примечание о сессиях:** После первого успешного запуска парсер сохраняет cookies в `session_cookies.pkl` (chmod 600). При следующих запусках он использует сохранённую сессию, пропуская авторизацию и решение капчи. Файл автоматически удаляется при истечении сессии.

#### Шаг 6: Настройка Cron (5 минут)
```bash
# Посмотреть рекомендуемую строку для crontab
make setup-cron

# Редактирование crontab
crontab -e

# Добавление расписания (MSK)
CRON_TZ=Europe/Moscow
0 * * * * cd /home/user/gogetlinks-api && /home/user/gogetlinks-api/venv/bin/python gogetlinks_parser.py --skip-sites >> /var/log/gogetlinks_cron.log 2>&1
15 7 * * * cd /home/user/gogetlinks-api && /home/user/gogetlinks-api/venv/bin/python gogetlinks_parser.py --skip-tasks >> /var/log/gogetlinks_cron.log 2>&1

# Проверка активности cron
crontab -l
```

### План отката

#### Условия для отката
- Код выхода != 0 для 3 последовательных запусков
- Обнаружено повреждение базы данных
- Баланс Anti-captcha исчерпан

#### Шаги отката
```bash
# 1. Отключение cron
crontab -r

# 2. Резервное копирование текущей базы данных
mysqldump -u gogetlinks_parser -p ddl > rollback_backup_$(date +%Y%m%d).sql

# 3. Откат кода к последней стабильной версии
cd ~/gogetlinks-api
git checkout tags/v1.2  # Или конкретный коммит

# 4. Восстановление базы данных из резервной копии (при необходимости)
mysql -u gogetlinks_parser -p ddl < backup.sql

# 5. Повторное включение cron с исправленным расписанием
crontab -e
```

## Мониторинг и оповещения

### Ключевые метрики

| Метрика | Целевое значение | Порог оповещения |
|---------|------------------|------------------|
| Процент успешного парсинга | >95% | <90% за 24 часа |
| Среднее время цикла | 2-3 мин | >10 мин |
| Процент успешного решения капчи | >90% | <80% за 24 часа |
| Новых задач в день | Базовое значение | Отклонение на 50% |
| Рост базы данных | ~100 МБ/месяц | >500 МБ/месяц |

### Команды мониторинга

```bash
# Быстрый просмотр через Makefile
make logs           # Последние 50 строк лога
make logs-errors    # Только ошибки
make db-tasks       # Новые задачи в БД

# Детальная диагностика
grep "Authentication failed" logs/gogetlinks_parser.log
grep "Total execution time" logs/gogetlinks_parser.log | awk '{sum+=$NF; count++} END {print sum/count}'

# Статистика cron
grep -c "Exit code: 0" /var/log/gogetlinks_cron.log
grep -c "Exit code: [^0]" /var/log/gogetlinks_cron.log
```

### Уведомления об оповещениях (будущее улучшение)

**Email оповещения:**
```python
def send_alert(subject, body):
    import smtplib
    # Отправка email при критической ошибке
    # Условия срабатывания:
    # - Код выхода 2 (капча) 3 раза подряд
    # - Код выхода 4 (база данных) в любом случае
    # - Нет успешного запуска в течение 12 часов
```

**Telegram уведомления (реализовано в v1.2.2):**
Парсер отправляет уведомления о новых задачах и о смене статусов сайтов.
Для новых задач поддерживаются теги `mention`, для статусов сайтов уведомления идут без тегов.
Настройка в секции `[telegram]` файла `config.ini` (опционально).

## CI/CD конвейер (будущее улучшение)

### GitHub Actions рабочий процесс

```.github/workflows/deploy.yml
name: Deploy to VPS

on:
  push:
    tags:
      - 'v*'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - run: pip install -r requirements.txt
      - run: pytest tests/

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Deploy to VPS
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.SSH_KEY }}
          script: |
            cd ~/gogetlinks-api
            git pull origin main
            source venv/bin/activate
            pip install -r requirements.txt
            python gogetlinks_parser.py --skip-sites
```

## Документация передачи

### Для команды эксплуатации

**Руководство по эксплуатации:**
1. **Ежедневная проверка:** `make logs-errors` — просмотр ошибок
2. **Еженедельно:** Проверка баланса капчи > $10
3. **Ежемесячно:** `make backup-db` — резервное копирование базы данных
4. **При оповещении:** `make logs` — проверка логов, перезапуск cron при необходимости

**Makefile — основные команды:**

Полный список: `make help`

| Команда | Описание |
|---------|----------|
| `make run` | Запустить парсер |
| `make run-debug` | Запустить с debug-выводом |
| `make logs` | Последние 50 строк лога |
| `make logs-errors` | Только ошибки из лога |
| `make db-tasks` | Новые задачи из БД |
| `make deploy-check` | Проверить готовность (Python, Chrome, MySQL, файлы) |
| `make backup-db` | Создать timestamped дамп БД |
| `make test` | Запустить тесты |
| `make test-cov` | Тесты + покрытие |
| `make clean` | Очистить кеши |

**Распространенные проблемы:**

| Проблема | Диагностика | Решение |
|----------|-------------|---------|
| "Authentication failed" | Проверить учетные данные в config.ini | Обновить конфигурацию, проверить вручную |
| "Captcha solving failed" | Проверить баланс anti-captcha | Пополнить счет, проверить API ключ |
| "Database error" | Проверить службу MySQL | Перезапустить MySQL: `sudo systemctl restart mysql` |
| Парсер не запускается | Проверить cron | Проверить crontab, проверить логи |

### Для команды разработки

**Структура кода:**
```
gogetlinks-api/
├── gogetlinks_parser.py    # Основной скрипт (~1200 LOC)
├── config.ini             # Учетные данные (в gitignore)
├── config.ini.example     # Шаблон конфигурации
├── schema.sql             # Схема базы данных
├── requirements.txt       # Зависимости Python
├── Makefile               # Автоматизация команд
├── session_cookies.pkl    # Сессионные cookies (в gitignore)
├── logs/                  # Директория логов
├── tests/                 # Модульные и интеграционные тесты
├── docs/                  # Документация
└── README.md              # Руководство по быстрому старту
```

**Рекомендации по внесению изменений:**
1. Создать ветку функции: `git checkout -b feature/new-parser`
2. Написать тесты для нового кода
3. Обновить документацию
4. Создать PR с описанием
5. Пометить релиз после слияния: `git tag v1.2.2`

### Для команды QA

**Настройка тестовой среды:**
```bash
# Использовать отдельную базу данных
CREATE DATABASE ddl_test;

# Использовать config_test.ini с тестовыми учетными данными
cp config.ini config_test.ini
# Отредактировать для использования тестовой базы данных и низкоприоритетной учетной записи anti-captcha
```

**Сценарии тестирования:**
1. Запустить парсер вручную, проверить вставленные задачи
2. Запустить дважды, проверить отсутствие дубликатов
3. Отключить интернет, проверить корректное завершение с ошибкой
4. Неверные учетные данные, проверить код выхода 1
5. Пустой список задач, проверить код выхода 0

---

**Версия развертывания:** 1.2.2
**Расчетное время развертывания:** 40 минут
**Время отката:** 10 минут
