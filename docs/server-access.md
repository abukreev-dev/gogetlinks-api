# Server Access

## SSH
- Алиас: `ssh ddl`

## Код проекта
- Проект сам находится в /root/scripts/gogetlinks-api/

## Логи
 - Лог самого парсера: /root/scripts/gogetlinks-api/logs/gogetlinks_parser.log
 - Лог крона: /var/log/gogetlinks_cron.log

## База данных
 - База даных доступна под текущим пользователем ssh без пароля
 - Таблицы проекта находятся в базе ddl
 - Таблица ggl_tasks - список тасок из gogetlinks.net 
 - Таблица domain - список доменов для работы и обновления параметров доменов

