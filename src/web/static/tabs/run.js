"use strict";

/* ============================================================================
   tabs/run.js — вкладка «Запуск»: ползунки важности и весов (levelSlider),
   тщательность и число вариантов, свои правила (окно penaltyDialog), запуск и
   остановка сборки, опрос хода сборки pollJob() и журнал решателя.
   Пара на сервере — src/web/tabs/run.py.
   Берёт из других файлов: S, HOOKS, t, tr, fieldLabel, act, api, remember
   (core.js); элементы интерфейса из ui.js; currentStage, dayName,
   isInSchedule, pendingCourses, courseByName, allJoint, buildState, stageStatus, buildingNote (domain.js); RENDERERS,
   render, switchTab (shell.js).
   Отдаёт: RENDERERS.run (pollJob зовут только сама вкладка и её подписка на
   HOOKS.projectOpened; другие вкладки узнают о конце сборки по HOOKS.buildFinished).
   При загрузке подписывается на HOOKS.projectOpened: открытый проект сразу
   проверяется на идущую сборку (pollJob). Когда сборка закончилась, сообщает об
   этом другим вкладкам событием HOOKS.buildFinished.

   Вкладка собирается из карточек: слева weightsCard, solverCard, customCard,
   rulesCard; справа stagesCard и runCard (кнопки — runButtons; под статусом потока
   runStatus — линейки, которые ждут свой поток-источник, waitingNotes; поток только из
   копий — allJoint из domain.js). Окно своего правила: поля каждого шаблона — PENALTY_FORMS.
   ============================================================================ */

// ---------------------------------------------------------------- ползунки «Неважно … Очень важно» (только для «Запуска»)

// Номер деления из values, ближайшего к числу number. Близость считается по отношению
// чисел, а не по разнице (300 ближе к 100, чем к 1 000); ноль совпадает только с нулём.
function nearestLevel(values, number) {
    const distance = (a, b) => (a === b ? 0 : a <= 0 || b <= 0 ? Infinity : Math.abs(Math.log(a / b)));

    return values.reduce((best, item, at) => (distance(item, number) < distance(values[best], number) ? at : best), 0);
}

// Где на дорожке стоит деление at из count делений — в процентах от её ширины.
function levelShare(at, count) {
    return count > 1 ? at / (count - 1) * 100 : 0;
}

// Подписи делений под дорожкой: каждая стоит ровно под своим делением (крайние — по краям).
function levelTicks(labels) {
    return h("div", { class: "level-ticks" }, labels.map((label, at) => {
        const share = levelShare(at, labels.length);

        return h("span", { style: { left: `${share}%`, transform: `translateX(-${share}%)` } }, label);
    }));
}

// Подменяет подпись note полем, в которое вписывают точное число (начальное — value).
// Enter или щелчок мимо — сохранить, Esc — отменить; после этого подпись возвращается
// на место и вызывается finish(число) или finish(null), если число не вписано или неверное
// (пустое, отрицательное).
function editLevelNumber(note, value, finish) {
    const field = h("input", { type: "number", min: 0, step: 1, value, class: "level-input" });
    let done = false;
    const close = (save) => {
        if (done) return;
        done = true;

        const number = Math.round(Number(field.value));

        field.replaceWith(note);
        finish(save && field.value !== "" && Number.isFinite(number) && number >= 0 ? number : null);
    };

    field.addEventListener("keydown", (event) => {
        if (event.key === "Enter") close(true);
        if (event.key === "Escape") { event.stopPropagation(); close(false); }
    });
    field.addEventListener("blur", () => close(true));
    note.replaceWith(field);
    field.focus();
    field.select();
}

// Ползунок с названными делениями вместо голого числа.
// values — числа делений по порядку, labels — их названия; value — сейчас сохранённое число.
// Ползунок встаёт на ближайшее деление (nearestLevel); если сохранённое число не совпадает
// ни с одним делением, рядом пишется «своё значение: …», и оно меняется, только когда
// человек сам сдвинет ползунок. caption(число) — пояснение под названием деления
// (например, «вес 1 500»); щелчок по нему открывает поле для точного числа
// (editLevelNumber). onchange(число) вызывается, когда выбрано новое число.
// compact — без подписей делений под дорожкой. disabled — ползунок закрыт (идёт сборка):
// дорожка недоступна, а подпись — просто текст, поле для числа не открывается.
function levelSlider({ values, labels, value, caption, onchange, compact = false, disabled = false }) {
    // Число, которое сейчас выбрано (делением или вписано руками)
    let current = value;

    const name = h("b", {}, labels[nearestLevel(values, current)]);
    const note = disabled ? h("span", { class: "level-note" })
        : h("span", { class: "level-note editable", tabindex: "0", title: t("web.level.manual_hint"), role: "button" });
    // Название и подпись деления at; own — выбрано не деление, а своё число. --fill — какая
    // часть дорожки закрашена (до ползунка)
    const show = (at, own) => {
        range.style.setProperty("--fill", `${levelShare(at, values.length)}%`);
        name.textContent = labels[at];
        note.textContent = own ? tr("web.level.own", { value: current.toLocaleString("ru-RU") }) : caption(values[at]);
    };
    // Ползунок и подписи по текущему числу
    const sync = () => {
        const at = nearestLevel(values, current);

        range.value = at;
        show(at, values[at] !== current);
    };
    const choose = (number) => {
        if (number === null || number === current) return;

        current = number;
        onchange(current);
    };
    const range = h("input", {
        type: "range", min: 0, max: values.length - 1, step: 1, value: nearestLevel(values, current), "aria-label": labels[nearestLevel(values, current)],
        disabled: disabled || null,
        oninput: (event) => show(Number(event.target.value), false),
        onchange: (event) => choose(values[Number(event.target.value)]),
    });
    const edit = () => editLevelNumber(note, current, (number) => { choose(number); sync(); });

    if (!disabled) {
        note.addEventListener("click", edit);
        note.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); edit(); } });
    }

    sync();

    return h("div", { class: `level-slider ${compact ? "compact" : ""}` },
        h("div", { class: "level-head" }, name, note),
        range,
        compact ? null : levelTicks(labels));
}

// Деления важности: доля от обычного значения правила (Неважно … Очень важно)
const IMPORTANCE = [0, 0.3, 1, 3, 10];
const importanceValues = (base) => IMPORTANCE.map((share) => Math.round(base * share));
const importanceLabels = () => IMPORTANCE.map((_, at) => t(`web.level.importance.${at}`));
// Место веса key в карточке «Что важно в расписании». Порядок задаёт сервер (S.meta.weightOrder —
// variants.WEIGHT_ORDER: сначала про линейку и уровни, потом про преподавателей), а сами веса
// в S.state.weights идут по алфавиту ключей; вес, которого нет в порядке, — в конце.
function weightOrder(key) {
    const order = S.meta.weightOrder;

    return order.includes(key) ? order.indexOf(key) : order.length;
}

// ---------------------------------------------------------------- вкладка «Запуск» (составление вариантов)

// Таймер опроса состояния сборки (pollJob)
let pollTimer = null;

// Открыли проект — сразу узнаём, не идёт ли в нём сборка (её могли запустить раньше)
HOOKS.projectOpened.push(pollJob);

// Строка хода сборки: «Вариант 2 из 5, прошло 40 с» (job — задача сборки с сервера).
function progressText(job) {
    return tr("menu.main.tab.run.progress", { number: job.number, total: job.total, seconds: job.seconds });
}

// Ширина полосы хода сборки в процентах: доля уже готовых вариантов (не меньше 4 %,
// чтобы полоса была видна с самого начала); 0 — если общее число вариантов неизвестно.
function progressPercent(job) {
    return job.total ? Math.max(4, Math.round(((job.number - 1) / job.total) * 100)) : 0;
}

// Обновляет прогресс и журнал идущей сборки прямо в существующих элементах,
// без полной перерисовки (чтобы не сбивать прокрутку и не мигать).
// job — состояние задачи с сервера ({number, total, seconds, log…}).
// Возвращает false, если нужных элементов на странице нет — тогда нужен render().
function updateRunProgress(job) {
    const text = document.getElementById("run-progress-text");
    const bar = document.getElementById("run-progress-bar");
    const log = document.querySelector('pre.console[data-keep="log"]');

    if (!text || !bar || (job.log?.length && !log)) return false;

    text.textContent = progressText(job);
    bar.style.width = `${progressPercent(job)}%`;

    if (log) {
        const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
        log.replaceChildren(...consoleLines(job.log));
        if (atBottom) log.scrollTop = log.scrollHeight;
    }

    return true;
}

// Следит за сборкой вариантов (solve.exe работает на сервере в фоне).
// Раз в секунду, пока job.running, запрашивает /job. Когда сборка закончилась —
// загружает свежее состояние проекта, сообщает вкладкам (HOOKS.buildFinished — например,
// «Предпросмотр» забывает загруженные варианты) и, если варианты получены, переходит
// на «Предпросмотр» через switchTab (вкладка запоминается, страница начинается сверху).
// На «Запуске» во время сборки обновляет прогресс на месте
// (updateRunProgress), иначе перерисовывает страницу. Ошибки сети — не страшно,
// следующий опрос попробует снова.
async function pollJob() {
    clearTimeout(pollTimer);

    if (!S.project) return;

    const wasRunning = S.state?.job?.running;
    const project = S.project;

    try {
        const job = await api(`/api/project/${encodeURIComponent(project)}/job`);

        // Пока ждали ответ, открыли другой проект: этот ответ к нему не относится
        if (S.project !== project) return;

        if (S.state) S.state.job = job;

        if (wasRunning && job && !job.running) {
            // Сборка закончилась: берём свежие статусы этапов; если варианты получены
            // (и сборку не остановили вручную), открывается «Предпросмотр» на этом этапе
            const fresh = await api(`/api/project/${encodeURIComponent(project)}`);

            if (S.project !== project) return;

            S.state = fresh;
            HOOKS.buildFinished.forEach((hook) => hook(job));

            if (job.saved && !job.stopped) {
                remember("stage", job.stage);
                // Совпавшие варианты сервер не сохраняет (job.repeats) — сообщение называет и их
                // Ни один вариант принять нельзя (build._summaryLine) — сообщение так и говорит
                toast(job.unacceptable ? tr("web.run.variants_unacceptable_short", { count: job.saved })
                    : !job.repeats ? tr("web.run.variants_ready_short", { count: job.saved })
                    : job.saved === 1 ? t("web.run.variants_all_same_short")
                    : tr("web.run.variants_ready_repeated_short", { count: job.saved, repeats: job.repeats }));
                // Сборка уже не идёт — опрашивать дальше не нужно, а switchTab сам
                // перерисует страницу
                switchTab("preview");
                return;
            }
        }
    } catch (error) { /* the next poll tries again */ }

    const running = Boolean(S.state?.job?.running);
    // Сборка идёт и «Запуск» открыт: достаточно обновить ход сборки на месте
    const updatedInPlace = S.tab === "run" && wasRunning && running && updateRunProgress(S.state.job);

    if (!updatedInPlace && (S.tab === "run" || Boolean(wasRunning) !== running)) render();
    if (running) pollTimer = setTimeout(pollJob, 1000);
}

// Текст под названием потока на вкладке «Запуск»: все курсы — копии (allJoint) или все уже
// идут; иначе какие курсы ждут нового составления (pendingCourses), иначе — насколько этап
// составлен (код buildState из domain.js). «Только копии» проверяется раньше allStarted: для
// такого этапа он тоже верен, но «все курсы уже идут» было бы неправдой.
// Конфликт преподавателей здесь не пишется: он виден на значке этапа и на «Расписании».
// stage может быть undefined — тогда пустая строка.
function runStatus(stage) {
    if (!stage) return "";
    if (allJoint(stage)) return t("web.run.all_joint");
    if (stage.allStarted) return t("web.run.all_started");

    const pending = pendingCourses(stage);

    if (pending.length) return tr("web.run.status_pending", { courses: pending.map((course) => course.name).join(", ") });

    const texts = {
        built: () => t("web.run.status_built"),
        partial: () => tr("web.run.status_partial", { count: stage.expected - stage.placed }),
        variants: () => tr("web.run.status_variants", { count: stage.variants }),
        new: () => t("web.run.status_new"),
    };

    return texts[buildState(stage)]();
}

// Строки под статусом потока: какие его линейки ждут свой поток-источник (stage.waiting с
// сервера — [{line, number}]). Их уроки встанут сами, когда примут тот поток, поэтому
// «не хватает уроков» у такого потока — не повод составлять его заново. Пусто, если ждать
// нечего или stage undefined.
function waitingNotes(stage) {
    return (stage?.waiting || []).map(({ line, number }) => h("p", { class: "hint" }, tr("web.run.joint_waiting", { line, number })));
}

// Оформление строки журнала сборки по её уровню (level — его определяет сервер, см.
// LOG_LEVELS в src/web/build.py): служебные «=== … ===», итог удачной сборки,
// предупреждения решателя, приглушённый ход отжига «Шаг …»; обычный текст — без класса.
const LOG_CLASSES = { head: "c-head", done: "c-done", warn: "c-warn", progress: "c-dim" };

// Строки журнала сборки с подсветкой по уровню. lines — [{text, level}] из job.log.
// Пустой журнал — подсказка серым.
function consoleLines(lines) {
    if (!lines?.length) return [h("span", { class: "c-empty" }, t("menu.main.tab.run.output_hint"))];

    return lines.map(({ text, level }) => h("span", { class: LOG_CLASSES[level] || "" }, `${text}\n`));
}

// Вкладка «Запуск»: слева — веса правил, настройки решателя (сколько
// перебирать, сколько вариантов), свои штрафы и список жёстких правил; справа —
// выбор потока со статусами и карточка запуска (кнопки «Составить варианты» и
// «Убрать из расписания», галочка «Оставить уже принятые уроки на месте» = keep mode,
// прогресс и журнал; во время сборки — кнопка «Остановить»).
// Во время сборки выбирать другой поток нельзя: показывается собираемый. Веса, «Как
// подбирать» и свои правила тоже закрыты — сборка уже работает по ним (сервер такие правки
// не примет); над ними подпись buildingNote. Когда сборка кончится, pollJob перерисует вкладку.
RENDERERS.run = (main) => {
    const job = S.state.job;
    const isRunning = Boolean(job?.running);
    const stage = isRunning ? job.stage : currentStage();
    const launch = runCard(job, stage);

    main.append(
        pageHead(t("menu.main.tab.run"), t("web.run.page_hint")),
        h("div", { class: "grid run" },
            h("div", { class: "stack", style: { gap: "20px" } },
                isRunning ? buildingNote() : null, weightsCard(isRunning), solverCard(isRunning), customCard(isRunning), rulesCard()),
            h("div", { class: "stack sticky", style: { gap: "20px" } }, stagesCard(stage, isRunning), launch),
        ),
    );

    // Журнал сборки прокручен вниз — видны самые свежие строки
    const log = launch.querySelector('pre.console[data-keep="log"]');
    if (log) requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
};

// Подпись под делением ползунка важности: «вес 1 500».
function weightCaption(number) {
    return tr("web.level.weight", { value: number.toLocaleString("ru-RU") });
}

// Карточка «Что важно в расписании»: веса штрафов решателя (насколько «дорого» каждое
// нарушение мягкого правила) — ползунок «Неважно … Очень важно», деления — доли
// обычного значения этого правила. locked — идёт сборка: ползунки закрыты.
function weightsCard(locked) {
    return card({ title: t("menu.main.tab.run.weights_title"), hint: t("menu.main.tab.run.weights_hint") }, h("div", { class: "fields" },
        Object.entries(S.state.weights).sort(([a], [b]) => weightOrder(a) - weightOrder(b)).map(([key, value]) => h("div", { class: "field-row slider-row" },
            h("span", { class: "label title-row" }, withDot(t(`weights.${key}`), t(`weights_hint.${key}`))),
            levelSlider({
                values: importanceValues(S.state.weightDefaults?.[key] || value || 100), labels: importanceLabels(), value,
                caption: weightCaption, disabled: locked,
                onchange: (next) => act("setWeight", { key, value: next }),
            }))),
    ));
}

// Карточка «Как подбирать» — настройки решателя: тщательность (ползунок с примерным
// временем на один вариант и на всю сборку) и сколько вариантов составлять.
// Деления тщательности (шагов решателя на вариант) задаёт сервер — S.state.iterationLevels
// (build.ITERATION_LEVELS); их подписи — web.level.effort.0, .1, … по порядку.
// locked — идёт сборка: ползунок и поле закрыты.
function solverCard(locked) {
    // Примерная скорость решателя: секунд на миллион шагов перебора
    const SECONDS_PER_MILLION = 1.2;
    const duration = (seconds) => (seconds < 60
        ? tr("web.level.seconds", { n: Math.max(1, Math.round(seconds)) })
        : tr("web.level.minutes", { n: Math.round(seconds / 60) }));
    const levels = S.state.iterationLevels;
    const iterations = levelSlider({
        values: levels, labels: levels.map((_, at) => t(`web.level.effort.${at}`)), value: S.state.iterations, disabled: locked,
        caption: (number) => tr("web.level.time", {
            one: duration(number / 1e6 * SECONDS_PER_MILLION),
            all: duration(number / 1e6 * SECONDS_PER_MILLION * S.state.variants),
        }),
        onchange: (next) => act("setNumber", { key: "iterations", value: next }),
    });

    return card({ title: t("web.run.solver") }, h("div", { class: "fields" },
        h("div", { class: "field-row slider-row" }, h("span", { class: "label title-row" }, withDot(t("menu.main.tab.run.iterations"), t("menu.main.tab.run.iterations_hint"))), iterations),
        h("div", { class: "field-row" },
            h("span", { class: "label title-row" }, withDot(t("menu.main.tab.run.variants"), t("menu.main.tab.run.variants_hint"))),
            input({ type: "number", min: 1, step: 1, value: S.state.variants, disabled: locked || null, onchange: (event) => act("setNumber", { key: "variants", value: event.target.value }) }),
        ),
    ));
}

// Карточка «Свои правила»: штрафы, созданные пользователем по шаблонам (penaltyDialog),
// у каждого — ползунок важности и кнопки «Изменить» и «Удалить». Деления ползунка — доли
// веса «Средне» своего правила, его задаёт сервер (S.meta.mediumWeight, penalties.MEDIUM_WEIGHT).
// locked — идёт сборка: ползунки и кнопки закрыты.
function customCard(locked) {
    const penaltyCard = (penalty) => h("div", { class: "item-card" },
        h("div", { class: "top" },
            h("span", { class: "name title-row" }, penalty.name, infoDot(penalty.description)),
        ),
        levelSlider({
            values: importanceValues(S.meta.mediumWeight), labels: importanceLabels(), value: penalty.weight, compact: true,
            caption: weightCaption, disabled: locked,
            onchange: (next) => act("setPenaltyWeight", { id: penalty.id, weight: next }),
        }),
        h("div", { class: "row" },
            btn(t("menu.main.tab.run.custom_edit"), () => penaltyDialog(penalty), { iconName: "pencil", size: "sm", kind: "ghost", disabled: locked }),
            btn(t("menu.main.tab.run.custom_delete"), async () => {
                if (await confirmDialog(tr("menu.main.tab.run.custom_confirm_delete", { name: penalty.name }), { danger: true })) act("deletePenalty", { id: penalty.id });
            }, { iconName: "trash", size: "sm", kind: "ghost danger", disabled: locked }),
        ),
    );

    return card({
        title: t("menu.main.tab.run.custom_title"), hint: t("menu.main.tab.run.custom_hint"),
        foot: btn(t("menu.main.tab.run.custom_add"), () => penaltyDialog(null), { iconName: "plus", size: "sm", disabled: locked }),
    }, S.state.penalties.length ? h("div", { class: "stack-sm" }, S.state.penalties.map(penaltyCard)) : h("p", { class: "hint" }, t("web.no_penalties")));
}

// Карточка «Что программа соблюдает всегда»: правила, которые решатель соблюдает всегда. Тексты —
// menu.main.tab.run.rule.1, .2, … из ru.hjson; правил столько, сколько таких ключей подряд,
// поэтому новое правило достаточно дописать в ru.hjson.
function rulesCard() {
    const rules = [];

    for (let number = 1; `menu.main.tab.run.rule.${number}` in S.i18n; number++) {
        rules.push(tr(`menu.main.tab.run.rule.${number}`, { limit: S.state.limits.max_courses_per_teacher }));
    }

    return card({ title: t("menu.main.tab.run.rules_title") }, h("ul", { class: "rules" }, rules.map((text) =>
        h("li", {}, icon("shield"), h("span", {}, text)))));
}

// Карточка «Что составить»: потоки/блоки со статусами; клик выбирает, что составлять.
// Во время сборки (isRunning) выбор закрыт, у собираемого — крутящаяся иконка.
function stagesCard(stage, isRunning) {
    const pills = h("div", { class: "stage-pills" }, S.state.stages.map((item) => {
        const [kind, iconName, text] = stageStatus(item);

        return h("button", {
            class: `stage-pill ${item.key === stage ? "active" : ""}`, disabled: isRunning || null,
            onclick: () => { remember("stage", item.key); render(); },
        },
            h("span", { class: `s-icon ${kind}` }, isRunning && item.key === stage ? icon("loader", "spin") : icon(iconName)),
            h("span", {}, h("div", { class: "s-name" }, item.label), h("div", { class: "s-status" }, text)),
        );
    }));

    return card({ title: t("web.run.stages"), hint: t("menu.main.tab.run.stages_hint") }, pills);
}

// Кнопки карточки запуска, пока сборка не идёт: «Убрать из расписания» (вопрос — с сервера), галочка
// «Оставить уже принятые уроки на месте» (keep mode) и «Составить варианты». info — выбранный этап.
// Keep mode (по умолчанию включён): решатель не трогает принятое в этом потоке и только
// добавляет недостающее. Галочка видна, только пока потоку не хватает уроков: если
// всё стоит, программе с этой галочкой нечего менять. Под галочкой — сколько уроков
// останется на месте и сколько подберёт программа (info.forecast с сервера: keep — с
// галочкой, fresh — без неё), а если курс некому вести — и сколько уроков не ставится
// (тот же текст пишет в журнал сборки build._explainPins); подпись меняется вместе с галочкой.
// Все курсы потока — копии (allJoint): кнопки закрыты, подсказка — почему; их уроки
// задаёт и убирает поток-источник.
function runButtons(stage, info) {
    const joint = Boolean(info && allJoint(info));
    // Убирать нечего, а общие уроки стоят: у своих курсов уроков нет, у копий есть (joint.waiting
    // ложно). Подсказка у закрытой кнопки — тот же текст, что отказ сервера (run.nothingToReset)
    const onlyJoint = Boolean(info && !isInSchedule(info) && info.courses.some((name) => courseByName(name)?.joint?.waiting === false));
    // Почему составлять нечего (подсказка у закрытых кнопок) или null
    const closed = joint ? t("web.run.all_joint") : info?.allStarted ? t("web.run.all_started") : null;
    const canKeep = Boolean(info && isInSchedule(info) && !closed && info.placed < info.expected);
    const forecastText = () => {
        const forecast = info.forecast[S.ui.keepAccepted !== false ? "keep" : "fresh"];
        return tr(forecast.noTeacher ? "web.run.pin_forecast_no_teacher" : "web.run.pin_forecast", forecast);
    };
    const forecast = canKeep ? h("div", { class: "hint keep-forecast" }, forecastText()) : null;

    return [
        // Вопрос «Убрать?» задаёт сервер (ask): в одном окне и общий текст, и линейки более
        // поздних потоков, чьи общие уроки уберутся тоже
        btn(t("menu.main.tab.run.reset_stage"), () => act("resetStage", { stage, ask: true }), { iconName: "undo", kind: "ghost", disabled: !(info && isInSchedule(info)) || Boolean(closed) || null, title: joint || onlyJoint ? t("web.run.nothing_to_reset_joint") : info?.allStarted ? t("web.run.nothing_to_reset") : null }),
        canKeep ? h("div", { class: "keep-box" },
            h("label", { class: "check keep-check", title: t("web.run.keep_hint") },
                h("input", { type: "checkbox", checked: S.ui.keepAccepted !== false || null, onchange: (event) => {
                    S.ui.keepAccepted = event.target.checked;
                    forecast.textContent = forecastText();
                } }),
                t("web.run.keep")),
            forecast) : null,
        btn(t("menu.main.tab.run.run_stage"), async () => {
            // Галочка не показана (оставлять нечего) — keep выключен
            await act("run", { stage, keep: canKeep && S.ui.keepAccepted !== false });
            pollJob();
        }, { iconName: "play", kind: "primary lg", disabled: Boolean(closed) || null, title: closed }),
    ];
}

// Предупреждение под статусом потока: уроки идущих курсов, которые сборка не сможет оставить как
// в расписании (stage.blockedStarted с сервера, stages.blockedStarted: «не может», урок другого потока,
// у преподавателя больше нет предмета…). Каждый вариант такой сборки сдвинет их или сменит курсу
// преподавателя, и принять его будет нельзя — завуч узнаёт об этом до сборки.
// Курсы — короткими подписями, строки «день и час: причина» — как в пометке «Предпросмотра».
function blockedNotes(stage) {
    const lessons = (stage?.blockedStarted || []).flatMap(({ course, lines }) => lines.map((line) => `${shortCourse(course)} — ${line}`));

    return lessons.length ? h("p", { class: "hint started-blocked", style: { color: "var(--warn)" } }, tr("web.run.started_blocked", { lessons: lessons.join("; ") })) : null;
}

// Карточка запуска выбранного этапа stage: название и статус (во время сборки — ход
// сборки), под ним — линейки, которые ждут свой поток-источник (waitingNotes), уроки идущих
// курсов, которые не смогут остаться как в расписании (blockedNotes), кнопки
// (runButtons или «Остановить»), полоса хода и журнал решателя.
// job — задача сборки с сервера. Элементы #run-progress-text, #run-progress-bar и журнал
// pre.console обновляет на месте updateRunProgress.
function runCard(job, stage) {
    const isRunning = Boolean(job?.running);
    const info = S.state.stages.find((item) => item.key === stage);
    const log = h("pre", { class: "console", "data-keep": "log" }, consoleLines(job?.log));
    const details = job?.log?.length ? h("details", { class: "log-details", open: S.ui.logOpen || null, ontoggle: (event) => { S.ui.logOpen = event.target.open; } },
        h("summary", {}, t("web.run.details")), log) : null;

    return h("section", { class: "card" },
        h("div", { class: "card-head" },
            h("div", { class: "grow" },
                h("h2", {}, isRunning ? `${t("web.run.building")} ${info?.label || ""}` : info?.label || ""),
                h("p", { class: "hint", id: "run-progress-text" }, isRunning ? progressText(job) : runStatus(info)),
                waitingNotes(info),
                isRunning ? null : blockedNotes(info),
            ),
            isRunning ? btn(t("menu.main.tab.run.stop"), () => act("stop"), { iconName: "stop", kind: "danger" }) : runButtons(stage, info),
        ),
        isRunning ? h("div", { style: { padding: "12px 16px 0" } }, h("div", { class: "progress" }, h("div", { id: "run-progress-bar", style: { width: `${progressPercent(job)}%` } }))) : null,
        details ? h("div", { style: { padding: "12px 16px 0" } }, details) : null,
    );
}

// ---------------------------------------------------------------- окно «Своё правило»

// Возможные значения для «к кому применять» по виду цели (penalty.target_kind.*).
function penaltyTargetValues(target) {
    if (target === "line") return [...new Set(S.state.courses.map((course) => course.line))].sort();
    if (target === "subject") return S.state.subjects;
    if (target === "course") return S.state.courses.map((course) => course.name);
    if (target === "teacher") return S.state.teachers.map((teacher) => teacher.name);

    return [];
}

// Строка «Кому» шаблона template: вид цели (все / линейка / предмет / курс /
// преподаватель — из S.meta.targets) и конкретное значение. own — сохранённые
// параметры правила. Возвращает {field, read}: field — строка из двух списков,
// read() — {target, value}.
function penaltyTargetField(template, own) {
    const kinds = S.meta.targets[template];
    const valueSelect = h("select", { class: "select grow" });
    const kindSelect = select(kinds.map((key) => [key, t(`penalty.target_kind.${key}`)]), own.target || kinds[0], () => fill());
    const fill = () => {
        const target = kindSelect.value;

        valueSelect.replaceChildren();
        valueSelect.disabled = target === "all";
        // «Все курсы»: второй список не нужен — пустой он выглядел как поломка
        valueSelect.hidden = target === "all";

        if (target === "all") return;
        if (template === "daily_limit" || target === "teacher") valueSelect.append(h("option", { value: "" }, t(`penalty.target.every_${target}`)));

        for (const item of penaltyTargetValues(target)) valueSelect.append(h("option", { value: item, selected: own.value === item || null }, item));
    };

    fill();

    return {
        field: h("div", { class: "row", style: { flexWrap: "nowrap" } }, kindSelect, valueSelect),
        read: () => ({ target: kindSelect.value, value: kindSelect.value === "all" ? "" : valueSelect.value }),
    };
}

// Поля каждого шаблона своего правила: шаблон → функция(own), где own — сохранённые
// параметры правила (или {} для нового). Функция возвращает {rows, read}: rows — пары
// [ключ подписи, поле] для формы, read() — параметры правила из полей.
//   time        — нежелательные дни и время;
//   daily_limit — не больше N уроков в день;
//   adjacent    — уроки курса не в соседние дни;
//   same_day    — пара предметов в один день.
const PENALTY_FORMS = {
    time(own) {
        const target = penaltyTargetField("time", own);
        const days = checkList([...Array(S.meta.days).keys()].map((day) => [String(day), dayName(day, true)]), (own.days || []).map(String), "days");
        const times = checkList([...new Set(S.state.grid.flat())].sort().map((time) => [time, time]), own.times || []);

        return {
            rows: [["penalty.dialog.target", target.field], ["penalty.dialog.days", days], ["penalty.dialog.times", times]],
            read: () => ({ ...target.read(), days: days.values().map(Number), times: times.values() }),
        };
    },
    daily_limit(own) {
        const target = penaltyTargetField("daily_limit", own);
        const limit = input({ type: "number", min: 0, max: S.state.maxLessons, value: own.limit ?? 3, style: { width: "100px" } });

        return {
            rows: [["penalty.dialog.target", target.field], ["penalty.dialog.limit", limit]],
            // Пустое поле — null, а не 0 (Number("") === 0 молча дал бы правило «не больше
            // 0 уроков в день»): сервер отвечает понятной ошибкой, окно остаётся открытым.
            // Дробное и отрицательное число сервер тоже не примет.
            read: () => ({ ...target.read(), limit: limit.value.trim() === "" ? null : Number(limit.value) }),
        };
    },
    adjacent(own) {
        const target = penaltyTargetField("adjacent", own);

        return { rows: [["penalty.dialog.target", target.field]], read: target.read };
    },
    same_day(own) {
        const subjects = S.state.subjects.map((subject) => [subject, subject]);
        const first = select(subjects, own.first || S.state.subjects[0], () => {});
        const second = select(subjects, own.second || S.state.subjects[1], () => {});

        return {
            rows: [["penalty.dialog.first", first], ["penalty.dialog.second", second]],
            read: () => ({ first: first.value, second: second.value }),
        };
    },
};

// Форма из пар [ключ подписи, поле]: подпись слева, поле справа.
function penaltyForm(rows) {
    return h("div", { class: "form" }, rows.map(([label, field]) => [h("label", {}, fieldLabel(label)), field]));
}

// Окно «Своё правило» (penalty = null — новое, иначе — правка существующего): название,
// шаблон (с «i»-пояснением), поля шаблона (PENALTY_FORMS) и важность. При смене шаблона
// его поля строятся заново; сохранённые параметры подставляются, только если шаблон тот же.
// Сохраняет действием savePenalty; окно остаётся открытым, если сервер отказал.
async function penaltyDialog(penalty) {
    const name = input({ value: penalty?.name || "", placeholder: t("penalty.dialog.name_placeholder") });
    const template = select(S.meta.templates.map((key) => [key, t(`penalty.template.${key}`)]), penalty?.template || "time", () => showTemplate());
    const templateDot = infoDot("");
    const fields = h("div", { class: "stack" });
    // Важность: число меняет ползунок, а читает кнопка «Сохранить»
    let weight = penalty?.weight ?? S.meta.mediumWeight;
    const weightSlider = levelSlider({
        values: importanceValues(S.meta.mediumWeight), labels: importanceLabels(), value: weight,
        caption: weightCaption,
        onchange: (next) => { weight = next; },
    });
    // Параметры правила из полей выбранного шаблона
    let read = () => ({});

    // Поля и «i»-пояснение выбранного шаблона
    const showTemplate = () => {
        const kind = template.value;
        const form = PENALTY_FORMS[kind](penalty?.template === kind ? penalty.params || {} : {});
        const hint = t(`penalty.template_hint.${kind}`);

        templateDot.dataset.tip = hint;
        templateDot.setAttribute("aria-label", hint);
        fields.replaceChildren(penaltyForm(form.rows));
        read = form.read;
    };

    showTemplate();

    await dialog(t(penalty ? "penalty.dialog.title_edit" : "penalty.dialog.title_add"), h("div", { class: "stack" },
        h("div", { class: "form" },
            h("label", {}, fieldLabel("penalty.dialog.name")), name,
            h("label", { class: "title-row" }, fieldLabel("penalty.dialog.template"), templateDot), template,
        ),
        fields,
        h("div", { class: "form" }, h("label", { class: "title-row" }, fieldLabel("penalty.dialog.weight"), infoDot(t("penalty.dialog.weight_hint"))), weightSlider),
    ), [
        [t("web.common.cancel"), null, "ghost"],
        [t("penalty.dialog.save"), async () => {
            const result = await act("savePenalty", { penalty: { id: penalty?.id, name: name.value, template: template.value, weight: Number(weight), params: read() } });
            return result ? true : undefined;
        }, "primary"],
    ], { width: 720 });
}
