# Solution Strategy: Gogetlinks Task Parser

## Problem Analysis Framework

### Problem Statement
Gogetlinks.net — биржа заданий для веб-разработчиков — не предоставляет API для автоматического получения списка доступных задач. Необходимо создать парсер для автоматического сбора информации о заданиях с последующим хранением в БД для отслеживания новых возможностей.

### First Principles Decomposition

#### Core Truth 1: Проблема доступа к данным
**Фундаментальная природа:**
- Данные существуют (публичные задания на сайте)
- Доступ ограничен авторизацией + капча
- Структура данных присутствует в HTML (парсится человеком визуально)

**Следствие:** Browser automation — единственный способ имитировать человеческий доступ.

#### Core Truth 2: Проблема автоматизации
**Фундаментальная природа:**
- Периодическое повторение одних и тех же действий (login → navigate → parse)
- Необходимость различения новых и уже обработанных заданий
- Требование минимального вмешательства пользователя

**Следствие:** Cron scheduling + database deduplication + comprehensive logging.

#### Core Truth 3: Проблема защиты от ботов
**Фундаментальная природа:**
- Капча спроектирована для различения человека и бота
- Anti-captcha.org решает капчу руками реальных людей → фактически делегируем "человеческий" шаг

**Следствие:** Интеграция captcha solver — необходимая часть архитектуры.

### TRIZ Pattern Application

#### Pattern 1: Посредничество (Mediation)
**Проблема:** Капча блокирует автоматизацию  
**TRIZ Решение:** Ввести посредника (anti-captcha.org), который имеет доступ к "человеческому" решению  
**Реализация:** Anti-Captcha API + browser plugin

#### Pattern 2: Предварительное действие (Prior Action)
**Проблема:** Каждый запуск требует полной авторизации  
**TRIZ Решение:** Использовать cookie persistence для сохранения сессии между запусками  
**Реализация:** Session cookie storage (если сессия валидна → skip auth)

#### Pattern 3: Дробление (Segmentation)
**Проблема:** Монолитный парсинг всех данных замедляет процесс  
**TRIZ Решение:** Разделить на минимальный парсинг (list view) + детальный (detail view)  
**Реализация:** 
- Фаза 1: Парсинг списка (только базовые поля)
- Фаза 2: Детальный парсинг (только для новых заданий)

#### Pattern 4: Асимметрия (Asymmetry)
**Проблема:** Одинаковая частота проверки для всех типов задач  
**TRIZ Решение:** Разная частота проверки в зависимости от типа (NEW > WAIT > PAID)  
**Реализация:** Multiple cron schedules с разными интервалами

## Solution Design Principles

### 1. Minimal Viable Implementation
**Принцип:** Start simple, add complexity only when needed  
**Реализация:**
- ✅ No Docker (простой Python script)
- ✅ No retry-логика (базовое логирование)
- ✅ No уведомления (только БД)
- ✅ Headless режим (no GUI на VPS)

### 2. Separation of Concerns
```
┌─────────────────┐
│  Auth Module    │ → Авторизация + captcha solving
├─────────────────┤
│  Parser Module  │ → HTML extraction + data cleaning
├─────────────────┤
│  Storage Module │ → MySQL insert/update + deduplication
├─────────────────┤
│  Config Module  │ → INI parsing + credentials management
└─────────────────┘
```

### 3. Fail-Safe Design
**Стратегия:** Log everything, fail gracefully  
- Каждая операция логируется с timestamp
- Exceptions не прерывают весь процесс (catch → log → continue)
- Exit codes для мониторинга cron jobs

### 4. Data Integrity
**Стратегия:** UNIQUE INDEX + ON CONFLICT handling  
```sql
CREATE UNIQUE INDEX idx_task_id ON tasks(task_id);

INSERT INTO tasks (...) VALUES (...)
ON DUPLICATE KEY UPDATE
    updated_at = NOW(),
    is_new = 0;
```

## Alternative Approaches Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| **API Reverse Engineering** | Прямой доступ к данным | Может сломаться при обновлении, риск блокировки | ❌ Rejected |
| **Static HTML Parser (requests)** | Быстрее Selenium | Не работает с JavaScript, не пройдёт капчу | ❌ Rejected |
| **Puppeteer (Node.js)** | Более современный | Требует Node.js, менее популярен для scraping | ❌ Rejected |
| **Selenium + Python** | Mature ecosystem, обширная документация | Медленнее, больше overhead | ✅ **SELECTED** |
| **Playwright** | Быстрее Selenium, лучше API | Менее stable для anti-captcha | ⚠️ Future consideration |

## Risk Analysis

### Technical Risks

#### Risk 1: Изменение вёрстки сайта
**Вероятность:** Medium  
**Влияние:** High (парсер перестанет работать)  
**Mitigation:**
- Использовать гибкие CSS selectors (не жёсткие XPath)
- Логировать HTML при ошибках парсинга
- Тесты на валидацию структуры данных

#### Risk 2: Капча не решается
**Вероятность:** Low  
**Влияние:** Critical (блокировка авторизации)  
**Mitigation:**
- Логировать все captcha failures с timestamp
- Мониторить баланс anti-captcha аккаунта
- Fallback: manual notification при N последовательных ошибках (будущая версия)

#### Risk 3: IP-блокировка
**Вероятность:** Low (при редких запусках)  
**Влияние:** High  
**Mitigation:**
- Запускать не чаще 1 раза в час
- Random User-Agent rotation (будущая версия)
- Proxy rotation (будущая версия, если потребуется)

### Operational Risks

#### Risk 4: Cron не запустился
**Вероятность:** Medium  
**Влияние:** Medium (пропущенные задания)  
**Mitigation:**
- Логировать каждый запуск в отдельный файл с timestamp
- Exit codes для мониторинга
- Crontab с email notifications на failure (опционально)

#### Risk 5: Переполнение БД
**Вероятность:** Low  
**Влияние:** Low (диск заполнится)  
**Mitigation:**
- Автоматическая архивация старых задач (> 30 дней) в отдельную таблицу
- Мониторинг размера таблицы

## Success Criteria

### Must Have (MVP)
- [x] Успешная авторизация через anti-captcha
- [x] Парсинг списка новых задач (NEW)
- [x] Сохранение в MySQL с дедупликацией
- [x] Вывод на экран (отключаемый через config)
- [x] Запуск по cron без ошибок

### Should Have (v1.1)
- [ ] Парсинг деталей задания (description, requirements)
- [ ] Session persistence (skip auth if valid)
- [ ] Retry-логика для transient errors
- [ ] Email notifications на новые задания

### Could Have (v2.0)
- [ ] Telegram bot для уведомлений
- [ ] Фильтрация задач по критериям (цена, deadline)
- [ ] Web UI для просмотра задач
- [ ] Proxy rotation для масштабирования

## Implementation Strategy

### Phase 1: Core Functionality (MVP)
**Timeline:** 2-3 дня  
**Deliverables:**
1. Auth module + captcha solving
2. Parser module (list view only)
3. MySQL schema + insert logic
4. Config management (INI)
5. Basic logging

### Phase 2: Robustness (v1.1)
**Timeline:** 1-2 дня  
**Deliverables:**
1. Detail parsing (description, requirements, contacts)
2. Session persistence
3. Retry decorator для нестабильных операций
4. Enhanced error handling

### Phase 3: Monitoring (v2.0)
**Timeline:** 2-3 дня  
**Deliverables:**
1. Telegram bot integration
2. Filtering engine
3. Web dashboard (Flask + Bootstrap)

## Constraints Validation

✅ **Python** — основной язык  
✅ **Selenium** — browser automation  
✅ **MySQL** — database  
✅ **No Docker** — прямой запуск на VPS  
✅ **Cron** — scheduler  
✅ **Anti-Captcha** — captcha solver  
✅ **Headless Chrome** — VPS compatibility  

---

**Confidence Level:** High (95%)  
**Rationale:** Все компоненты проверены research фазой, нет технологических блокеров.
