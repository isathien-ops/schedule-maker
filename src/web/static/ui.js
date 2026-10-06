"use strict";

/* ============================================================================
   ui.js — строительные блоки интерфейса, не знающие о расписании: иконки,
   конструктор DOM h(), поля, кнопки, карточки, значки, аватары, всплывающее
   сообщение toast(), модальные окна и всплывающие подсказки «i».
   Цвета предметов и аватары преподавателей знают о расписании — они в domain.js.
   Берёт из других файлов: t (core.js).
   Отдаёт: icon, h, btn, select, dateInput, input, infoDot, withDot, badge, card,
   pageHead, empty, hash, initials, avatar, iconTile, formError, withTip, tipBadge,
   legendBadge, tabStrip, toast, dialog, confirmDialog, checkList.
   При загрузке вешает слушатели на document и window: отметка отправленных
   полей (change) и показ/скрытие подсказок.
   ============================================================================ */

// ---------------------------------------------------------------- иконки (контурные, сетка 24px)

// Контуры иконок: имя → SVG-путь (атрибут d) в сетке 24×24.
const ICONS = {
    sliders: "M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4",
    layers: "M12 2 2 7l10 5 10-5-10-5ZM2 17l10 5 10-5M2 12l10 5 10-5",
    users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
    play: "M7 4.5v15l12.5-7.5L7 4.5Z",
    sparkles: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3ZM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z",
    calendar: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z",
    bookmark: "M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16Z",
    download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
    upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
    plus: "M12 5v14M5 12h14",
    trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6",
    pencil: "M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3Z",
    check: "M20 6 9 17l-5-5",
    x: "M18 6 6 18M6 6l12 12",
    alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
    clock: "M12 6v6l4 2M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z",
    loader: "M21 12a9 9 0 1 1-6.2-8.6",
    back: "M19 12H5M12 19l-7-7 7-7",
    stop: "M7 7h10v10H7z",
    undo: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5",
    info: "M12 16v-4M12 8h.01M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z",
    minus: "M5 12h14",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10ZM9 12l2 2 4-4",
    copy: "M9 9h11v11H9zM5 15H4V4h11v1",
    pin: "M12 17v5M9 10.8V4h6v6.8l2 3.2H7l2-3.2Z",
    sheet: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6ZM14 2v6h6M8 13h8M8 17h8M12 13v8",
    archive: "M3 4h18v4H3zM5 8v12h14V8M10 12h4",
    logo: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2ZM8 14h3M8 17.5h6",
    ban: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM4.9 4.9l14.2 14.2",
    lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
    sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4",
    moon: "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z",
    monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
    // Два звена цепи: линейка идёт вместе с другим потоком, общий урок двух потоков
    link: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
};

// Создаёт SVG-иконку по имени из ICONS. cls — дополнительные CSS-классы
// (например "spin" для вращающегося индикатора). Неизвестное имя → пустая иконка.
function icon(name, cls = "") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");

    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", `icon ${cls}`);
    svg.setAttribute("aria-hidden", "true");
    path.setAttribute("d", ICONS[name] || "");
    svg.append(path);

    return svg;
}

// ---------------------------------------------------------------- помощники для построения страницы

// Главный «конструктор» DOM: h("div", {class: "x", onclick: f}, дети…).
// attrs:
//   on* (onclick, onchange…) — обработчики событий;
//   class, value, checked — задаются как свойства элемента;
//   style — строка или объект (поддерживаются CSS-переменные «--hue»);
//   остальные — атрибуты; true → пустой атрибут; null/undefined/false — пропускаются.
// children — узлы, строки, числа или (вложенные) массивы; null/undefined/false
// пропускаются, поэтому удобно писать «условие ? h(...) : null».
// Возвращает созданный элемент.
function h(tag, attrs, ...children) {
    const element = document.createElement(tag);

    for (const [key, value] of Object.entries(attrs || {})) {
        if (value === null || value === undefined || value === false) continue;

        if (key.startsWith("on")) element.addEventListener(key.slice(2).toLowerCase(), value);
        else if (key === "class") element.className = value;
        else if (key === "value") element.value = value;
        else if (key === "checked") element.checked = value;
        else if (key === "style" && typeof value === "object") {
            // CSS-переменные (например --hue) задаются только через setProperty
            for (const [name, item] of Object.entries(value)) {
                if (name.startsWith("--")) element.style.setProperty(name, item);
                else element.style[name] = item;
            }
        }
        else element.setAttribute(key, value === true ? "" : value);
    }

    for (const child of children.flat(Infinity)) {
        if (child === null || child === undefined || child === false) continue;
        element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }

    return element;
}

// Кнопка. kind — вид ("primary", "ghost", "danger", "icon-only", "block"… можно
// несколько через пробел), size — "sm"/"lg", iconName — иконка слева от текста,
// title — всплывающий текст браузера.
function btn(label, onclick, { kind = "", iconName = null, size = "", disabled = false, title = null } = {}) {
    return h("button", { class: `btn ${kind} ${size}`, onclick, disabled: disabled || null, title, type: "button" },
        iconName ? icon(iconName) : null, label);
}

// Выпадающий список. options — массив пар [значение, подпись]; value — выбранное
// (сравнение как строк); onchange(новое значение) — при выборе; attrs — доп. атрибуты.
function select(options, value, onchange, attrs = {}) {
    return h("select", { class: "select", onchange: (event) => onchange(event.target.value), ...attrs },
        options.map(([key, label]) => h("option", { value: key, selected: String(key) === String(value) || null }, label)));
}

// Поле даты. Дата сохраняется, когда поле теряет фокус или нажат Enter:
// пока дату набирают цифра за цифрой, промежуточные значения не отправляются.
// value — текущая дата «ГГГГ-ММ-ДД»; onsave(новая) вызывается, только если дата изменилась.
function dateInput(value, onsave) {
    const field = input({ type: "date", value });
    const save = () => { if (field.value && field.value !== value) onsave(field.value); };

    field.addEventListener("blur", save);
    field.addEventListener("keydown", (event) => event.key === "Enter" && field.blur());

    return field;
}

// Поле ввода с общим стилем; числовые поля (type="number") выравниваются вправо.
function input(attrs) {
    // data-rendered хранит значение, которое нарисовала страница: так render() отличает
    // набранную, но ещё не отправленную правку от того, что уже есть на сервере
    return h("input", { class: `input ${attrs.type === "number" ? "num" : ""}`, "data-rendered": String(attrs.value ?? ""), ...attrs });
}

// Поле, изменение которого уже ушло на сервер (событие change), помечается data-sent:
// при следующей перерисовке его значение берётся с сервера, а не из набранного текста.
// Слушатель на фазе перехвата (true), чтобы сработать раньше обработчиков самих полей.
document.addEventListener("change", (event) => {
    if (event.target?.dataset) event.target.dataset.sent = "1";
}, true);

// Круглая «i» рядом с подписью; пояснение text всплывает при наведении мыши
// или фокусе с клавиатуры (см. showTip в конце этого файла).
function infoDot(text) {
    return h("span", { class: "info-dot", tabindex: "0", role: "note", "aria-label": text, "data-tip": text }, "i");
}

// Заголовок с «i» на конце. Последнее слово и «i» склеены в неразрывный кусок,
// чтобы «i» не переносилась на новую строку одна. Без tip — просто text.
// Если text не строка (DOM-узел), «i» просто ставится после него.
function withDot(text, tip) {
    if (!tip) return text;
    if (typeof text !== "string") return [text, infoDot(tip)];

    const cut = text.lastIndexOf(" ") + 1;

    return [text.slice(0, cut), h("span", { class: "nowrap" }, text.slice(cut), infoDot(tip))];
}

// Значок-«таблетка». kind — цвет ("ok", "warn", "bad", "info", "accent"),
// dot — показать цветную точку перед текстом.
function badge(text, kind = "", dot = false) {
    return h("span", { class: `badge ${kind}` }, dot ? h("span", { class: "dot" }) : null, text);
}

// Карточка — основной блок страницы.
// title — заголовок (строка или узел), hint — пояснение в «i» у заголовка,
// actions — кнопки справа в шапке, foot — содержимое нижней полосы,
// flush — тело без внутренних отступов (для таблиц во всю ширину),
// cls — доп. класс карточки, body — содержимое.
function card({ title = null, hint = null, actions = null, foot = null, flush = false, cls = "" }, ...body) {
    return h("section", { class: `card ${cls}` },
        title || actions ? h("div", { class: "card-head" },
            h("div", { class: "grow" }, title ? h("h2", { class: "title-row" }, withDot(title, hint)) : (hint ? infoDot(hint) : null)),
            actions) : null,
        h("div", { class: `card-body ${flush ? "flush" : ""}` }, body),
        foot ? h("div", { class: "card-foot" }, foot) : null,
    );
}

// Шапка вкладки: крупный заголовок с «i»-пояснением и кнопки справа.
function pageHead(title, hint, actions = null) {
    return h("div", { class: "page-head" },
        h("div", { class: "titles" }, h("h1", { class: "title-row" }, withDot(title, hint))),
        actions ? h("div", { class: "actions" }, actions) : null,
    );
}

// Заглушка «пусто»: иконка, заголовок, пояснение и (необязательно) кнопка действия.
function empty(iconName, title, text, action = null) {
    return h("div", { class: "empty" },
        h("div", { class: "e-icon" }, icon(iconName)),
        h("div", { class: "e-title" }, title),
        text ? h("p", { class: "hint", style: { maxWidth: "420px" } }, text) : null,
        action,
    );
}

// Простой хеш строки (как в Java: value*31 + код символа), 32 бита без знака.
// Нужен, чтобы одно и то же имя всегда получало один и тот же цвет.
function hash(text) {
    let value = 0;

    for (const char of String(text)) value = (value * 31 + char.charCodeAt(0)) >>> 0;

    return value;
}

// Инициалы для аватара: первые буквы первых двух слов («Иванова Мария» → «ИМ»).
function initials(name) {
    return String(name).split(/[\s_]+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

// Круглый цветной аватар с инициалами. hue — оттенок; если не задан — из хеша имени.
// Сам цвет (насыщенность и яркость для светлой и тёмной темы) задаёт класс .hued в app.css
function avatar(name, cls = "avatar-sm", hue = null) {
    return h("span", { class: `${cls} hued`, style: { "--hue": hue ?? hash(name) % 360 } }, initials(name));
}

// Квадратная плитка с иконкой name на мягком фоне цвета акцента (карточки «Создание
// проекта», «Импорт проекта», выгрузки на «Экспорте»). cls — доп. класс (например,
// "small" — плитка поменьше для строк окна «Экспортировать»).
function iconTile(name, cls = "") {
    return h("span", { class: `avatar icon-tile ${cls}` }, icon(name));
}

// Строка для ошибки формы под полями (красный текст; пустая строка держит место,
// чтобы форма не прыгала). Текст ошибки пишут в её textContent.
function formError() {
    return h("p", { class: "hint form-error" });
}

// Добавляет элементу (кнопке, значку) всплывающее пояснение text — то же, что у «i»:
// оно появляется при наведении мыши или фокусе (см. showTip в конце файла).
// Возвращает сам элемент.
function withTip(element, text) {
    element.classList.add("has-tip");
    element.dataset.tip = text;

    return element;
}

// Значок легенды с подсказкой: при наведении/фокусе показывает tip — что означает этот цвет.
// Значок сам по себе не фокусируется, поэтому ему даётся tabIndex (подсказка с клавиатуры).
function tipBadge(text, kind, dot, tip) {
    const element = withTip(badge(text, kind, dot), tip);

    element.tabIndex = 0;

    return element;
}

// Значок легенды с иконкой слева и подсказкой tip (легенды таблиц на «Преподавателях»).
function legendBadge(text, kind, tip, iconName) {
    const element = tipBadge(text, kind, false, tip);

    element.prepend(icon(iconName));

    return element;
}

// Ряд вкладок-переключателей (.stage-tabs): этапы с датами на «Преподавателях»,
// варианты на «Предпросмотре». items — [{key, name, sub, cls}]: name — подпись (строка
// или узлы, например название со значками), sub — мелкая вторая строка (даты),
// cls — доп. класс кнопки. selected — ключ выбранной; onchange(ключ) вызывается при
// выборе другой вкладки.
function tabStrip(items, selected, onchange) {
    return h("div", { class: "stage-tabs", role: "tablist" }, items.map(({ key, name, sub = null, cls = "" }) => h("button", {
        class: `stage-tab ${key === selected ? "active" : ""} ${cls}`, role: "tab", "aria-selected": String(key === selected),
        onclick: () => key !== selected && onchange(key),
    }, h("span", { class: "t-name" }, name), sub ? h("span", { class: "t-dates" }, sub) : null)));
}

// Всплывающее сообщение внизу экрана (элемент #toast из index.html).
// Обычное держится 3,5 с, ошибка (isError) — 6 с; новое сообщение заменяет старое.
let toastTimer = null;

function toast(text, isError = false) {
    const box = document.getElementById("toast");

    box.replaceChildren(icon(isError ? "alert" : "check"), h("span", {}, text));
    box.className = isError ? "toast error-toast" : "toast";
    box.hidden = false;

    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (box.hidden = true), isError ? 6000 : 3500);
}

// ---------------------------------------------------------------- диалоговые окна

// Раскрыт ли сейчас какой-нибудь выпадающий список. Раскрытый список в оформлении программы
// (app.css, «настраиваемый select») — часть страницы, и нажатие Esc доходит до окна: без этой
// проверки Esc закрывал бы всё окно, а не только список. Браузер без псевдокласса :open
// бросает ошибку на таком селекторе — тогда список свой, браузерный, и Esc до окна не доходит.
function selectOpen() {
    try {
        return Boolean(document.querySelector("select:open"));
    } catch {
        return false;
    }
}

// Модальное окно. Возвращает Promise, который разрешается значением нажатой кнопки
// (или null при Esc / клике по затемнению). Окно может открыться поверх другого (вопрос
// «точно?» от сервера поверх окна «День и время»): тогда Esc закрывает только верхнее —
// как его «Отмена», а нижнее остаётся открытым с уже выбранными значениями.
// buttons — массив [подпись, значение, вид]. Значение может быть функцией (в т.ч.
// async): тогда окно закроется её результатом, а если она вернёт undefined —
// окно останется открытым (так диалоги не закрываются, если сервер вернул ошибку).
// width — ширина окна в пикселях. Первое поле ввода в окне сразу получает фокус.
function dialog(title, body, buttons, { width = null } = {}) {
    return new Promise((resolve) => {
        const close = (value) => {
            backdrop.remove();
            document.removeEventListener("keydown", onKey);
            resolve(value);
        };
        // Esc слушают все открытые окна; закрывается только верхнее — последнее затемнение
        // в документе (окна добавляются в конец body). Нижнее окно слушает Esc раньше
        // верхнего (подписалось первым) и в этот момент ещё видит верхнее над собой.
        // Esc при раскрытом выпадающем списке закрывает только список (selectOpen), а не окно
        const onKey = (event) => {
            if (event.key === "Escape" && !selectOpen() && backdrop === [...document.querySelectorAll(".backdrop")].pop()) close(null);
        };
        const backdrop = h("div", { class: "backdrop", onclick: (event) => event.target === backdrop && close(null) },
            h("div", { class: "dialog", role: "dialog", "aria-modal": "true", style: width ? { width: `min(${width}px, 100%)` } : null },
                h("div", { class: "dialog-head" }, h("h2", { style: { fontSize: "17px" } }, title)),
                h("div", { class: "dialog-body" }, body),
                h("div", { class: "dialog-foot" }, buttons.map(([label, value, kind]) => btn(label, async () => {
                    const result = typeof value === "function" ? await value() : value;
                    if (result !== undefined) close(result);
                }, { kind: kind || "" }))),
            ));

        document.addEventListener("keydown", onKey);
        document.body.append(backdrop);
        backdrop.querySelector(".dialog-body input, .dialog-body select")?.focus();
    });
}

// Окно «Подтвердите»: «Отмена» / «Да». danger — красная кнопка для необратимых
// действий, yes — своя подпись кнопки согласия. Разрешается true или false/null.
function confirmDialog(text, { danger = false, yes = null, title = null } = {}) {
    return dialog(title || t("web.common.confirm_title"), h("p", { class: "message" }, text), [
        [t("web.common.cancel"), false, "ghost"], [yes || t("web.common.yes"), true, danger ? "solid-danger" : "primary"],
    ], { width: 520 });
}

// Набор галочек. options — [[значение, подпись]], selected — отмеченные значения.
// У возвращаемого элемента есть метод values() — массив отмеченных значений.
function checkList(options, selected, cls = "") {
    const box = h("div", { class: `checks ${cls}` }, options.map(([value, label]) =>
        h("label", { class: "check" }, h("input", { type: "checkbox", value, checked: selected.includes(value) }), label)));

    box.values = () => [...box.querySelectorAll("input:checked")].map((item) => item.value);

    return box;
}

// ---------------------------------------------------------------- всплывающие подсказки «i»

/* Пояснение «i» (или значка легенды) — один общий элемент #tip, который висит над
   страницей рядом с «владельцем». Владелец — любой элемент с классом .info-dot или
   .has-tip и атрибутом data-tip; tipOwner — элемент, чья подсказка показана сейчас.
     showTip(event) — показывает подсказку владельца под указателем/в фокусе:
       ниже-правее него, а у правого/нижнего края окна — левее/выше; если страницу
       перерисовали под указателем, старая подсказка сначала убирается; чтение
       offsetWidth перезапускает CSS-анимацию появления.
     hideTip(event) — прячет подсказку, если указатель не ушёл внутрь того же
       владельца.
   Обработчики mouseover/focusin/mouseout/focusout висят на всём документе
   (делегирование), поэтому переживают любые перерисовки; прокрутка и изменение
   размера окна подсказку прячут. */
const tip = h("div", { id: "tip", role: "tooltip", hidden: true });
let tipOwner = null;

function showTip(event) {
    const owner = event.target.closest?.(".info-dot, .has-tip");

    // Страница перерисовалась под курсором: старое пояснение больше не к чему привязать — прячем его
    if (tipOwner && !tipOwner.isConnected) hideTip();

    if (!owner || owner === tipOwner || !owner.dataset.tip) return;

    if (!tip.isConnected) document.body.append(tip);

    tipOwner = owner;
    tip.textContent = owner.dataset.tip;
    tip.hidden = false;
    tip.classList.remove("shown");
    void tip.offsetWidth;
    tip.classList.add("shown");

    const box = owner.getBoundingClientRect();
    const gap = 8, edge = 12;
    const width = tip.offsetWidth, height = tip.offsetHeight;

    let left = box.left - gap;
    if (left + width > window.innerWidth - edge) left = box.right + gap - width;
    left = Math.max(edge, Math.min(left, window.innerWidth - edge - width));

    let top = box.bottom + gap;
    if (top + height > window.innerHeight - edge && box.top - gap - height >= edge) top = box.top - gap - height;

    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
}

function hideTip(event) {
    if (!tipOwner) return;
    if (event?.relatedTarget && tipOwner.contains(event.relatedTarget)) return;

    tipOwner = null;
    tip.hidden = true;
}

document.addEventListener("mouseover", showTip);
document.addEventListener("focusin", showTip);
document.addEventListener("mouseout", (event) => event.target.closest?.(".info-dot, .has-tip") === tipOwner && hideTip(event));
document.addEventListener("focusout", (event) => event.target === tipOwner && hideTip());
// Прокрутка прячет пояснение, только если сдвинулось то, где оно стоит (страница или окно с «i»).
// Журнал составления прокручивается сам каждую секунду — иначе пояснения пропадали бы сразу
document.addEventListener("scroll", (event) => {
    if (tipOwner && (event.target === document || event.target.contains?.(tipOwner))) hideTip();
}, true);
window.addEventListener("resize", () => hideTip());

