-- Таблица обмена заказными статьями между gogetlinks-api и DDL.
-- Контракт: ~/git/garden-network/docs/TZ-ggl-orders.md, сторона парсера: docs/TZ_ggl_article_order.md
-- Схема базы ddl принадлежит DDL. Здесь файл лежит для сверки: таблица накачена вручную
-- 25.09.2026, потому что миграции в ddl-gpbn ещё нет. Миграция DDL должна быть
-- CREATE TABLE IF NOT EXISTS и совпадать с этой структурой.
-- Применение: mysql ddl < docs/sql/ggl_article_order.sql

CREATE TABLE IF NOT EXISTS ggl_article_order (
  id INT AUTO_INCREMENT PRIMARY KEY,
  task_id INT NOT NULL,
  domain VARCHAR(255) NOT NULL,
  target_url VARCHAR(500) NOT NULL,
  anchor VARCHAR(500) NOT NULL,
  anchor_inflect TINYINT NOT NULL DEFAULT 0,
  requirements TEXT,
  price DECIMAL(10,2) DEFAULT NULL,
  status ENUM('new','working','published','cancel','cancelled') NOT NULL DEFAULT 'new',
  article_url VARCHAR(500) DEFAULT NULL,
  error VARCHAR(500) DEFAULT NULL,
  attempts INT NOT NULL DEFAULT 0,
  notified_at DATETIME DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  published_at DATETIME DEFAULT NULL,
  cancelled_at DATETIME DEFAULT NULL,
  UNIQUE KEY uniq_task_id (task_id),
  KEY idx_status (status),
  KEY idx_status_notified (status, notified_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
