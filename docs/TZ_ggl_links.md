# ТЗ: Проверка доступности оплаченных GGL-ссылок

## Контекст

В DDL есть две крон-задачи для GoGetLinks:
- **`ggl/check`** — проверяет HTTP-доступность оплаченных ссылок, при ошибках шлёт алерт в Telegram
- **`ggl/warm`** — прогревает те же ссылки GET-запросом (кеш)

Обе получали список URL через PHP-клиент (`Gogetlinks.php`) — авторизация на gogetlinks.net, экспорт CSV оплаченных (`web_paid`) и ожидающих индексации (`wait_indexation`). Этот клиент больше не работает (сменилась авторизация, reCAPTCHA).

Python-парсер (`gogetlinks-api`) уже умеет авторизоваться через Selenium + reCAPTCHA и парсить задачи (`ggl_tasks`). Нужно добавить в него получение оплаченных ссылок.

## Часть 1: Новая таблица `ggl_links` (MySQL)

```sql
CREATE TABLE IF NOT EXISTS ddl.ggl_links (
    id INT AUTO_INCREMENT PRIMARY KEY,
    url VARCHAR(500) NOT NULL COMMENT 'URL размещённой ссылки',
    date_paid DATE DEFAULT NULL COMMENT 'Дата оплаты',
    status ENUM('paid', 'wait_indexation') NOT NULL COMMENT 'Статус ссылки',
    last_check_at DATETIME DEFAULT NULL COMMENT 'Время последней HTTP-проверки',
    last_check_code INT DEFAULT NULL COMMENT 'HTTP-код последней проверки',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_url (url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## Часть 2: Python-парсер (`gogetlinks_parser.py`) — новый этап

Добавить стадию --only-links:

1. После авторизации перейти на `https://gogetlinks.net/webTask/index/action/viewPaid`
2. Экспортировать CSV (кнопка "Экспорт в Excel") — получить список оплаченных ссылок с полями: URL, дата оплаты
3. Перейти на `https://gogetlinks.net/webTask/index/action/viewWaitIndexation`
4. Аналогично экспортировать CSV ожидающих индексации
5. Сохранить/обновить все URL в таблице `ggl_links`:
   - INSERT ON DUPLICATE KEY UPDATE (по `url`)
   - Проставить `status = 'paid'` или `'wait_indexation'`
   - Проставить `date_paid` из CSV (формат: `дд.мм.гггг;URL` или `URL;дд.мм.гггг` — нужно проверить порядок колонок)
6. Удалить из `ggl_links` записи, которых больше нет ни в одном из двух списков (ссылка снята/удалена)

**Частота запуска:** `@daily` (в crontab, аналогично `--skip-sites`)

## Часть 3: Проверка доступности (Python-парсер) — замена `ggl/check`

Добавить стадию `--check-links`:

1. Выбрать все URL из `ggl_links`
2. Для каждого выполнить HTTP HEAD-запрос (timeout 10s)
3. Записать `last_check_at = NOW()`, `last_check_code = HTTP-код`
4. Собрать список с кодом != 200
5. Если есть ошибки — отправить в Telegram:
   - Чат: ID из конфига
   - Формат сообщения:
   ```
   Проблемы с доступом оплаченных ссылок:
   https://example.com/page1 503
   https://example.com/page2 0
   ```

**Частота запуска:** `@daily`

## Часть 4: DDL (`ggl/warm`) — переделка

После создания таблицы `ggl_links`, команда `ggl/warm` в DDL берёт URL из БД вместо API:

```php
public function actionWarm()
{
    $urls = (new Query())
        ->select('url')
        ->from('ggl_links')
        ->column();
    // ... далее прогрев GET-запросами как сейчас
}
```

**Частота:** остаётся `@hourly` в crontab www.

## Что убрать после внедрения

1. В DDL: удалить `actionCheck()` из `GglController`, удалить/упростить `Gogetlinks.php`
2. В crontab www: закомментировать `ggl/check` (если был раскомментирован)
3. В crontab root: добавить `--sync-links` и `--check-links` к запуску парсера


