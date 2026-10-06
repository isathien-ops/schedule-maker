"""Серверная часть вкладок открытого проекта: по модулю на вкладку страницы.

Ключ вкладки (S.tab в JS, menu.main.tab.<ключ> в ru.hjson) → модуль здесь → файл страницы:

    ключ      вкладка          сервер                  страница
    settings  «Настройки»      tabs/settings.py        static/tabs/settings.js
    classes   «Курсы»          tabs/classes.py         static/tabs/classes.js
    teachers  «Преподаватели»  tabs/teachers.py        static/tabs/teachers.js
    run       «Запуск»         tabs/run.py             static/tabs/run.js
    preview   «Предпросмотр»   tabs/preview.py         static/tabs/preview.js
    view      «Расписание»     — (данные из state())   static/tabs/view.js
    save      «Версии»         tabs/save.py            static/tabs/save.js
    export    «Экспорт»        tabs/export.py          static/tabs/export.js

Правила:
* Модуль вкладки импортирует только core, project, actions, state, ranking и build (build —
  только как модуль: `from src.web import build`) и предметные модули src/modules/functions.
  Другие вкладки, projects и server он не импортирует.
* Имя функции с @action — это имя действия в API (страница вызывает его по имени):
  не переименовывать. Действие, которое меняет то, что строит сборка (сетку, курсы,
  преподавателей, расписание…), или то, что сборка берёт в работу (веса, свои правила,
  параметры подбора, настройки), помечается `@action(blocking=True)`: пока идёт сборка,
  оно отклоняется (см. шапку actions.py).
* Предметная логика — в src/modules/functions; в модуле вкладки остаются проверка аргументов,
  вопрос человеку, версия «Перед: …» (project.saveBeforeVersion) и сохранение файлов.
* Имена функций-маршрутов (@app.route) уникальны во всём пакете src.web: это endpoint Flask.
* Совпадения имён здесь безопасны, потому что импорты абсолютные: tabs/export.py
  и src/modules/functions/export.py, функция run в tabs/run.py.
* Модули регистрируют маршруты и действия при импорте; список импортов — в src/web/server.py.
"""
