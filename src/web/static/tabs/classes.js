"use strict";

/* ============================================================================
   tabs/classes.js — вкладка «Курсы»: потоки и блоки с датами, линейки потока,
   таблица курсов линейки (преподаватель, день и время, уроков в неделю) и диалоги
   «Добавить линейку», «Добавить предмет в линейку», «День и время».
   Пара на сервере — src/web/tabs/classes.py.
   Берёт из других файлов: S, t, tr, fieldLabel, act, recall, remember (core.js);
   элементы интерфейса из ui.js; dayName, lessonTime, slotLabel, slotKey,
   slotFromKey, hasSlot, swatch, shortDate, teacherPending, pinsPending, stageLabel,
   andList, isJointCopy (domain.js); RENDERERS, render (shell.js).
   Отдаёт: RENDERERS.classes.

   Вкладка собирается сверху вниз из трёх карточек: sectionsCard (потоки и блоки),
   linesCard (линейки выбранного потока или блока), coursesCard (курсы выбранной
   линейки).
   Ячейки таблицы курсов рисуют courseTeacherCell, courseSlotsCell и courseHoursCell.

   «Присоединяется к» (.spec/joint-lines/SPEC.md): в шапке курсов линейки — выбор более раннего
   потока (jointHead; какие можно выбрать, говорит сервер: jointOptions раздела), у линейки
   потока-источника — пометка, какие потоки к ней присоединяются. У курса-копии ячейки
   закрыты «как в Потоке N» (jointCell), а пока у курса-источника нет уроков в расписании
   (поток-источник не принят или курсу там не нашлось преподавателя) — «ждут Поток N».
   У обычного курса отмеченной линейки — пометка separateNote: предмета в Потоке N нет или
   он там появился позже (тогда кнопка «Присоединить к Потоку N»).
   ============================================================================ */

// ---------------------------------------------------------------- вкладка «Курсы»

// Вкладка «Курсы»: потоки/блоки с датами → линейки выбранного потока или блока →
// таблица курсов линейки (предмет, преподаватель, день и время, уроков в неделю).
// Выбранные поток (или блок) и линейка запоминаются (ключи "section" и "line").
RENDERERS.classes = (main) => {
    const choice = classesChoice();

    main.append(
        pageHead(t("menu.main.tab.classes"), t("web.classes.page_hint")),
        // Сверху вниз: поток → его линейки → курсы выбранной линейки
        h("div", { class: "stack", style: { gap: "20px" } }, sectionsCard(choice), linesCard(choice), coursesCard(choice)),
    );
};

// Что выбрано на вкладке: {section — ключ потока/блока, current — сам поток/блок из
// S.state.sections, line — линейка (null, если линеек нет), courses — курсы линейки}.
// Запомненный выбор, которого больше нет в проекте, заменяется первым по порядку.
function classesChoice() {
    const sections = S.state.sections;
    let section = recall("section", sections[0]?.key);

    if (!sections.some((item) => item.key === section)) section = sections[0]?.key;

    const current = sections.find((item) => item.key === section);
    let line = recall("line", null);

    if (!current.lines.includes(line)) line = current.lines[0] ?? null;

    const courses = S.state.courses.filter((course) => course.section === section && course.line === line);

    return { section, current, line, courses };
}

// Карточка «Потоки»: ряд потоков и блоков (с датами и числом курсов), под ним —
// даты начала и конца выбранного. Кнопки: «+ Поток» (добавить поток) и корзина
// «Удалить поток» (подсказка у кнопки; блоки не удаляются).
function sectionsCard({ section, current }) {
    const sections = S.state.sections;
    const sectionCourses = (key) => S.state.courses.filter((course) => course.section === key).length;
    const dateField = (labelKey, infoKey, value, field) => h("label", { class: "row", style: { gap: "8px", flexWrap: "nowrap" } },
        fieldLabel(labelKey), infoDot(t(infoKey)),
        dateInput(value, (date) => act("setDates", { section, [field]: date })));

    return card({
        title: t("menu.main.tab.classes.streams"), hint: t("menu.main.tab.classes.streams_hint"),
        actions: h("div", { class: "row" },
            btn(t("web.add_stream_short"), async () => { const result = await act("newStream"); if (result) { remember("section", result.section); render(); } }, { iconName: "plus", size: "sm" }),
            btn("", () => act("deleteStream", { section }), { iconName: "trash", kind: "ghost danger icon-only", size: "sm", disabled: current.block, title: t("menu.main.tab.classes.remove_stream") }),
        ),
    },
        h("div", { class: "chip-row" }, sections.map((item, index) => [
            // Перед первым блоком — подпись «Курсы без потока» (web.blocks): дальше идут не потоки
            index > 0 && item.block && !sections[index - 1].block ? h("span", { class: "chip-sep" }, t("web.blocks")) : null,
            h("button", {
                class: `stage-pill ${item.key === section ? "active" : ""}`,
                onclick: () => { remember("section", item.key); remember("line", null); render(); },
            },
                h("span", { class: "grow" }, h("div", { class: "s-name" }, item.name), h("div", { class: "s-status" }, item.dates || "—")),
                h("span", { class: "badge" }, sectionCourses(item.key)),
            ),
        ])),
        h("div", { class: "dates-row" },
            h("span", { class: "dates-title" }, current.name),
            dateField("menu.main.tab.classes.start_date", "menu.main.tab.classes.start_date_info", current.start, "start"),
            dateField("menu.main.tab.classes.end_date", "menu.main.tab.classes.end_date_info", current.end, "end"),
        ),
    );
}

// Карточка «Линейки»: линейки выбранного потока или блока — ряд «чипсов» с цветным
// квадратиком и числом курсов (у линейки, которая идёт вместе с другим потоком или с которой
// идут другие потоки, — значок цепи и пояснение jointText при наведении). Кнопки: «+ Линейка»
// (добавить линейку) и корзина «Удалить линейку» (подсказка у кнопки).
function linesCard({ section, current, line }) {
    const courses = (name) => S.state.courses.filter((course) => course.section === section && course.line === name);

    return card({
        title: `${t("menu.main.tab.classes.lines")}: ${current.name}`, hint: t("menu.main.tab.classes.lines_hint"),
        actions: h("div", { class: "row" },
            btn(t("web.add_line_short"), () => addLineDialog(current), { iconName: "plus", size: "sm" }),
            btn("", () => act("deleteLine", { section, line }), { iconName: "trash", kind: "ghost danger icon-only", size: "sm", disabled: line === null, title: t("menu.main.tab.classes.remove_line") }),
        ),
    },
        current.lines.length
            ? h("div", { class: "chip-row" }, current.lines.map((name) => {
                const joint = jointText(current, name, courses(name));

                return h("button", {
                    class: `chip ${name === line ? "active" : ""}`, title: joint,
                    onclick: () => { remember("line", name); render(); },
                }, swatch(name), name, joint ? icon("link", "chip-joint") : null, h("span", { class: "badge" }, courses(name).length));
            }))
            : empty("layers", t("web.no_lines_title"), t("menu.main.tab.classes.no_lines")),
    );
}

// Карточка курсов выбранной линейки: таблица «предмет — преподаватель — день и
// время — уроков в неделю» и кнопки «Добавить предмет в линейку» и «Скопировать в
// другие потоки».
// Шапка «Поток — линейка» прилипает: при прокрутке длинного списка курсов видно, чьи это курсы.
// Справа в шапке — «Присоединяется к» (jointHead).
// Если в потоке нет линеек, пояснение «добавьте линейку» уже есть в карточке линеек
// выше, поэтому здесь только заголовок «Курсов пока нет».
function coursesCard({ section, current, line, courses }) {
    const streams = S.state.sections.filter((item) => !item.block);
    const days = S.state.grid.filter((times) => times.length).length;
    // Линейка присоединяется к Потоку N (source): у обычных курсов — пометка separateNote
    // (предмета в той линейке Потока N нет или он не присоединён — тогда с кнопкой «Присоединить»)
    const source = line ? current.joint?.[line] ?? null : null;

    return card({
        cls: "sticky-card",
        title: line ? h("span", {}, swatch(line), ` ${current.name} — ${line}`) : current.name,
        hint: line ? `${t("menu.main.tab.classes.hint")} ${t("menu.main.tab.classes.columns_hint")}` : null,
        actions: line ? jointHead({ section, current, line, courses }) : null,
        flush: true,
        foot: [
            btn(t("menu.main.tab.classes.add_subject"), () => addSubjectDialog(current, line, courses), { iconName: "plus", kind: "primary", size: "sm", disabled: line === null }),
            btn(t("menu.main.tab.classes.copy_line"), async () => {
                if (await confirmDialog(tr("menu.main.tab.classes.confirm_copy_line", { name: line }), { yes: t("web.copy_yes") })) act("copyLine", { section, line });
            }, { iconName: "copy", size: "sm", disabled: line === null || current.block || streams.length < 2, title: t("menu.main.tab.classes.copy_line_hint") }),
        ],
    },
        courses.length ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
            h("thead", {}, h("tr", {},
                h("th", {}, t("menu.main.tab.classes.subject")),
                h("th", { style: { width: "32%" } }, t("menu.main.tab.classes.teacher")),
                h("th", { style: { width: "30%" } }, t("menu.main.tab.classes.when")),
                h("th", { class: "center" }, t("web.hours_short")),
                h("th"),
            )),
            h("tbody", {}, courses.map((course) => h("tr", {},
                h("td", {}, h("b", {}, course.subject), source !== null && !isJointCopy(course) ? separateNote(section, line, course, source) : null),
                h("td", {}, courseTeacherCell(course)),
                h("td", {}, courseSlotsCell(course)),
                h("td", { class: "center" }, courseHoursCell(course, days)),
                h("td", { class: "right" }, btn("", () => act("deleteCourse", { course: course.name }), { iconName: "trash", kind: "ghost danger icon-only", size: "sm", title: t("menu.main.tab.classes.remove_subject") })),
            ))),
        )) : empty("layers", t("web.no_courses_title"), line ? t("web.no_courses") : null),
    );
}

// ---------------------------------------------------------------- «Присоединяется к»

// Номера потоков, которые идут вместе с курсами courses (jointWith у курсов-источников), по порядку.
function jointStreamNumbers(courses) {
    return [...new Set(courses.flatMap((course) => course.jointWith || []))].sort((a, b) => a - b);
}

// Пометка у линейки-источника по номерам потоков, которые к ней присоединяются: «К этой линейке
// присоединяется Поток 2» или «…присоединяются Потоки 2 и 3».
function joinedText(numbers) {
    return numbers.length > 1
        ? tr("web.classes.joint_with_many", { numbers: andList(numbers) })
        : tr("web.classes.joint_with", { streams: stageLabel(String(numbers[0])) });
}

// Пояснение у линейки line раздела section (courses — её курсы): «Присоединяется к: Поток 1» у
// линейки-копии или «К этой линейке присоединяется Поток 2» у линейки-источника; null — линейка
// ни с кем не связана.
function jointText(section, line, courses) {
    const source = section.joint?.[line];

    if (source !== undefined) return `${t("web.classes.joint_label")} ${stageLabel(String(source))}`;

    const streams = jointStreamNumbers(courses);

    return streams.length ? joinedText(streams) : null;
}

// Шапка таблицы курсов: выбор «Присоединяется к: [нет ▾]» (пункты — «нет» и более ранние
// потоки, где есть линейка с тем же названием и хотя бы одним таким же предметом и которые сами
// ни к кому не присоединены, — jointOptions с сервера; у Потока 1, блоков и линейки, которой
// раньше нет или у которой там нет общих предметов, выбора нет) и у линейки-источника пометка
// «К этой линейке присоединяется Поток 2».
// Выбор отправляет setJoint; вопрос «уроки уже есть…» задаёт сервер. Если курсы-копии уже идут,
// выбор закрыт: отметку не снять (сервер тоже откажет — web.error.joint_started).
function jointHead({ section, current, line, courses }) {
    const options = current.jointOptions?.[line] || [];
    const source = current.joint?.[line] ?? null;
    const streams = jointStreamNumbers(courses);
    const note = streams.length
        ? h("span", { class: "joint-note joint-with" }, icon("link"), joinedText(streams))
        : null;

    if (!options.length && source === null) return note;

    const numbers = source === null || options.includes(source) ? options : [source, ...options];
    const started = source !== null && courses.some((course) => isJointCopy(course) && course.started);
    const box = select([["", t("web.classes.joint_apart")], ...numbers.map((number) => [number, stageLabel(String(number))])], source ?? "",
        (value) => act("setJoint", { section, line, source: value ? Number(value) : null }),
        { disabled: started, title: started ? t("web.error.joint_started") : null });

    return h("div", { class: "row joint-head" }, note,
        h("label", { class: "joint-pick" }, h("span", {}, t("web.classes.joint_label")), box, infoDot(t("web.classes.joint_hint"))));
}

// Пометка у обычного курса course в линейке line раздела section, которая идёт вместе с Потоком
// number. Предмета в той линейке Потока number нет — «в Потоке 1 этого предмета нет». Есть (его
// добавили туда после отметки) — «не присоединён…» и кнопка «Присоединить к Потоку 1»: она повторяет отметку
// линейки (setJoint с тем же потоком), и курс тоже становится общим; если у него уже свои уроки,
// сервер сначала спросит.
function separateNote(section, line, course, number) {
    const there = S.state.courses.some((other) => other.section === number && other.line === line && other.subject === course.subject);

    if (!there) return h("span", { class: "joint-note" }, tr("web.classes.joint_missing", { number }));

    return h("span", { class: "joint-note" }, tr("web.classes.joint_separate", { number }), " ",
        btn(tr("web.classes.joint_join", { number }), () => act("setJoint", { section, line, source: number }),
            { iconName: "link", kind: "ghost", size: "sm", title: tr("web.classes.joint_join_hint", { number }) }));
}

// Ячейка курса-копии (преподаватель, день и время, число уроков): значение как у курса-источника,
// не меняется — значок цепи и пометка «как в Потоке N»; при наведении — где его менять.
function jointCell(course, ...content) {
    const number = course.joint.number;

    return h("span", { class: "locked joint-field has-tip", tabindex: "0", "data-tip": tr("web.error.joint_locked", { number }) },
        icon("link"), content, h("span", { class: "joint-note" }, tr("web.state.joint", { number })));
}

// ---------------------------------------------------------------- ячейки таблицы курсов

// Неизменяемое значение в ячейке идущего курса: замочек и содержимое; при наведении —
// пояснение, почему не меняется (курс уже идёт или зафиксирован, с датой ДД.ММ.ГГГГ, с которой идут
// его уроки). Дата — runningSince с сервера, а не своё start курса: курс-источник, к линейке которого
// присоединился уже идущий поток, закрыт, хотя его собственный поток ещё не начался, — его уроки уже
// ходят ученики потока-копии, и «Курс идёт с» должно назвать начало того потока. start — запасной
// вариант, если runningSince пуст.
function lockedCell(course, ...content) {
    const date = shortDate(course.runningSince || course.start, true);
    const note = tr(course.locked ? "web.course_locked" : "web.course_started_short", { date });

    return h("span", { class: "locked has-tip", tabindex: "0", "data-tip": note }, icon("lock"), content);
}

// Подпись пустого пункта в списке преподавателей курса: «без преподавателя»
// (курс идёт или уже стоит в расписании без преподавателя), «авто: <кто стоит в
// расписании>» или «— авто (выберет программа)».
function automaticTeacherLabel(course) {
    if (course.started || (course.slots.length && !course.scheduled.length && !course.assigned.length)) return t("web.classes.no_teacher");
    if (course.scheduled.length && !course.assigned.length) return `${t("menu.main.tab.classes.auto_short")}: ${course.scheduled.join(", ")}`;

    return t("web.common.auto");
}

// Пометка под ячейкой, что изменение ещё не попало в принятое расписание.
function pendingNote(iconName, text) {
    return h("span", { class: "pending-note" }, icon(iconName), text);
}

// Ячейка «Преподаватель»: список выбора или (у идущего курса с преподавателем) текст
// с замочком. Пустое значение — «авто»: преподавателя подберёт решатель. У курса-копии —
// преподаватель источника «как в Потоке N» (jointCell).
function courseTeacherCell(course) {
    if (isJointCopy(course)) return jointCell(course, course.scheduled.join(", ") || "—");

    // Курс уже идёт по принятому расписанию: преподаватель зафиксирован
    // (выбирать можно только тогда, когда у идущего курса преподавателя нет)
    if (course.started && course.scheduled.length) return lockedCell(course, course.scheduled.join(", "));

    // Преподаватели, которых нельзя поставить на уроки курса (заняты, отметили «не может»
    // или упрутся в лимит курсов; поле busyOptions с сервера), помечены в списке подписью
    // «(сейчас назначить нельзя)» (web.classes.busy_option). Зафиксированный курс (он всегда уже идёт) доходит сюда, только если в расписании
    // у него нет преподавателя, — тогда выбран пустой пункт «без преподавателя»
    const busy = course.busyOptions || [];
    const options = course.options.map((name) => [name, busy.includes(name) ? `${name} ${t("web.classes.busy_option")}` : name]);
    const box = select([["", automaticTeacherLabel(course)], ...options], course.locked ? "" : (course.assigned[0] || ""),
        (value) => act("setTeacher", { course: course.name, subject: course.subject, teacher: value || null }),
        {
            title: `${t("menu.main.tab.classes.may_teach")}: ${[...course.candidates, ...course.assigned].join(", ") || "—"}`
                + (course.forbidden.length ? `\n${t("web.state.forbidden")}: ${course.forbidden.join(", ")}` : ""),
            style: { width: "100%" },
        });

    // Выбранный преподаватель ещё не в принятом расписании (teacherPending): там у курса
    // пока никого нет ("none") или стоит другой ("other") — так будет, пока этап не составят заново
    const pending = teacherPending(course);

    if (pending === "none") {
        return h("div", { class: "stack-xs" }, box, pendingNote("alert", tr("web.classes.teacher_pending_none", { name: course.assigned[0] })));
    }

    if (pending === "other") {
        return h("div", { class: "stack-xs" }, box, pendingNote("alert", tr("web.classes.teacher_pending", { name: course.scheduled.join(", ") })));
    }

    return box;
}

// Ячейка «День и время»: уроки курса в расписании (или закреплённые, если расписания ещё нет).
// Закреплённые уроки — со значком булавки. Клик открывает pinDialog.
// У курса-копии — уроки источника «как в Потоке N», а пока у источника нет уроков в принятом
// расписании (поток-источник не принят или курсу там не нашлось преподавателя) — «ждут Поток N»
// с пояснением, когда уроки появятся (course.joint.waiting с сервера, state.py).
function courseSlotsCell(course) {
    if (isJointCopy(course) && course.joint.waiting) {
        const number = course.joint.number;

        return h("span", { class: "locked joint-field has-tip", tabindex: "0", "data-tip": tr("web.classes.joint_waiting_hint", { number }) },
            icon("clock"), tr("web.classes.joint_waiting", { number }));
    }

    if (isJointCopy(course)) return jointCell(course, course.slots.map((slot) => h("span", { class: "badge" }, slotLabel(slot))));

    const list = course.slots.length ? course.slots : course.pinned;

    // Идущий курс оставляет свои уроки на местах; недостающие добавятся
    // при «Составить варианты» на вкладке «Запуск»
    if (course.started) return lockedCell(course, list.map((slot) => h("span", { class: "badge" }, slotLabel(slot))));

    const slotBadge = (slot) => {
        const pinned = hasSlot(course.pinned, slot);

        return h("span", { class: `badge ${pinned ? "accent" : ""}` }, pinned ? icon("pin") : null, slotLabel(slot));
    };
    const button = h("button", { class: "btn sm", style: { width: "100%", justifyContent: "flex-start", gap: "4px", overflow: "hidden" }, title: t("menu.main.tab.classes.when_hint"), onclick: () => pinDialog(course) },
        list.length ? list.map(slotBadge) : h("span", { style: { color: "var(--muted)" } }, t("menu.main.tab.classes.auto_short")));

    // Время закреплено, но в принятом расписании уроки пока стоят в другом месте —
    // до следующего составления этапа
    const waiting = pinsPending(course);

    if (waiting.length) {
        return h("div", { class: "stack-xs" }, button, pendingNote("pin", tr("web.classes.pins_pending", { slots: waiting.map(slotLabel).join(", ") })));
    }

    return button;
}

// Ячейка «Уроков в неделю»: числовое поле (от 1 до числа учебных дней days) или,
// у зафиксированного курса, число с замочком; у курса-копии — число источника (jointCell).
function courseHoursCell(course, days) {
    if (isJointCopy(course)) return jointCell(course, String(course.hours));
    if (course.locked) return lockedCell(course, String(course.hours));

    return input({
        type: "number", min: 1, max: Math.max(days, 1), value: course.hours, style: { width: "64px" },
        onchange: (event) => act("setHours", { course: course.name, subject: course.subject, hours: event.target.value }),
    });
}

// Диалог «Добавить линейку» в поток/блок section: название (с подсказками из
// стандартных, которых ещё нет) и галочки предметов. После создания новая линейка
// становится выбранной.
async function addLineDialog(section) {
    const suggestions = section.suggested.filter((name) => !section.lines.includes(name));
    const name = input({ list: "line-names", value: suggestions[0] || "" });
    const subjects = checkList(S.state.subjects.map((subject) => [subject, subject]), []);

    await dialog(`${t("menu.main.tab.classes.add_line")}: ${section.name}`, h("div", { class: "stack" },
        h("datalist", { id: "line-names" }, suggestions.map((item) => h("option", { value: item }))),
        h("div", { class: "form" }, h("label", {}, fieldLabel("menu.main.tab.classes.line_name")), name),
        h("h3", {}, t("menu.main.tab.classes.line_subjects")),
        subjects,
    ), [
        [t("web.common.cancel"), null, "ghost"],
        [t("web.common.create"), async () => {
            const result = await act("newLine", { section: section.key, name: name.value, subjects: subjects.values() });
            if (!result) return undefined;

            remember("line", name.value.trim());
            render();

            return true;
        }, "primary"],
    ]);
}

// Диалог «Добавить предмет в линейку»: предлагаются только предметы, которых в ней
// ещё нет (courses — текущие курсы линейки). Если добавлять нечего — сообщение.
async function addSubjectDialog(section, line, courses) {
    const present = courses.map((course) => course.subject);
    const options = S.state.subjects.filter((subject) => !present.includes(subject));

    if (!options.length) return toast(t("web.all_subjects_added"));

    const choice = select(options.map((subject) => [subject, subject]), options[0], () => {});

    await dialog(`${t("menu.main.tab.classes.add_subject")}: ${line}`, h("div", { class: "form" }, h("label", {}, t("menu.main.tab.classes.subject")), choice), [
        [t("web.common.cancel"), null, "ghost"],
        [t("web.common.add"), async () => ((await act("newCourse", { section: section.key, line, subject: choice.value })) ? true : undefined), "primary"],
    ], { width: 480 });
}

// Диалог «День и время»: для каждого урока курса (их course.hours) можно закрепить день и
// время или оставить «— авто (выберет программа)». Подпись пустого пункта показывает, где урок
// стоит сейчас в принятом расписании. Сохраняет действием setPins.
async function pinDialog(course) {
    const options = [];

    S.state.grid.forEach((times, day) => times.forEach((time, lesson) => options.push([day, lesson])));

    const automatic = course.slots.filter((slot) => !hasSlot(course.pinned, slot));
    const selects = [...Array(course.hours).keys()].map((index) => {
        let label = t("web.common.auto");

        if (index >= course.pinned.length && index - course.pinned.length < automatic.length) {
            label = `${t("menu.main.tab.classes.auto_short")}: ${slotLabel(automatic[index - course.pinned.length])}`;
        }

        const pinned = course.pinned[index];

        return select([["", label], ...options.map(([day, lesson]) => [slotKey(day, lesson), `${dayName(day)}, ${lessonTime(day, lesson)}`])],
            pinned ? slotKey(...pinned) : "", () => {});
    });

    await dialog(`${t("menu.main.tab.classes.when")}: ${course.subject}`, h("div", { class: "stack" },
        h("p", { class: "hint title-row" }, course.name, infoDot(t("menu.main.tab.classes.when_dialog_hint"))),
        h("div", { class: "form" }, selects.map((choice, index) => [h("label", {}, tr("menu.main.tab.classes.week_lesson", { number: index + 1 })), choice])),
    ), [
        [t("web.common.cancel"), null, "ghost"],
        [t("web.common.save"), async () => {
            const slots = selects.map((choice) => choice.value).filter(Boolean).map(slotFromKey);
            return (await act("setPins", { course: course.name, subject: course.subject, slots })) ? true : undefined;
        }, "primary"],
    ], { width: 520 });
}
