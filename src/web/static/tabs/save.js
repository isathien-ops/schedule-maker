"use strict";

/* ============================================================================
   tabs/save.js — вкладка «Версии»: что сейчас в принятом расписании,
   сохранение версии, возврат к версии и её удаление.
   Пара на сервере — src/web/tabs/save.py.
   Берёт из других файлов: S, t, tr, fieldLabel, act (core.js); элементы интерфейса
   из ui.js; isInSchedule, allJoint, stageLabel (domain.js); RENDERERS, render (shell.js).
   Отдаёт: RENDERERS.save.

   Вкладка собирается из карточек: слева nowCard и newVersionCard, справа
   versionsCard (таблица versionsTable, кнопки versionButtons).
   ============================================================================ */

// ---------------------------------------------------------------- вкладка «Версии» (сохранение и восстановление)

// Вкладка «Версии»: что сейчас в принятом расписании, форма «Сохранить версию» и
// таблица сохранённых версий с кнопками «Вернуться к этой версии» и «Удалить версию».
// Выбранная в таблице версия хранится в S.ui.version.
RENDERERS.save = (main) => {
    const selected = S.state.versions.find((version) => version.id === S.ui.version) || null;

    main.append(
        pageHead(t("menu.main.tab.save"), t("menu.main.tab.save.hint")),
        h("div", { class: "grid side" },
            h("div", { class: "stack", style: { gap: "20px" } }, nowCard(), newVersionCard()),
            versionsCard(selected),
        ),
    );
};

// Карточка «Сейчас в расписании»: сколько уроков в неделю во всех потоках вместе (тот же
// текст «Уроков в неделю во всех потоках вместе: N», что на «Расписании», — число стоит
// после двоеточия, поэтому слово «уроков» не нужно склонять), этапы (зелёный — принят
// полностью, оранжевый — не хватает уроков, серый — ещё не в принятом расписании: не
// составлен или есть только варианты; так же объясняет легенда web.save.legend в «i»)
// и предупреждения о принятых этапах, где часть уроков не расставлена. У потока, где все курсы
// присоединены к другому потоку (allJoint), такого совета нет: составлять его нечего («Запуск»
// закрыт с текстом web.run.all_joint), а уроков не хватает у потока-источника — совет стоит у него.
function nowCard() {
    return card({ title: t("web.save.now"), hint: t("web.save.legend") },
        h("div", { class: "stack" },
            h("div", { class: "row" }, badge(tr("web.view.lessons_count_all", { count: S.state.lessons }), "accent")),
            h("div", { class: "row", style: { gap: "6px" } }, S.state.stages.map((stage) => badge(stage.label, stage.built ? "ok" : isInSchedule(stage) ? "warn" : "", isInSchedule(stage)))),
            S.state.stages.filter((stage) => stage.placed && !stage.built && !allJoint(stage)).map((stage) => h("p", { class: "hint", style: { color: "var(--warn)" } },
                tr("web.save.partial", { name: stage.label, count: stage.expected - stage.placed }))),
            S.state.stages.some(isInSchedule) ? null : h("p", { class: "hint" }, t("menu.main.tab.save.nothing_built")),
        ));
}

// Карточка «Новая версия»: имя и комментарий. Пустое имя сервер заменяет на «Версия от
// ДД.ММ.ГГГГ ЧЧ:ММ» (newVersion в src/web/tabs/save.py) — в поле это видно подсказкой.
function newVersionCard() {
    const now = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    const placeholder = `${t("menu.main.tab.save.default_name")} ${pad(now.getDate())}.${pad(now.getMonth() + 1)}.${now.getFullYear()} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
    const name = input({ placeholder });
    // Две строки высотой: подсказка и комментарий подлиннее видны целиком
    const comment = h("textarea", { class: "input", rows: 2, placeholder: t("menu.main.tab.save.comment_placeholder"), style: { height: "auto", padding: "8px 10px", resize: "vertical", width: "100%" } });

    return card({
        title: t("web.save.new"),
        foot: btn(t("menu.main.tab.save.save"), () => act("newVersion", { name: name.value, comment: comment.value }), { iconName: "bookmark", kind: "primary block" }),
    }, h("div", { class: "stack" },
        h("label", { class: "stack-sm" }, h("h3", {}, fieldLabel("menu.main.tab.save.name")), name),
        h("label", { class: "stack-sm" }, h("h3", {}, fieldLabel("menu.main.tab.save.comment")), comment),
    ));
}

// Карточка «Сохранённые версии»: таблица версий (или «пока нет») и внизу кнопки
// для выбранной версии selected (null — ничего не выбрано).
function versionsCard(selected) {
    const versions = S.state.versions;

    return card({
        title: t("menu.main.tab.save.versions"), actions: badge(versions.length), flush: true,
        foot: versions.length ? versionButtons(selected) : null,
    }, versions.length ? versionsTable(selected) : empty("bookmark", t("menu.main.tab.save.no_versions"), t("web.save.empty_hint")));
}

// Таблица сохранённых версий: имя, когда сохранена, какие этапы в ней, уроков, комментарий.
// Щелчок по строке выбирает версию.
function versionsTable(selected) {
    const formatDate = (value) => {
        const date = new Date(value);

        return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
    };

    return h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, ["name", "created", "stages", "lessons", "comment"].map((key) => h("th", { class: key === "lessons" ? "right" : "" }, t(`menu.main.tab.save.column.${key}`))))),
        h("tbody", {}, S.state.versions.map((item) => h("tr", {
            class: `clickable ${item.id === selected?.id ? "selected" : ""}`,
            onclick: () => { S.ui.version = item.id; render(); },
        },
            h("td", {}, h("b", {}, item.name)),
            h("td", { style: { whiteSpace: "nowrap" } }, formatDate(item.created)),
            h("td", {}, h("span", { class: "row", style: { gap: "4px" } }, (item.stages || []).map((stage) => badge(stageLabel(stage), "ok")))),
            h("td", { class: "right" }, item.lessons),
            h("td", { style: { color: "var(--muted)" } }, item.comment),
        ))),
    ));
}

// Кнопки под таблицей версий: «Вернуться к этой версии» и «Удалить версию» для
// выбранной версии selected (обе — после подтверждения); без выбора — подсказка.
function versionButtons(selected) {
    const restore = async () => {
        if (!await confirmDialog(tr("menu.main.tab.save.confirm_restore", { name: selected.name }), { yes: t("web.restore_yes") })) return;
        if (await act("restore", { version: selected.id })) toast(t("web.restored"));
    };
    const remove = async () => {
        // Исходное расписание, которое передали вместе с программой (поле handover от
        // сервера), — особое предупреждение: без него вернуться к началу будет нельзя
        const warning = selected.handover ? `\n\n${t("web.save.handover_warning")}` : "";

        if (await confirmDialog(tr("menu.main.tab.save.confirm_delete", { name: selected.name }) + warning, { danger: true, yes: t("web.common.delete") })) {
            act("removeVersion", { version: selected.id });
        }
    };

    return [
        btn(t("menu.main.tab.save.restore"), restore, { iconName: "undo", kind: "primary", disabled: !selected }),
        btn(t("menu.main.tab.save.delete"), remove, { iconName: "trash", kind: "danger", disabled: !selected }),
        selected ? null : h("span", { class: "hint" }, t("web.save.pick")),
    ];
}
