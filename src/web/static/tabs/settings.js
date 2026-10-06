"use strict";

/* ============================================================================
   tabs/settings.js — вкладка «Настройки»: «Сетка расписания» — время уроков (с
   черновиком gridDraft, пока правки идут на сервер), «Ограничения для
   преподавателей» — сколько курсов на преподавателя, матрица «Пересечения
   предметов». Пара на сервере — src/web/tabs/settings.py.
   Берёт из других файлов: S, HOOKS, t, fieldLabel, act (core.js); h,
   btn, input, card, badge, icon, pageHead (ui.js); dayName, hyphenate,
   isBuilding, buildingNote (domain.js); RENDERERS (shell.js).
   Отдаёт: RENDERERS.settings.
   При загрузке подписывается на HOOKS: черновик сетки сбрасывается, когда сервер
   ответил на последнее действие в очереди и когда проект закрыт.

   Вкладка собирается из карточек gridCard, limitsCard и pairsCard (ячейки — pairCell).
   ============================================================================ */

// Время уроков, набранное в сетке «Настроек» и ещё не подтверждённое сервером
// (см. onchange сетки): пока идут действия, сетка рисуется из этого черновика
let gridDraft = null;

// Сбросить черновик: сетка снова показывает то, что на сервере
function dropGridDraft() {
    gridDraft = null;
}

// Сервер ответил на последнее действие из очереди (успешно или отказом) — черновик
// больше не нужен; пока в очереди есть ещё правки сетки, он остаётся
HOOKS.afterAction.push(({ last }) => { if (last) dropGridDraft(); });
HOOKS.projectClosed.push(dropGridDraft);

// ---------------------------------------------------------------- вкладка «Настройки»

// Вкладка «Настройки»: сетка времени уроков по дням недели (gridCard), ограничение —
// сколько курсов может одновременно вести один преподаватель (limitsCard) — и матрица
// пар предметов (pairsCard: какие предметы можно/нежелательно/нельзя ставить в одно время).
// Пока идёт сборка (isBuilding), всё это закрыто — сборка уже работает по этим настройкам
// (сервер такие правки не примет); сверху подпись buildingNote. Когда сборка кончится,
// pollJob перерисует страницу.
RENDERERS.settings = (main) => {
    const locked = isBuilding();

    main.append(
        pageHead(t("menu.main.tab.settings"), t("web.settings.page_hint")),
        h("div", { class: "grid settings" },
            locked ? h("div", { class: "span-all" }, buildingNote()) : null,
            gridCard(locked),
            limitsCard(locked),
            // Матрице предметов нужна вся ширина страницы
            h("div", { class: "span-all" }, pairsCard(locked)),
        ),
    );
};

// Карточка «Сетка расписания»: строки — дни, столбцы — номера уроков, в ячейке — время урока.
// При изменении одной ячейки на сервер уходит вся сетка целиком (setGrid). Пока действие
// не вернулось, набранные значения хранятся в gridDraft, чтобы быстрая правка соседних
// ячеек не затиралась промежуточной перерисовкой. Внизу — «Сделать все рабочие дни как
// понедельник». locked — идёт сборка: поля и кнопка закрыты.
function gridCard(locked) {
    const max = S.state.maxLessons;
    // Время в ячейке: из черновика, пока правки идут на сервер, иначе с сервера
    const cellTime = (day, lesson) => (gridDraft ? gridDraft[day]?.[lesson] : S.state.grid[day][lesson]) || "";
    const table = h("table", { class: "times" },
        h("thead", {}, h("tr", {}, h("th"), [...Array(max).keys()].map((lesson) => h("th", { class: "center" }, `${t("menu.main.tab.settings.lesson")} ${lesson + 1}`)))),
        h("tbody", {}, [...Array(S.meta.days).keys()].map((day) => h("tr", { "data-day": day },
            h("th", {}, dayName(day)),
            [...Array(max).keys()].map((lesson) => h("td", {}, h("input", {
                class: "grid-input", value: cellTime(day, lesson), "data-rendered": cellTime(day, lesson),
                placeholder: "—", "aria-label": `${dayName(day)}, ${lesson + 1}`, disabled: locked || null,
                onchange: (event) => {
                    // Поле уже убрано перерисовкой — это не правка
                    if (!event.target.isConnected) return;

                    // Текущие значения всех полей сетки: [день][урок] → строка времени
                    gridDraft ||= [...table.querySelectorAll("tr[data-day]")].map((row) => [...row.querySelectorAll("input")].map((item) => item.value));
                    gridDraft[day][lesson] = event.target.value;
                    act("setGrid", { days: gridDraft.map((row) => [...row]) });
                },
            }))),
        ))),
    );

    return card({
        title: t("web.settings.grid"), hint: t("menu.main.tab.settings.grid_hint"), flush: true,
        foot: btn(t("menu.main.tab.settings.copy_monday"), () => act("copyMonday"), { iconName: "copy", size: "sm", disabled: locked }),
    }, h("div", { class: "table-wrap" }, table));
}

// Карточка «Ограничения для преподавателей»: сколько курсов может вести один преподаватель (не меньше 1).
// locked — идёт сборка: поле закрыто.
function limitsCard(locked) {
    return card({ title: t("web.settings.limits"), hint: t("menu.main.tab.settings.limits_hint") }, h("div", { class: "fields" }, h("div", { class: "field-row" },
        h("span", { class: "label" }, fieldLabel("menu.main.tab.settings.max_courses_per_teacher")),
        input({ type: "number", min: 1, value: S.state.limits.max_courses_per_teacher, disabled: locked || null,
            onchange: (event) => act("setLimit", { key: "max_courses_per_teacher", value: event.target.value }) }),
    )));
}

// Ячейка матрицы пар предметов. Клик по кругу меняет состояние:
// allowed (можно, «·») → soft (нежелательно, «−») → hard (нельзя, «×»).
// Диагональ (предмет сам с собой) неактивна; locked — идёт сборка: клетка закрыта.
function pairCell(first, second, locked) {
    if (first === second) return h("td", {}, h("button", { class: "pair self", disabled: true }, "—"));

    const state = S.state.pairs[first][second];

    return h("td", {}, h("button", {
        class: `pair ${state}`, title: `${first} + ${second}: ${t(`menu.main.tab.settings.pair_${state}`)}`, disabled: locked || null,
        onclick: () => act("cyclePair", { first, second }),
    }, state === "allowed" ? "·" : icon(state === "hard" ? "x" : "minus")));
}

// Карточка «Пересечения предметов»: матрица предмет × предмет (pairCell) и легенда состояний.
// locked — идёт сборка: клетки закрыты.
function pairsCard(locked) {
    const subjects = S.state.subjects;

    return card({
        title: t("web.settings.pairs"), hint: t("menu.main.tab.settings.pairs_hint"), flush: true,
        foot: h("div", { class: "legend" },
            h("span", {}, h("span", { class: "swatch", style: { background: "var(--border-strong)" } }), t("menu.main.tab.settings.pair_allowed")),
            badge(t("menu.main.tab.settings.pair_soft"), "warn"),
            badge(t("menu.main.tab.settings.pair_hard"), "bad"),
        ),
    }, h("div", { class: "table-wrap" }, h("table", { class: "pairs" },
        h("colgroup", {}, h("col", { style: { width: "170px" } }), subjects.map(() => h("col"))),
        // Сверху полные названия предметов (с переносами), оформленные как названия слева
        h("thead", {}, h("tr", {}, h("th"), subjects.map((subject) => h("th", { class: "subject" }, hyphenate(subject))))),
        h("tbody", {}, subjects.map((first) => h("tr", {}, h("th", {}, first), subjects.map((second) => pairCell(first, second, locked))))),
    )));
}
