-- Gogetlinks Task Parser - Database Schema
-- MySQL 8.0+
--
-- Использование:
-- mysql -u root -p < schema.sql

-- Создание таблицы задач
-- Важно: база ddl должна существовать заранее
CREATE TABLE IF NOT EXISTS ddl.ggl_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Внутренний ID',
    task_id INT UNIQUE NOT NULL COMMENT 'ID задачи на gogetlinks.net',

    -- Основная информация
    title VARCHAR(500) DEFAULT NULL COMMENT 'Заголовок задачи',
    description TEXT DEFAULT NULL COMMENT 'Полное описание задачи',
    price DECIMAL(10,2) DEFAULT NULL COMMENT 'Цена задачи',
    deadline DATETIME DEFAULT NULL COMMENT 'Срок выполнения',

    -- Информация о заказчике
    customer VARCHAR(255) DEFAULT NULL COMMENT 'Имя заказчика',
    customer_url VARCHAR(500) DEFAULT NULL COMMENT 'Ссылка на профиль заказчика',

    -- Детали задачи
    domain VARCHAR(255) DEFAULT NULL COMMENT 'Домен для размещения',
    url VARCHAR(500) DEFAULT NULL COMMENT 'URL для размещения',
    requirements TEXT DEFAULT NULL COMMENT 'Требования к выполнению',
    contacts TEXT DEFAULT NULL COMMENT 'Контактная информация',

    -- Метаданные
    external_links INT DEFAULT NULL COMMENT 'Количество внешних ссылок',
    time_passed VARCHAR(100) DEFAULT NULL COMMENT 'Время с момента публикации',

    -- Системные поля
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Время первого обнаружения',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Время последнего обновления',
    is_new BOOLEAN DEFAULT 1 COMMENT 'Флаг новой задачи (1 = новая, 0 = уже обработана)',

    -- Индексы для производительности
    INDEX idx_task_id (task_id),
    INDEX idx_created_at (created_at),
    INDEX idx_is_new (is_new),
    INDEX idx_price (price),
    INDEX idx_deadline (deadline)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Задачи с gogetlinks.net';

-- Создание таблицы оплаченных ссылок
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='Оплаченные ссылки с gogetlinks.net';

-- Эксперимент с ценами: группа каждого домена (заполняет --prices-assign)
CREATE TABLE IF NOT EXISTS ddl.ggl_price_experiment (
    host VARCHAR(255) NOT NULL PRIMARY KEY COMMENT 'domain.host',
    site_id INT DEFAULT NULL COMMENT 'site_id на gogetlinks (карточка сайта)',
    grp VARCHAR(20) NOT NULL COMMENT 'control или цена группы',
    target_price INT DEFAULT NULL COMMENT 'Цена статьи/заметки/контекста; NULL = контроль',
    sales_before INT NOT NULL DEFAULT 0 COMMENT 'Продаж за 90 дней до эксперимента',
    revenue_before DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT 'Выручка за 90 дней до',
    traffic INT NOT NULL DEFAULT 0 COMMENT 'ggl_traffic на момент распределения',
    assigned_at DATETIME NOT NULL,
    applied_at DATETIME DEFAULT NULL COMMENT 'Когда цена выставлена и проверена'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='Эксперимент с ценами площадок GGL';

-- История прочитанных цен из карточки сайта (--prices-read, --prices-apply)
CREATE TABLE IF NOT EXISTS ddl.ggl_site_prices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    host VARCHAR(255) NOT NULL,
    site_id INT NOT NULL,
    price_paper DECIMAL(10,2) NOT NULL COMMENT 'Статья',
    price_post DECIMAL(10,2) NOT NULL COMMENT 'Заметка',
    price_link DECIMAL(10,2) NOT NULL COMMENT 'Контекстная ссылка',
    not_paper TINYINT(1) NOT NULL DEFAULT 0 COMMENT '«не размещаю»',
    not_post TINYINT(1) NOT NULL DEFAULT 0,
    not_link TINYINT(1) NOT NULL DEFAULT 0,
    read_at DATETIME NOT NULL,
    KEY idx_host_read (host, read_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='Снимки цен площадок GGL';

-- Создание пользователя для парсера (выполните отдельно с правами root)
-- CREATE USER 'gogetlinks_parser'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD_HERE';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ddl.* TO 'gogetlinks_parser'@'localhost';
-- FLUSH PRIVILEGES;

-- Проверка создания таблицы
SHOW TABLES FROM ddl;
DESCRIBE ddl.ggl_tasks;
