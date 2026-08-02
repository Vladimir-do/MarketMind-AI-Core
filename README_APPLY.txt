MARKETMIND FIX STAGE 4 — единый runtime

Перед применением сделайте копию папки проекта.

Содержимое архива нужно распаковать ПОВЕРХ корня проекта с заменой файлов.
Архив НЕ содержит базу данных, runtime, cookies, логи или секреты.

Что меняется:
- единый runtime по умолчанию: <project>/runtime;
- база: runtime/database/marketmind.db;
- проекты: runtime/projects;
- логи и JSONL: runtime/logs;
- Linux launcher больше не использует app/data;
- плановый запуск продолжает диагностику после сбоя отдельного этапа;
- Windows launcher использует runtime/projects;
- добавлены проверки конфигурации и расширены ignore-файлы.

Запуск Linux:
  chmod +x start_marketmind.sh scripts/*.sh
  ./start_marketmind.sh

Запуск Windows:
  start_marketmind.bat

Важно: существующую старую базу из app/data/parser.db не удаляйте.
Сначала скопируйте её в runtime/database/marketmind.db и только затем запускайте новую версию.
