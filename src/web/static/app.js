"use strict";

/* ============================================================================
   app.js — точка входа страницы, загружается последним. Список файлов страницы
   и порядок их загрузки — в index.html и в шапке core.js.
   start() — запуск страницы: загружает тексты интерфейса (/api/i18n) и справочные
   данные (/api/meta), ставит заголовок вкладки браузера, открывает проект из
   адреса (#имя_проекта) или показывает стартовый экран и дальше следит за
   адресом: «/#проект», вставленный в уже открытую вкладку, открывает проект без
   перезагрузки (событие hashchange → followAddress).
   Берёт из других файлов: S, t, api (core.js); openProject, renderStart,
   projectInAddress, followAddress (projects.js).
   ============================================================================ */

// ---------------------------------------------------------------- запуск страницы

(async function start() {
    [S.i18n, S.meta] = await Promise.all([api("/api/i18n"), api("/api/meta")]);
    document.title = t("menu.start.label_name");

    const project = projectInAddress();

    if (project) openProject(project);
    else renderStart();

    window.addEventListener("hashchange", followAddress);
})();
