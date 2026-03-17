# Server Access (Read-Only)

## SSH
- Алиас: `ssh ddl`
- Проект: `/root/scripts/gogetlinks-api/`

## Только чтение
- Можно: ssh + read команды, SELECT запросы, tail/grep логов
- НЕЛЬЗЯ: изменять файлы, рестарты, запись в БД, удаление

## Логи
- Парсер: `/root/scripts/gogetlinks-api/logs/gogetlinks_parser.log`
- Крон: `/var/log/gogetlinks_cron.log`

## База данных
- Доступна без пароля: `mysql ddl -N -e "SQL"`
- Таблицы: `ggl_tasks` (таски), `domain` (домены)
