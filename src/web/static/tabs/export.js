"use strict";

/* ============================================================================
   tabs/export.js — вкладка «Экспорт» и окно «Экспортировать»: список выгрузок
   EXPORTS, скачивание download() и выгрузка вариантов потока.
   Пара на сервере — src/web/tabs/export.py.
   Берёт из других файлов: S, t, api, recall (core.js); элементы интерфейса из
   ui.js; RENDERERS (shell.js).
   Отдаёт: RENDERERS.export, download (кнопка «Скачать варианты» на
   «Предпросмотре»), exportDialog (кнопки «Экспортировать» на «Расписании»).

   Одни и те же выгрузки (exportItems) показываются двумя способами:
   • RENDERERS.export — вкладка «Экспорт»: карточка на каждый вид файла
     (иконка, название, «i»-пояснение, формат) с кнопкой «Скачать»;
   • exportDialog() — окно со строками тех же выгрузок; открывается кнопкой
     «Экспортировать» на вкладке «Расписание», закрывается кнопкой «Закрыть».
   ============================================================================ */

// ---------------------------------------------------------------- вкладка «Экспорт» (скачивание файлов)

// Что можно скачать: [вид (часть адреса /export/<вид>), иконка, ключ подписи,
// ключ подсказки, формат файла].
const EXPORTS = [
    ["courses", "sheet", "save_classes_schedule", "classes_hint", "XLSX"],
    ["teachers", "users", "save_teachers_schedule", "teachers_hint", "XLSX"],
    ["teacher_list", "bookmark", "save_teacher_list", "teacher_list_hint", "XLSX"],
    ["calendar", "calendar", "save_calendar", "calendar_hint", "XLSX"],
    ["project", "archive", "save_project", "project_hint", "ZIP"],
];

// Скачивает файл экспорта kind. Имя файла берётся из заголовка Content-Disposition
// (сначала вариант filename*=UTF-8'' для русских имён, потом обычный filename),
// иначе «<проект>-<kind>». Кнопка button на время загрузки неактивна.
// Скачивание — через временную ссылку на Blob. Отказ сервера (его текст) и «сервер не
// ответил» показываются всплывающим сообщением.
// kind — вид выгрузки, может быть с параметрами адреса ("variants?stage=2")
async function download(kind, button) {
    button.disabled = true;

    try {
        const response = await api(`/api/project/${encodeURIComponent(S.project)}/export/${kind}`, { raw: true });
        const blob = await response.blob();
        const disposition = response.headers.get("Content-Disposition") || "";
        const utf = /filename\*=UTF-8''([^;]+)/.exec(disposition);
        const plain = /filename="?([^";]+)"?/.exec(disposition);
        const link = h("a", { href: URL.createObjectURL(blob), download: utf ? decodeURIComponent(utf[1]) : plain ? plain[1] : `${S.project}-${kind}` });

        document.body.append(link);
        link.click();
        link.remove();
        // Временная ссылка держит файл в памяти страницы — освобождаем, когда скачивание уже началось
        setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    } catch (error) {
        // Сервер отказал или не ответил (программа закрыта и т. п.) — сообщение, а не тихая ошибка
        toast(error.message, true);
    } finally {
        button.disabled = false;
    }
}

// Кнопка «Скачать» выгрузки kind (download). kind — вид выгрузки или функция, которая
// возвращает его в момент нажатия (у вариантов поток выбирают уже после отрисовки).
// iconOnly — кнопка без подписи, только иконка (в окне «Экспортировать»).
function downloadButton(kind, iconOnly, disabled = false) {
    return btn(iconOnly ? "" : t("web.common.download"), (event) => download(typeof kind === "function" ? kind() : kind, event.currentTarget),
        { iconName: "download", kind: iconOnly ? "primary icon-only" : "primary block", disabled, title: iconOnly ? t("web.common.download") : null });
}

// Выгрузка вариантов потока: выбор потока (только те, у которых есть варианты) и кнопка.
// Возвращает [список выбора или пояснение «вариантов нет», кнопку]; iconOnly — кнопка без подписи
function variantsExport(iconOnly = false) {
    const stages = S.state.stages.filter((item) => item.variants);
    const preferred = recall("stage", null);
    let stage = stages.some((item) => item.key === preferred) ? preferred : stages[0]?.key;

    const chooser = stages.length
        ? select(stages.map((item) => [item.key, item.label]), stage, (value) => { stage = value; })
        : h("span", { style: { color: "var(--muted)", fontSize: "12.5px" } }, t("web.export_variants.none"));
    const button = downloadButton(() => `variants?stage=${encodeURIComponent(stage)}`, iconOnly, !stages.length);

    return [chooser, button];
}

// Выгрузки по порядку: обычные из EXPORTS, затем варианты потока, «Весь проект» — последним.
// row(iconName, label, hint, format, extra, button) рисует одну выгрузку; label и hint — ключи
// menu.main.tab.export.*, extra — выбор потока у вариантов (у остальных выгрузок null)
function exportItems(row, iconOnly) {
    const [chooser, button] = variantsExport(iconOnly);
    const item = ([kind, iconName, label, hint, format]) => row(iconName, label, hint, format, null, downloadButton(kind, iconOnly));

    return [
        ...EXPORTS.filter(([kind]) => kind !== "project").map(item),
        row("sparkles", "save_variants", "variants_hint", "XLSX", chooser, button),
        ...EXPORTS.filter(([kind]) => kind === "project").map(item),
    ];
}

// Окно «Экспортировать» на странице «Расписание»: те же выгрузки строками
function exportDialog() {
    const row = (iconName, label, hint, format, extra, button) => h("div", { class: "item-card inline" },
        iconTile(iconName, "small"),
        h("div", { class: "grow title-row" }, h("b", {}, t(`menu.main.tab.export.${label}`)), infoDot(t(`menu.main.tab.export.${hint}`))),
        extra,
        badge(format),
        button,
    );

    return dialog(t("web.export_button"), h("div", { class: "stack-sm" }, exportItems(row, true)), [[t("web.common.close"), null, "ghost"]], { width: 640 });
}

// Вкладка «Экспорт»: выгрузки плитками (.tile — как карточки проектов на стартовом экране,
// но не кнопки: скачивает только кнопка «Скачать» внизу плитки)
RENDERERS.export = (main) => {
    const row = (iconName, label, hint, format, extra, button) => h("div", { class: "tile" },
        h("div", { class: "p-top" },
            iconTile(iconName),
            h("div", { class: "grow" }, h("div", { class: "p-name title-row" }, t(`menu.main.tab.export.${label}`), infoDot(t(`menu.main.tab.export.${hint}`)))),
            badge(format),
        ),
        // Распорка: выбор потока и кнопка прижаты к низу плитки, даже если подписи разной длины
        h("span", { class: "grow" }),
        extra,
        button,
    );

    main.append(
        pageHead(t("menu.main.tab.export"), t("web.export.page_hint")),
        h("div", { class: "tile-grid" }, exportItems(row, false)),
    );
};

