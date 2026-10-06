"use strict";

/* ============================================================================
   core.js — ядро страницы веб-приложения «Расписание занятий»: глобальное
   состояние S, меню и константы, события ядра HOOKS, тексты t(), tr() и
   fieldLabel(), запоминание вида (remember/recall), запросы к серверу api(), кеш
   отдельно загружаемых данных remoteCache() и очередь действий act()/doAct().
   Загружается первым.
   Берёт из других файлов (только внутри функций, при вызове): h, toast, dialog,
   confirmDialog (ui.js); render (shell.js); closeProject (projects.js).
   Отдаёт: S, NAV, TAB_ICONS, HOOKS, t, tr, fieldLabel, remember, recall,
   api, remoteCache, withoutActions (render() в shell.js), act; pendingActs читают
   браузерные тесты (tests/ui/base.py).

   КАК ЭТО УСТРОЕНО
   • Все данные и правила живут на локальном сервере (Flask, src/web/*.py;
     карта модулей — в шапке src/web/server.py).
     Страница сама ничего «по-настоящему» не решает: она показывает состояние
     проекта и отправляет на сервер «действия» (actions).
   • Каждое изменение — действие: act("setHours", {...}) → POST
     /api/project/<имя>/action → сервер проверяет правила, сохраняет проект и
     возвращает свежее состояние целиком (`state`). Страница кладёт его в
     S.state и заново рисует себя функцией render().
   • Перерисовка простая и «грубая»: каждый раз строится новое DOM-дерево через
     h(...) и целиком заменяет старое. Чтобы пользователю это не мешало,
     render() сохраняет прокрутку, фокус, позицию курсора и ещё не отправленный
     набранный текст.
   • Ядро не знает, что вкладки хранят у себя (черновики, кеши): вкладки сами
     подписываются на события HOOKS — «сервер ответил на действие», «проект
     закрыт» и «проект открыт». Новой вкладке с кешем не нужно править ни
     core.js, ни projects.js.
   • Тексты на странице берутся только из ru.hjson: t(ключ) — как есть, tr(ключ,
     {имя: значение}) — с подстановкой значений вместо «{имя}». Исключения — два
     мелких правила русского языка в domain.js: окончание слова после числа
     (pluralText; lessonsText — «1 урок», «2 урока», «5 уроков»; coursesText —
     «1 курс», «2 курса», «5 курсов») и союз « и » в списках курсов
     накладки (clashLabel, clashText; так же склеена подсказка накладки в таблице
     «Когда удобно» в tabs/teachers.js) и в списках номеров потоков общих уроков
     (andList: «1 и 2», «1, 2 и 3»). Решения страница принимает по данным и
     кодам сервера (поле code ошибки, level строки…), а не по тексту сообщений.

   ГЛАВНЫЕ СТРУКТУРЫ ДАННЫХ
   • S — глобальное состояние страницы:
       S.i18n    — тексты интерфейса: ключ → русская строка (из ru.hjson);
       S.meta    — справочник сервера (/api/meta, src/web/core.py) — постоянные
                   значения, которые страница не повторяет у себя: шаблоны своих
                   правил templates и виды их целей targets, число дней в сетке days
                   (0 — понедельник … 6 — воскресенье), ключ блока доп. курсов
                   extraBlock, короткие названия линеек shortLines, порядок весов
                   weightOrder, вес «Средне» своего правила mediumWeight;
       S.project — имя открытого проекта (null — показан стартовый экран);
       S.state   — состояние проекта с сервера: сетка уроков `grid`, курсы
                   `courses`, преподаватели `teachers`, этапы `stages`,
                   принятое расписание `answer`, веса `weights`, версии
                   `versions`, задача сборки `job`, конфликты `clashes` и т.д.;
       S.tab     — открытая вкладка (ключ из NAV);
       S.ui      — мелкие настройки вида (выбранный поток, преподаватель,
                   вариант…); часть запоминается в localStorage (remember/recall).
   • Термины предметной области:
       поток («Поток 1», «Поток 2»…) — группа курсов с общими датами; в коде
         поток — это «этап» (stage) с числовым ключом "1", "2"…; кроме потоков
         есть «блоки» без потока (доп. курсы, май, лето: "extra", "may", "summer");
         на вкладке «Курсы» потоки и блоки вместе называются sections;
       линейка (line) — экзамен или класс внутри потока: ОГЭ, ЕГЭ основной,
         ЕГЭ продвинутый, 10 класс, 8 класс; у блоков без потока свои линейки
         (у доп. курсов — «Семинар ОГЭ», «Семинар ЕГЭ продвинутый»; их общая
         программа называется «Семинары»);
       курс — один предмет одной линейки, имя вида «Поток 1 — ОГЭ — Математика»
         (у доп. курса — «Семинар ОГЭ: Математика»);
       варианты — расписания этапа, которые составил решатель solve.exe;
       принятое расписание (answer.json, S.state.answer) — выбранный вариант,
         ставший рабочим расписанием;
       закреплённые уроки (pinned) — время урока, заданное вручную;
       «курс уже идёт» (course.started, courseStarted на сервере) — дата начала
         наступила и у курса есть уроки в принятом расписании: преподаватель и
         уже стоящие уроки больше не двигаются. У курса-источника «присоединяется»
         — по всей группе «источник + копии»: идёт копия — идёт и источник, а
         дата, с которой идут уроки, приходит в course.runningSince;
       «курс зафиксирован» (course.locked, courseLocked) — курс идёт и все его
         уроки расставлены: не меняется уже ничего, даже число часов.

   ФАЙЛЫ СТРАНИЦЫ (в порядке загрузки — так они перечислены в index.html)
   core.js           — ядро: S, меню, HOOKS, t()/tr(), remember/recall, api(),
                       remoteCache(), act()/doAct();
   ui.js             — блоки интерфейса, не знающие о расписании: иконки, h(),
                       поля, кнопки, карточки, значки, вкладки-переключатели,
                       всплывающее сообщение, модальные окна, подсказки «i»;
   domain.js         — помощники предметной области: дни, уроки и даты, цвета
                       предметов и линеек, курсы, этапы и их статусы, накладки,
                       «требует внимания», таблица недели weekTable();
   shell.js          — оболочка проекта: тема, RENDERERS, боковое меню, render();
   projects.js       — стартовый экран, открытие и закрытие проекта, адрес #проект;
   tabs/settings.js  — вкладка «Настройки»;
   tabs/classes.js   — вкладка «Курсы»;
   tabs/teachers.js  — вкладка «Преподаватели»;
   tabs/run.js       — вкладка «Запуск»;
   tabs/preview.js   — вкладка «Предпросмотр»;
   tabs/view.js      — вкладка «Расписание»;
   tabs/save.js      — вкладка «Версии»;
   tabs/export.js    — вкладка «Экспорт» и окно «Экспортировать»;
   app.js            — запуск страницы start(), загружается последним.
   Ключ вкладки (S.tab, menu.main.tab.<ключ> в ru.hjson) совпадает с именем файла
   tabs/<ключ>.js; на сервере ему соответствует src/web/tabs/<ключ>.py (кроме
   «Расписания»: его данные приходят в общем состоянии S.state).

   ПРАВИЛА
   Сборщика и ES-модулей нет: это обычные синхронные <script>, они выполняются
   строго по порядку и делят одну глобальную область (function и верхнеуровневые
   const/let одного файла видны всем остальным).
   1. Каждый файл начинается со строки "use strict"; — строгий режим действует
      только на свой скрипт.
   2. Имя верхнего уровня объявляется ровно в одном файле: повторный let или
      const — SyntaxError, и весь файл не загрузится.
   3. На верхнем уровне (то, что выполняется при загрузке) можно пользоваться
      только именами из более ранних файлов или из своего. Внутри функций можно
      звать и более поздние: функции вызываются уже после загрузки всех файлов.
      Нового кода верхнего уровня, кроме объявлений, RENDERERS.<ключ> = … и
      подписки HOOKS.<событие>.push(…), не добавлять. Новая вкладка — новая
      строка <script> перед app.js.
   4. Верхнеуровневый let и содержимое кешей меняются только в своём файле.
      Ядро (core.js) и стартовый экран (projects.js) чужие кеши не сбрасывают:
      вкладка подписывается на HOOKS и чистит своё сама. Владельцы: pendingActs,
      actQueue, redrawing — core.js; renderedTab — shell.js; gridDraft —
      tabs/settings.js; teacherCache — tabs/teachers.js; pollTimer — tabs/run.js;
      variantsCache, pickedStage — tabs/preview.js; tipOwner, toastTimer — ui.js.
   5. Окончания строк CRLF, кодировка UTF-8 без BOM.
   6. Вызывать функции других файлов можно (переходы openCourse, switchTab, окно
      exportDialog, скачивание download и общие помощники); чужие переменные не
      трогать (правило 4).
      Если вкладке нужно узнать, что случилось в другой вкладке (сборка закончилась,
      проект закрыт), она подписывается на событие HOOKS, а не ждёт прямого вызова.
   7. Зависимость только «вкладка → общие файлы»: ядро, ui.js, domain.js, shell.js
      и projects.js функций вкладок не зовут — вкладка подписывается на HOOKS
      или регистрирует отрисовщик в RENDERERS.
   Правила 1, 2, 4, 5, 7 и порядок файлов проверяет tests/test_page_files.py.
   ============================================================================ */

// Глобальное состояние страницы (подробно — в шапке файла).
const S = {
    i18n: {},
    meta: {},
    project: null,
    state: null,
    tab: "settings",
    ui: {},
};

// Боковое меню: три шага работы и вкладки каждого шага.
// «prepare» — подготовка данных, «build» — составление, «result» — результат.
const NAV = [
    ["prepare", ["settings", "classes", "teachers"]],
    ["build", ["run", "preview"]],
    ["result", ["view", "save", "export"]],
];

// Иконка для каждой вкладки бокового меню (ключи из ICONS).
const TAB_ICONS = {
    settings: "sliders", classes: "layers", teachers: "users",
    run: "play", preview: "sparkles",
    view: "calendar", save: "bookmark", export: "download",
};

// События ядра. Файл вкладки при загрузке подписывается: HOOKS.<событие>.push(функция).
//   afterAction({ ok, last }) — сервер ответил на действие act(): ok — действие прошло
//     (S.state уже новое), false — сервер отказал или не ответил; last — это последнее
//     действие в очереди (за ним больше ничего не ждёт);
//   projectClosed() — проект закрывают или открывают другой: всё, что вкладка
//     запомнила о прежнем проекте, нужно забыть;
//   projectOpened() — проект открыт и нарисован (S.state уже загружено);
//   buildFinished(job) — сборка вариантов закончилась (её видит pollJob в tabs/run.js;
//     S.state уже свежее): job — задача сборки с сервера (stage, saved, stopped…).
// Подписчики: tabs/settings.js (черновик сетки), tabs/teachers.js и tabs/preview.js (кеши) —
// projectClosed и afterAction; tabs/run.js — projectOpened (подхватить идущую сборку);
// tabs/preview.js — buildFinished (у этапа появились новые варианты: старые забыть).
const HOOKS = {
    afterAction: [],
    projectClosed: [],
    projectOpened: [],
    buildFinished: [],
};

// Перевод: текст интерфейса по ключу из ru.hjson. Если ключа нет,
// возвращается сам ключ — так пропущенный текст сразу виден на странице.
function t(key) {
    return S.i18n[key] ?? key;
}

// Место для значения в тексте ru.hjson: {имя}.
const PLACEHOLDER = /\{(\w+)\}/g;

// Текст по ключу с подставленными значениями: tr("web.project_deleted", { name }) —
// «{name}» в тексте заменяется на String(values.name). Пара на сервере —
// tr() в src/modules/translate.py, правила те же: подстановка идёт за один проход
// (фигурные скобки внутри подставленного значения, например в названии курса, не
// принимаются за новое место), а место, для которого значения нет, остаётся как есть.
function tr(key, values = {}) {
    return t(key).replace(PLACEHOLDER, (place, name) => (name in values ? String(values[name]) : place));
}

// Подпись поля по ключу без двоеточия на конце. Часть подписей в ru.hjson записана
// с «:» («Название:»), а на странице подпись стоит над полем или слева от него
// отдельным столбцом, и двоеточие там лишнее.
function fieldLabel(key) {
    return t(key).replace(/:$/, "");
}

// Запоминает настройку вида: в S.ui и в localStorage под ключом
// «schedule.<проект>.<key>», чтобы выбор сохранялся после перезагрузки страницы.
// Ошибки хранилища (приватный режим, запрет) молча игнорируются.
function remember(key, value) {
    S.ui[key] = value;

    try {
        localStorage.setItem(`schedule.${S.project}.${key}`, JSON.stringify(value));
    } catch (error) { /* storage may be unavailable */ }
}

// Достаёт настройку вида, сохранённую remember(): сначала из S.ui, потом из
// localStorage (и кэширует в S.ui). Если ничего нет — fallback.
function recall(key, fallback) {
    if (key in S.ui) return S.ui[key];

    try {
        const value = localStorage.getItem(`schedule.${S.project}.${key}`);
        if (value !== null) return (S.ui[key] = JSON.parse(value));
    } catch (error) { /* storage may be unavailable */ }

    return fallback;
}

// Запрос к серверу — единственное место, где страница зовёт fetch. options — как у fetch,
// но body передаётся объектом (здесь превращается в JSON) или FormData (уходит как есть,
// например файл архива при импорте проекта); raw: true — вернуть сам ответ fetch (Response),
// а не разобранный JSON: так скачиваются файлы выгрузок.
// Возвращает разобранный ответ (или Response при raw). При ошибке HTTP бросает Error с
// текстом из поля error ответа сервера (он уже на русском); у ошибки есть code — код из
// поля code ответа (например "no_project") или null: по коду страница решает, что делать,
// а текст только показывает. Если сервер не ответил совсем (программа закрыта), fetch
// бросает свою ошибку — её текст тоже можно показать человеку.
async function api(path, { raw = false, body, ...options } = {}) {
    const form = body instanceof FormData;
    const response = await fetch(path, {
        // Заголовок для FormData браузер ставит сам (с границей между частями)
        headers: form ? {} : { "Content-Type": "application/json" },
        ...options,
        body: form ? body : body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw Object.assign(new Error(data.error || response.statusText), { code: data.code ?? null });
    }

    return raw ? response : response.json().catch(() => ({}));
}

// ---------------------------------------------------------------- кеш данных, которые вкладка загружает отдельно

// Кеш ответов сервера, которые вкладка запрашивает отдельно от состояния проекта
// (подробности о преподавателе, варианты этапа). Все такие кеши устроены одинаково:
//   get(key)       — запись по ключу: ответ сервера, {error: текст} или undefined
//                    (ещё не загружено);
//   needsLoad(key) — записи нет или она устарела (stale);
//   load(key, url) — запрашивает url; пока идёт запрос этого ключа, второй не
//                    отправляется. Ответ (или {error}) кладётся в кеш, затем
//                    вызывается onLoaded() — обычно перерисовка вкладки;
//   markStale()    — все записи устарели (после действия): на экране остаются
//                    прежние данные, пока не придут свежие, и страница не «прыгает»;
//   forget()       — забыть всё (смена проекта); ответы на запросы, отправленные
//                    раньше, выбрасываются.
// Ответ на запрос, отправленный до последнего markStale(), уже может быть старым:
// он кладётся, но помеченным stale, и перечитывается при следующей отрисовке.
// Ошибку так не помечаем: при постоянной ошибке загрузка и перерисовка пошли бы
// по кругу; новая попытка будет после следующего действия.
function remoteCache(onLoaded) {
    const entries = new Map();
    const loading = new Set();
    // generation растёт с каждым forget(), version — с каждым markStale()
    let generation = 0;
    let version = 0;

    return {
        get: (key) => entries.get(key),
        needsLoad: (key) => !entries.has(key) || Boolean(entries.get(key).stale),

        markStale() {
            version += 1;
            for (const entry of entries.values()) entry.stale = true;
        },

        forget() {
            generation += 1;
            entries.clear();
            loading.clear();
        },

        async load(key, url) {
            if (loading.has(key)) return;

            loading.add(key);
            const asked = { generation, version };
            let entry;

            try {
                entry = await api(url);
            } catch (error) {
                entry = { error: error.message };
            }

            // Пока шёл запрос, проект закрыли или открыли другой: ответ чужой
            if (asked.generation !== generation) return;

            loading.delete(key);
            entry.stale = asked.version !== version && !entry.error;
            entries.set(key, entry);
            onLoaded();
        },
    };
}

// ---------------------------------------------------------------- действия (изменения на сервере)

// act(action, args) — главный способ что-то изменить в проекте. action — имя действия
// на сервере (например "setHours", "newTeacher", "accept"), args — его параметры.
// Возвращает Promise с ответом сервера или null, если действие не прошло / отменено
// или сервер вернул notice (окно с пояснением).
// Действия выполняются строго по очереди: второй клик или быстрая вторая правка
// ждут окончания первой и не теряются (actQueue — хвост этой очереди,
// pendingActs — сколько действий в очереди ещё не завершилось).
let actQueue = Promise.resolve();
let pendingActs = 0;
// Идёт замена DOM при перерисовке (см. withoutActions): действия не отправляются
let redrawing = false;

// Выполняет replace() — замену DOM при перерисовке (render() в shell.js) — так, что
// act() на это время ничего не отправляет: старые поля, теряя фокус, присылают
// blur/change, но это не правки пользователя.
function withoutActions(replace) {
    redrawing = true;

    try {
        replace();
    } finally {
        redrawing = false;
    }
}

function act(action, args = {}) {
    // Если поле потеряло фокус из-за перерисовки страницы (а не из-за пользователя),
    // его change — не правка: ничего не отправляем
    if (redrawing) return Promise.resolve(null);

    pendingActs += 1;
    const next = actQueue.then(() => doAct(action, args)).finally(() => { pendingActs -= 1; });
    actQueue = next.catch(() => null);

    return next;
}

// Сообщает подписчикам HOOKS.afterAction, что сервер ответил на действие
// (ok — действие прошло; last — в очереди act() оно последнее).
function afterAction(ok) {
    const last = pendingActs <= 1;

    HOOKS.afterAction.forEach((hook) => hook({ ok, last }));
}

// Ошибка error от api() значит «проекта больше нет» (его удалили в другой вкладке браузера).
// Узнаётся по коду ответа сервера "no_project" (src/web/project.py, projectPath).
function isProjectGone(error) {
    return error.code === "no_project";
}

// Выполняет одно действие из очереди act(). Что может вернуть сервер:
//   state   — новое состояние проекта (всегда при успехе);
//   notice  — важное сообщение: показывается в окне, которое надо закрыть;
//   confirm — вопрос «точно?» (с danger/yes для вида кнопки): при согласии
//             действие повторяется с args.force = true («всё равно сделать»);
//   message — короткое сообщение об успехе (всплывающее).
// После ответа страница перерисовывается. Возвращает ответ сервера или null.
// Побочные эффекты: меняет S.state и сообщает вкладкам об ответе (afterAction).
async function doAct(action, args) {
    try {
        const result = await api(`/api/project/${encodeURIComponent(S.project)}/action`, { method: "POST", body: { action, args } });

        S.state = result.state;
        afterAction(true);

        if (result.notice) {
            render();
            await dialog(t("web.common.notice_title"), h("p", { class: "message" }, result.notice), [[t("web.common.ok"), true, "primary"]], { width: 560 });
            return null;
        }

        if (result.confirm) {
            if (await confirmDialog(result.confirm, { danger: result.danger, yes: result.yes })) return doAct(action, { ...args, force: true });

            render();
            return null;
        } else if (result.message) {
            toast(result.message);
        }

        render();

        return result;
    } catch (error) {
        // Проект удалили в другой вкладке браузера: возвращаемся к списку проектов
        if (isProjectGone(error)) {
            closeProject();
            toast(error.message, true);
            return null;
        }

        afterAction(false);
        toast(error.message, true);
        render();

        return null;
    }
}
