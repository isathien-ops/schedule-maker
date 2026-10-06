# PLAN: «Линейка идёт вместе с Потоком N»

Спека: `SPEC.md` (AC-1…AC-38, решения Р-1…Р-10).

Прогон тестов: `.venv/Scripts/python -m unittest discover -s tests` (pytest нет). Браузерные — `tests/ui` (Playwright, msedge). Движковые используют `src/modules/solve.exe`. Если в solve.cpp есть правки новее exe, сначала пересобрать exe (`compile.bat`).

## Порядок и ворота

- **G0 — слияние другой группы.** Она сейчас правит `solver_input.py`, `state.py`, `build.py`, `run.js`, `solve.cpp`. Подзадачи с пометкой **[после G0]** начинаются только после слияния.
- Тесты (T1–T6) пишутся до кода и должны быть **красными**. После этого они заморожены: ослаблять ожидания, ставить skip или удалять тесты нельзя. Если тест кажется неверным, остановиться и спросить.
- Тексты ru.hjson (T7) — одна подзадача, один владелец файла. Остальные подзадачи только ссылаются на ключи. Правка ru.hjson — Write-скриптом, не через heredoc в Bash: там ломаются `\n`.
- `solve.cpp` **не меняется** (Р-4, вариант A). Подзадача T19 запасная: только если AC-22 не выполнится на варианте A.

## Подзадачи

### Тесты (до кода)

**T1. Общие построители для тестов.**
- Файлы: `tests/builders.py`. Новые функции:
  - `jointProject(...)`: Потоки 1–3, линейки «ЕГЭ основной» и «ЕГЭ продвинутый», разные наборы предметов, принятый Поток 1;
  - `markJoint(...)`.
- AC: основа для всех.
- Зависит: —.

**T2. [parallel] Предметный модуль `joint`.**
- Файлы: `tests/test_functions_joint.py` (новый).
- AC: 1, 2, 3, 4, 7, 8, 9, 11 (часы), 12, 19, 34 — на уровне `setJointLine`, `syncJointSettings`, `syncJointAnswer`, `jointOptions`, `jointRoot`.
- Зависит: T1.

**T3. [parallel] Подсчёты без двойного счёта.**
- Файлы: `tests/test_functions_stages.py`, `test_functions_variants.py`, `test_functions_courses.py`, `test_functions_staffing.py`, `test_functions_teacher_card.py`, `test_functions_export.py`.
- AC: 21 (метрики), 23, 25 (`isAccepted`, `changeableCourses`), 26, 27, 28, 32, 33.
- Зависит: T1.

**T4. [parallel] Вход движка и сборка. [после G0]**
- Файлы: `tests/test_functions_solver_input.py`, `tests/test_web_build.py`.
- AC: 20, 21 (копии в вариантах), 24.
- Зависит: T1, G0.

**T5. [parallel] Сервер и действия.**
- Файлы:
  - `tests/test_web_tab_classes.py` (`setJoint`, отказы, удаление источника, `newCourse`, `copyLine`, `newStream`);
  - `test_web_tab_teachers.py`, `test_web_tab_preview.py`, `test_web_tab_run.py`, `test_web_project.py`, `test_web_projects.py` (архив), `test_web_tab_export.py`;
  - `test_structure.py` (35/31 действий: всего / запрещено во время сборки, слой `joint` в DOMAIN_LAYERS).
- AC: 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 (данные), 15, 16, 17, 18, 19, 25, 34, 35, 36, 38.
- Зависит: T1.
- Тесты `test_web_state.py` (`courseInfo.joint`, `sections.joint/jointOptions`, AC-1, AC-13) — отдельно, **[после G0]**.

**T6. [parallel] Движок и страница.**
- Файлы:
  - `tests/test_engine_joint.py` (новый, AC-22 на маленьком проекте, где выровненная расстановка точно есть);
  - `tests/ui/test_joint.py` (новый, AC-1, 5, 7, 10, 13, 29, 30, 31);
  - `tests/ui/base.py`: крючок `PREPARE`, чтобы поставить отметку до заранее составленных вариантов.
- Зависит: T1. UI-часть «Запуск» (AC-13) — **[после G0]**.

После T2–T6: полный прогон, все новые тесты красные, старые зелёные. Список «AC → тест» показать пользователю.

### Код

**T7. Тексты.**
- Файлы: `src/files/bundles/ru.hjson`.
- Ключи: `web.classes.joint*`, `web.lesson.joint*`, `web.run.joint_waiting`, `web.problem.joint_waiting(_todo)`, `web.preview.joint_moves`, вопросы и сообщения `setJoint`, `web.version.joint`, абзацы в вопросах удаления, accept и resetStage, отказы «как в Потоке N», фраза об общих уроках в `menu.main.tab.run.rule.1` (`rule.12` нет, см. SPEC), `commitment_joint`, `web.state.joint`, `teachers.state_hint.joint`, `columns_hint`.
- Тексты для завуча: коротко, «линейка», «программа», падежи через `{number}`.
- AC: 38 (тексты).
- Зависит: —.

**T8. Предметный модуль `joint.py`.**
- Файлы: `src/modules/functions/joint.py` (новый), шапка-карта `src/modules/functions/__init__.py`.
- Функции: `jointSource`, `jointCopies`, `jointRoot`, `jointGroup`, `jointOptions`, `setJointLine`, `syncJointSettings`, `syncJointAnswer`.
- AC: 1, 2, 3, 4 (наследование поля), 7, 8, 9, 12, 19, 34.
- Зависит: T2 (красные тесты).

**T9. [parallel] `courses.py`.**
- Где: `teacherConflicts` (лимит и busy по корню), `peerSlotConflicts` / `slotConflicts` (соседи копии в её потоке, свои корни — не помеха), `courseStarted` / `courseLocked` по группе для источника (новая обёртка, старые функции не менять), `addCourse` / `newCourse` (наследование поля через `joint`).
- AC: 4, 11, 16, 27, 28.
- Зависит: T8, T3.

**T10. [parallel] `stages.py`.**
- Где:
  - `teacherClashes` — по корню;
  - `occupiedByOtherStages` — копии строящегося этапа дают занятость, группа считается одним курсом, копии источника строящегося этапа пропускаются. Сигнатура та же;
  - `pinnedForTeacher`;
  - `changeableCourses` — без копий;
  - `allStarted` / «все курсы — копии».
- AC: 20 (занятость, лимит), 23, 25, 26, 27.
- Зависит: T8, T3.

**T11. [parallel] `variants.py` и `ranking.py`.**
- Где:
  - `VariantWeek.copies`;
  - `teacherSlotIssues`, `teacherDays`, `missing`, `missingDetails` — без копий;
  - уровни и пары — с копиями;
  - `isAccepted` и `movedLessons` — без копий;
  - `jointMoved` для варианта источника.
- AC: 15 (сдвиг), 21, 25, 30 (данные).
- Зависит: T8, T10 (`occupiedByOtherStages`), T3.

**T12. [parallel] `staffing.py`, `teacher_card.py`, `penalties.py`.**
- Где:
  - `unplacedLessons` и `streamLoad` — без копий;
  - `lessonsInStageDates` и `own` — с признаком `joint`;
  - `teacherCourses.joint`;
  - вид commitments `"joint"`;
  - копии в `StageWeek` не считать.
- AC: 27 (карточка), 31 (данные), 33.
- Зависит: T8, T3.

**T13. [parallel] `export.py`.**
- Где: `jointNote`, книги курсов, преподавателей и календаря, листы вариантов, `teacherSheet` / `teacherCourseStates` (один курс, один урок).
- AC: 28, 32.
- Зависит: T8, T3.

**T14. [parallel] Точка синхронизации.**
- Файлы: `src/web/project.py` (`saveSettings` → `syncJointSettings`, `saveAnswer(..., settings=None)` → `syncJointAnswer`), `src/modules/functions/tree.py` (`prepareProject`: синхронизация при открытии).
- AC: 19, 34, 35, 36.
- Зависит: T8, T5.

**T15. Действия «Курсов» и «Преподавателей».**
- Файлы: `src/web/tabs/classes.py`, `src/web/tabs/teachers.py`, `src/web/actions.py` (реестр, если нужен).
- Где:
  - новое `@action(blocking=True) setJoint`: вопрос → версия → `setJointLine` → `saveSettings` → `saveAnswer` → `clearVariants`;
  - охрана «как в Потоке N» в `setHours`, `setTeacher`, `setPins`, `cycleCourse`;
  - абзацы в `confirmRemoval` для источника;
  - `newCourse`;
  - вопрос `lessonCourses` по корню.
- AC: 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 16, 19, 38 (реестр).
- Зависит: T7, T8, T9, T14, T5.

**T16. [parallel] «Предпросмотр» и «Запуск» на сервере.**
- Файлы: `src/web/tabs/preview.py` (вопрос accept: сдвиг копий и конфликты в их потоке), `src/web/tabs/run.py` (`resetStage`: вопрос про копии; «составлять нечего»; `expected` и `placed` без копий).
- AC: 13 (`run`), 15, 17, 24 (keep без копий), 25.
- Зависит: T7, T9, T10, T11, T14, T5.

**T17. Вход движка и варианты. [после G0]**
- Файлы:
  - `src/modules/functions/solver_input.py`:
    - вычесть копии в `buildStageSettings`;
    - обобщить `blockDroppedCourses` на копии;
    - цены в `class_slots` для мягких правил;
    - новый параметр `weights` (вызовы `build.py:313`, `variants.py:487`);
  - `src/web/build.py`: `_fixedCourses` с третьим набором `copies`, `_storeVariant` переносит копии, `keep` без копий.
- AC: 20, 21, 22, 24.
- Зависит: G0, T10, T11, T4.

**T18. Состояние для страницы. [после G0]**
- Файлы: `src/web/state.py`: `courseInfo.joint` и `jointWith`; у копии `hours`, `scheduled`, `slots` от источника, остальное пустое; `sectionsInfo.joint` и `jointOptions`; `noTeacherCourses` без копий; `stagesInfo.waiting`.
- AC: 1, 10, 13.
- Зависит: G0, T8, T10.

**T19. Запасной путь B: движок.**
- Файлы: `src/modules/solve.cpp`, пересборка `solve.exe`.
- Новый необязательный ключ входа: неподвижные курсы, которые участвуют в `linePeers`, `levelPeers`, `hardBlockers`.
- Запускать только если AC-22 красный после T17 и причина — вариант A. Перед этим согласовать с пользователем.
- Зависит: T17, G0.

**T20. Страница.**
- Файлы:
  - `src/web/static/tabs/classes.js`: select «Присоединяется к» в шапке `coursesCard`, `jointCell`, «ждут Поток N», пометка у источника, иконка у чипов линеек;
  - `domain.js`: `jointNote`, `lesson.joint` в `weekTable`, без копий в `lackingCourses` и `pendingCourses`;
  - `tabs/view.js`: склейка общего урока в режимах «Вся школа», «Преподаватель», «Предмет»; подписи;
  - `tabs/preview.js`: подписи, `joint_moves`, `number` в `problemsCard`;
  - `tabs/teachers.js`: commitments `"joint"`, `courseStateCell`, легенда;
  - `ui.js`: иконка `link`;
  - `app.css`: `.l-joint`, `.joint-note`, `.joint-field`.
- AC: 1, 10, 13 (Курсы, Расписание), 29, 30, 31.
- Зависит: T7, T18, T6.

**T21. «Запуск» на странице. [после G0]**
- Файлы: `src/web/static/tabs/run.js`: строка `joint_waiting` в `runStatus`. Правила 12 нет: фраза об общих уроках — в `rule.1` (SPEC, «Решено с заказчиком после реализации»).
- AC: 13.
- Зависит: G0, T7, T18.

**T22. [parallel] Документация.**
- Файлы: `DATA_CONTRACT.md` (§3.2 поле, §4 answer копий, §6.2 вход, §7.4 действие, §7.5 state, §7.7 teacher), `README.md`, `CHANGELOG.md`.
- AC: 38.
- Зависит: T8 (имена). Писать можно параллельно с кодом.

**T23. Проверка целиком.**
- Полный прогон unittest + `tests/ui`, таблица AC → тест → статус.
- Ручная проверка на временной копии проекта руководителя: импорт `Расписание_2026-27.zip`, отметка у «ЕГЭ основной» Потока 2, составить Поток 2. Сам проект не трогать, копию удалить.
- Пересборка `build.bat`, переупаковка `Расписание_для_передачи.zip`.
- Зависит: все.

## Что можно делать параллельно

| Волна | Подзадачи | Пересечения по файлам |
|---|---|---|
| 1 | T1, T7, T22 (черновик) | нет |
| 2 | T2, T3, T5, T6 (без частей «после G0») | разные файлы тестов |
| 3 | T8 | — |
| 4 | T9, T10, T12, T13, T14 | разные файлы; T11 после T10 |
| 5 | T11, T15, T16 | T15 — classes.py/teachers.py, T16 — preview.py/run.py |
| после G0 | T4, T17, T18, T21, части T5/T6 | — |
| 6 | T20, затем T23 | — |

## Риски, которые держать в голове

- Без T10 (`occupiedByOtherStages`) и T17 копии либо удвоят занятость, либо пропадут из вариантов: принятие Потока 2 удалит копии из answer.
- Двойной счёт живёт в нескольких независимых местах (T9–T13). Тест на каждое место есть в T3 — не пропускать.
- `saveAnswer` читает settings с диска. Новое действие `setJoint` обязано писать settings первым.
- `restoreVersion` и `tools/create_school_project.py` пишут answer мимо `saveAnswer`. Версия согласована сама, а проект по инструменту синхронизируется при открытии (T14).
