"use strict";

/* ============================================================================
   projects.js — стартовый экран: список проектов, создание, импорт ZIP-архива,
   удаление; открытие и закрытие проекта и адрес страницы «#имя_проекта».
   Пара на сервере — src/web/projects.py.
   Берёт из других файлов: S, HOOKS, t, tr, api, recall (core.js); h, btn, input,
   icon, avatar, iconTile, formError, empty, toast, confirmDialog (ui.js);
   attentionCount (domain.js); themeSwitch, RENDERERS, render (shell.js).
   Что вкладки запомнили о проекте, они забывают сами по событию
   HOOKS.projectClosed (его зовут openProject и closeProject); об открытом проекте
   узнают по HOOKS.projectOpened (его зовёт openProject).
   Отдаёт: renderStart, openProject, closeProject, projectInAddress, followAddress.
   ============================================================================ */

// ---------------------------------------------------------------- стартовый экран (список проектов)

// Рисует стартовый экран: шапку с названием программы и под ней список проектов
// (карточки со статистикой), карточку «Создание проекта» и карточку «Импорт проекта». Загружает
// список с /api/projects; если сервер не ответил, вместо списка — сообщение об ошибке
// и кнопка «Повторить» (снова renderStart, когда программа снова запущена).
async function renderStart() {
    let body;

    try {
        const projects = await api("/api/projects");

        body = h("div", { class: "tile-grid" }, projects.map(projectCard), newProjectCard(), importCard());
    } catch (error) {
        body = empty("alert", t("web.error.generic"), error.message, btn(t("web.common.retry"), renderStart, { iconName: "undo" }));
    }

    document.getElementById("app").replaceChildren(h("div", { class: "start" }, themeSwitch(true), h("div", { class: "start-inner" },
        h("div", { class: "start-hero" },
            h("div", { class: "brand-mark" }, icon("logo")),
            h("div", {}, h("h1", {}, t("menu.start.label_name")), h("p", { class: "hint", style: { fontSize: "14px" } }, t("web.tagline"))),
        ),
        h("div", { class: "stack" }, h("h2", {}, t("web.projects")), body),
    )));
}

// Карточка проекта на стартовом экране: аватар, имя, когда меняли, корзина
// (removeProject) и статистика — курсы, преподаватели, составлено этапов.
// project — элемент ответа /api/projects. Клик или Enter — openProject().
function projectCard(project) {
    const modified = project.modified
        ? new Date(project.modified).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })
        : "";

    return h("div", {
        class: "tile project-card", role: "button", tabindex: "0",
        onclick: () => openProject(project.name),
        onkeydown: (event) => event.target === event.currentTarget && event.key === "Enter" && openProject(project.name),
    },
        h("div", { class: "p-top" },
            avatar(project.name, "avatar"),
            h("div", { class: "grow", style: { minWidth: 0 } }, h("div", { class: "p-name" }, project.name), h("div", { class: "p-date" }, modified)),
            btn("", (event) => { event.stopPropagation(); removeProject(project.name); },
                { iconName: "trash", kind: "ghost danger icon-only p-delete", size: "sm", title: t("web.delete_project") }),
        ),
        h("div", { class: "p-stats" },
            h("span", {}, h("b", {}, project.courses), t("web.stat_courses")),
            h("span", {}, h("b", {}, project.teachers), t("web.stat_teachers")),
            h("span", {}, h("b", {}, `${project.built}/${project.stages}`), t("web.stat_stages")),
        ),
    );
}

// Карточка «Создание проекта»: имя и «Создать» (или Enter в поле). Сервер проверяет имя;
// ошибка показывается под полем, при успехе новый проект сразу открывается.
function newProjectCard() {
    const name = input({ placeholder: t("web.new_project_placeholder") });
    const error = formError();
    const create = async () => {
        try {
            const result = await api("/api/projects", { method: "POST", body: { name: name.value } });
            openProject(result.project);
        } catch (failure) {
            error.textContent = failure.message;
        }
    };

    name.addEventListener("keydown", (event) => event.key === "Enter" && create());

    return h("div", { class: "tile new" },
        h("div", { class: "p-top" }, iconTile("plus"), h("div", { class: "p-name" }, t("dialog.create_project.title"))),
        name,
        btn(t("web.common.create"), create, { kind: "primary block" }),
        error,
    );
}

// Стартовый экран: удаляет проект насовсем (после подтверждения) и перерисовывает
// список. Ошибка сервера показывается всплывающим сообщением.
async function removeProject(name) {
    const sure = await confirmDialog(tr("web.delete_project_confirm", { name }), { danger: true, yes: t("web.delete_project"), title: t("web.delete_project") });

    if (!sure) return;

    try {
        await api(`/api/project/${encodeURIComponent(name)}`, { method: "DELETE" });
        toast(tr("web.project_deleted", { name }));
    } catch (failure) {
        toast(failure.message, true);
    }

    renderStart();
}

// Стартовый экран: карточка «Импорт проекта» — ZIP-архив (из «Экспорт» → «Весь проект»)
// загружается на сервер (/api/projects/import, файл и имя — в FormData) и становится
// новым проектом, который сразу открывается. Ошибка показывается под полями.
// Возвращает DOM-элемент карточки.
function importCard() {
    const file = h("input", { type: "file", accept: ".zip,application/zip", hidden: true });
    const fileName = h("span", { class: "hint grow", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, t("web.import_no_file"));
    const name = input({ placeholder: t("web.import_name") });
    const error = formError();

    file.addEventListener("change", () => {
        const chosen = file.files[0];

        fileName.textContent = chosen ? chosen.name : t("web.import_no_file");

        // Имя по умолчанию берётся из файла: «Расписание_26_27.zip» → «Расписание_26_27»
        if (chosen && !name.value) name.value = chosen.name.replace(/\.zip$/i, "").replace(/\s+/g, "_");
    });

    const upload = async (event) => {
        const button = event.currentTarget;

        if (!file.files[0]) return (error.textContent = t("web.import_pick"));

        const form = new FormData();
        form.append("file", file.files[0]);
        form.append("name", name.value.trim());

        button.disabled = true;

        try {
            const result = await api("/api/projects/import", { method: "POST", body: form });

            toast(tr("web.import_done", { name: result.project }));
            openProject(result.project);
        } catch (failure) {
            // Сервер отказал (не архив проекта, имя занято…) или не ответил: текст — под полями
            error.textContent = failure.message;
        } finally {
            button.disabled = false;
        }
    };

    return h("div", { class: "tile new" },
        h("div", { class: "p-top" }, iconTile("upload"), h("div", { class: "p-name" }, t("web.import_project"))),
        file,
        h("div", { class: "row", style: { flexWrap: "nowrap" } }, btn(t("web.import_choose"), () => file.click(), { size: "sm" }), fileName),
        name,
        btn(t("web.import_button"), upload, { kind: "primary block", iconName: "upload" }),
        error,
    );
}

// ---------------------------------------------------------------- открытие и закрытие проекта

// Открывает проект name: вкладки забывают прежний проект (HOOKS.projectClosed),
// сбрасываются настройки вида S.ui, загружается состояние проекта (POST /open),
// выбирается вкладка (запомненная; при проблемах в расписании — «Расписание»,
// иначе «Настройки»), имя пишется в адрес страницы (#имя), страница рисуется и
// вкладки узнают, что проект открыт (HOOKS.projectOpened: «Запуск» подхватывает
// идущую сборку). При ошибке — сообщение и назад к списку проектов.
async function openProject(name) {
    HOOKS.projectClosed.forEach((hook) => hook());
    S.project = name;
    S.ui = {};

    try {
        S.state = await api(`/api/project/${encodeURIComponent(name)}/open`, { method: "POST" });
        if (S.state.message) setTimeout(() => toast(S.state.message), 300);
    } catch (error) {
        toast(error.message, true);
        return closeProject();
    }

    S.tab = recall("tab", attentionCount() ? "view" : "settings");
    // Запомненной вкладки может уже не быть (её переименовали или убрали) — тогда «Настройки»
    if (!RENDERERS[S.tab]) S.tab = "settings";
    location.hash = encodeURIComponent(name);
    render();
    HOOKS.projectOpened.forEach((hook) => hook());
}

// Закрывает проект и показывает список проектов: вкладки забывают проект
// (HOOKS.projectClosed), адрес страницы очищается. Зовут кнопка с именем проекта
// в боковом меню, doAct (проект удалили в другой вкладке браузера), openProject
// (проект не открылся) и followAddress (из адреса убрали имя проекта).
function closeProject() {
    HOOKS.projectClosed.forEach((hook) => hook());
    S.project = null;
    S.state = null;
    location.hash = "";
    renderStart();
}

// Имя проекта из адреса страницы («…/#Расписание_26_27» → «Расписание_26_27»);
// "" — в адресе проекта нет. Битый адрес (например, обрезанная ссылка
// «…/#%E0%A4%A», которую нельзя раскодировать) тоже считается адресом без проекта:
// откроется стартовый экран, а не пустая страница.
function projectInAddress() {
    try {
        return decodeURIComponent(location.hash.slice(1));
    } catch (error) {
        return "";
    }
}

// Адрес страницы поменяли вручную (вставили «/#проект» в открытую вкладку, нажали
// «Назад» в браузере): открывается проект из адреса или, если его там нет, список
// проектов. Адрес, который поставила сама страница (openProject, closeProject),
// совпадает с открытым проектом — тогда ничего не делаем.
function followAddress() {
    const project = projectInAddress();

    if (project === (S.project ?? "")) return;

    if (project) openProject(project);
    else closeProject();
}
