"use strict";

/* ============================================================================
   domain.js — помощники предметной области поверх S.state, общие для оболочки
   и нескольких вкладок: дни, время уроков и даты, ключи уроков «день-урок»,
   цвета линеек и предметов, аватары преподавателей, курсы, этапы (потоки и
   блоки) и коды их статусов, накладки «два урока одновременно», число «требует
   внимания», идёт ли сборка (isBuilding, buildingNote) и общая таблица недели weekTable().
   Курсы линейки, которая идёт вместе с более ранним потоком (поле joint курса-копии и
   jointWith курса-источника с сервера, .spec/joint-lines/SPEC.md): isJointCopy, подписи
   jointNote и jointStreams, без копий в lackingCourses и pendingCourses.
   Берёт из других файлов: S, t, tr, recall (core.js); h, hash, avatar, icon (ui.js).
   Отдаёт: dayName, lessonTime, slotLabel, surnames, shortLine, lineHue,
   swatch, subjectHue, subjectBadge, teacherSubject, teacherAvatar, slotKey, slotFromKey,
   sameSlot, hasSlot, courseByName, shortCourse, isExtraKey, isStreamKey,
   courseStream, stageLabel, lessonEntries, currentStage, openStages, stageSwitch,
   isJointCopy, allJoint, andList, jointNote, jointStreams,
   weekTable, hyphenate, isoDay, shortDate, pluralText, lessonsText, coursesText, clashLabel, clashText,
   teacherPending, pinsPending, pendingCourses, lackingCourses, stageClashes,
   scheduleProblem, buildState, stageState, stageStatus, isInSchedule, attentionCount,
   isBuilding, buildingNote.
   ============================================================================ */

// Название дня недели по номеру (0 — понедельник); short — сокращённое («Пн»).
function dayName(day, short = false) {
    return t(short ? `abbreviate.day.${day}` : `day.${day}`);
}

// Время урока lesson в день day из сетки, например «10:00 - 10:45»; "" если урока нет.
function lessonTime(day, lesson) {
    return (S.state.grid[day] || [])[lesson] || "";
}

// Короткая подпись слота [день, урок]: «Пн 10:00» (или «Пн 3», если время не задано).
function slotLabel([day, lesson]) {
    const time = lessonTime(day, lesson);

    return `${dayName(day, true)} ${time ? time.split(" - ")[0] : lesson + 1}`;
}

// Только фамилии преподавателей через запятую (первое слово имени); пусто → «—».
function surnames(teachers) {
    return teachers.length ? teachers.map((name) => name.split(" ")[0]).join(", ") : "—";
}

// Короткое название линейки для тесных карточек уроков («ЕГЭ осн.») или само название.
// Сокращения задаёт сервер (S.meta.shortLines — variants.SHORT_LINES, те же, что в выгрузке
// вариантов в Excel).
function shortLine(line) {
    return S.meta.shortLines[line] || line;
}

// Цвет квадратика каждой линейки; для незнакомой линейки — из хеша названия.
const LINE_HUES = {
    "ОГЭ": 152, "ЕГЭ основной": 214, "ЕГЭ продвинутый": 262,
    "10 класс": 24, "8 класс": 42, "Семинар ЕГЭ продвинутый": 322, "Семинар ОГЭ": 348,
};

// Оттенок линейки: из LINE_HUES или из хеша названия.
function lineHue(line) {
    return LINE_HUES[line] ?? hash(line) % 360;
}

// Маленький цветной квадратик линейки (рядом с её названием).
function swatch(line) {
    return h("span", { class: "swatch", style: { background: `hsl(${lineHue(line)} 70% 52%)` } });
}

// Свой оттенок (hue 0–360) для каждого предмета: уроки, значки и аватары
// преподавателей одного предмета окрашены одинаково. Незнакомый предмет
// получает оттенок из хеша названия.
const SUBJECT_HUES = {
    "Русский язык": 0, "История": 26, "Обществознание": 46, "Биология": 92, "Химия": 145, "География": 172,
    "Информатика": 195, "Математика": 220, "Математика база": 235, "Физика": 252, "Английский язык": 282, "Литература": 312,
};

// Оттенок предмета: из SUBJECT_HUES или из хеша названия.
function subjectHue(subject) {
    return SUBJECT_HUES[subject] ?? hash(subject || "") % 360;
}

// Значок в цвете предмета subject; text — надпись (по умолчанию — название предмета).
function subjectBadge(subject, text = subject) {
    return h("span", { class: "badge subject", style: { "--hue": subjectHue(subject) } }, text);
}

// Первый предмет преподавателя name (из S.state.teachers) — по нему выбирается его цвет;
// undefined, если преподавателя нет или у него нет предметов.
function teacherSubject(name) {
    return S.state.teachers.find((item) => item.name === name)?.subjects[0];
}

// Аватар преподавателя в цвете его первого предмета.
function teacherAvatar(name, cls = "avatar-sm") {
    return avatar(name, cls, subjectHue(teacherSubject(name)));
}

// ---------------------------------------------------------------- уроки: ключ «день-урок»

// Ключ урока «день-урок» («0-3» — понедельник, четвёртый урок) для словарей и
// значений списков выбора; так же записаны ключи в issues вариантов на сервере.
function slotKey(day, lesson) {
    return `${day}-${lesson}`;
}

// Урок [день, урок] по ключу slotKey: «0-3» → [0, 3].
function slotFromKey(key) {
    return key.split("-").map(Number);
}

// Один и тот же ли урок: a и b — пары [день, урок] (с сервера могут прийти и числа, и строки).
function sameSlot(a, b) {
    return String(a) === String(b);
}

// Есть ли урок slot (пара [день, урок]) в списке slots.
function hasSlot(slots, slot) {
    return slots.some((item) => sameSlot(item, slot));
}

// Курс из S.state.courses по полному имени (undefined, если нет).
function courseByName(name) {
    return S.state.courses.find((course) => course.name === name);
}

// Подпись курса name для списков и пояснений: «Поток 2, ЕГЭ основной, Математика»,
// у доп. курса — «Семинар ОГЭ: Математика». Подпись готовой присылает сервер (поле short
// курса, courses.courseLabel — собрана из полей курса); страница имя курса не разбирает.
// Курса, которого уже нет в проекте, — его имя как есть.
function shortCourse(name) {
    return courseByName(name)?.short ?? name;
}

// Ключ этапа — блок доп. курсов (его ключ даёт сервер: S.meta.extraBlock, model.EXTRA_BLOCK):
// у курсов этого блока нет потока.
function isExtraKey(key) {
    return key === S.meta.extraBlock;
}

// Ключ этапа — поток ("1", "2"…), а не блок ("extra", "may", "summer").
function isStreamKey(key) {
    return /^\d+$/.test(key);
}

// Поток курса name для коротких подписей («Поток 1») или null, если курс не из потока
// (блок, доп. курс) или его уже нет в проекте. Поток берётся из данных курса, а не из имени.
function courseStream(name) {
    const stage = courseByName(name)?.stage;

    return stage && isStreamKey(stage) ? stageLabel(stage) : null;
}

// Название этапа по ключу: из S.state.stages; если этапа там нет — «Поток N»
// для числового ключа или перевод stage.<key> для блока.
function stageLabel(key) {
    return S.state.stages.find((stage) => stage.key === key)?.label
        || (isStreamKey(key) ? `${t("stage.stream")} ${key}` : t(`stage.${key}`));
}

// Все уроки курса name в расписании answer как список {day, lesson, entry},
// где entry — ячейка {subject, teachers}. Пустые ячейки (subject "#") пропускаются.
function lessonEntries(answer, name) {
    const result = [];

    (answer[name] || []).forEach((cells, day) => cells.forEach((entry, lesson) => {
        if (entry.subject && entry.subject !== "#") result.push({ day, lesson, entry });
    }));

    return result;
}

// Ключ этапа (потока), выбранного сейчас на вкладках «Преподаватели», «Запуск»,
// «Предпросмотр». Берётся запомненный выбор; если его нет — этап, которому нужна
// работа; если запомненного этапа больше нет в проекте — первый этап.
function currentStage() {
    const keys = S.state.stages.map((stage) => stage.key);
    // Если поток ещё не выбирали, по умолчанию берётся первый, которому нужна работа
    // (из openStages — где ещё не все курсы зафиксированы), в порядке важности статусов NEEDS_WORK
    const rank = (stage) => NEEDS_WORK.indexOf(stageState(stage));
    const needsWork = openStages().filter((stage) => rank(stage) >= 0)
        .reduce((best, stage) => (!best || rank(stage) < rank(best) ? stage : best), null)?.key || keys[0];
    const stage = recall("stage", needsWork);

    return keys.includes(stage) ? stage : keys[0];
}

// Этапы, в которых ещё не все курсы зафиксированы: для них составляют варианты и отмечают
// время преподавателей. Зафиксированы все курсы (stage.allStarted с сервера) — значит, все
// курсы этапа уже идут и у каждого расставлены все уроки; этап, где идущему курсу не
// хватает уроков, сюда входит — ему сборка ещё нужна.
function openStages() {
    return S.state.stages.filter((stage) => !stage.allStarted);
}

// Переключатель потоков на «Предпросмотре» — чьи варианты показать (только этапы, прошедшие
// filter): кнопки в одну строку, выбранная подсвечена — как переключатель темы. Потоков обычно
// два-три, поэтому выбор в один щелчок удобнее выпадающего списка. onchange(ключ) вызывается
// только при выборе другого этапа. Подпись для экранного диктора — своя (web.preview.stage_switch),
// а не заголовок карточки потоков «Запуска» («Что составить»): здесь поток выбирают, чтобы смотреть.
function stageSwitch(selected, onchange, filter = () => true) {
    return h("div", { class: "segmented", role: "radiogroup", "aria-label": t("web.preview.stage_switch") },
        S.state.stages.filter(filter).map((stage) => h("button", {
            type: "button", role: "radio", class: stage.key === selected ? "active" : "",
            "aria-checked": stage.key === selected ? "true" : "false",
            onclick: () => { if (stage.key !== selected) onchange(stage.key); },
        }, stage.label)));
}

// ---------------------------------------------------------------- линейка идёт вместе с более ранним потоком

// Курс-копия: его линейка идёт вместе с более ранним потоком, и уроки, преподаватель и часы
// у него — как у курса-источника (course.joint с сервера: {number, stage, source, waiting}).
// Такой курс сам не составляется и не меняется: всё меняется у источника.
function isJointCopy(course) {
    return Boolean(course?.joint);
}

// Все курсы этапа stage — копии (линейки присоединены к другому потоку): их уроки задаёт поток-
// источник, составлять нечего. Та же проверка, что у сервера в run (отказ web.run.all_joint):
// «Запуск» закрывает кнопки заранее, а «Версии» не советуют составить такой поток заново.
function allJoint(stage) {
    return stage.courses.every((name) => isJointCopy(courseByName(name)));
}

// Список через запятую, последний — через « и »: «1 и 2», «1, 2 и 3». Как союз в clashLabel —
// мелкое правило русского языка, ключа в ru.hjson для него нет.
function andList(items) {
    return items.length > 1 ? `${items.slice(0, -1).join(", ")} и ${items[items.length - 1]}` : items.join("");
}

// Подпись урока курса course там, где видны уроки одного потока (поток, линейка, курс,
// вариант): у копии — «вместе с Потоком 1», у источника — «вместе с Потоком 2» (или «вместе
// с Потоками 2 и 3»); у обычного курса — null.
function jointNote(course) {
    if (isJointCopy(course)) return tr("web.lesson.joint", { number: course.joint.number });

    const streams = course?.jointWith || [];

    if (streams.length > 1) return tr("web.lesson.joint_many", { numbers: andList(streams) });

    return streams.length ? tr("web.lesson.joint", { number: streams[0] }) : null;
}

// Подпись общего урока там, где уроки всех потоков на одной неделе (вся школа, преподаватель,
// предмет): у источника, с которым идут другие потоки, — «Потоки 1 и 2»; иначе null.
// Копия там своей карточки не получает: её урок — тот же урок источника.
function jointStreams(course) {
    if (!course?.jointWith?.length) return null;

    return tr("web.lesson.joint_streams", { numbers: andList([course.stage, ...course.jointWith]) });
}

// ---------------------------------------------------------------- сетка недели (общая таблица для нескольких вкладок)

// Строки таблицы недели: все различные времена уроков из сетки, по порядку.
// Возвращает [[время, {день: номер урока в этот день}], …] — у разных дней
// одно и то же время может быть разным по счёту уроком.
function weekRows() {
    const rows = new Map();

    S.state.grid.forEach((times, day) => times.forEach((time, lesson) => {
        if (!rows.has(time)) rows.set(time, {});
        rows.get(time)[day] = lesson;
    }));

    return [...rows.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

// Дни, в которые вообще есть уроки (у которых в сетке задано хоть одно время).
function weekDays() {
    return [...Array(S.meta.days).keys()].filter((day) => S.state.grid[day].length);
}

// Рисует таблицу недели: строки — время уроков, столбцы — дни.
// cell(day, lesson) вызывается для каждой ячейки и возвращает либо готовый DOM-узел,
// либо {lessons: [{tag, title, meta, joint, hue, fresh, issues}]} — список карточек уроков:
//   tag — короткая метка сверху (линейка/поток), title — предмет, meta — строка
//   снизу (преподаватели), joint — подпись общего урока со значком цепи («вместе с
//   Потоком 1», jointNote), hue — цвет, fresh — урок новый относительно принятого,
//   issues — подписи под уроком (только «Предпросмотр»): проблемы и пометки. Строка —
//   проблема (красным); {text, level: "warn"} — не критично (жёлтым); {text: DOM-узел} без
//   level — пометка со своим оформлением внутри узла (метка «новый преподаватель» teacherLabel
//   на «Предпросмотре»: span всё равно получает класс l-issue, а цвет перебивает .teacher-new
//   в app.css).
// dayCounts — {день: число уроков} для подписи под названием дня (необязательно);
// cellClass — CSS-класс для всех рабочих ячеек.
// Ячейки, где в этот день нет урока в это время, закрашены как «нет урока».
function weekTable(cell, { dayCounts = null, cellClass = "" } = {}) {
    const rows = weekRows();
    const days = weekDays();

    // Содержимое ячейки: готовый узел как есть, иначе список карточек уроков
    const content = (value) => {
        if (value instanceof Node) return value;

        return h("div", { class: "lessons" }, (value.lessons || []).map((lesson) => h("div", {
            class: `lesson ${lesson.fresh ? "fresh" : ""}`, style: { "--hue": lesson.hue ?? 230 },
        },
            lesson.tag ? h("span", { class: "l-tag" }, lesson.tag) : null,
            h("span", { class: "l-title" }, hyphenate(lesson.title)),
            lesson.meta ? h("span", { class: "l-meta" }, lesson.meta) : null,
            lesson.joint ? h("span", { class: "l-joint" }, icon("link"), lesson.joint) : null,
            // Подписи под уроком (только в «Предпросмотре»): каждая своей строкой. Строка — проблема
            // (красным); {text, level: "warn"} — не критично (жёлтым); {text: узел} — пометка со
            // своим оформлением внутри узла (метка «новый преподаватель»)
            (lesson.issues || []).map((issue) => h("span", { class: `l-issue ${issue.level === "warn" ? "warn" : ""}` }, issue.text ?? issue)),
        )));
    };

    return h("div", { class: "table-wrap" }, h("table", { class: "week" },
        h("colgroup", {}, h("col", { class: "time-col" }), days.map(() => h("col"))),
        h("thead", {}, h("tr", {},
            h("th"),
            days.map((day) => h("th", {},
                h("span", { class: "day" }, dayName(day)),
                dayCounts ? h("span", { class: "day-sub" }, dayCounts[day] ? lessonsText(dayCounts[day]) : "—") : null)),
        )),
        h("tbody", {}, rows.map(([time, byDay]) => {
            const [start, end] = time.split(" - ");

            return h("tr", {},
                h("th", {}, h("b", {}, start), end),
                days.map((day) => day in byDay
                    ? h("td", { class: cellClass }, content(cell(day, byDay[day])))
                    : h("td", { class: "off" }, t("web.common.no_lesson"))),
            );
        })),
    ));
}

// Расставляет в длинных словах (от 8 букв) мягкие переносы (U+00AD) между слогами,
// чтобы в узкой ячейке слово переносилось по слогам с дефисом, а не где попало.
// Правило: между двумя гласными разрыв ставится перед единственной согласной или
// после первой из группы согласных; с каждой стороны остаётся минимум две буквы.
function hyphenate(text) {
    const vowels = "аеёиоуыэюяАЕЁИОУЫЭЮЯ";
    const signs = "ьъйЬЪЙ";

    return String(text).split(" ").map((word) => {
        if (word.length < 8) return word;

        const at = [...word].map((char, index) => vowels.includes(char) ? index : -1).filter((index) => index >= 0);
        const breaks = new Set();

        for (let k = 0; k + 1 < at.length; k++) {
            const left = at[k], right = at[k + 1];
            const cluster = right - left - 1;
            let cut;

            if (cluster === 0) cut = right;
            else if (cluster === 1) cut = left + 1;
            else cut = left + 2;

            // Часть слова никогда не начинается с ь, ъ или й
            while (cut < right && signs.includes(word[cut])) cut++;

            if (cut >= 2 && word.length - cut >= 2) breaks.add(cut);
        }

        return [...word].map((char, index) => (breaks.has(index) ? "\u00AD" : "") + char).join("");
    }).join(" ");
}

// Дата «ГГГГ-ММ-ДД» для «сегодня + days дней» по местному времени (не UTC).
function isoDay(days) {
    const date = new Date();
    date.setDate(date.getDate() + days);

    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

// Дата «ГГГГ-ММ-ДД» коротко: «31.12» или, с withYear, «31.12.2026».
// Пустое или неверное значение → "" (вызывающий сам решает, что показать вместо даты).
function shortDate(iso, withYear = false) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || "")) return "";

    const [year, month, day] = iso.split("-");

    return withYear ? `${day}.${month}.${year}` : `${day}.${month}`;
}

// Число со словом в нужной форме: pluralText(2, ["урок", "урока", "уроков"]) → «2 урока».
function pluralText(count, [one, few, many]) {
    const tens = count % 100, ones = count % 10;
    const word = tens >= 11 && tens <= 14 ? many : ones === 1 ? one : ones >= 2 && ones <= 4 ? few : many;

    return `${count} ${word}`;
}

// Число уроков с правильным окончанием: «1 урок», «2 урока», «5 уроков», «11 уроков».
function lessonsText(count) {
    return pluralText(count, ["урок", "урока", "уроков"]);
}

// Число курсов с правильным окончанием: «1 курс», «3 курса», «5 курсов» (значок смены преподавателя на «Предпросмотре»).
function coursesText(count) {
    return pluralText(count, ["курс", "курса", "курсов"]);
}

// Короткая подпись для конфликта «два урока одновременно»: «Поток 1 и Поток 2», если
// все курсы из разных потоков, иначе — сами курсы через «и». courses — имена курсов.
function clashLabel(courses) {
    const streams = courses.map((name) => courseStream(name) || name);

    return new Set(streams).size === streams.length ? streams.join(" и ") : courses.map(shortCourse).join(" и ");
}

// Полный текст конфликта: «Поток 1 и Поток 2, ЕГЭ основной, Математика», если все курсы
// из потоков и отличаются только потоком (линейка и предмет одни и те же);
// иначе — каждый курс целиком через «и».
function clashText(courses) {
    const known = courses.map(courseByName);
    const rests = new Set(known.map((course) => course && `${course.line}, ${course.subject}`));

    if (rests.size === 1 && courses.every(courseStream)) return `${clashLabel(courses)}, ${[...rests][0]}`;

    return courses.map(shortCourse).join(" и ");
}

// Выбранный вручную преподаватель курса ещё не стоит в принятом расписании (появится,
// когда этап составят заново): "none" — у уроков курса в расписании преподавателя нет,
// "other" — там стоит другой; null — расхождения нет, преподаватель не выбран или у курса
// ещё нет уроков в расписании.
function teacherPending(course) {
    const chosen = course.assigned[0];

    if (!chosen || !course.slots.length) return null;
    if (!course.scheduled.length) return "none";

    return course.scheduled.includes(chosen) ? null : "other";
}

// Закреплённое время курса, которого нет в принятом расписании (уроки пока стоят в другом
// месте — до следующего составления этапа): список [день, урок]. Пустой, если всё на месте
// или у курса ещё нет уроков в расписании.
function pinsPending(course) {
    return course.slots.length ? course.pinned.filter((slot) => !hasSlot(course.slots, slot)) : [];
}

// Курсы этапа stage, у которых изменения ещё не попали в принятое расписание:
// уроков в расписании больше, чем часов; выбран другой преподаватель (teacherPending —
// "other"); или закреплено время, которого нет в расписании (pinsPending). Учитываются
// только курсы, у которых уже есть уроки в расписании. Возвращает массив объектов курсов.
// У курса, который уже идёт (course.started), преподаватель и время уроков не меняются и при
// новом составлении (solver_input.pinPlan): выбор преподавателя и закрепления, сделанные до
// начала, уже стоящие уроки не сдвинут — звать «составить заново» из-за них незачем.
// Курс, где выбран преподаватель, а в расписании у уроков никого нет ("none"), сюда не
// входит: этап с ним не считается «изменён» (вкладка «Курсы» лишь пишет пометку).
// Копии (isJointCopy) не входят: их уроки меняются вместе с источником.
function pendingCourses(stage) {
    return S.state.courses.filter((course) => course.stage === stage.key && !isJointCopy(course) && course.slots.length && (
        course.slots.length > course.hours
        || (!course.started && (teacherPending(course) === "other" || pinsPending(course).length))
    ));
}

// Курсы, которым не хватает уроков: в принятом расписании у них уроков меньше, чем
// часов в неделю. Учитываются только этапы, уже попавшие в принятое расписание
// (у ещё не составленного этапа уроков нет у всех курсов — это не проблема).
// Копии (isJointCopy) не входят: их уроки — уроки источника; нехватка видна у него самого,
// а копия, которая ждёт (у курса-источника в принятом расписании нет уроков), получит уроки
// сама, когда они появятся у источника.
function lackingCourses() {
    return S.state.courses.filter((course) => course.slots.length < course.hours && !isJointCopy(course)
        && S.state.stages.some((stage) => stage.key === course.stage && isInSchedule(stage)));
}

// Конфликты «два урока одновременно» из принятого расписания, в которых участвует
// хотя бы один курс этапа stage. Элемент: [преподаватель, день, урок, [курсы]].
function stageClashes(stage) {
    return (S.state.clashes || []).filter(([, , , courses]) => courses.some((name) => stage.courses.includes(name)));
}

// ---------------------------------------------------------------- статус этапа
//
// Статус этапа — код; лесенка проверок написана один раз (stageState), а подписи
// к кодам каждая вкладка выбирает свои (stageStatus — значок карточек, runStatus на
// «Запуске»). Коды по порядку проверок:
//   "clash"    — в принятом расписании преподаватель на двух уроках сразу;
//   "pending"  — изменения курсов ещё не попали в принятое расписание (pendingCourses);
//   "built"    — этап составлен полностью;
//   "partial"  — этап в расписании, но части уроков не хватает;
//   "variants" — есть варианты, ни один не принят;
//   "new"      — ещё не составлен.

// Проблема этапа в принятом расписании: "clash", "pending" или null (проблем нет или
// этапа в расписании ещё нет).
function scheduleProblem(stage) {
    if (!isInSchedule(stage)) return null;
    if (stageClashes(stage).length) return "clash";
    if (pendingCourses(stage).length) return "pending";

    return null;
}

// Насколько этап составлен: "built", "partial", "variants" или "new".
function buildState(stage) {
    if (stage.built) return "built";
    if (stage.placed) return "partial";
    if (stage.variants) return "variants";

    return "new";
}

// Код статуса этапа: сначала проблемы в принятом расписании, потом — насколько составлен.
function stageState(stage) {
    return scheduleProblem(stage) || buildState(stage);
}

// Каким этапам нужна работа и в каком порядке важности (currentStage выбирает первый):
// конфликты → неучтённые изменения → не все уроки расставлены → есть непринятые варианты →
// не составлен.
const NEEDS_WORK = ["clash", "pending", "partial", "variants", "new"];

// Статус этапа для карточек: [вид, иконка, текст]. Вид — "bad"/"warn"/"ok"/"none" (цвет значка).
function stageStatus(stage) {
    const statuses = {
        clash: () => ["bad", "alert", t("web.stage.clash")],
        pending: () => ["warn", "alert", t("web.stage.pending")],
        built: () => ["ok", "check", t("web.stage.done")],
        partial: () => ["warn", "alert", tr("web.stage.partial", { count: stage.expected - stage.placed })],
        variants: () => ["warn", "sparkles", t("web.stage.variants")],
        new: () => ["none", "clock", t("web.stage.new")],
    };

    return statuses[stageState(stage)]();
}

// Попал ли этап в принятое расписание: составлен полностью или хотя бы частично
// (placed — сколько уроков этапа уже расставлено).
function isInSchedule(stage) {
    return stage.built || stage.placed > 0;
}

// ---------------------------------------------------------------- что требует внимания

// Сколько вещей требуют внимания на вкладке «Расписание» (красное число в меню):
// преподаватели на двух уроках одновременно (каждый считается один раз),
// курсы с уроками без преподавателя, курсы, которым не хватает уроков
// (lackingCourses: только этапы, уже попавшие в принятое расписание), и предметы,
// которым не хватает свободного времени преподавателей (staffing с level "short";
// "tight" — «следующий поток не поместится» — не считается). 0 — если проект не открыт.
// Жёлтая карточка «Общий урок, когда преподаватель «не может»» (S.state.jointCannot) тоже не
// считается: это не ошибка расписания, а предупреждение — общий урок стоит там, куда его поставил
// поток-источник, преподаватель его ведёт, осталось лишь договориться и снять отметку (как «tight»,
// это повод проверить, а не то, что мешает работать с расписанием).
function attentionCount() {
    const state = S.state;

    if (!state) return 0;

    const clashTeachers = new Set((state.clashes || []).map(([teacher]) => teacher)).size;
    const understaffed = (state.staffing || []).filter((item) => item.level === "short").length;

    return clashTeachers + (state.noTeacher || []).length + lackingCourses().length + understaffed;
}

// ---------------------------------------------------------------- идёт сборка

// Идёт ли в открытом проекте сборка вариантов (S.state.job с сервера; его обновляет опрос
// pollJob на вкладке «Запуск», а когда сборка кончается, страница перерисовывается).
function isBuilding() {
    return Boolean(S.state?.job?.running);
}

// Подпись над закрытыми во время сборки настройками («Запуск», «Настройки»): почему их не изменить.
// Сервер такие правки тоже не примет (web.error.busy).
function buildingNote() {
    return h("p", { class: "build-note" }, icon("lock"), h("span", {}, t("web.run.locked")));
}
