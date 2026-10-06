"use strict";

/* ============================================================================
   tabs/teachers.js — вкладка «Преподаватели»: кеш подробностей о
   преподавателях, список с фильтром и поиском, таблица удобства по этапу,
   курсы преподавателя по предметам и диалоги.
   Пара на сервере — src/web/tabs/teachers.py.
   Берёт из других файлов: S, HOOKS, t, tr, fieldLabel, act, recall, remember,
   remoteCache (core.js); элементы интерфейса из ui.js; currentStage, openStages,
   stageLabel, isStreamKey, slotKey, hasSlot, swatch, subjectBadge, teacherAvatar,
   weekTable, clashLabel, shortCourse, shortDate, courseByName (domain.js); RENDERERS, render,
   openCourse (shell.js).
   Отдаёт: RENDERERS.teachers.
   При загрузке подписывается на HOOKS: после каждого успешного действия
   подробности устаревают, при закрытии проекта — забываются.

   Вкладка собирается из карточек: слева teacherListCard, справа teacherColumn —
   шапка teacherHeader, availabilityCard (таблица availabilityTable) и по карточке
   teacherCourses на каждый предмет (таблицы subjectCourseTable, ячейки
   courseStateCell). Ячейки, которые не кнопки-отметки по кругу, рисует staticState; среди них —
   общие уроки двух потоков («вместе», COMMITMENT_KINDS) и курсы-копии «как в Потоке N».
   Исключение среди них — жёлтая «вместе» с «не может» под общим уроком: щелчок снимает отметку.
   ============================================================================ */

// ---------------------------------------------------------------- кеш подробностей о преподавателях

// Подробности о преподавателе по ключу «имя|этап»: отметки доступности (busy/possible),
// занятость другими этапами (commitments), его уроки (own), конфликты (clashes), курсы по
// предметам (subjects) и предел курсов (limit). Загружаются отдельно от состояния проекта
// (GET /teacher); когда приходят, открытая вкладка «Преподаватели» перерисовывается.
const teacherCache = remoteCache(() => { if (S.tab === "teachers") render(); });

HOOKS.afterAction.push(({ ok }) => { if (ok) teacherCache.markStale(); });
HOOKS.projectClosed.push(() => teacherCache.forget());

// Подробности о преподавателе name в этапе stage из кеша (undefined — ещё не загружены).
// Если их нет или они устарели — запрашивает; страница перерисуется, когда придут.
function teacherDetails(name, stage) {
    const key = `${name}|${stage}`;

    if (teacherCache.needsLoad(key)) {
        teacherCache.load(key, `/api/project/${encodeURIComponent(S.project)}/teacher?name=${encodeURIComponent(name)}&stage=${encodeURIComponent(stage)}`);
    }

    return teacherCache.get(key);
}

// ---------------------------------------------------------------- вкладка «Преподаватели»

// Вкладка «Преподаватели»: слева список с фильтром по предмету и поиском; справа —
// выбранный преподаватель: его предметы, таблица доступности по этапу и таблицы
// курсов по каждому предмету (кто может вести, у кого курс в расписании, кому запрещено).
RENDERERS.teachers = (main) => {
    const teachers = S.state.teachers;
    const query = (S.ui.teacherQuery || "").toLowerCase();
    // Фильтр по предмету: показываются только преподаватели выбранного предмета
    let subjectFilter = recall("teacherSubject", "");

    if (subjectFilter && !S.state.subjects.includes(subjectFilter)) subjectFilter = "";

    const shown = teachers.filter((item) =>
        (!subjectFilter || item.subjects.includes(subjectFilter))
        && (!query || `${item.name} ${item.subjects.join(" ")}`.toLowerCase().includes(query)));
    let selected = recall("teacher", teachers[0]?.name);

    if (!teachers.some((item) => item.name === selected)) selected = teachers[0]?.name;
    // Если выбранный преподаватель не прошёл фильтр, выбирается первый из показанных
    if (shown.length && !shown.some((item) => item.name === selected)) selected = shown[0].name;

    let right;

    // Преподавателей нет совсем — приглашение добавить первого
    if (!selected) right = card({}, empty("users", t("web.no_teachers"), t("web.no_teachers_hint"), btn(t("menu.main.tab.teachers.add_teacher"), () => teacherDialog(null), { iconName: "plus", kind: "primary" })));
    // Поиск и фильтр никого не нашли: карточку прежнего выбранного преподавателя не показываем
    else if (!shown.length) right = card({}, empty("users", t("web.nothing_found"), t("web.teachers.nothing_found_hint")));
    else right = teacherColumn(teachers.find((item) => item.name === selected));

    main.append(pageHead(t("menu.main.tab.teachers"), t("web.teachers.page_hint")), h("div", { class: "grid side" },
        teacherListCard(teachers, shown, selected, subjectFilter, query), right));
};

// Левая карточка: фильтр по предмету, поиск, список показанных преподавателей
// (shown — прошедшие фильтр и поиск; selected — имя выбранного) и кнопка «Добавить».
function teacherListCard(teachers, shown, selected, subjectFilter, query) {
    const subjectSelect = select(
        [["", t("web.all_subjects")], ...S.state.subjects.map((subject) => [subject, `${subject} (${teachers.filter((item) => item.subjects.includes(subject)).length})`])],
        subjectFilter,
        (value) => { remember("teacherSubject", value); render(); },
        { style: { width: "100%" }, "aria-label": t("web.filter_subject") },
    );

    const search = input({ type: "search", placeholder: t("web.search_teacher"), value: S.ui.teacherQuery || "", style: { width: "100%" } });
    // Поиск фильтрует список на каждый символ; фокус и курсор в новом поле поиска после
    // перерисовки возвращает сама render() (restoreFocus в shell.js)
    search.addEventListener("input", (event) => {
        S.ui.teacherQuery = event.target.value;
        render();
    });

    return card({
        title: t("menu.main.tab.teachers"), actions: badge(subjectFilter || query ? `${shown.length} / ${teachers.length}` : teachers.length), flush: true,
        foot: btn(t("menu.main.tab.teachers.add_teacher"), () => teacherDialog(null), { iconName: "plus", kind: "primary block", size: "sm" }),
    },
        h("div", { class: "stack-sm", style: { padding: "10px 10px 0" } }, subjectSelect, search),
        shown.length ? h("div", { class: "list", "data-keep": "teachers" }, shown.map((item) => h("button", {
            class: `list-item ${item.name === selected ? "active" : ""}`,
            onclick: () => { remember("teacher", item.name); render(); },
        },
            teacherAvatar(item.name),
            h("div", { class: "main" }, h("div", { class: "title" }, item.name), h("div", { class: "sub" }, item.subjects.join(", "))),
        ))) : empty("users", t("web.nothing_found"), null),
    );
}

// Есть ли у преподавателя teacher на этапе key общий урок, под которым отмечено «не может»
// (S.state.jointCannot: [преподаватель, день, урок, курс-копия]; жёлтая карточка на «Расписании»).
function jointCannotStage(teacher, key) {
    return (S.state.jointCannot || []).some(([name, , , course]) => name === teacher && courseByName(course)?.stage === key);
}

// Этап, для которого показывается доступность преподавателя teacher: выбранный (currentStage),
// но только из openStages (где ещё не все курсы зафиксированы) — время отмечается только для них.
// Исключение — этап, где у преподавателя под общим уроком осталось «не может» (jointCannotStage):
// его показываем, даже если менять в нём нечего (например, поток только из присоединённых линеек),
// иначе жёлтую клетку не снять и предупреждение на «Расписании» не убрать.
function teacherStage(teacher) {
    const timeStages = openStages();
    const stage = currentStage();
    const shown = timeStages.some((item) => item.key === stage) || jointCannotStage(teacher, stage);

    return timeStages.length && !shown ? timeStages[0].key : stage;
}

// Правая колонка для преподавателя teacher: прилипающая шапка с именем и предметами,
// затем (когда подробности загружены) таблица доступности по этапу и карточки курсов
// по каждому предмету.
function teacherColumn(teacher) {
    const stage = teacherStage(teacher.name);
    const details = teacherDetails(teacher.name, stage);
    const column = h("div", { class: "stack", style: { gap: "20px" } }, teacherHeader(teacher));

    if (!details) column.append(card({}, empty("clock", t("web.common.loading"), null)));
    else if (details.error) column.append(card({}, empty("alert", details.error, null)));
    else {
        column.append(availabilityCard(teacher.name, stage, details));

        if (!details.subjects.length) column.append(card({}, empty("layers", t("web.teachers.no_courses"), t("web.teachers.no_courses_hint"))));

        for (const item of details.subjects) column.append(teacherCourses(teacher.name, item, details.limit));
    }

    return column;
}

// Шапка выбранного преподавателя: большой аватар, имя, предметы и кнопки «Изменить
// предметы» и корзина «Удалить» (подсказка у кнопки). Прилипает к верху окна: при прокрутке длинных таблиц ниже видно, чей это преподаватель.
function teacherHeader(teacher) {
    const big = teacherAvatar(teacher.name);

    Object.assign(big.style, { width: "46px", height: "46px", fontSize: "15px" });

    return h("section", { class: "card teacher-head", style: { padding: "16px" } }, h("div", { class: "row", style: { gap: "14px" } },
        big,
        h("div", { class: "grow" },
            h("h2", { style: { fontSize: "17px" } }, teacher.name),
            h("div", { class: "row", style: { marginTop: "6px", gap: "6px" } }, teacher.subjects.map((subject) => subjectBadge(subject))),
        ),
        btn(t("menu.main.tab.teachers.edit_subjects"), () => teacherDialog(teacher), { iconName: "pencil" }),
        btn("", () => act("deleteTeacher", { name: teacher.name }), { iconName: "trash", kind: "danger icon-only", title: t("menu.main.tab.teachers.delete") }),
    ));
}

// Карточка «Когда удобно: <этап>»: вкладки этапов (открытые и этапы, где под общим уроком
// осталось «не может», — jointCannotStage), таблица доступности, легенда цветов (значки «вместе»
// и «уже идёт» — только если в таблице есть такие клетки, ключи — availabilitySlots, как у самой
// таблицы) и (если этапов с отметками больше одного) кнопка «Скопировать отметки…».
// Строка дней этой таблицы прилипает сразу под карточкой с именем преподавателя.
function availabilityCard(name, stage, details) {
    const stageInfo = S.state.stages.find((item) => item.key === stage);
    const { started } = availabilitySlots(details);

    return card({
        cls: "teacher-week",
        title: `${t("web.teachers.availability_for")} ${stageInfo?.label || ""}`, hint: t("menu.main.tab.teachers.availability_hint"), flush: true,
        actions: stageTabs(stage, (value) => { remember("stage", value); render(); }, (item) => !item.allStarted || item.key === stage || jointCannotStage(name, item.key)),
        foot: [h("div", { class: "legend grow" },
            tipBadge(t("menu.main.tab.teachers.free"), "ok", true, t("web.tip.free")),
            tipBadge(t("menu.main.tab.teachers.possible"), "warn", true, t("web.tip.possible")),
            tipBadge(t("menu.main.tab.teachers.busy"), "bad", true, t("web.tip.busy")),
            tipBadge(t("menu.main.tab.teachers.commitment_busy"), "", true, t("web.tip.taken")),
            tipBadge(t("menu.main.tab.teachers.commitment_pinned"), "info", true, t("web.tip.pinned")),
            details.commitments.some(([, , kind]) => kind === "joint") ? legendBadge(t("menu.main.tab.teachers.commitment_joint"), "info", t("web.tip.joint"), "link") : null,
            // Жёлтая ячейка «вместе»: под общим уроком осталось «не может» (снимается щелчком)
            details.commitments.some(([day, lesson, kind]) => kind === "joint" && hasSlot(details.busy, [day, lesson]))
                ? legendBadge(t("web.teachers.joint_cannot_legend"), "warn", t("web.teachers.joint_cannot_legend_hint"), "link") : null,
            started.size ? legendBadge(t("web.state.started"), "info", t("web.teachers.own_started"), "lock") : null,
            // Жёлтая ячейка «уже идёт»: под уроком идущего курса осталось «не может» (снимается щелчком)
            details.busy.some(([day, lesson]) => started.has(slotKey(day, lesson)))
                ? legendBadge(t("web.teachers.started_cannot_legend"), "warn", t("web.teachers.started_cannot_legend_hint"), "lock") : null,
        ), openStages().length > 1 ? btn(t("web.teachers.copy_marks"), () => copyMarksDialog(name, stage), { iconName: "copy", size: "sm" }) : null],
    }, availabilityTable(name, stage, details));
}

// Окно «Скопировать отметки удобства…» (заголовок — web.teachers.copy_marks): переносит
// отметки «удобно / может / не может» из другого этапа (другого потока или блока курсов:
// доп. курсы, майские марафоны, летняя школа) в этап stage — для преподавателя name или,
// с галочкой, для всех сразу (действие copyAvailability).
async function copyMarksDialog(name, stage) {
    const others = openStages().filter((item) => item.key !== stage);
    const source = select(others.map((item) => [item.key, item.label]), others[0]?.key, () => {});
    const everybody = h("input", { type: "checkbox" });
    const target = S.state.stages.find((item) => item.key === stage)?.label || stage;

    await dialog(t("web.teachers.copy_marks"), h("div", { class: "stack" },
        h("p", { class: "message" }, tr("web.teachers.copy_marks_text", { target })),
        h("div", { class: "form" }, h("label", {}, t("web.teachers.copy_from")), source),
        h("label", { class: "check" }, everybody, t("web.teachers.copy_everybody")),
    ), [
        [t("web.common.cancel"), null, "ghost"],
        [t("web.copy_yes"), async () => (await act("copyAvailability", { source: source.value, target: stage, name: everybody.checked ? null : name })) ? true : undefined, "primary"],
    ], { width: 520 });
}

// Этапы в виде вкладок с датами («01.09 – 31.12»): время преподавателя отмечается
// для каждого этапа отдельно. selected — ключ выбранного этапа; onchange(ключ) —
// вызывается при выборе другого; filter — какие этапы показывать.
function stageTabs(selected, onchange, filter = () => true) {
    return tabStrip(S.state.stages.filter(filter).map((item) => {
        const [start, end] = item.dates || [];

        return { key: item.key, name: item.label, sub: [shortDate(start), shortDate(end)].filter(Boolean).join(" – ") };
    }), selected, onchange);
}

// Ячейка-состояние, а не кнопка-отметка по кругу (накладка, занято другим этапом, курс
// уже идёт…): цвет kind ("bad", "neutral", "info", "warn"), подпись text (с иконкой iconName,
// если она задана), мелкая вторая строка sub и пояснение tip при наведении или фокусе.
// onclick — переход к тому, что надо исправить, или (у жёлтых клеток «вместе» и «уже идёт»
// с «не может») снятие отметки; ячейка тогда кликается.
function staticState({ kind, iconName = null, text, sub = null, tip, onclick = null }) {
    return h("div", { class: `state static ${kind} has-tip ${onclick ? "clickable" : ""}`, tabindex: "0", "data-tip": tip, onclick },
        iconName ? h("span", {}, icon(iconName), text) : text,
        sub ? h("span", { class: "state-sub" }, sub) : null);
}

// Цвет ячейки «Когда удобно» для каждого вида commitments с сервера (stages.teacherCommitments):
// занят уроком другого этапа — серая, закреплён — синяя, общий урок с более ранним потоком — синяя.
const COMMITMENT_KINDS = { busy: "neutral", pinned: "info", joint: "info" };

// Ячейки таблицы «Когда удобно» по ключам slotKey из подробностей details (ответ GET /teacher):
//   commitments — {ключ: [вид, курс]} занятость другими этапами и общие уроки двух потоков;
//   own — {ключ: курс} свои уроки преподавателя в этом этапе;
//   started — ключи клеток «уже идёт»: свои уроки идущих курсов, кроме тех, что рисуются раньше
//     (накладка или commitments — например, урок идущей копии нарисован клеткой «вместе»);
//   clashes — {ключ: курсы} два урока одновременно.
// Одни и те же наборы у таблицы (availabilityTable) и у легенды (availabilityCard): значок
// «уже идёт» в легенде есть, только если такая клетка есть в таблице.
function availabilitySlots(details) {
    const commitments = new Map(details.commitments.map(([day, lesson, kind, course]) => [slotKey(day, lesson), [kind, course]]));
    const own = new Map((details.own || []).map(([day, lesson, course]) => [slotKey(day, lesson), course]));
    const clashes = new Map((details.clashes || []).map(([day, lesson, courses]) => [slotKey(day, lesson), courses]));
    const started = new Set((details.own || []).filter((item) => item[3]).map(([day, lesson]) => slotKey(day, lesson))
        .filter((key) => !clashes.has(key) && !commitments.has(key)));

    return { commitments, own, started, clashes };
}

// Таблица доступности преподавателя name в этапе stage (неделя).
// Что может быть в ячейке (по приоритету):
//   конфликт — два урока одновременно (красная, не кликается);
//   занят/закреплён другим этапом, общий урок с более ранним потоком (commitments) — серая/синяя
//     («вместе» — со значком цепи), не кликается; «вместе» с «не может» под ним — жёлтая,
//     щелчок снимает «не может»;
//   свой урок идущего курса (started из availabilitySlots) — синяя с замком «уже идёт», не кликается;
//     с «не может» под ним — жёлтая, щелчок снимает «не может»;
//   иначе — кнопка-отметка по кругу: удобно → может → не может (cycleAvailability).
// details — подробности о преподавателе из teacherDetails (ответ GET /teacher).
function availabilityTable(name, stage, details) {
    const { commitments, own, started, clashes } = availabilitySlots(details);

    return weekTable((day, lesson) => {
        const key = slotKey(day, lesson);

        // Преподаватель на двух уроках сразу (в этом этапе или с уроками других этапов) — красная ячейка
        if (clashes.has(key)) {
            const courses = clashes.get(key);

            return staticState({
                kind: "bad", iconName: "alert", text: t("web.teachers.clash"), sub: clashLabel(courses),
                tip: tr("web.teachers.clash_hint", { courses: courses.map((course) => `«${course}»`).join(" и ") }),
            });
        }

        if (commitments.has(key)) {
            const [kind, course] = commitments.get(key);

            // Общий урок двух потоков (kind "joint", course — курс-источник): преподаватель ведёт
            // его один раз, это не «занят» и не накладка — ячейка «вместе» со значком цепи.
            // Если под ним осталось «не может» (поставили раньше, чем туда встал урок), ячейка
            // жёлтая и щелчком снимает отметку (cycleAvailability) — иначе предупреждение не убрать
            if (kind === "joint" && hasSlot(details.busy, [day, lesson])) {
                return staticState({
                    kind: "warn", iconName: "link", text: t(`menu.main.tab.teachers.commitment_${kind}`),
                    sub: t("menu.main.tab.teachers.busy"), tip: t("web.teachers.joint_cannot_hint"),
                    onclick: () => act("cycleAvailability", { name, stage, day, lesson }),
                });
            }

            return staticState({
                kind: COMMITMENT_KINDS[kind], iconName: kind === "joint" ? "link" : null,
                text: t(`menu.main.tab.teachers.commitment_${kind}`), sub: shortCourse(course),
                tip: `${t(`menu.main.tab.teachers.commitment_${kind}_hint`)}: ${course}`,
            });
        }

        // Это время держит уже идущий курс, а не закрепление в «Курсах»: подпись «уже идёт»
        // с замком, как у идущих курсов в таблицах курсов ниже
        if (started.has(key)) {
            // «Не может» поставили до начала курса: из-за отметки новое составление может перенести
            // этот урок — ячейка жёлтая и щелчком снимает отметку (cycleAvailability)
            if (hasSlot(details.busy, [day, lesson])) {
                return staticState({
                    kind: "warn", iconName: "lock", text: t("web.state.started"),
                    sub: t("menu.main.tab.teachers.busy"), tip: `${t("web.teachers.started_cannot_hint")} ${own.get(key)}`,
                    onclick: () => act("cycleAvailability", { name, stage, day, lesson }),
                });
            }

            return staticState({
                kind: "info", iconName: "lock", text: t("web.state.started"), sub: shortCourse(own.get(key)),
                tip: `${t("web.teachers.own_started")}: ${own.get(key)}`,
            });
        }

        const onclick = () => act("cycleAvailability", { name, stage, day, lesson });
        // Собственный урок преподавателя в этом этапе по принятому расписанию подписывается под отметкой
        const lessonNote = own.has(key) ? h("span", { class: "state-sub" }, shortCourse(own.get(key))) : null;
        const mark = (kind, iconName, text) => h("button", { class: `state ${kind} ${lessonNote ? "with-lesson" : ""}`, onclick, title: lessonNote ? `${t("web.teachers.own_lesson")}: ${own.get(key)}` : null },
            h("span", {}, icon(iconName), t(text)), lessonNote);

        if (hasSlot(details.busy, [day, lesson])) return mark("bad", "x", "menu.main.tab.teachers.busy");
        if (hasSlot(details.possible, [day, lesson])) return mark("warn", "minus", "menu.main.tab.teachers.possible");

        return mark("ok", "check", "menu.main.tab.teachers.free");
    }, { cellClass: "state-cell" });
}

// Состояния курса для преподавателя: [цвет, иконка, ключ подписи]. Щелчок по ячейке
// меняет состояние по кругу (cycleCourse):
//   no (не ведёт) → may (может вести) → assigned (ведёт) → forbidden (запрещено).
const COURSE_STATES = {
    assigned: ["ok", "check", "web.state.teaches"],
    may: ["warn", "minus", "web.state.may_teach"],
    no: ["ghost", "x", "web.state.not_teaches"],
    forbidden: ["bad", "ban", "web.state.forbidden"],
};

// Карточка «Курсы предмета» для преподавателя name. item — {subject, courses}
// из подробностей; limit — максимум курсов на преподавателя (для подсказки).
// Таблица «потоки × линейки»; курсы без потока (доп. курсы, марафоны, летняя школа)
// выводятся отдельной таблицей. Внизу — легенда состояний (courseLegend).
function teacherCourses(name, item, limit) {
    const isStream = (course) => isStreamKey(course.stage);
    const tables = [item.courses.filter(isStream), item.courses.filter((course) => !isStream(course))]
        .filter((courses) => courses.length)
        .map((courses) => subjectCourseTable(name, item.subject, courses));

    return card({
        title: h("span", {}, `${t("web.teachers.courses")} `, subjectBadge(item.subject)),
        hint: `${t("menu.main.tab.teachers.courses_hint")} ${limit}`, flush: true, foot: courseLegend(item.courses),
    }, h("div", { class: "course-tables" }, tables));
}

// Легенда таблицы курсов: четыре основных состояния (COURSE_STATES) и особые —
// только если такие ячейки есть среди courses (у «как в Потоке N» — номер первой такой копии).
function courseLegend(courses) {
    // Ячейка копии всегда «как в Потоке N», поэтому её пометки (в расписании, идёт…) легенде не нужны
    const has = (test) => courses.some((course) => !course.joint && test(course));
    const copy = courses.find((course) => course.joint);

    return h("div", { class: "legend" },
        ["no", "may", "assigned", "forbidden"].map((state) => {
            const [kind, iconName, text] = COURSE_STATES[state];
            return legendBadge(t(text), kind === "ghost" ? "" : kind, t(`teachers.state_hint.${state}`), iconName);
        }),
        copy ? legendBadge(tr("web.state.joint", { number: copy.joint.number }), "", t("teachers.state_hint.joint"), "link") : null,
        has((course) => course.started && !course.scheduled && !course.orphan) ? legendBadge(t("web.state.started"), "", t("teachers.state_hint.started"), "lock") : null,
        has((course) => course.orphan) ? legendBadge(t("web.classes.no_teacher"), "bad", t("teachers.state_hint.orphan_future"), "alert") : null,
        has((course) => course.scheduled) ? legendBadge(t("web.state.scheduled"), "info", t("teachers.state_hint.scheduled"), "check") : null,
    );
}

// Таблица «этап × линейка» для курсов одного предмета subject у преподавателя name;
// ячейка — courseStateCell.
function subjectCourseTable(name, subject, courses) {
    const lines = [...new Set(courses.map((course) => course.line))];
    const stages = [...new Set(courses.map((course) => course.stage))];

    return h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th"), lines.map((line) => h("th", { class: "center" },
            h("span", { class: "row", style: { justifyContent: "center", gap: "6px" } }, swatch(line), line))))),
        h("tbody", {}, stages.map((stage) => h("tr", {},
            h("th", {}, stageLabel(stage)),
            lines.map((line) => {
                const course = courses.find((entry) => entry.stage === stage && entry.line === line);

                return course ? h("td", { class: "state-cell" }, courseStateCell(name, subject, course)) : h("td");
            }),
        ))),
    ));
}

// Ячейка курса course в таблице преподавателя name. Особые ячейки (щелчок состояние не
// меняет): курс-копия линейки, которая идёт вместе с более ранним потоком (joint — «как в
// Потоке N»: преподаватель у неё тот же, что у курса того потока), курс без преподавателя
// (orphan — щелчок открывает курс), курс уже идёт, курс в принятом расписании у этого
// преподавателя. Иначе — кнопка состояния (COURSE_STATES).
function courseStateCell(name, subject, course) {
    if (course.joint) {
        return staticState({
            kind: "neutral", iconName: "link", text: tr("web.state.joint", { number: course.joint.number }),
            tip: `${t("teachers.state_hint.joint")}\n\n${course.name}`,
        });
    }

    if (course.orphan) {
        return staticState({
            kind: "bad", iconName: "alert", text: t("web.classes.no_teacher"), onclick: () => openCourse(course.name),
            tip: `${t(course.started ? "teachers.state_hint.orphan" : "teachers.state_hint.orphan_future")}\n\n${course.name}`,
        });
    }

    if (course.started && !course.scheduled) {
        return staticState({ kind: "neutral", iconName: "lock", text: t("web.state.started"), tip: `${t("teachers.state_hint.started")}\n\n${course.name}` });
    }

    if (course.scheduled) {
        return staticState({ kind: "info", iconName: "check", text: t("web.state.scheduled"), tip: `${t("teachers.state_hint.scheduled")}\n\n${course.name}` });
    }

    const [kind, iconName, text] = COURSE_STATES[course.state];

    return h("button", {
        class: `state ${kind}`, title: `${t(`teachers.state_hint.${course.state}`)}\n\n${course.name}`,
        onclick: () => act("cycleCourse", { name, subject, course: course.name }),
    }, icon(iconName), t(text));
}

// Диалог «Добавить преподавателя» (teacher = null: имя + предметы) или
// «Предметы преподавателя» (teacher задан: только предметы). Новый преподаватель
// сразу становится выбранным в списке.
async function teacherDialog(teacher) {
    const name = input({ value: teacher?.name || "", placeholder: t("web.teacher_name_placeholder") });
    const subjects = checkList(S.state.subjects.map((subject) => [subject, subject]), teacher?.subjects || []);

    await dialog(teacher ? `${t("dialog.teacher_subjects.title")}: ${teacher.name}` : t("dialog.add_teacher.title"), h("div", { class: "stack" },
        teacher ? null : h("div", { class: "form" }, h("label", {}, fieldLabel("dialog.add_teacher.label")), name),
        h("h3", {}, t("dialog.add_teacher.subjects")),
        subjects,
    ), [
        [t("web.common.cancel"), null, "ghost"],
        [teacher ? t("web.common.save") : t("dialog.add_teacher.allow"), async () => {
            const result = teacher
                ? await act("teacherSubjects", { name: teacher.name, subjects: subjects.values() })
                : await act("newTeacher", { name: name.value, subjects: subjects.values() });

            if (!result) return undefined;
            if (!teacher) { remember("teacher", name.value.trim()); render(); }

            return true;
        }, "primary"],
    ]);
}
