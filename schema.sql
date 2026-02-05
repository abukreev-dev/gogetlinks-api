-- Gogetlinks Task Parser - Database Schema
-- MySQL 8.0+
--
-- Использование:
-- mysql -u root -p < schema.sql

-- Создание базы данных
CREATE DATABASE IF NOT EXISTS gogetlinks
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE gogetlinks;

-- Создание таблицы задач
CREATE TABLE IF NOT EXISTS tasks (
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

-- Создание пользователя для парсера (выполните отдельно с правами root)
-- CREATE USER 'gogetlinks_parser'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD_HERE';
-- GRANT SELECT, INSERT, UPDATE ON gogetlinks.* TO 'gogetlinks_parser'@'localhost';
-- FLUSH PRIVILEGES;

-- Проверка создания таблицы
SHOW TABLES;
DESCRIBE tasks;
