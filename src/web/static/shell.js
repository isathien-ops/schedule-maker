"use strict";

/* ============================================================================
   shell.js — оболочка открытого проекта: переход к курсу, тема оформления
   (авто / светлая / тёмная), реестр вкладок RENDERERS, боковое меню, полная
   перерисовка render() (снимок вида → новое дерево → восстановление вида) и
   переключение вкладок switchTab().
   Берёт из других файлов: S, NAV, TAB_ICONS, t, tr, remember, withoutActions
   (core.js); h, icon, avatar (ui.js); courseByName, attentionCount (domain.js);
   closeProject (projects.js — по кнопке «Ко всем проектам»). RENDERERS.<ключ>
   дописывают файлы tabs/*.js.
   Отдаёт: openCourse, setTheme, themeSwitch, RENDERERS, render, switchTab.
   При загрузке вешает window «resize» → stickyHeads.
   ============================================================================ */

// Вкладка, нарисованная последней (фокус восстанавливается только на той же).
let renderedTab = null;

// ---------------------------------------------------------------- переход к курсу

// Открывает курс на вкладке «Курсы»: запоминает его поток и линейку и
// переключает вкладку. name — полное имя курса; неизвестный курс игнорируется.
function openCourse(name) {
    const course = courseByName(name);

    if (!course) return;

    remember("section", course.section);
    remember("line", course.line);
    switchTab("classes");
}

// ---------------------------------------------------------------- тема оформления (авто / светлая / тёмная)

// Варианты темы: [ключ, иконка]. Выбор хранится в localStorage «schedule.theme»
// (его же читает маленький скрипт в index.html до отрисовки, чтобы не было вспышки).
const THEMES = [["auto", "monitor"], ["light", "sun"], ["dark", "moon"]];

// Сохранённая тема ("auto", "light" или "dark"); по умолчанию и при ошибке — "auto".
function currentTheme() {
    try {
        const theme = localStorage.getItem("schedule.theme");
        return THEMES.some(([key]) => key === theme) ? theme : "auto";
    } catch (error) {
        return "auto";
    }
}

// Применяет и запоминает тему, затем заменяет все переключатели темы на странице
// новыми (чтобы подсветилась выбранная кнопка) без полной перерисовки.
function setTheme(theme) {
    // «auto» — следовать системной теме: атрибут убирается, работает CSS-медиазапрос
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;

    try {
        localStorage.setItem("schedule.theme", theme);
    } catch (error) { /* storage may be unavailable */ }

    document.querySelectorAll(".theme-switch").forEach((box) => box.replaceWith(themeSwitch(box.classList.contains("start-theme"))));
}

// Переключатель темы из трёх кнопок. onStart — вариант для стартового экрана
// (закреплён в правом верхнем углу).
function themeSwitch(onStart = false) {
    const theme = currentTheme();

    return h("div", { class: `theme-switch ${onStart ? "start-theme" : ""}`, role: "radiogroup", "aria-label": t("web.theme") },
        THEMES.map(([key, iconName]) => h("button", {
            class: key === theme ? "active" : "", role: "radio", "aria-checked": String(key === theme),
            title: t(`web.theme.${key}_hint`), onclick: () => setTheme(key),
        }, icon(iconName), t(`web.theme.${key}`))));
}

// ---------------------------------------------------------------- боковое меню

// Отрисовщики вкладок: RENDERERS[ключ вкладки](main) дописывает содержимое
// вкладки в элемент main. Заполняют их файлы tabs/*.js, по одному на вкладку.
const RENDERERS = {};

// Число справа от пункта меню: курсов; преподавателей; у «Предпросмотра» — этапов,
// у которых есть составленные варианты, а сам этап ещё не составлен полностью (принят
// ли уже какой-то из вариантов, не важно); «составлено/всего» этапов; сохранённых
// версий; у «Запуска» во время сборки — крутящаяся иконка. null — ничего не показывать.
function navCount(tab) {
    const state = S.state;

    if (tab === "classes") return state.courses.length;
    if (tab === "teachers") return state.teachers.length;
    if (tab === "preview") return state.stages.filter((stage) => stage.variants && !stage.built).length || null;
    if (tab === "view") return `${state.stages.filter((stage) => stage.built).length}/${state.stages.length}`;
    if (tab === "save") return state.versions.length || null;
    if (tab === "run" && state.job?.running) return icon("loader", "spin");

    return null;
}

// Пункт бокового меню для вкладки tab: иконка, название, красное число «требует
// внимания» (только у «Расписания») и число справа (navCount).
function navItem(tab) {
    const count = navCount(tab);
    const attention = tab === "view" ? attentionCount() : 0;

    return h("button", { class: `nav-item ${tab === S.tab ? "active" : ""}`, onclick: () => switchTab(tab), title: tab === "view" ? t("web.nav.view_count") : null },
        icon(TAB_ICONS[tab]),
        t(`menu.main.tab.${tab}`),
        attention ? h("span", { class: "nav-alert", title: tr("web.nav.attention", { count: attention }) }, attention) : null,
        count !== null ? h("span", { class: "count" }, count) : null);
}

// Боковое меню: название программы, кнопка с именем проекта (назад к списку
// проектов), три шага работы с их вкладками (NAV), переключатель темы.
function sidebar() {
    return h("aside", { class: "sidebar" },
        h("div", { class: "brand" },
            h("div", { class: "brand-mark" }, icon("logo")),
            h("div", {}, h("div", { class: "brand-name" }, t("menu.start.label_name")), h("div", { class: "brand-sub" }, t("web.version"))),
        ),
        h("button", { class: "project-switch", title: t("web.all_projects"), onclick: closeProject },
            avatar(S.project, "avatar"),
            h("div", { class: "grow", style: { minWidth: 0 } }, h("div", { class: "label" }, t("web.project")), h("div", { class: "name" }, S.project)),
            icon("back"),
        ),
        NAV.map(([group, tabs], index) => [
            h("div", { class: "nav-group" }, h("span", { class: "step" }, index + 1), t(`web.nav.${group}`)),
            tabs.map(navItem),
        ]),
        h("div", { class: "sidebar-bottom" }, themeSwitch(), h("div", { class: "sidebar-foot" }, t("web.local_only"))),
    );
}

// ---------------------------------------------------------------- перерисовка

// Карточки .sticky-card («Курсы», неделя на «Расписании»): шапка с названием прилипает к верху
// окна, а строка заголовков таблицы — сразу под ней (на «Преподавателях» — под карточкой с именем).
// Высота шапки зависит от ширины окна, поэтому её записываем в переменную --card-head после
// каждой перерисовки и при смене размера окна.
function stickyHeads() {
    requestAnimationFrame(() => {
        document.querySelectorAll(".sticky-card").forEach((element) => {
            const head = element.querySelector(":scope > .card-head");
            if (head) element.style.setProperty("--card-head", `${head.offsetHeight}px`);
        });
        // «Преподаватели»: строка дней таблицы удобства встаёт под прилипшую карточку с именем
        document.querySelectorAll(".teacher-head").forEach((head) => head.parentElement.style.setProperty("--teacher-head", `${head.offsetHeight}px`));
    });
}

window.addEventListener("resize", stickyHeads);

// Все поля и кнопки открытого проекта по порядку: фокус запоминается номером в этом списке.
function pageFields() {
    return [...document.querySelectorAll("#app input, #app select, #app textarea, #app button")];
}

// Снимок того, что пользователь видит и делает сейчас: прокрутка окна и элементов
// с data-keep, выбранные пункты левых списков (picked — их названия), поле в фокусе
// (номер среди pageFields и тег), набранный, но ещё не отправленный текст (typed) и
// выделение в поле (cursor). restoreScroll() и restoreFocus() возвращают всё это
// после замены DOM.
function captureView() {
    const active = document.activeElement;
    const focusIndex = pageFields().indexOf(active);
    const focused = focusIndex >= 0;

    return {
        tab: renderedTab,
        scroll: window.scrollY,
        keepScroll: [...document.querySelectorAll("[data-keep]")].map((element) => [element.dataset.keep, element.scrollTop]),
        picked: [...document.querySelectorAll(".list .list-item.active")].map(listItemName),
        focusIndex,
        tagName: focused ? active.tagName : null,
        // Переносится только набираемый и ещё не отправленный текст; у списков выбора и
        // уже отправленных полей показывается то, что вернул сервер
        typed: focused && ["INPUT", "TEXTAREA"].includes(active.tagName) && active.type !== "checkbox"
            && !active.dataset.sent && active.value !== (active.dataset.rendered ?? "") ? active.value : null,
        cursor: focused && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null,
    };
}

// Заменяет содержимое #app новым деревом tree. Старые поля, теряя фокус, присылают
// blur/change — на время замены act() их не отправляет (это не правки, см. withoutActions).
function replaceApp(tree) {
    withoutActions(() => document.getElementById("app").replaceChildren(tree));
}

// Название пункта левого списка («Преподаватели», «Расписание»): текст его .title
// (у пункта без .title — весь текст). По нему снимок узнаёт, сменился ли выбор.
function listItemName(item) {
    return (item.querySelector(".title") || item).textContent;
}

// Прокрутка после перерисовки: окно и элементы с data-keep — как в снимке view;
// только что выбранный элемент списка (например, добавленный преподаватель)
// прокручивается в видимую область самого списка, страница остаётся на месте.
// Прокручивается только пункт, которого не было среди выбранных в снимке (view.picked):
// при обычной перерисовке (отметка, правка) список остаётся там, куда его прокрутили
// руками. Прокручивается то, что действительно прокручивается: в широком окне сам
// .list, в узком — .card-body карточки; scrollIntoView({block: "nearest"}) находит это
// сам, а сдвинутое им окно потом возвращается на место из снимка.
function restoreScroll(view) {
    window.scrollTo(0, view.scroll);
    stickyHeads();

    for (const [key, top] of view.keepScroll) {
        const element = document.querySelector(`[data-keep="${key}"]`);
        if (element) element.scrollTop = top;
    }

    document.querySelectorAll(".list .list-item.active").forEach((item) => {
        if (!view.picked.includes(listItemName(item))) item.scrollIntoView({ block: "nearest" });
    });
    window.scrollTo(0, view.scroll);
}

// Фокус после перерисовки той же вкладки: поле с тем же номером (и тем же тегом)
// снова в фокусе, с набранным текстом и положением курсора из снимка view.
function restoreFocus(view) {
    if (view.focusIndex < 0 || view.tab !== S.tab) return;

    const field = pageFields()[view.focusIndex];

    if (!field || field.tagName !== view.tagName) return;

    if (view.typed !== null && "value" in field) {
        field.value = view.typed;

        // Перенесённая правка всё равно отправится, когда поле потеряет фокус
        // (присвоение value само по себе не вызывает событие change)
        field.addEventListener("blur", () => {
            if (!field.dataset.sent && field.value !== (field.dataset.rendered ?? "")) field.dispatchEvent(new Event("change"));
        }, { once: true });
    }

    field.focus({ preventScroll: true });
    if (view.cursor && typeof field.setSelectionRange === "function" && ["text", "search", ""].includes(field.type || "")) field.setSelectionRange(...view.cursor);
}

// Полностью перерисовывает открытый проект: боковое меню + текущая вкладка.
//   1) captureView — снимок прокрутки, фокуса, набранного текста и курсора;
//   2) строит новое дерево (sidebar и RENDERERS[S.tab]) и заменяет им старое (replaceApp);
//   3) restoreScroll и restoreFocus возвращают вид из снимка.
// Ничего не делает, если проект не открыт.
function render() {
    if (!S.state) return;

    const view = captureView();
    const menu = sidebar();
    const content = h("main", { class: "content" });

    RENDERERS[S.tab](content);
    replaceApp(h("div", { class: "shell" }, menu, content));
    restoreScroll(view);
    restoreFocus(view);

    renderedTab = S.tab;
}

// Переключает вкладку (с запоминанием), прокручивает наверх и перерисовывает.
function switchTab(tab) {
    S.tab = tab;
    remember("tab", tab);
    window.scrollTo(0, 0);
    render();
}
