## Сверка тестов «линейка идёт вместе с Потоком N»: старые тесты зелёные, все новые красные

Код в `src/` не трогал. Весь набор прогнал (`discover tests`). После прогона дописал два теста и перезапустил только их модули.

### (а) Итог прогона

- **Всего 748 тестов.** В общем прогоне было 746, к ним два моих (AC-37, AC-38).
- **Старые: 612 зелёных, ни одного красного.** Красные только в новых классах `Joint*` / `ExportJoint*`, в `ExportTabTests.test_project_archive_keeps_joint_marks` и в двух обновлённых тестах `test_structure`.
- **Новые: 136, все красные.**
  - Авторы написали 134: T2 — 46, T3 — 21, T4 — 15, T5 — 34 (32 новых и 2 обновлённых в `test_structure`), T6 — 18.
  - Мои два красные: первый из-за `ModuleNotFoundError`, второй потому, что в `DATA_CONTRACT.md` нет `together_with`.
  - Модуль `unittest` насчитал failures=86, errors=56, потому что считает каждый подтест отдельно. Разных тестов — 134.
- **Новых тестов, которые проходят без кода, нет.**
- **Расхождение с базой:** было заявлено 611 старых тестов, а до этапа их получается 614 (612 и 2 обновлённых `test_structure`). Ни один из них не падает. Скорее всего, 3 теста добавила группа G0 — не проверял.
- **pyflakes по `tests`** — чисто.
- **Окончания строк:** изменённые файлы остались с LF, как были.

### (б) AC → тесты → статус

Все перечисленные тесты красные. Ни одна причина падения не оказалась ошибкой в тесте (опечатка, неверный путь, неверный помощник).

| AC | Тесты | Почему падает |
|---|---|---|
| 1 | joint `JointOptionsTests` ×4, `JointRefusalTests` ×3; state `test_joint_options_of_sections`, `test_source_courses_name_streams_going_with_them`; classes `test_set_joint_refusals_leave_project_unchanged`; ui `test_select_only…`, `test_choosing_stream_1…`, `test_source_line_names…` | нет модуля `joint`; `KeyError` `jointOptions` / `jointWith`; нет действия `setJoint` (400); нет выбора на странице |
| 2 | joint `SetJointLineTests` ×7, `JointReadingTests` ×3; classes `test_set_joint_puts_source_lessons_into_copies`; ui `test_choosing_stream_1…` | нет модуля; нет `setJoint` |
| 3 | joint `test_subject_missing_in_source…`, `…in_copy…` | нет модуля |
| 4 | joint `JointNewSubjectTests` ×3; classes `test_new_course_in_joint_line` | нет модуля; `newCourse` не ставит поле (None != 1) |
| 5 | classes `test_set_joint_over_other_lessons…`; ui `test_mark_over_own_lessons…` | нет `setJoint`; нет выбора |
| 6 | joint `test_same_lessons_already_running_allowed`; classes `test_set_joint_when_lessons_already_match` | нет модуля; нет `setJoint` |
| 7 | joint `JointRemovalTests` ×4; classes `test_unset_joint…`; ui `test_apart…` | нет модуля / действия / выбора |
| 8 | joint `test_running_copy…`, `test_not_started…`, `test_removal_refused…`; classes `test_started_copies_cannot_change_mark` | нет модуля; общий текст ошибки вместо `web.error.joint_started` |
| 9 | joint `test_copy_stream_is_not_offered`, `test_copy_as_source_refused`, `test_source_of_other_stream…`, `test_copies_of_two_streams`; classes `test_chains_are_refused` | нет модуля; нет ключа `web.error.joint_chain` |
| 10 | classes `test_copy_fields_are_closed`; teachers `test_copy_course_state_is_closed`; state `test_copy_course_takes_hours…`; ui `test_copy_cells_are_locked…` | действия над копией проходят (200); `KeyError 'joint'`; 0 ячеек `.locked` |
| 11 | joint `test_source_hours_reach_copy`, `test_copy_line_cannot_change_copy_hours`; classes `test_source_changes_reach_copies`, `test_copy_line_keeps_copy_hours`, `test_started_copy_locks_source` | нет модуля; копия не следует за источником; источник меняется, хотя копия идёт |
| 12 | joint `test_new_stream_does_not_inherit_mark`; classes `test_new_stream_does_not_inherit_mark` | нет модуля; нет ключа |
| 13 | state `test_copies_wait_for_source_stream`; preview `test_waiting_copies_are_not_missing` (в том числе «составить и принять»); ui `test_waiting_copies_on_courses_tab`, `test_waiting_copies_are_not_lacking`, `test_run_tab_names_line_waiting…` | `KeyError 'joint'`; причина `rules` вместо `joint_waiting`; на странице «— авто»; копии в «Не хватает»; нет строки `web.run.joint_waiting` |
| 14 | variants `test_waiting_copy_is_not_missing`; joint `test_copy_of_source_without_lessons_has_no_key` | `missing` = 2; нет модуля |
| 15 | preview `test_accepting_source_variant_moves_copies`, `…names_conflicts_of_copies` | нет ключей `web.preview.confirm_joint_*` |
| 16 | classes `test_source_pins_check_copy_neighbours`, `test_source_changes_reach_copies` | соседи копии не проверяются |
| 17 | run `test_reset_source_stage_asks_about_copies` | вопроса нет |
| 18 | teachers `test_deleting_source_teacher_counts_joint_lessons_once`, `test_dropping_source_subject…` | в вопросе «4 урока» вместо 2 |
| 19 | joint `JointSourceRemovedTests` ×5; classes `test_deleting_source_{course,line,stream}…`; project `test_save_drops_mark_without_source…` | нет модуля; нет ключа `web.classes.joint_remove_note`; поле остаётся |
| 20 | solver_input `JointCopiesInputTests` ×6 | копии во входе; нет «занят»; `blocked_slots` пуст; нет параметра `weights`; лимит 2 != 1 |
| 21 | variants `test_levels_and_pairs…`, `test_waiting_copy…`, `test_copy_days…`; build `test_copies_are_carried_into_every_variant…` | накладки от копий; копии в `missing`; рабочие дни 5 != 1; копии во входе |
| 22 | engine `JointStreamBuildTests` ×3 | движок переставил копию; лимит; «ЕГЭ продвинутый» не в часах копии |
| 23 | stages `test_copies_do_not_occupy_source_stage`; variants `test_accepted_copies_are_no_clash…` | «busy» от копий; `teacherClash` = 4 |
| 24 | solver_input `test_keep_and_forecast_leave_copies_out`; build `test_keep_build_leaves_copies_out…`, `test_keep_switch_does_not_count_copies` | копии в `keep` и в `constants`; переключатель `keep` считает копии |
| 25 | stages `test_copies_are_not_changeable`; variants `test_variant_is_accepted_without_copies`; preview `test_accepting_copy_stream_keeps_copies`, `test_accepting_stale_copies…`; run `test_stage_of_only_copies_has_nothing_to_build` | копии в `changeableCourses`; у `isAccepted` нет `settings=`; вопрос «переедут»; копии перезаписываются; `run` не отказывает |
| 26 | stages `test_source_and_copy_are_one_course_for_third_stream`; variants `test_limit_counts_source_and_copy_once`; solver_input `test_source_and_copy_count_as_one_course…` | двойной счёт в лимите |
| 27 | stages `test_shared_lesson_is_not_a_clash`; courses `test_copy_is_not_busy…`, `test_moving_source_lessons_ignores_copy`; teacher_card `test_shared_lessons_are_not_clashes` | пара «источник + копия» считается накладкой или «busy» |
| 28 | courses `test_source_and_copy_are_one_course_in_limit`; export `test_teacher_list_counts_shared_course_once` | отказ по лимиту; 4 урока вместо 2 |
| 29 | ui `test_copy_and_source_cards_are_signed`, `test_shared_lesson_is_one_card_without_clash` | нет подписей; есть карточка накладки |
| 30 | ui `test_stream_1_variant_moving_shared_lessons_is_marked`, `JointPreviewTest.test_copy_cards_in_stream_2_variant` | нет пометки `joint_moves`; 0 подписей из 19 |
| 31 | teacher_card `test_shared_lessons_are_joint_cells`; ui `test_shared_hours_are_together_cells`, `test_copy_in_course_table…` | вид «busy» вместо «joint»; красная ячейка; в ячейке «в расписании» |
| 32 | export `ExportJointTests` ×5 | нет пометок; общий урок дважды |
| 33 | staffing `test_waiting_copies_are_not_lacking` | «short» вместо «tight» |
| 34 | joint `JointSyncTests` ×4; project `test_first_save_aligns_copies…` | нет модуля; `saveSettings` не выравнивает часы |
| 35 | projects `test_restored_versions_bring_back_marks` | после восстановления версии `clashes` не пуст |
| 36 | projects `test_project_archive_keeps_marks`; export_tab `test_project_archive_keeps_joint_marks` | после импорта `clashes` не пуст; нет `setJoint` |
| 37 | **новый:** joint `JointOldProjectTests.test_project_without_marks_unchanged_by_sync`; плюс все 612 старых тестов зелёные | нет модуля |
| 38 | structure `test_actions_unchanged`, `test_every_module_has_a_layer`; **новый:** structure `DataContractTests.test_joint_lines_are_described` | нет `setJoint` в реестре; нет слоя `joint`; в DATA_CONTRACT нет `together_with` |

**Что автоматически не проверяется — часть AC-38 «на странице нет строк по-русски».** Общего сторожа нет, а в JS много кириллицы в блочных комментариях, так что простой поиск по тексту не годится. Частично это закрывают UI-тесты: в конце каждого вызывается `known(key)`, и тест падает, если страница показывает ключ вместо текста. Вручную: после T20 открыть разницу файлов `src/web/static/**/*.js` и проверить, что новые русские слова есть только в комментариях, а не в строках.

### (в) Имена, на которые опираются тесты

**Модуль `src/modules/functions/joint.py`, слой 3** (`DOMAIN_LAYERS`: `joint` 3; `stages`, `penalties`, `school_defaults` — 4; `solver_input` — 5; `variants` — 6; `staffing`, `teacher_card`, `export`, `tree`, `versions` — 7). В шапке `functions/__init__.py` должен упоминаться `joint.py`.
- `setJointLine(settings, section, line, source|None, answer=…, today=…)` — отказ через `ValueError`. При `source=None` сама убирает уроки бывших копий из answer.
- `syncJointSettings(settings)` и `syncJointAnswer(settings, answer)` — меняют данные на месте.
- `jointOptions(settings, section, line)` — отсортированный список, у блока `[]`.
- `jointSource(settings, group)` — имя источника или `None`, в том числе когда источник пропал.
- `jointCopies(settings)` — `{копия: источник}`, только копии с живым источником.
- `jointRoot(settings, name)`.

**Поле курса** `together_with` (int). Его ставит и `newCourse`.

**Изменённые сигнатуры:**
- `isAccepted(answer, variant, courses, settings=…)`;
- `buildStageSettings(settings, answer, stage, keep=(), weights=…)` — ключи весов `softSubjectPair`, `levelsApart`, `pairsSameDay`;
- `resetStage(stage, force=False)`;
- `saveAnswer(project, answer)` без settings читает settings с диска.

**Действие** `setJoint(section:int, line, source:int|None, force=False)`. Входит в «запрещено во время сборки». Итого 35 действий, 31 запрещено (в SPEC написано 24 — устаревшее число).

**Что получает страница:**
- `courses[*].joint = {number, stage, source, waiting}|null`, `courses[*].jointWith = [N]`;
- у копии `hours`, `scheduled`, `slots` — от источника; `assigned`, `pinned`, `options`, `busyOptions` — пустые;
- `sections[*].joint = {линейка: N}`, `sections[*].jointOptions = {линейка: [N]}`;
- `stages[*].waiting = [{line, number}]`;
- `noTeacher` и `clashes` — без копий.

**`/variants`:** `variants[*].jointMoved = [{line, number, lessons}]`; в `problems` — `{course, reason:"joint_waiting", number}`.

**`/teacher`:** в `commitments` вид `"joint"`, у курса в `subjects[].courses` — поле `joint`.

**Страница:**
- выбор — `.sticky-card select:not(tbody select)`;
- закрытые ячейки копии — `.locked`;
- подсказка «ждут Поток 1» — в `data-tip` или `title`;
- иконка `ICONS.link`;
- глобальные `remember`, `render`, `pendingActs`;
- крючок `UICase.PREPARE` в `tests/ui/base.py`.

**Ключи ru.hjson:**
- `web.classes.`: `joint_label`, `joint_apart`, `joint_with`, `joint_waiting`, `joint_waiting_hint`, `joint_confirm`, `joint_off`, `joint_remove_note`;
- `web.error.`: `joint_started` (сравнивается точно), `joint_chain`, `joint_has_copies` (в тексте «3»), `joint_locked` (в тексте «1»);
- `web.lesson.`: `joint` («вместе с Потоком {number}»), `joint_streams`;
- `web.preview.`: `joint_moves`, `confirm_joint_moved`, `confirm_joint_conflicts`;
- `web.run.`: `joint_waiting`, `confirm_reset_joint`, `all_joint` (сравнивается точно);
- `web.state.joint`, `web.version.joint`, `menu.main.tab.teachers.commitment_joint`.

### (г) Что сделал при сверке

1. **`tests/__init__.py`, раздел «Раскладка»:** добавил `test_engine_joint`, `test_functions_joint` и `ui/test_joint`. LF сохранены.
2. **AC-37 без теста** — дописал в `tests/test_functions_joint.py` `JointOldProjectTests.test_project_without_marks_unchanged_by_sync`. Проверяет: в проекте без отметок копий нет, синхронизация не меняет settings и answer, `PROJECT_FORMAT == 1`. Шапку модуля обновил.
3. **У AC-38 не была проверена часть про DATA_CONTRACT** — дописал в `tests/test_structure.py` `DataContractTests.test_joint_lines_are_described`. Проверяет, что в `DATA_CONTRACT.md` есть `together_with`, `setJoint`, `jointOptions`, `jointWith`, `joint_waiting`, `"joint"`. Шапку модуля обновил.
4. **Исправлять в тестах авторов ничего не пришлось.** Падают только новые тесты, и каждый — из-за отсутствующей функции, поля, действия, ключа или поведения.

**Что согласовать до заморозки тестов:**
- **AC-18:** в тестах в вопросе «2 урока», то есть общий урок считается один раз. Если нужно «4 урока», тест надо поменять.
- **AC-38:** в SPEC «24 запрещено», в тестах 31.
- **`stages[*].waiting`:** формат `[{line, number}]` выбрал автор T4, в SPEC его нет.
- **`isAccepted(settings=…)` и `buildStageSettings(weights=…)`:** параметры добавили авторы тестов, в SPEC их нет.
- **Риск для T17:** старый тест `test_web_build.RunJobTests.test_all_variants_use_the_input_taken_at_start` строит вход без `weights`. Если сборка начнёт передавать веса и вход от этого изменится, тест покраснеет.

**Изменённые файлы:**
- `D:\Work nowork\Schedule-main\tests\__init__.py`
- `D:\Work nowork\Schedule-main\tests\test_functions_joint.py`
- `D:\Work nowork\Schedule-main\tests\test_structure.py`