"use strict";

/* ============================================================================
   tabs/preview.js — вкладка «Предпросмотр»: загрузка вариантов этапа (кеш
   variantsCache), таблица сравнения, принятие и отклонение варианта, карточка
   «Что не получилось» и неделя выбранного варианта.
   Пара на сервере — src/web/tabs/preview.py.
   Берёт из других файлов: S, HOOKS, t, tr, act, recall, remember, remoteCache
   (core.js); элементы интерфейса из ui.js; shortLine, courseByName,
   currentStage, lessonEntries, lessonsText, coursesText, shortCourse, slotKey, stageSwitch, subjectHue,
   surnames, weekTable, isJointCopy, jointNote (domain.js); RENDERERS, render, switchTab (shell.js);
   download (tabs/export.js — по нажатию кнопки).
   Отдаёт: RENDERERS.preview.
   При загрузке подписывается на HOOKS: после каждого успешного действия варианты
   устаревают; при закрытии проекта и когда сборка закончилась (buildFinished — у
   этапа появились новые варианты) — забываются.

   Вкладка собирается из карточек: variantsCard (таблица сравнения variantsTable с блоком
   «Кто ведёт» teachersFoot, пометки variantNotes, значок общих уроков jointBadge), problemsCard и
   variantWeekCard (неделя варианта stageWeek с меткой «новый преподаватель» teacherLabel,
   кнопки acceptButton и rejectButton). Кто из преподавателей сменился, считает сервер
   (поля teachers и teacherChanges — src/web/ranking.py, teacherCourses — variants.teacherCourses);
   страница только показывает. Так же и с вариантом, составленным до начала курсов, которые
   уже идут (поле staleStarted — stages.staleStarted), и с вариантом, который сдвинул урок курса,
   шедшего уже при сборке (поле movedStarted — stages.movedStarted, с причиной): сервер его не примет,
   страница показывает пометку и не даёт нажать «Принять» (staleText).
   ============================================================================ */

// ---------------------------------------------------------------- загруженные варианты

// Варианты этапа по его ключу: метрики, расписания, проблемы, метка сборки build
// (GET /variants). Загружаются отдельно от состояния проекта; когда приходят, открытый
// «Предпросмотр» перерисовывается. После действия (отклонить, принять, поменять пары
// в «Настройках»…) на экране остаются прежние варианты, пока не придут свежие:
// страница не укорачивается и не прыгает наверх.
const variantsCache = remoteCache(() => { if (S.tab === "preview") render(); });

HOOKS.afterAction.push(({ ok }) => { if (ok) variantsCache.markStale(); });
HOOKS.projectClosed.push(() => { variantsCache.forget(); pickedStage = null; });
HOOKS.buildFinished.push(() => { variantsCache.forget(); pickedStage = null; });

// Поток, который человек сам выбрал переключателем на «Предпросмотре» (null — не выбирал).
// Пока он задан и совпадает с потоком, выбранным на всех вкладках (currentStage),
// «Предпросмотр» не перескакивает сам на поток с непринятыми вариантами. Выбор потока
// на «Запуске» или «Преподавателях» его отменяет. Сбрасывается, когда закончилась новая
// сборка (показать её варианты) и при смене проекта.
let pickedStage = null;

// Варианты этапа stage из кеша (undefined — ещё не загружены; {error} — не загрузились).
// Если их нет или они устарели — запрашивает; страница перерисуется, когда придут.
function stageVariants(stage) {
    if (variantsCache.needsLoad(stage)) variantsCache.load(stage, `/api/project/${encodeURIComponent(S.project)}/variants?stage=${encodeURIComponent(stage)}`);

    return variantsCache.get(stage);
}

// ---------------------------------------------------------------- вкладка «Предпросмотр» (сравнение вариантов)

// Вкладка «Предпросмотр»: таблица сравнения вариантов этапа (сумма штрафов и
// нарушения по каждому правилу), кнопка «Принять вариант N», список проблем
// (недорасставленные уроки) и неделя выбранного варианта; уроки, которых нет
// в принятом расписании, обведены пунктиром.
RENDERERS.preview = (main) => {
    const stages = S.state.stages.filter((item) => item.variants);

    main.append(pageHead(t("menu.main.tab.preview"), t("menu.main.tab.preview.hint")));

    if (!stages.length) {
        main.append(card({}, empty("sparkles", t("web.preview.empty_title"), t("menu.main.tab.preview.empty"),
            btn(t("web.preview.go_run"), () => switchTab("run"), { iconName: "play", kind: "primary" }))));
        return;
    }

    const stage = previewStage(stages);
    const data = stageVariants(stage);

    // Варианты этого этапа ещё не загружены: показываем «Загрузка…»
    if (!data) {
        main.append(card({}, empty("clock", t("web.common.loading"), null)));
        return;
    }

    // Варианты не загрузились (сервер вернул ошибку или не ответил): показываем текст ошибки.
    // Новая попытка будет после любого действия или при выборе другого этапа (см. remoteCache).
    if (data.error) {
        main.append(card({}, empty("alert", data.error, null)));
        return;
    }

    const selected = selectedVariant(data);
    const chosen = data.variants.find((item) => item.number === selected);

    main.append(h("div", { class: "stack", style: { gap: "20px" } },
        variantsCard(data, stage, selected),
        chosen?.problems?.length ? problemsCard(chosen.problems, data.limit) : null,
        chosen ? variantWeekCard(data, stage, chosen) : null,
    ));

    // Строка дней недели прилипает сразу под шапкой недели: её высота зависит от ширины окна
    requestAnimationFrame(() => {
        const head = main.querySelector(".week-head");
        if (head) main.querySelector(".preview-week").style.setProperty("--week-head", `${head.offsetHeight}px`);
    });
};

// Этап, варианты которого показываются (stages — этапы, у которых варианты есть).
// Выбранный вручную переключателем (pickedStage), пока его не сменили на другой вкладке, —
// главнее всего. Иначе выбранный на других вкладках (currentStage), если у него есть варианты,
// а если он уже составлен и у другого этапа есть непринятые варианты — тот (например, сразу
// после составления потока).
function previewStage(stages) {
    let stage = currentStage();

    if (pickedStage === stage && stages.some((item) => item.key === stage)) return stage;

    if (!stages.some((item) => item.key === stage)) stage = stages[0].key;

    const waiting = stages.find((item) => !item.built);

    if (S.state.stages.find((item) => item.key === stage)?.built && waiting) stage = waiting.key;

    return stage;
}

// Номер выбранного варианта: запомненный (S.ui.previewVariant), иначе принятый,
// иначе лучший, иначе первый, который можно принять (без staleStarted и movedStarted), иначе первый.
// Лучший вариант (best) и «ничью» (tied — у нескольких не отклонённых вариантов та же оценка,
// что у лучшего) отмечает сервер (variants.rankVariants; вариант, который принять нельзя,
// лучшим не бывает): страница их только показывает.
function selectedVariant(data) {
    const numbers = data.variants.map((item) => item.number);
    const selected = S.ui.previewVariant;

    if (numbers.includes(selected)) return selected;

    return data.variants.find((item) => item.accepted)?.number
        ?? data.variants.find((item) => item.best)?.number
        ?? data.variants.find((item) => !unacceptable(item))?.number
        ?? numbers[0];
}

// Выбрать вариант number (клик по столбцу таблицы или по вкладке над неделей).
function pickVariant(number) {
    S.ui.previewVariant = number;
    render();
}

// Значки варианта: «принят» (вариант сейчас в расписании), «как сейчас» (совпадает с
// принятым расписанием, но сам не принят), «лучший» (если не «ничья»), «отклонён»,
// «нельзя принять» (unacceptable; та же пометка, что в шапке листа «Сравнение» в Excel,
// export.variantsWorkbook).
// dot — у «принят» цветная точка (в шапке таблицы; во вкладках над неделей — без неё).
function variantBadges(item, dot) {
    return [
        item.accepted ? badge(t("menu.main.tab.preview.accepted"), "ok", dot) : null,
        item.same ? badge(t("web.preview.same"), "") : null,
        item.best && !item.tied ? badge(t("menu.main.tab.preview.best"), "warn") : null,
        item.rejected ? badge(t("web.preview.rejected"), "") : null,
        unacceptable(item) ? badge(t("web.export_variants.stale"), "bad") : null,
    ];
}

// Вариант item принять нельзя (как variants.unacceptable на сервере): он составлен до начала курсов,
// которые уже идут (непустой staleStarted), или сдвинул урок курса, шедшего уже при сборке (movedStarted).
function unacceptable(item) {
    return Boolean(item.staleStarted?.length || item.movedStarted?.length);
}

// Таблица сравнения: правила — строки, варианты — столбцы; клик в любом месте столбца
// выбирает этот вариант. Первая строка — общая сумма штрафов, дальше — каждое правило
// (свои правила пользователя — после правил программы), под правилами — блок «Кто ведёт»
// (teachersFoot), если варианты различаются преподавателями.
// Строка правила — {key} у правила программы (ключ метрики из data.metrics) или
// {penalty} у своего правила (элемент data.penalties; его число — metrics.custom[id]).
function variantsTable(data, selected) {
    const rules = [...data.metrics.map((key) => ({ key })), ...data.penalties.map((penalty) => ({ penalty }))];

    // Атрибуты ячейки столбца варианта item; extra — доп. классы
    const pick = (item, extra) => ({
        class: `pick ${item.number === selected ? "selected" : ""} ${item.rejected ? "rejected" : ""} ${extra}`,
        onclick: () => pickVariant(item.number),
    });
    // Подпись строки: название правила и «i» с пояснением
    const ruleLabel = ({ key, penalty }) => {
        const [name, hint] = penalty
            ? [penalty.name, `${penalty.description} — ${penalty.weight} ${t("penalty.each")}`]
            : [t(`menu.main.tab.preview.column.${key}`).replace(/\n/g, " "), t(`menu.main.tab.preview.column_hint.${key}`)];

        return h("th", { class: "rule" }, h("span", { class: "title-row" }, name, infoDot(hint)));
    };
    // Ячейка метрики: нарушение жёсткого правила — красный значок, ноль — бледным
    const metric = (item, { key, penalty }) => {
        const value = penalty ? item.metrics.custom[penalty.id] ?? 0 : item.metrics[key];
        const hard = !penalty && data.hard.includes(key) && value;

        return h("td", pick(item, `center ${hard ? "metric-bad" : value ? "" : "metric-zero"}`), hard ? h("span", { class: "badge bad" }, icon("alert"), value) : value);
    };

    return h("div", { class: "table-wrap" }, h("table", { class: "data variants" },
        h("thead", {}, h("tr", {},
            h("th", { class: "rule" }, h("span", { class: "title-row" }, t("web.preview.rules"), infoDot(t("menu.main.tab.preview.column_hint.state")))),
            data.variants.map((item) => h("th", pick(item, "center variant-head"),
                h("span", { class: "v-name" }, `${t("menu.main.tab.run.variant")} ${item.number}`),
                h("span", { class: "v-badges" }, variantBadges(item, true)),
            )),
        )),
        h("tbody", {},
            h("tr", { class: "total-row" },
                ruleLabel({ key: "total" }),
                data.variants.map((item) => h("td", pick(item, "center"), h("b", {}, item.metrics.total.toLocaleString("ru-RU")),
                    item.tied ? h("span", { class: "tie-note" }, t("menu.main.tab.preview.equal")) : null)),
            ),
            rules.map((rule) => h("tr", {}, ruleLabel(rule), data.variants.map((item) => metric(item, rule)))),
        ),
        teachersFoot(data, pick),
    ));
}

// Блок «Кто ведёт» под правилами таблицы сравнения: строка на каждый курс, у которого преподаватель
// различается между вариантами или с принятым расписанием (data.teacherCourses), в ячейке —
// фамилии из item.teachers. Если курс есть в item.teacherChanges (в варианте его ведёт не тот,
// кто в принятом расписании), ячейка выделена, а в подсказке — кто ведёт сейчас.
// У заголовка блока «i»: что значит жёлтая ячейка (как пояснения у строк правил, ruleLabel).
// Блок — отдельный tfoot: в tbody остаются только правила. Таких курсов нет — блока нет (null).
// pick(item, extra) — атрибуты ячейки столбца варианта (variantsTable).
function teachersFoot(data, pick) {
    const courses = data.teacherCourses || [];

    if (!courses.length) return null;

    // Ячейка курса course в столбце варианта item
    const cell = (item, course) => {
        const changes = (item.teacherChanges || []).filter((change) => change.course === course);
        const element = h("td", pick(item, `center ${changes.length ? "teacher-changed" : ""}`), surnames(item.teachers?.[course] || []));

        if (!changes.length) return element;

        element.tabIndex = 0;

        return withTip(element, tr("web.preview.teacher_now", { teacher: surnames([...new Set(changes.flatMap((change) => change.before))]) }));
    };

    return h("tfoot", { class: "teachers" },
        h("tr", { class: "group-row" },
            h("th", { class: "rule" }, h("span", { class: "title-row" }, t("web.preview.teachers_head"), infoDot(t("web.preview.teachers_hint")))),
            data.variants.map((item) => h("td", pick(item, "")))),
        courses.map((course) => h("tr", {}, h("th", { class: "rule" }, shortCourse(course)), data.variants.map((item) => cell(item, course)))),
    );
}

// Пометки под таблицей про выбранный вариант chosen: в расписании, сколько уроков не
// расставлено, все варианты одинаковы, сколько уроков сдвинется (и общих уроков в
// потоках-копиях — jointMoved с сервера), у скольких курсов сменится преподаватель
// (разные курсы в teacherChanges с сервера), есть ли у курсов два урока в один день
// (metrics.equalLessons), нельзя ли его принять (staleText: составлен до начала идущих курсов или
// сдвинул урок курса, который уже идёт). У такого варианта пометок «если принять…» (переезд уроков, общие уроки,
// смена преподавателя) нет: принять его нельзя. Его пометка длинная (список курсов) и переносится
// по строкам (класс wrap), а не уходит за край карточки.
// «У всех вариантов одинаковая оценка неудобств — можно принять любой» решает сервер (поле allTied, variants.allTied:
// сравнивается полная оценка — сначала обязательные правила, потом сумма штрафов); страница
// сама варианты не сравнивает.
function variantNotes(chosen, data) {
    const notes = [];
    const stale = staleText(chosen);
    // Пометки о том, что будет после принятия, — только у варианта, который можно принять
    const acceptable = !chosen?.accepted && !stale;

    if (chosen?.accepted) notes.push(badge(t("menu.main.tab.preview.in_schedule"), "ok", true));
    if (chosen?.metrics.missing) notes.push(badge(tr("menu.main.tab.preview.has_missing", { count: chosen.metrics.missing }), "bad"));
    if (data.allTied) notes.push(badge(t("web.preview.all_equal"), "", true));
    if (chosen?.moved && acceptable) notes.push(badge(tr("web.preview.moved", { lessons: lessonsText(chosen.moved) }), "warn", true));
    // Вариант потока-источника двигает общие уроки: если принять вариант, уроки потоков-копий
    // (линеек, присоединённых к этому потоку) тоже переедут — по отметке на каждую такую линейку
    (stale ? [] : chosen?.jointMoved || []).forEach(({ line, number }) => notes.push(jointBadge(tr("web.preview.joint_moves", { line, number }))));
    if (chosen?.teacherChanges?.length && acceptable) {
        const count = new Set(chosen.teacherChanges.map((change) => change.course)).size;

        notes.push(badge(tr("web.preview.teacher_changes", { count: coursesText(count) }), "warn", true));
    }
    if (chosen?.metrics.equalLessons) notes.push(badge(tr("menu.main.tab.preview.has_doubles", { count: chosen.metrics.equalLessons }), "bad"));

    if (stale) notes.push(badge(stale, "bad wrap", true));

    return notes;
}

// Почему вариант chosen нельзя принять:
// * его составили, когда курсы, которые уже идут, ещё не начались, и он поменял бы им время уроков
//   или преподавателя (поле staleStarted, stages.staleStarted; web.preview.stale_started);
// * курсы шли уже при сборке, но программа не смогла оставить их уроки как в расписании (поле movedStarted,
//   stages.movedStarted: курс и строки «день и час: причина»; web.preview.moved_started).
// Это те же курсы, с которыми сервер откажет в принятии (web.error.variant_stale_started,
// web.error.variant_moved_started). Курсы — короткими подписями (как в блоке «Кто ведёт»), через «;»:
// в самой подписи уже есть запятые. Причины (одна или обе) — внутри одной фразы web.preview.cannot_accept
// («Этот вариант нельзя принять: …» один раз). null — вариант принять можно.
// Текст — и пометка под таблицей (variantNotes), и подсказка у неактивной «Принять» (acceptButton).
function staleText(chosen) {
    const courses = chosen?.staleStarted || [];
    const moved = (chosen?.movedStarted || []).flatMap(({ course, lines }) => lines.map((line) => `${shortCourse(course)} — ${line}`));
    const reasons = [
        courses.length ? tr("web.preview.stale_started", { courses: courses.map(shortCourse).join("; ") }) : null,
        moved.length ? tr("web.preview.moved_started", { lessons: moved.join("; ") }) : null,
    ].filter(Boolean);

    return reasons.length ? tr("web.preview.cannot_accept", { reasons: reasons.join("; ") }) : null;
}

// Жёлтый значок со значком цепи — пометка про общие уроки потоков (variantNotes).
function jointBadge(text) {
    const element = badge(text, "warn");

    element.prepend(icon("link"));

    return element;
}

// Кнопка «Скачать варианты» этапа stage: все варианты потока в Excel (сравнение и неделя
// каждого варианта). Формат файла — такой же меткой, как на вкладке «Экспорт».
function variantsDownload(stage) {
    const button = btn(t("web.export_variants.button"), (event) => download(`variants?stage=${encodeURIComponent(stage)}`, event.currentTarget), { iconName: "download" });

    button.append(badge("XLSX"));

    return button;
}

// Карточка «Варианты»: выбор этапа, таблица сравнения, внизу — пометки про выбранный
// вариант и «Скачать варианты». «Принять» и «Отклонить» — только в шапке недели ниже,
// чтобы не было двух одинаковых кнопок.
function variantsCard(data, stage, selected) {
    const chosen = data.variants.find((item) => item.number === selected);

    return card({
        title: t("web.preview.variants"),
        actions: stageSwitch(stage, (key) => { pickedStage = key; remember("stage", key); S.ui.previewVariant = null; render(); }, (item) => item.variants),
        flush: true,
        foot: [variantNotes(chosen, data), h("span", { class: "grow" }), variantsDownload(stage)],
    }, variantsTable(data, selected));
}

// «Принять вариант N»: вариант chosen становится принятым расписанием (answer.json).
// data.build — метка сборки, чтобы сервер не принял вариант из устаревшего набора.
// Вариант, составленный до начала идущих курсов (staleText), сервер не примет даже после
// вопроса «точно?»: кнопка неактивна, в подсказке — почему и что сделать.
function acceptButton(data, stage, chosen) {
    const stale = staleText(chosen);

    return withTip(btn(`${t("menu.main.tab.preview.accept")} ${chosen.number}`, async () => {
        const number = chosen.number;

        if (!await act("accept", { stage, number, build: data.build })) return;

        toast(tr("web.preview.accepted_toast", { number }));
        render();
    }, { iconName: "check", kind: "primary", disabled: chosen.accepted || chosen.rejected || Boolean(stale) }),
    stale || tr("web.preview.accept_hint", { number: chosen.number }));
}

// «Отклонить»: вариант больше не нужно разбирать — он бледнеет, а выбор переходит
// на следующий не отклонённый. У отклонённого — «Вернуть» (снять отметку).
// У принятого варианта кнопки нет (null).
function rejectButton(data, stage, chosen) {
    if (chosen.accepted) return null;

    return withTip(btn(t(chosen.rejected ? "web.preview.unreject" : "web.preview.reject"), async () => {
        const number = chosen.number;
        const next = data.variants.find((item) => !item.rejected && item.number !== number)?.number;

        if (!await act("rejectVariant", { stage, number, rejected: !chosen.rejected })) return;
        if (!chosen.rejected && next !== undefined) S.ui.previewVariant = next;
        render();
    }, { iconName: chosen.rejected ? "undo" : "ban", kind: chosen.rejected ? "" : "reject" }), t(chosen.rejected ? "web.preview.unreject_hint" : "web.preview.reject_hint"));
}

// Карточка «Неделя — вариант N» для выбранного варианта chosen. Её шапка (выбор варианта,
// «Принять», «Отклонить», выбор линейки) и строка с днями недели прилипают к верху экрана:
// варианты можно переключать, не прокручивая страницу.
function variantWeekCard(data, stage, chosen) {
    // Отмечать «новые» уроки есть смысл, только если что-то из этих курсов уже есть
    // в принятом расписании и сам вариант ещё не принят. Курсы-копии (линейка присоединена к
    // более раннему потоку) не в счёт: они в принятом расписании всегда, как только принят
    // поток-источник, — иначе у ещё не составленного потока все его уроки были бы «новыми»
    const anyFresh = !chosen.accepted && Object.keys(chosen.answer).some((name) => S.state.answer[name] && !isJointCopy(courseByName(name)));
    // Линейки курсов варианта (в порядке курсов этапа) — для выбора «показать только одну»
    const order = S.state.stages.find((item) => item.key === stage)?.courses || [];
    const weekLines = [...new Set([...order.filter((name) => chosen.answer[name]), ...Object.keys(chosen.answer)]
        .map((name) => courseByName(name)?.line).filter(Boolean))];
    const remembered = recall(`previewLine.${stage}`, "");
    const onlyLine = weekLines.includes(remembered) ? remembered : "";
    const variantName = (item) => `${t("menu.main.tab.run.variant")} ${item.number}`;
    const tabs = tabStrip(data.variants.map((item) => ({
        key: item.number, name: [variantName(item), variantBadges(item, false)], cls: item.rejected ? "rejected" : "",
    })), chosen.number, pickVariant);

    return h("section", { class: "card preview-week" },
        h("div", { class: "card-head week-head" },
            h("h2", { class: "grow title-row" }, `${t("web.preview.week")} — ${variantName(chosen)}`),
            tabs,
            acceptButton(data, stage, chosen),
            rejectButton(data, stage, chosen),
            // Только одна линейка или все сразу (запоминается для каждого потока)
            weekLines.length > 1 ? h("div", { class: "line-filter" },
                h("span", { class: "line-filter-label" }, t("web.preview.show_line")),
                ["", ...weekLines].map((line) => h("button", {
                    class: `line-chip ${line === onlyLine ? "active" : ""}`, "aria-pressed": String(line === onlyLine),
                    onclick: () => { remember(`previewLine.${stage}`, line); render(); },
                }, line || t("web.preview.all_lines")))) : null),
        h("div", { class: "card-body flush" },
            anyFresh ? h("div", { class: "fresh-legend" }, h("span", { class: "fresh-sample" }), t("web.preview.fresh_hint")) : null,
            stageWeek(chosen.answer, anyFresh ? S.state.answer : null, chosen.issues || {}, onlyLine, chosen.teacherChanges || [])));
}

// Карточка «Что не получилось поставить»: курсы варианта, которым не хватило уроков, с причиной
// (reason → текст web.problem.<reason>) и советом, что сделать (<reason>_todo).
// В teachers элемент может быть [имя, свободных часов] или просто строкой. У причины
// "joint_waiting" (копия ждёт свой поток-источник) есть number — номер этого потока.
function problemsCard(problems, limit) {
    const teacherList = (teachers) => teachers.map((item) => Array.isArray(item)
        ? tr("web.problem.free_hours", { name: item[0], count: item[1] })
        : item).join(", ");

    return card({ title: t("web.problem.title"), hint: t("web.problem.hint") }, h("div", { class: "stack-sm" }, problems.map((problem) => {
        const why = tr(`web.problem.${problem.reason}`, { teachers: teacherList(problem.teachers), limit, subject: problem.subject, number: problem.number });
        const todo = tr(`web.problem.${problem.reason}_todo`, { subject: problem.subject, number: problem.number });

        return h("div", { class: "item-card" },
            h("div", { class: "top" },
                h("span", { class: "name" }, problem.course),
                badge(tr("web.problem.missing", { missing: problem.expected - problem.placed, expected: problem.expected }), "bad"),
            ),
            h("p", { style: { margin: 0 } }, why),
            h("p", { class: "hint", style: { display: "flex", gap: "6px" } }, icon("info"), todo),
        );
    })));
}

// Вся неделя этапа: каждый урок — карточка в цвете своего предмета.
// answer — расписание варианта (как answer.json: {курс: [дни][уроки] → ячейка}).
// accepted — текущее принятое расписание; если передано, уроки, которых в нём
// не было, помечаются как новые (fresh — пунктирная рамка). Уроки копий (линейка идёт вместе
// с более ранним потоком) и их источников подписаны jointNote; копия новой не бывает.
// issues — {курс: {"день-урок": [подпись]}} (variants.lessonIssues на сервере): что не так с уроком,
// пишется на карточке под преподавателем; подпись — строка (проблема) или {text, level: "warn"};
// onlyLine — показать уроки только этой линейки ("" — все);
// changes — teacherChanges варианта с сервера ([{course, subject, before, after}]): у уроков этих
// курсов по этому предмету первой подписью идёт метка «новый преподаватель» (teacherLabel).
// Копий в changes нет: их уроки идут за источником, метки у них нет. У урока, который в варианте
// остался без преподавателя («after» пуст), метки тоже нет: выделение в «Кто ведёт» и вопрос при принятии остаются.
function stageWeek(answer, accepted = null, issues = {}, onlyLine = "", changes = []) {
    const cells = {};
    const counts = {};
    // Кто ведёт сейчас курс + предмет, которым вариант даёт другого преподавателя: {"курс\nпредмет": [имена]}
    const previous = new Map(changes.map((change) => [`${change.course}\n${change.subject}`, change.before]));

    for (const name of Object.keys(answer)) {
        const course = courseByName(name);
        const line = course?.line || name;

        if (onlyLine && line !== onlyLine) continue;

        const before = accepted?.[name] ? new Set(lessonEntries(accepted, name).map(({ day, lesson }) => slotKey(day, lesson))) : null;

        for (const { day, lesson, entry } of lessonEntries(answer, name)) {
            const key = slotKey(day, lesson);
            const was = previous.get(`${name}\n${entry.subject}`);

            counts[day] = (counts[day] || 0) + 1;
            (cells[key] ||= []).push({
                tag: shortLine(line), title: entry.subject, meta: surnames(entry.teachers || []), joint: jointNote(course), hue: subjectHue(entry.subject),
                // Копия стоит там же, где источник в принятом расписании, — вариант её не двигает
                fresh: Boolean(accepted) && !isJointCopy(course) && !(before && before.has(key)),
                // У урока без преподавателя («—») нового преподавателя нет — метки нет
                issues: [was && entry.teachers?.length ? teacherLabel(was) : null, ...(issues[name]?.[key] || [])].filter(Boolean),
            });
        }
    }

    return weekTable((day, lesson) => ({ lessons: (cells[slotKey(day, lesson)] || []).sort((a, b) => a.tag.localeCompare(b.tag) || a.title.localeCompare(b.title)) }), { dayCounts: counts });
}

// Метка «новый преподаватель» на карточке урока (stageWeek): подпись урока {text} для weekTable,
// где text — сама метка с подсказкой «Сейчас ведёт: …» (before — кто ведёт курс в принятом расписании).
// Цвет метки задаёт app.css (.teacher-new): это не проблема урока, а пометка.
function teacherLabel(before) {
    const label = withTip(h("span", { class: "teacher-new", tabindex: "0" }, t("web.preview.teacher_new")), tr("web.preview.teacher_now", { teacher: surnames(before) }));

    return { text: label };
}
