Сверка T1–T5 сделана: прежние 775 тестов зелёные, падают только новые. На прежнем движке новых тестов 48: 41 красный по своей причине, 7 зелёных — это сторожа, и они должны быть зелёными и до кода. Три зелёных теста проходили без кода, я их переписал (п. 4). Тесты есть у всех AC, кроме AC-11 и AC-12: это замеры на копиях. `pyflakes tests` чистый, `src/` не тронут.

## 1. Итог прогона
`.venv/Scripts/python -m unittest discover tests`: 823 теста за 311 с, `FAILED (failures=42, errors=4)`. Это последний полный прогон. После него я перенёс один импорт в `test_preview_names_teacher_of_each_variant`, и ошибка импорта у этого теста стала падением. С этой правкой ожидается 43 падения и 3 ошибки. Её я проверил прогоном двух затронутых классов, а не полным прогоном.

- **Прежние 775:** все зелёные, среди упавших нет ни одного прежнего теста.
- **41 красный новый тест:** 46 записей, потому что у AC-10 шесть подтестов. Три записи — ошибки: импорт `teacherOverLimit` в `TeacherOverLimitTests`.
- **7 зелёных сторожей:**
  - `CompatTests.test_same_bytes_as_old_engine` и `CompatTests.test_same_seed_same_bytes` (AC-13);
  - `StructureTests.test_teacher_swap_adds_no_actions` (AC-14);
  - `CheckInputsTests.test_release_build_has_no_check` (Р-11);
  - `BetterTeacherTests.test_levels_reference_of_old_engine` (эталон AC-2);
  - `RulesWithSwapTests.test_inputs_are_what_they_claim` и `CheckInputsTests.test_inputs_have_switchable_courses` (входы AC-7 и AC-10).

## 2. AC → тест → статус

| AC | Тест | Статус |
|---|---|---|
| 1 | `test_engine_swap.BetterTeacherTests.test_busy_day_teacher_takes_the_course`, `test_possible_slots_lever` | красный: курс ведёт Иванова, а не Петрова |
| 2 | `BetterTeacherTests.test_levels_apart_fixed_by_swap` (+ эталон `test_levels_reference_of_old_engine`) | красный: «ЕГЭ продвинутый» ведёт Иванова (эталон зелёный) |
| 3 | `FixedTeacherTests.test_assigned_teacher_stays` | красный на контроле: без «ведёт» курс не переходит к Петровой |
| 4 | `KeptCoursesTests.test_running_and_kept_courses_keep_teacher`; `test_functions_solver_input.TeacherSwapInputTests.test_started_and_kept_courses_keep_their_teacher`, `test_better_teacher_wins_where_move_is_allowed` | красный: контроль хода — курс `fresh` и курс без keep не уходят к Петровой |
| 5 | `FixedTeacherTests.test_pinned_course_keeps_teacher` | красный на контроле: без закрепления курс не уходит к Петровой |
| 6 | `FixedTeacherTests.test_keep_teacher_courses_key` | красный на контроле: курс не уходит к Петровой |
| 6 | `TeacherSwapInputTests.test_sources_of_joint_lessons_keep_their_teacher`, `test_no_joint_lessons_no_keep_teacher_courses` | красный: во входе нет `keep_teacher_courses` |
| 6 | копии во входе: прежние `JointBuildTests` | зелёный (прежнее поведение) |
| 7 | `RulesWithSwapTests.test_hard_rules` (+ `test_inputs_are_what_they_claim`) | красный: «ход 4 не сменил ни одного преподавателя» на 6 входах |
| 8 | `RulesWithSwapTests.test_course_limit`; `test_engine_swap_check.CheckEnergyTests.test_limit_rejects_on_limit_input` | красный: то же; в отладочной сборке нет строки `CHECK` |
| 9 | `RulesWithSwapTests.test_one_teacher_per_course`; `CheckEnergyTests.test_missing_lessons_keep_course_teacher` | красный: то же; нет строки `CHECK` |
| 10 | `CheckEnergyTests.test_energy_by_parts_equals_full_recount` (6 подтестов) | красный: нет строки `CHECK checks=… bad=… badState=…` |
| 11 | — | не тест: замер T10 на копии данных |
| 12 | — | не тест: замер T10 на копиях `b2`/`b2u` |
| 13 | `CompatTests.test_same_bytes_as_old_engine`, `test_same_seed_same_bytes` | зелёный сторож (по PLAN) |
| 14 | прежние тесты движка, `test_solver_prints_the_same_numbers`, `test_forecast_matches_solver_line`, `StructureTests.test_teacher_swap_adds_no_actions` | зелёный сторож |
| 15 | `test_web_build.TeacherVariantsBuildTests.test_variants_differing_only_by_teacher_are_both_saved`, `test_preview_names_teacher_of_each_variant` | красный: в `/variants` нет `teacherCourses` / `teachers` |
| 16 | `test_web_tab_preview.TeacherChangeVariantsTests` (4 теста) | красный: `teacherCourses` / `teacherChanges` = None |
| 17 | `test_functions_export.ExportTeacherRowsTests` (3 теста) | красный: нет ключа `web.preview.teachers_head`, нет строки «Кто ведёт» |
| 17 | `ui.test_preview.PreviewTest.test_teacher_change_is_visible`, `test_no_teacher_block_without_changes` | красный: нет ключей ru.hjson |
| 18 | `TeacherChangeAcceptTests.test_accept_asks_about_new_teacher`, `test_accept_names_copies_of_changed_course`, `test_variant_without_teacher_change_does_not_ask_about_teachers` | красный: нет `web.preview.confirm_teacher` |
| 19 | `TeacherChangeAcceptTests.test_new_teacher_busy_at_shared_lesson` | красный: в вопросе нет абзаца `confirm_joint_conflicts` (`copyConflicts` не видит смену) |
| 20 | `test_functions_variants.TeacherOverLimitTests` (3 теста) | красный: ImportError `teacherOverLimit` |
| 20 | `TeacherChangeAcceptTests.test_accept_names_teacher_over_limit` | красный: нет `confirm_over_limit` |
| 20 | проверка «пусто» внутри тестов AC-15, AC-16, AC-18 | красный вместе с этими тестами |
| 21 | `test_web_tab_run.KeepHintTests.test_keep_hint_mentions_teachers` | красный: в подсказке нет «преподавател» |
| 22 | `test_structure.DataContractTests.test_teacher_swap_is_described`, `test_engine_header_describes_teacher_swap`, `test_teacher_swap_texts` | красный: нет §6.2-ключа, нет хода 4 в шапке solve.cpp, нет 7 ключей |

AC-17 тестами покрыт не полностью: условие «у курсов не из расписания и у копий метки нет» UI-тест проверяет только косвенно — меток ровно столько, сколько уроков у курса X.

## 3. Имена для кода

- **Движок, вход и журнал:**
  - вход: ключ `keep_teacher_courses: [курс]`; нет ключа — пусто; в нём только источники копий этапа;
  - сборка: `-DCHECK_ENERGY`, без новых флагов командной строки, проверка раз в N ≤ 100 000 шагов;
  - строка итога одна: `CHECK checks=N bad=N badState=N … limitRejects=N`;
  - строки журнала прежние: `PIN_FAILED`, `ASSIGNED_OVER`, `MISSING_TOTAL`, «Из неудобств E…», «лучшее пока B»;
  - флаги в тестах только `--iterations`, `--seed`, `--cycle`;
  - отсев Р-3 идёт по `constants`, а не по `locked`;
  - цена «без выигрыша»: на равноценных кандидатах меняется 0 курсов.
- **Сервер:**
  - `/variants`: у варианта `teachers: {курс: [имена]}` (без копий) и `teacherChanges: [{course, subject, before, after}]`;
  - у ответа `teacherCourses: [курс]`, только по не отклонённым вариантам;
  - `variants.teacherOverLimit(settings, answer, stage, variant)` → `[(имя, курсов, лимит)]`.
- **Тексты ru.hjson:**
  - `web.preview.teachers_head`, `teacher_now`, `teacher_changes` (с «1 курс»), `teacher_new`;
  - `web.preview.confirm_teacher` (строка «курс: A → B»), `confirm_teacher_joint` (номер потока), `confirm_over_limit` (имя);
  - правка `web.run.keep_hint`.
- **Вопрос при принятии:** заканчивается текстом `confirm_accept`. Накладку `copyConflicts` (причина `busy`) пишет `menu.main.tab.classes.slot_busy` внутри абзаца `confirm_joint_conflicts`.
- **Страница:** `table.variants td.teacher-changed`, подсказка в `data-tip`/`title` с фамилией A. Метка `teacher_new` на `.preview-week .lesson`, в `.l-meta` — фамилия B. Ни одной русской строки в `preview.js`.
- **Excel:** в столбце A листа сравнения (строка > 2) заголовок `teachers_head`, затем строка с названием курса, в ячейках варианта — имя.
- **Документы:** в DATA_CONTRACT §6.2 `` `keep_teacher_courses` ``; в §6.4 «смена преподавател…»; в §7.6 `` `teachers` ``, `` `teacherChanges` ``, `` `teacherCourses` ``; в §4 `confirm_teacher` или «смена преподавател…». В шапке `solve.cpp` до `#include` — «смена преподавателя». Действий по-прежнему 35.

## 4. Что исправил
- **`tests/__init__.py`:** в раскладку добавлены `test_engine_swap`, `test_engine_swap_check`, `fixtures/engine_compat/` и абзац о том, где лежат остальные тесты смены преподавателя.
- **`tests/test_functions_solver_input.py`:**
  - `test_started_and_kept_courses_keep_their_teacher` проходил без кода. Теперь в тех же прогонах проверяется, что `fresh` ведёт Петрова. На черновике `solve_swap.exe` оба теста AC-4 проходят.
  - Из `test_better_teacher_wins_where_move_is_allowed` убрана повторившаяся половина с keep.
  - `test_no_joint_lessons_no_keep_teacher_courses` проходил без кода. Теперь после `markJoint` у этапа «1» ключ должен содержать источники, а у этапов «2» и «3» оставаться пустым.
- **`tests/test_web_build.py`:**
  - `test_variants_differing_only_by_teacher_are_both_saved` проходил без кода. Добавлена проверка `/variants`: курс есть в `teacherCourses`, у каждого варианта свой `teachers[курс]`.
  - В `test_preview_names_teacher_of_each_variant` добавлен сторож AC-20 (`teacherOverLimit` пуст). Импорт стоит после проверки полей, чтобы тест падал по отсутствию поля, а не на импорте.
- Тестов с опечатками или неверными помощниками не нашёл. Окончания строк LF сохранены во всех трёх файлах. Скрипты правок лежат в `C:\Users\isath\AppData\Local\Temp\claude\d--Work-nowork-Schedule-main\ecb4ca78-1c2c-437d-9b60-6a193537d333\scratchpad\sverka\`, там же журналы прогонов `run1.txt` и `run2.txt`.

Изменённые файлы:
- `D:\Work nowork\Schedule-main\tests\__init__.py`
- `D:\Work nowork\Schedule-main\tests\test_functions_solver_input.py`
- `D:\Work nowork\Schedule-main\tests\test_web_build.py`