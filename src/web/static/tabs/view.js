"use strict";

/* ============================================================================
   tabs/view.js — вкладка «Расписание»: что требует внимания (накладки, общие
   уроки во время «не может», уроки без преподавателя, нехватка уроков и
   преподавателей) и неделя принятого
   расписания в разных разрезах: вся школа, линейка, поток, курс, предмет,
   преподаватель. Своего модуля на сервере нет: всё берётся из S.state.
   Берёт из других файлов: S, t, tr, recall, remember (core.js); элементы интерфейса
   из ui.js; weekTable, clashText, shortCourse, shortLine, shortDate, slotKey,
   lackingCourses, stageStatus, lessonEntries, subjectHue, subjectBadge,
   teacherAvatar, teacherSubject, isExtraKey, isJointCopy, jointNote, jointStreams и другие
   помощники domain.js;
   RENDERERS, render, switchTab, openCourse (shell.js); exportDialog
   (tabs/export.js — по нажатию кнопки).
   Отдаёт: RENDERERS.view.

   Вкладка собирается из карточек-предупреждений alertCards (каждая — alertCard) и
   пары «список выбора viewListCard — неделя viewWeekCard»; что показать в неделе,
   считают viewChoices и viewLessons, а режимы просмотра описаны в VIEW_LESSONS.
   Общие уроки двух потоков (линейка идёт вместе с более ранним потоком): в режимах одного
   потока у карточки подпись «вместе с Потоком N», а на общей неделе всех потоков урок
   копии не повторяется — у источника одна карточка «Потоки 1 и 2».
   ============================================================================ */

// ---------------------------------------------------------------- вкладка «Расписание» (просмотр принятого расписания)

// Название потока или блока, к которому относится курс («Поток 1», «Майские марафоны»…),
// для меток уроков; у доп. курсов (isExtraKey) и неизвестных курсов — пустая строка.
function coursePlace(course) {
    return course && !isExtraKey(course.stage) ? stageLabel(course.stage) : "";
}

// Имена курсов этапа key (пусто, если этапа нет).
function stageCourseNames(key) {
    return S.state.stages.find((stage) => stage.key === key)?.courses || [];
}

// Карточка урока для «линейки» и «курса»: предмет и преподаватели полностью.
const subjectAndTeachers = ({ entry, teachers }) => ({ title: entry.subject, meta: teachers.join(", ") || "—" });

// Режимы просмотра принятого расписания (порядок — как в списке выбора) и что показывать
// в каждом:
//   courses(selected) — имена курсов, чьи уроки попадают в неделю (Set), или null — все
//     курсы принятого расписания;
//   lesson(урок, selected) — карточка урока {tag, title, meta} или null, если урок в неделю
//     не входит. Урок — {entry: ячейка, teachers, line: линейка курса, place: coursePlace};
//   merged — неделя собирает уроки разных потоков: общий урок источника и копии — одна
//     карточка источника, где вместо потока написано «Потоки 1 и 2» (jointStreams); в
//     остальных режимах у карточек копии и источника подпись jointNote.
// Подписи карточек зависят от режима: в «потоке» видна линейка, в «предмете» — поток и
// линейка, в «преподавателе» — поток, предмет и линейка.
const VIEW_LESSONS = {
    // Вся школа: сверху поток полностью и линейка коротко (у доп. курсов — только линейка),
    // ниже предмет и преподаватель
    all: {
        merged: true,
        courses: () => null,
        lesson: ({ entry, teachers, line, place }) => ({ tag: [place, shortLine(line)].filter(Boolean).join(", "), title: entry.subject, meta: surnames(teachers) }),
    },
    line: {
        courses: (selected) => {
            const [stage, line] = selected.split("\t");
            return new Set(stageCourseNames(stage).filter((name) => courseByName(name)?.line === line));
        },
        lesson: subjectAndTeachers,
    },
    stream: {
        courses: (selected) => new Set(stageCourseNames(selected)),
        lesson: ({ entry, teachers, line }) => ({ tag: shortLine(line), title: entry.subject, meta: surnames(teachers) }),
    },
    course: {
        courses: (selected) => new Set([selected]),
        lesson: subjectAndTeachers,
    },
    subject: {
        merged: true,
        courses: (selected) => new Set(S.state.courses.filter((course) => course.subject === selected).map((course) => course.name)),
        lesson: ({ entry, teachers, line, place }, selected) => (entry.subject === selected
            ? { tag: place || t("stage.extra"), title: shortLine(line), meta: surnames(teachers) } : null),
    },
    teacher: {
        merged: true,
        courses: () => null,
        lesson: ({ entry, teachers, line, place }, selected) => (teachers.includes(selected)
            ? { tag: place || t("stage.extra"), title: entry.subject, meta: line } : null),
    },
};

// Режимы просмотра: «all» — вся школа (все уроки всех потоков и доп. курсов на одной
// неделе), дальше — по линейке, потоку, курсу, предмету, преподавателю.
const VIEW_MODES = Object.keys(VIEW_LESSONS);

// Список выбора слева на вкладке «Расписание» для режима mode.
// Элемент: [ключ, подпись, подзаголовок?]; ключ null — это заголовок группы.
// Для «линейки» ключ — «этап\tлинейка» (через табуляцию), для «курса» —
// полное имя курса (сгруппированы по этапу и линейке).
function viewChoices(mode) {
    const result = [];

    if (mode === "all") return [["all", t("web.view.all_school"), t("web.view.all_school_sub")]];
    if (mode === "stream") return S.state.stages.map((stage) => [stage.key, stage.label, stageStatus(stage)[2]]);
    if (mode === "subject") return S.state.subjects.map((subject) => [subject, subject]);
    if (mode === "teacher") return S.state.teachers.map((teacher) => [teacher.name, teacher.name, teacher.subjects.join(", ")]);

    for (const stage of S.state.stages) {
        const courses = stage.courses.map(courseByName).filter(Boolean);
        const lines = [...new Set(courses.map((course) => course.line))];

        if (mode === "line") {
            result.push([null, stage.label]);
            lines.forEach((line) => result.push([`${stage.key}\t${line}`, line]));
            continue;
        }

        for (const line of lines) {
            result.push([null, isExtraKey(stage.key) ? line : `${stage.label} — ${line}`]);
            courses.filter((course) => course.line === line).forEach((course) => result.push([course.name, course.subject]));
        }
    }

    return result;
}

// Уроки принятого расписания для выбранного элемента списка (что брать и как подписать —
// VIEW_LESSONS[mode]). Возвращает {cells: {"день-урок": [карточки]}, counts: {день: число
// уроков}, stagesShown: этапы, чьи уроки попали в выборку (если их несколько — счётчик
// пишет «во всех потоках»)}.
function viewLessons(mode, selected) {
    const answer = S.state.answer;
    const { courses, lesson: card, merged = false } = VIEW_LESSONS[mode];
    const names = courses(selected);
    const cells = {};
    const counts = {};
    const stagesShown = new Set();

    for (const name of Object.keys(answer)) {
        if (names && !names.has(name)) continue;

        const course = courseByName(name);

        // Урок копии на общей неделе потоков — тот же урок источника: его карточка уже есть
        if (merged && isJointCopy(course)) continue;

        const line = course?.line || name;
        const place = (merged && jointStreams(course)) || coursePlace(course);
        const joint = merged ? null : jointNote(course);

        for (const { day, lesson, entry } of lessonEntries(answer, name)) {
            const item = card({ entry, teachers: entry.teachers || [], line, place }, selected);

            if (!item) continue;

            stagesShown.add(course?.stage ?? name);
            item.hue = subjectHue(entry.subject);
            item.joint = joint;
            counts[day] = (counts[day] || 0) + 1;
            (cells[slotKey(day, lesson)] ||= []).push(item);
        }
    }

    return { cells, counts, stagesShown };
}

// Вкладка «Расписание»: сверху — проблемы принятого расписания (alertCards); ниже — список
// выбора (режим + элементы) и неделя выбранного. Кнопка «Экспортировать» — exportDialog.
RENDERERS.view = (main) => {
    // Режим просмотра — по линейке, если не выбран другой (выбор запоминается под ключом "viewModeChoice")
    let mode = recall("viewModeChoice", "line");
    if (!VIEW_MODES.includes(mode)) mode = "line";

    const choices = viewChoices(mode);
    const keys = choices.map(([key]) => key).filter((key) => key !== null);
    let selected = recall(`view.${mode}`, keys[0]);

    if (!keys.includes(selected)) selected = keys[0];

    main.append(...[
        pageHead(t("menu.main.tab.view"), t("menu.main.tab.view.hint"), btn(t("web.export_button"), () => exportDialog(), { iconName: "download", kind: "primary" })),
        ...alertCards(),
        h("div", { class: "grid side" }, viewListCard(mode, choices, selected), viewWeekCard(mode, choices, selected)),
    ].filter(Boolean));
};

// Левая карточка: выбор режима просмотра и список его элементов (choices из viewChoices;
// ключ null — заголовок группы). Выбор запоминается для каждого режима (ключ view.<режим>).
function viewListCard(mode, choices, selected) {
    return card({
        actions: select(VIEW_MODES.map((key) => [key, t(`menu.main.tab.view.mode_${key}`)]), mode, (value) => { remember("viewModeChoice", value); render(); }, { style: { width: "100%" } }),
        flush: true, cls: "view-list",
    }, h("div", { class: "list", "data-keep": `view-${mode}` }, choices.map(([key, label, sub]) => key === null
        ? h("div", { class: "list-header" }, label)
        : h("button", { class: `list-item ${key === selected ? "active" : ""}`, onclick: () => { remember(`view.${mode}`, key); render(); } },
            mode === "teacher" ? teacherAvatar(label) : null,
            mode === "line" ? swatch(label) : null,
            h("div", { class: "main" }, h("div", { class: "title" }, label), sub ? h("div", { class: "sub" }, sub) : null)))));
}

// Строка статуса над неделей, когда показывать нечего: расписание ещё не составлено,
// этап (поток, линейка, курс) ещё не составлен, курсы выбора ждут свой поток-источник
// (waitingStatus). count — сколько уроков показано.
// null — статус не нужен.
function viewStatus(mode, selected, count) {
    if (!Object.keys(S.state.answer).length) return t("web.common.no_schedule");
    if (count) return null;

    const waiting = waitingStatus(mode, selected);

    if (waiting) return waiting;
    if (mode === "stream") return tr("menu.main.tab.view.stage_not_built", { name: stageLabel(selected) });
    if (mode === "line") return tr("menu.main.tab.view.line_not_built", { stage: stageLabel(selected.split("\t")[0]) });

    const course = mode === "course" ? courseByName(selected) : null;

    if (course) return tr("menu.main.tab.view.course_not_built", { stage: stageLabel(course.stage) });

    return null;
}

// Все курсы выбора (поток, линейка или курс) — копии, которые ждут свой поток-источник: составлять
// их поток незачем, уроки придут из источника. Тогда вместо «составьте варианты» — чего ждать:
// у курса — web.classes.joint_waiting_hint, у линейки и потока — строки «Линейка … ждёт Поток N»
// (stage.waiting с сервера, как под статусом потока на «Запуске»). "" — если это не так.
function waitingStatus(mode, selected) {
    if (!["stream", "line", "course"].includes(mode)) return "";

    const courses = [...VIEW_LESSONS[mode].courses(selected)].map(courseByName);

    if (!courses.length || !courses.every((course) => course?.joint?.waiting)) return "";
    if (mode === "course") return tr("web.classes.joint_waiting_hint", { number: courses[0].joint.number });

    const [key, line] = mode === "line" ? selected.split("\t") : [selected, null];
    const waiting = (S.state.stages.find((stage) => stage.key === key)?.waiting || []).filter((item) => !line || item.line === line);

    return waiting.map((item) => tr("web.run.joint_waiting", item)).join(". ");
}

// Карточка недели выбранного элемента: заголовок (что показано), число уроков (у
// преподавателя и предмета — в цвете предмета), статус, таблица недели и внизу ещё
// одна кнопка «Экспортировать». Шапка недели (что показано) прилипает к верху окна
// вместе со строкой дней.
function viewWeekCard(mode, choices, selected) {
    const { cells, counts, stagesShown } = selected !== undefined ? viewLessons(mode, selected) : { cells: {}, counts: {}, stagesShown: new Set() };
    const count = Object.values(cells).reduce((sum, items) => sum + items.length, 0);
    const info = viewStatus(mode, selected, count);
    const title = (choices.find(([key]) => key === selected) || [])[1] || "";
    const fullTitle = mode === "course" ? selected : mode === "line" && selected ? `${stageLabel(selected.split("\t")[0])} — ${title}` : title;

    // Неделя преподавателя или предмета: счётчик уроков окрашен в цвет предмета
    const colourSubject = mode === "subject" ? selected : mode === "teacher" ? teacherSubject(selected) : null;
    const countText = tr(stagesShown.size > 1 ? "web.view.lessons_count_all" : "menu.main.tab.view.lessons_count", { count });
    const countBadge = colourSubject ? subjectBadge(colourSubject, countText) : badge(countText, "accent");

    return card({
        cls: "sticky-card",
        title: fullTitle,
        actions: count ? countBadge : null,
        flush: true,
    },
        // Статус (например, «поток ещё не составлен») виден всегда — это не пояснение в «i»
        info ? h("p", { class: "status-line" }, icon("info"), info) : null,
        weekTable((day, lesson) => ({ lessons: (cells[slotKey(day, lesson)] || []).sort((a, b) => (a.tag || "").localeCompare(b.tag || "") || a.title.localeCompare(b.title)) }), { dayCounts: counts }),
        // Та же выгрузка, что вверху страницы, — чтобы после просмотра недели не листать наверх
        h("div", { class: "card-foot" }, h("span", { class: "grow" }), btn(t("web.export_button"), () => exportDialog(), { iconName: "download" })));
}

// ---------------------------------------------------------------- что требует внимания

// Карточки-предупреждения над неделей, по порядку: накладки преподавателей, общие уроки во
// время «не может», уроки без преподавателя, курсы с нехваткой уроков, нехватка преподавателей.
// Пустых нет (null).
function alertCards() {
    return [clashCard(), jointCannotCard(), noTeacherCard(), lackingCard(), staffCard()];
}

// Карточка-предупреждение: заголовок с иконкой iconName и «i»-пояснением hint, ниже —
// список строк items (alertRow). Красная; cls "warn-card" — жёлтая (не критично).
// Пустой список — карточки нет (null).
function alertCard(iconName, title, hint, items, cls = "") {
    if (!items.length) return null;

    return h("section", { class: `card clash-card ${cls}` },
        h("div", { class: "card-head" }, h("div", { class: "grow" }, h("h2", { class: "title-row" }, icon(iconName), ` ${title}`, infoDot(hint)))),
        h("div", { class: "card-body" }, h("ul", { class: "clash-list" }, items)),
    );
}

// Строка карточки-предупреждения: жирное название name и пояснение text.
// onclick — переход к тому, что надо исправить (строка кликается, tip — подсказка браузера).
function alertRow(name, text, onclick = null, tip = null) {
    return h("li", { class: onclick ? "clickable" : null, onclick, title: tip }, h("b", {}, name), h("span", {}, text));
}

// Преподаватели на двух уроках одновременно в принятом расписании: строка на
// преподавателя, в ней все его накладки «Пн 10:00: Поток 1 и Поток 2, ОГЭ, Математика».
function clashCard() {
    const byTeacher = new Map();

    for (const [teacher, day, lesson, courses] of S.state.clashes || []) {
        if (!byTeacher.has(teacher)) byTeacher.set(teacher, []);
        byTeacher.get(teacher).push(`${slotLabel([day, lesson])}: ${clashText(courses)}`);
    }

    return alertCard("alert", t("web.view.clashes_title"), t("web.view.clashes_hint"),
        [...byTeacher].map(([teacher, items]) => alertRow(teacher, items.join("; "))));
}

// Общие уроки во время, где у преподавателя на этапе потока-копии «не может» (S.state.jointCannot:
// [преподаватель, день, урок, курс-копия]; сервер — joint.copyCannot). Не запрет, а предупреждение
// (жёлтая): строка на преподавателя, в ней «Пн 16:20: Поток 2, ЕГЭ основной, Математика».
// Клик — «Преподаватели»: там отметку под общим уроком можно снять.
function jointCannotCard() {
    const byTeacher = new Map();

    for (const [teacher, day, lesson, course] of S.state.jointCannot || []) {
        if (!byTeacher.has(teacher)) byTeacher.set(teacher, { stage: courseByName(course).stage, items: [] });
        byTeacher.get(teacher).items.push(`${slotLabel([day, lesson])}: ${shortCourse(course)}`);
    }

    // Переход к «Когда удобно» преподавателя на этапе потока-копии (первого из его строк)
    const open = (teacher, stage) => () => {
        remember("teacher", teacher);
        remember("stage", stage);
        switchTab("teachers");
    };

    return alertCard("alert", t("web.view.joint_cannot_title"), t("web.view.joint_cannot_hint"),
        [...byTeacher].map(([teacher, { stage, items }]) => alertRow(teacher, items.join("; "), open(teacher, stage), t("web.view.joint_cannot_open"))),
        "warn-card");
}

// Курсы с уроками без преподавателя (S.state.noTeacher: [курс, сколько уроков, дата
// начала]) с подписью «идёт с …» / «начнётся завтра, …» / «начнётся …». Клик — курс
// на вкладке «Курсы».
function noTeacherCard() {
    const when = (start) => start && start <= isoDay(0) ? "web.view.runs_since" : start === isoDay(1) ? "web.view.starts_tomorrow" : "web.view.starts_on";

    return alertCard("alert", t("web.view.no_teacher_title"), t("web.view.no_teacher_hint"), (S.state.noTeacher || []).map(([course, count, start]) =>
        alertRow(shortCourse(course), `${lessonsText(count)}, ${tr(when(start), { date: shortDate(start) || "—" })}`, () => openCourse(course), t("web.view.open_course"))));
}

// Курсы принятых этапов, у которых уроков в расписании меньше, чем часов (жёлтая).
// Клик — курс на вкладке «Курсы».
function lackingCard() {
    return alertCard("alert", t("web.view.short_title"), t("web.view.short_hint"), lackingCourses().map((course) =>
        alertRow(shortCourse(course.name), tr("web.view.short_count", { placed: course.slots.length, hours: course.hours }),
            () => openCourse(course.name), t("web.view.open_course"))), "warn-card");
}

// «Нужен ещё преподаватель»: по предмету не хватает (красное) или скоро не хватит (жёлтое)
// свободного времени у преподавателей. Карточка красная, если хоть по одному предмету
// уже не хватает. Клик — «Преподаватели» с этим предметом в фильтре.
// Сервер (staffing.py) даёт free — всё свободное время преподавателей предмета, needed —
// сколько уроков ещё не поставлено, next — уроков на один поток. Красное сравнивает free с
// needed, а жёлтое — с next то, что останется после ещё не поставленных уроков
// (free − needed): его и пишем в «свободно {free}», иначе текст «следующему нужно 10,
// а свободно 14» сам себе противоречит.
function staffCard() {
    const staffing = S.state.staffing || [];
    const text = (item) => tr(item.level === "short" ? "web.view.staff_short" : "web.view.staff_tight", {
        needed: lessonsText(item.needed),
        free: lessonsText(item.level === "short" ? item.free : item.free - item.needed),
        next: lessonsText(item.next),
    })
        + (item.teachers.length ? `; ${t("web.view.staff_teachers")}: ${surnames(item.teachers)}` : `; ${t("web.view.staff_nobody")}`);

    return alertCard("users", t("web.view.staff_title"), t("web.view.staff_hint"), staffing.map((item) =>
        alertRow(item.subject, text(item), () => { remember("teacherSubject", item.subject); switchTab("teachers"); }, t("web.view.staff_open"))),
    staffing.some((item) => item.level === "short") ? "" : "warn-card");
}
