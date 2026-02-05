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

# Установка MySQL
sudo apt install -y mysql-server
sudo mysql_secure_installation
```

#### Шаг 2: Настройка MySQL (5 минут)
```bash
# Создание базы данных и пользователя
sudo mysql -u root -p << 'SQL'
CREATE DATABASE gogetlinks CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'gogetlinks_parser'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT SELECT, INSERT, UPDATE ON gogetlinks.* TO 'gogetlinks_parser'@'localhost';
FLUSH PRIVILEGES;
SQL

# Создание схемы
mysql -u gogetlinks_parser -p gogetlinks < schema.sql
```

#### Шаг 3: Развертывание кода (5 минут)
```bash
# Клонирование репозитория
cd ~
git clone https://github.com/YOUR_USERNAME/gogetlinks-parser.git
cd gogetlinks-parser

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
```

#### Шаг 4: Конфигурация (5 минут)
```bash
# Копирование шаблона конфигурации
cp config.ini.example config.ini

# Редактирование конфигурации (вставка учетных данных)
nano config.ini

# Установка прав доступа
chmod 600 config.ini
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
database = gogetlinks
user = gogetlinks_parser
password = STRONG_PASSWORD

[output]
print_tasks = false

[logging]
level = INFO
file = /home/user/gogetlinks-parser/gogetlinks_parser.log
```

#### Шаг 5: Тестовый запуск (5 минут)
```bash
# Активация виртуального окружения
source venv/bin/activate

# Запуск парсера вручную
python gogetlinks_parser.py

# Проверка логов
tail -f gogetlinks_parser.log

# Проверка базы данных
mysql -u gogetlinks_parser -p gogetlinks -e "SELECT COUNT(*) FROM tasks;"
```

#### Шаг 6: Настройка Cron (5 минут)
```bash
# Редактирование crontab
crontab -e

# Добавление ежечасной задачи
0 * * * * cd /home/user/gogetlinks-parser && /home/user/gogetlinks-parser/venv/bin/python gogetlinks_parser.py >> /var/log/gogetlinks_cron.log 2>&1

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
mysqldump -u gogetlinks_parser -p gogetlinks > rollback_backup_$(date +%Y%m%d).sql

# 3. Откат кода к последней стабильной версии
cd ~/gogetlinks-parser
git checkout tags/v1.0  # Или конкретный коммит

# 4. Восстановление базы данных из резервной копии (при необходимости)
mysql -u gogetlinks_parser -p gogetlinks < backup.sql

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

### Команды мониторинга логов

```bash
# Проверка количества ошибок (последние 24 часа)
grep -c "ERROR" gogetlinks_parser.log | tail -n 24

# Поиск неудачных попыток аутентификации
grep "Authentication failed" gogetlinks_parser.log

# Проверка среднего времени выполнения
grep "Total execution time" gogetlinks_parser.log | awk '{sum+=$NF; count++} END {print sum/count}'

# Подсчет успешных и неудачных запусков
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

**Telegram бот (будущее):**
```python
def send_telegram_alert(message):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message})
```

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
            cd ~/gogetlinks-parser
            git pull origin main
            source venv/bin/activate
            pip install -r requirements.txt
            python gogetlinks_parser.py --test
```

## Документация передачи

### Для команды эксплуатации

**Руководство по эксплуатации:**
1. **Ежедневная проверка:** Просмотр логов cron на наличие ошибок
2. **Еженедельно:** Проверка баланса капчи > $10
3. **Ежемесячно:** Резервное копирование базы данных
4. **При оповещении:** Проверка логов, перезапуск cron при необходимости

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
gogetlinks-parser/
├── gogetlinks_parser.py    # Основной скрипт
├── config.ini             # Учетные данные (в gitignore)
├── schema.sql             # Схема базы данных
├── requirements.txt       # Зависимости Python
├── tests/                 # Модульные и интеграционные тесты
├── docs/                  # Документация SPARC
└── README.md              # Руководство по быстрому старту
```

**Рекомендации по внесению изменений:**
1. Создать ветку функции: `git checkout -b feature/new-parser`
2. Написать тесты для нового кода
3. Обновить документацию
4. Создать PR с описанием
5. Пометить релиз после слияния: `git tag v1.1.0`

### Для команды QA

**Настройка тестовой среды:**
```bash
# Использовать отдельную базу данных
CREATE DATABASE gogetlinks_test;

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

**Версия развертывания:** 1.0
**Расчетное время развертывания:** 40 минут
**Время отката:** 10 минут
