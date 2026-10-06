// =====================================================================================
// solve.cpp — генератор расписания онлайн-школы («решатель», собирается в solve.exe).
// Только для Windows: windows.h нужен, чтобы консоль понимала UTF-8 (русские сообщения).
// =====================================================================================
//
// КАК ЭТО ВПИСЫВАЕТСЯ В ПРИЛОЖЕНИЕ
//   Веб-сервер (задание сборки — src/web/build.py, runJob) делит генерацию на этапы (stage):
//   например, сначала «Поток 1», потом «Поток 2», потом доп. курсы/семинары. Для каждого этапа
//   вход собирает solver_input.buildStageSettings (src/modules/functions/solver_input.py),
//   build.py пишет его в JSON и запускает этот exe. Exe строит расписание одного этапа
//   и пишет ответ в JSON. Сервер запускает exe несколько раз; каждый
//   запуск берёт случайное зерно (--seed не передаётся), поэтому получаются разные «варианты»,
//   из которых пользователь выбирает «принятое расписание» (answer.json).
//
// ВХОДНЫЕ ДАННЫЕ
//   --input   — настройки этапа: курсы (группы) с числом уроков по предметам, преподаватели
//               со слотами «не может» (free) и «может, но неудобно» (possible), курсы, которые
//               преподаватель «ведёт» (assigned), закреплённые уроки (constants), закрытые для
//               курса слоты (blocked_slots: клетки, которых нет в сетке дня; уроки других этапов
//               и курсов-копий этого этапа по программе, с которой курс не должен пересекаться;
//               время курсов, которых нет во входе, — начавшихся без преподавателя и курсов-копий
//               присоединённых линеек, — с которыми курсу нельзя совпадать), собственные штрафы
//               пользователя и цены соседей курсов-копий (custom_penalties_compiled) и т. д.
//               Лимит курсов на преподавателя — max_courses_per_teacher. keep_teacher_courses
//               (необязательный) — курсы, которым отжиг не меняет преподавателя (источники общих уроков
//               более позднего потока). Ключи, которые здесь не читаются, просто игнорируются.
//   --weights — веса штрафов из weights.json проекта (сколько «стоит» каждое неудобство).
//
// ВЫХОДНЫЕ ДАННЫЕ (--output)
//   {курс: [день][урок] -> {"subject": предмет, "teachers": [преподаватель]}}.
//   Пустая клетка — {"subject": "#", "teachers": []}.
//   Ход работы и предупреждения («[Внимание] ...», «Закреплено N из M уроков...», «Из неудобств ...»,
//   «Подбирать нечего / почти нечего ...», «Шаг N из M | ...», «Остановлено на шаге ...», «Готово: ...»)
//   печатаются в stdout — сервер читает их построчно и показывает пользователю (список строк
//   и когда они бывают — DATA_CONTRACT.md, раздел 6.4).
//
// ОСНОВНЫЕ ПОНЯТИЯ
//   Слот (slot)  — одна клетка недели: slot = день * MAX_LESSON_IN_DAY + номер урока.
//   Курс (class) — группа учеников по одному предмету, например «Поток 1 — ОГЭ — Математика».
//                  В одном слоте у курса не больше одного урока.
//   Линейка      — поле line курса (если его нет — program, если нет и его — имя курса целиком;
//                  само имя движок не разбирает). У курсов потока это ОГЭ, ЕГЭ (основной
//                  и продвинутый — два уровня одной линейки), 10 класс, 8 класс. У курса без
//                  потока (доп. курс, семинар) — линейка его блока как есть, например «Семинар ОГЭ»,
//                  но правила пар и уровней её не используют: соседи по линейке ищутся только
//                  среди курсов одного потока (linePeers, levelPeers).
//   Поток        — «Поток 1», «Поток 2»...: курсы одной линейки в одном потоке — это одни и те же
//                  ученики, поэтому для них действуют пары предметов «нельзя» (запрет)
//                  и «нежелательно» (штраф).
//   graph        — главная структура состояния: graph[строка][слот] = список рёбер (edge).
//                  Строки 1..T — преподаватели, строки T+1..T+C — курсы (общая нумерация id).
//                  У строки курса ребро хранит (id преподавателя, предмет), у строки
//                  преподавателя — (id курса, предмет). Урок всегда записан в обе строки.
//                  В клетке не больше одного ребра: у курса один урок в слоте, преподаватель
//                  ведёт один урок за раз; пустая клетка — пустой список.
//
// АЛГОРИТМ (простыми словами)
//   1. Каждому курсу (точнее, паре «курс + предмет») выбирается один преподаватель:
//      сначала «ведёт», потом лучший из «может вести» («выбор до отжига»).
//   2. Закреплённые уроки ставятся на свои места и больше никогда не двигаются.
//   3. Остальные уроки расставляются «жадно»: первым ставится урок, у которого меньше всего
//      подходящих слотов. Что не влезло — попадает в список missingLessons («не поставлено»).
//   4. Затем расписание улучшается методом ИМИТАЦИИ ОТЖИГА (simulated annealing): ходы двигают
//      уроки, а ход 4 (смена преподавателя) отдаёт курс другому преподавателю из «может вести».
//
// МАТЕМАТИКА ОТЖИГА — для неспециалиста
//   * «Энергия» (totalEnergy) — это общий штраф расписания, сумма всех «неудобств», каждое
//     со своим весом: окно у преподавателя, урок в неудобном слоте «может», нежелательная пара
//     предметов в одной линейке, уровни в разное время, собственные штрафы пользователя и т. д.
//     Чем меньше энергия, тем лучше расписание. Идеал — 0.
//   * Жёсткие правила (нельзя нарушать) в энергию НЕ входят: ходы, которые их нарушают, просто
//     не делаются (проверки canPlaceLesson, canSwapClassSlots, teacherCanAccept...). Это:
//     преподаватель не может вести два урока сразу и не работает в слотах «не может»;
//     курс не занимает закрытые слоты; пары предметов «нельзя» не встречаются в одной линейке
//     и потоке; семинар не пересекается с ЕГЭ продвинутым по тому же предмету;
//     закреплённые уроки не двигаются.
//   * Мягкие правила (желательно соблюдать) — это слагаемые энергии с весами из weights.json.
//     Два урока одного курса в день и непоставленный урок тоже входят в энергию, с огромной ценой
//     (1e6 и 2e6), но по сути это жёсткие правила. Второй урок курса в день не ставят ни жадная
//     расстановка, ни один ход отжига: слагаемое 1e6 бывает, только если так закреплено.
//     Непоставленный урок вставляется только в день, где у курса ещё нет урока; его цена 2e6
//     дороже любых других неудобств, поэтому такая вставка выгодна всегда.
//   * Шаг отжига: берём случайный «ход» (перенести урок, поменять два урока местами,
//     вставить непоставленный урок, сменить преподавателя курса), считаем изменение энергии
//     Δ = E_после − E_до.
//       - Δ ≤ 0 (стало лучше или так же) — ход принимается всегда.
//       - Δ > 0 (стало хуже) — ход принимается с вероятностью exp(−Δ/T) (правило Метрополиса).
//   * Температура T — это «готовность мириться с ухудшением». При большой T даже заметное
//     ухудшение иногда принимается; при маленькой T — почти никогда. Зачем вообще принимать
//     худшие ходы? Чтобы не застрять в «локальном минимуме»: иногда, чтобы добраться до
//     хорошего расписания, нужно сначала временно сделать хуже (например, сдвинуть урок через
//     неудобный слот, освободив место для другого).
//   * Охлаждение: прогон делится на равные циклы по --cycle шагов (по умолчанию 5 млн); если число
//     шагов на цикл не делится, циклы становятся чуть короче, чтобы и последний успел остыть. В каждом
//     цикле T уменьшается геометрически от t0 до tend: T_k = t0 * alpha^k, где
//     alpha = (tend / t0)^(1 / cycle). В начале цикла поиск «горячий» и свободно бродит, в конце
//     «холодный» и только спускается вниз. Новый цикл снова «нагревается», начиная с лучшего
//     найденного расписания: так поиск выбирается из «ямы», в которую успел спуститься.
//   * t0 по умолчанию — 0,4 от самого большого веса мягких правил (не меньше 100), tend — 1
//     (точнее, min(1, t0): t0, заданный флагом, может быть меньше 1):
//     температура соизмерима с весами, иначе тяжёлые неудобства (тысячи) нельзя было бы
//     временно ухудшить ради лучшего расписания.
//   * Лучшее состояние запоминается отдельно: из-за случайных ухудшений последнее состояние
//     не обязательно лучшее из виденных, а в ответ пишется именно лучшее.
//   * Сколько подбирать: K — уроки, которые программа может двигать (все, кроме закреплённых).
//     При K = 0 отжиг не запускается. При K ≤ 5 он останавливается раньше, если лучшее не менялось
//     1 млн шагов: у такой задачи мало допустимых расписаний, и лучшее находится за первые
//     сотни тысяч шагов.
//   * Энергия не пересчитывается целиком на каждом шаге (это дорого): считается только
//     «локальная» энергия затронутых курсов и преподавателей до и после хода (localEnergy).
//
// СМЕНА ПРЕПОДАВАТЕЛЯ (ход 4)
//   Все уроки курса по одному предмету — и поставленные, и непоставленные — отдаются другому
//   преподавателю из «может вести»; клетки уроков не двигаются. Жёстко: у нового преподавателя
//   меньше максимума курсов, и в каждой клетке курса он не «не может» и не занят. Слагаемые курса id
//   преподавателя не читают, поэтому Δ — это изменение штрафов двух преподавателей плюс маленькая
//   цена Weights::teacherChange (половина НОД цен неудобств — меньше любого настоящего выигрыша) за
//   курс, который ведёт не выбранный до отжига: смена без выигрыша не делается, а выигрыш по уровням
//   и парам приходит следующими переносами. Лучшее часто запоминается в горячей части цикла, вместе
//   со сменами, принятыми «в гору»; поэтому после возврата к лучшему (раздел 8) — доводка без случайных
//   чисел: делаются все смены с Δ < 0, в том числе возврат к выбранному до отжига, если смена ничего
//   не дала, и совместный возврат пары курсов, обменявшихся преподавателями.
//   Не меняют преподавателя («неподвижный преподаватель»): курсы с «ведёт», с закреплением времени
//   по этому предмету во входе (constants — даже если оно не встало), из keep_teacher_courses,
//   с одним кандидатом и курсы, у которых любому другому кандидату не даёт взять курс лимит
//   (existing + «ведёт»). Если таких курсов со сменой нет, ход не выбирается и лишнего случайного
//   числа не берётся: ответы и журнал те же байты, что до хода 4.
//   Лучшее состояние хранит вместе с графом преподавателя каждого курса и счётчики курсов.
//
// ОТЛАДОЧНАЯ СБОРКА (-DCHECK_ENERGY, только для тестов; в solve.exe её нет)
//   Раз в CHECK_EVERY шагов и после возврата к лучшему сравнивает энергию по частям с полным
//   пересчётом и проверяет состояние (рёбра курса и преподавателя зеркальны, у курса один
//   преподаватель, у его непоставленных уроков тот же, счётчики курсов равны пересчёту, лимит
//   соблюдён). В конце — строка «CHECK checks=… bad=… badState=… maxDiff=… limitRejects=…»
//   (limitRejects — сколько смен не сделано из-за лимита курсов).
//
// ФЛАГИ КОМАНДНОЙ СТРОКИ
//   --weights <файл>  --input <файл>  --output <файл>  --iterations <N> (число шагов отжига)
//   --seed <целое> (0 или нет флага — случайное зерно; иначе прогон точно повторяется)
//   --t0 <дробное> (начальная температура; 0 или нет флага — по весам: 0,4 × наибольший вес
//        мягких правил, не меньше 100)
//   --tend <дробное> (конечная температура; 0, нет флага или больше t0 — min(1, t0))
//   --cycle <N> (шагов в цикле, 0 — один цикл на весь прогон)
//   --cycle-from-best <0|1> (новый цикл — с лучшего расписания (1) или с текущего (0))
// КОДЫ ВЫХОДА: 0 — готово (ответ пишется, даже если часть уроков поставить не удалось);
//   не 0 — неверная командная строка (CLI11) или нечитаемый / испорченный входной файл или файл весов.

#include <bits/stdc++.h>
#include <ext/random>

// windows.h не должен объявлять макросы min/max: они ломают std::min / std::max
// (заголовки MinGW могут уже определять NOMINMAX, поэтому проверка #ifndef)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include "libs/CLI11.hpp"
#include "libs/json.hpp"

using namespace std;

using json = nlohmann::json;

// Глобальные размеры сетки и лимиты. Значения ниже — только начальные: Data() всегда
// перезаписывает их из --input до того, как они где-либо используются.
// JOB_WEEK_LENGHT — число рабочих дней недели (опечатка LENGHT историческая),
// MAX_LESSON_IN_DAY — уроков в дне (не больше 6),
// TEACHER_MAX_COURSES — сколько курсов может вести один преподаватель (Настройки).
int JOB_WEEK_LENGHT     = 5;
int MAX_LESSON_IN_DAY   = 6;
int TEACHER_MAX_COURSES = 5;

// Число слотов в неделе = дни * уроки в дне (считается в Data())
int SLOTS = 0;

// Пути к входному и выходному файлам (меняются флагами --input / --output)
string input = "settings.json";
string output = "answer.json";

// Один генератор случайных чисел на весь прогон: --seed делает прогон воспроизводимым,
// иначе зерно выбирается случайно в main()
__gnu_cxx::sfmt19937 rng;

// Случайное целое в отрезке [min, max] включительно
int randint(int min, int max) {
    std::uniform_int_distribution<int> dist(min, max);

    return dist(rng);
}

// Случайное дробное в [0, 1) — используется в правиле Метрополиса (принять ли худший ход)
double randreal() {
    std::uniform_real_distribution<double> dist(0.0, 1.0);

    return dist(rng);
}

// Форма слова при числе n для строк журнала: one — при 1, 21, 31…, few — при 2–4, 22–24…,
// many — при остальных (например, «урок», «урока», «уроков»)
const char* plural(long long n, const char* one, const char* few, const char* many) {
    if (n % 10 == 1 && n % 100 != 11) {
        return one;
    }

    return n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? few : many;
}

// Словари «id <-> имя». Нумерация общая для всего графа:
//   преподаватели — id 1..T, курсы — id T+1..T+C, предметы — свои id 1..S (отдельный счёт).
map<int, string> teacherNameByID;
map<string, int> IDByTeacherName;

map<int, string> subjectNameByID;
map<string, int> IDBySubjectName;

map<int, string> classNameByID;
map<string, int> IDByClassName;

// Закреплённый урок (constant, «закрепление» в интерфейсе): курс cls, слот и предмет.
// Преподавателя закрепление не задаёт: урок ведёт тот, кого решатель выбрал курсу
struct Constant {
    int cls, slot, subjectID;
};

// Data — все входные данные этапа, прочитанные из --input один раз (синглтон, см. getData()).
// Конструктор читает JSON, заполняет глобальные размеры (JOB_WEEK_LENGHT, SLOTS...) и словари
// id, строит списки кандидатов-преподавателей для каждого курса и отношения между курсами
// (linePeers — «соседи по линейке и потоку», hardBlockers — курсы, с которыми нельзя пересекаться).
// Ошибка открытия файла — исключение runtime_error (exe завершится с ненулевым кодом).
class Data {
public:
    // lessons[курс] = массив {"subject", "teachers": [кандидаты], "hours": уроков в неделю}
    json lessons;

    // Слоты, в которые преподаватель МОЖЕТ вести: все слоты, кроме списка "free" из
    // настроек (в настройках "free" исторически означает «не может»)
    vector<vector<int>> free;
    // Слоты, которые преподаватель может взять, но предпочёл бы не брать («может»)
    vector<vector<int>> possible;
    // Курсы, за которыми преподаватель закреплён («ведёт»): assignedTeachers[курс][предмет]
    map<string, map<string, vector<string>>> assignedTeachers;

    // Поэтапная генерация: слоты, которые курсу использовать нельзя (дыры сетки дня, уроки
    // конфликтующих программ других этапов и курсов-копий этого этапа, время курсов, которых нет
    // во входе, — начавшихся без преподавателя и курсов-копий присоединённых линеек, — с которыми
    // курсу нельзя совпадать), и сколько курсов у преподавателя уже есть на других этапах
    // (для лимита курсов)
    map<string, vector<int>> blockedSlotsByClass;
    map<string, int> existingCoursesByTeacher;

    // Собственные штрафы пользователя, уже переведённые приложением в «цены»
    json customPenalties = json::object();

    // Дни недели, в которые преподаватель уже ведёт уроки на других этапах:
    // за такие дни штраф «лишний рабочий день» (teacherWorkDays) не берётся
    map<string, vector<int>> busyDaysByTeacher;

    // Курсы, которым ход 4 не меняет преподавателя (keep_teacher_courses: источники общих уроков)
    set<string> keepTeacherCourses;

    // Имена преподавателей и курсов в порядке их id; jointSubjectPairs — пары
    // предметов «нельзя» (жёсткое правило: не в одно время внутри линейки и потока)
    vector<string> teachers, classes;
    set<pair<int, int>> jointSubjectPairs;
    // «Нежелательно»: пары предметов, которым лучше не встречаться внутри линейки и потока (мягкое правило)
    set<pair<int, int>> softSubjectPairs;

    // Линейки (ОГЭ, ЕГЭ, ...) и потоки: курсы одной линейки в одном потоке — общие ученики.
    // courseProgramByClass — программа курса (для правила «семинар не пересекается с ЕГЭ продвинутым
    // по тому же предмету»),
    // streamByClass — номер потока (-1 у курсов без потока, например семинаров),
    // nonOverlappingPrograms — пары программ, курсы которых не должны идти одновременно (в обе стороны)
    map<string, string> lineByClass;
    map<string, string> courseProgramByClass;
    map<string, int> streamByClass;
    set<pair<string, string>> nonOverlappingPrograms;

    // linePeers[id курса] — id курсов той же линейки и того же потока (проверка пар «нельзя» и
    // мягкое правило «нежелательно»); hardBlockers[id курса] — курсы, с которыми пересечение запрещено
    vector<vector<int>> linePeers;
    vector<vector<int>> hardBlockers;
    // levelPeers[id курса] — тот же предмет той же линейки и потока, но другого уровня (ЕГЭ основной
    // и ЕГЭ продвинутый): их совпадение по времени не штрафуется, наоборот — штрафуется, если они
    // идут в разное время (правило levelsApart: ученик может перейти с уровня на уровень без смены расписания)
    vector<vector<int>> levelPeers;

    // id всех курсов этапа (по ним отжиг выбирает случайный курс)
    vector<int> scheduledClasses;

    // Все закреплённые уроки из settings["constants"]
    vector<Constant> constants;

    // Часы предметов курсов, у которых нет ни одного подходящего преподавателя: они не ставятся
    // вовсе, но входят в «из M уроков» строки журнала после закреплённых уроков
    int hoursWithoutTeacher = 0;

    Data() {
        // --- Чтение файла настроек этапа ---
        ifstream file(input);

        json settings;

        if (file.is_open()) {
            settings = json::parse(file);

        } else {
            throw runtime_error("Can not open input file: " + input);
        }

        // --- Размеры недели и лимиты из «Настроек» ---
        // Уроков в дне не больше 6: столько уроков в дне допускает сетка на шаге «Настройки»
        // (grid.MAX_LESSONS_PER_DAY в Python-коде)
        JOB_WEEK_LENGHT     = settings["working_days_per_week"];
        MAX_LESSON_IN_DAY   = min(6, settings["max_lesson_count_per_day"].get<int>());

        // Сколько курсов может вести один преподаватель (не меньше 1)
        TEACHER_MAX_COURSES = max(1, settings.value("max_courses_per_teacher", 5));

        SLOTS = JOB_WEEK_LENGHT * MAX_LESSON_IN_DAY;

        // --- Курсы этапа ---
        // Каждый курс — объект custom_groups: имя, программа, линейка, номер потока.
        // Без линейки подставляется программа (без программы — имя), у курса без stream_id поток = -1
        auto customGroups = settings["classes"].value("custom_groups", json::array());

        if (customGroups.is_array() && !customGroups.empty()) {
            for (const auto& group : customGroups) {
                if (!group.is_object() || !group.contains("name") || !group["name"].is_string()) {
                    continue;
                }

                string name = group["name"];
                string program = group.value("program", name);

                classes.push_back(name);
                courseProgramByClass[name] = program;
                lineByClass[name] = group.value("line", program);
                streamByClass[name] = group.contains("stream_id") && group["stream_id"].is_number_integer() ? group["stream_id"].get<int>() : -1;
            }
        }

        // --- Преподаватели: доступные слоты ---
        // "free" в настройках = слоты «не может»; превращаем их в список разрешённых слотов.
        // "possible" = слоты «может» (разрешены, но за урок в них берётся штраф teacherPossibleSlot)
        for (auto& [teacher, value] : settings["teachers"].items()) {
            teachers.push_back(teacher);

            vector<int> exclude;

            if (value.contains("free") && value["free"].is_array()) {
                for (vector<int> element : value["free"]) {
                    exclude.push_back(MAX_LESSON_IN_DAY * element[0] + element[1]);
                }
            }

            possible.push_back(vector<int>());

            if (value.contains("possible") && value["possible"].is_array()) {
                for (vector<int> element : value["possible"]) {
                    possible.back().push_back(MAX_LESSON_IN_DAY * element[0] + element[1]);
                }
            }

            free.push_back(vector<int>());

            for (int i = 0; i < SLOTS; i++) {
                bool find = false;

                for (int j = 0; j < (int)exclude.size(); j++) {
                    if (i == exclude[j]) {
                        find = true;

                        break;
                    }
                }

                if (find) {
                    continue;
                }

                free.back().push_back(i);
            }
        }

        // --- Преподаватели: «ведёт» ---
        for (auto& [teacher, value] : settings["teachers"].items()) {
            for (auto& element : value["subjects"]) {
                string subject = element["subject"];

                // «ведёт» учитывается, только если курс есть и в списке «может вести» (classes)
                for (auto& classValue : element.value("assigned", json::array())) {
                    string cls = classValue;

                    for (auto& eligible : element["classes"]) {
                        if (eligible == cls) {
                            assignedTeachers[cls][subject].push_back(teacher);
                            break;
                        }
                    }
                }
            }
        }

        // --- Уроки курсов и кандидаты на каждый предмет курса ---
        // Для каждого предмета курса с ненулевым числом часов собираем всех преподавателей, которые
        // «может вести» этот курс. Если кандидатов нет — предупреждение, и предмет курса вообще
        // не планируется.
        for (string& cls : classes) {
            lessons[cls] = json::array();

            for (auto& [subject, count] : settings["classes"]["lessons"][cls].items()) {
                if (count == 0) {
                    continue;
                }

                vector<string> temp;

                for (string& teacher : teachers) {
                    for (auto& element : settings["teachers"][teacher]["subjects"]) {
                        if (element["subject"] == subject) {
                            bool find = false;

                            for (auto use : element["classes"]) {
                                if (use == cls) {
                                    find = true;
                                }
                            }

                            if (find) {
                                temp.push_back(teacher);
                            }
                        }
                    }
                }

                if (temp.size()) {
                    lessons[cls].push_back({{"subject", subject}, {"teachers", temp}, {"hours", count}});

                } else {
                    hoursWithoutTeacher += count.get<int>();

                    cout << "[Внимание] " << cls << ": нет преподавателя, который может вести «" << subject << "» — отметьте «ведёт» или «может вести» на шаге «Преподаватели»\n";
                }
            }
        }

        // --- Предметы получают id 1..S в порядке списка settings["subjects"] ---
        for (int idx = 0; idx < (int)settings["subjects"].size(); idx++) {
            subjectNameByID[idx + 1] = settings["subjects"][idx][0];
            IDBySubjectName[settings["subjects"][idx][0]] = idx + 1;
        }

        // --- Пары предметов «нельзя» (жёсткое правило) ---
        // Хранятся как (меньший id, больший id), чтобы порядок в паре не имел значения
        if (settings.contains("joint_subject_pairs") && settings["joint_subject_pairs"].is_array()) {
            for (const auto& pair : settings["joint_subject_pairs"]) {
                if (!pair.is_array() || pair.size() != 2 || !pair[0].is_string() || !pair[1].is_string()) {
                    continue;
                }

                string first = pair[0];
                string second = pair[1];

                if (IDBySubjectName.count(first) && IDBySubjectName.count(second)) {
                    int firstID = IDBySubjectName[first];
                    int secondID = IDBySubjectName[second];
                    jointSubjectPairs.insert({min(firstID, secondID), max(firstID, secondID)});
                } else {
                    cout << "[WARNING] unknown subject in joint_subject_pairs: " << first << " / " << second << "\n";
                }
            }
        }

        // --- Пары предметов «нежелательно» (мягкое правило, штраф softSubjectPair) ---
        // Неизвестные предметы молча пропускаются
        if (settings.contains("soft_subject_pairs") && settings["soft_subject_pairs"].is_array()) {
            for (const auto& pair : settings["soft_subject_pairs"]) {
                if (!pair.is_array() || pair.size() != 2 || !pair[0].is_string() || !pair[1].is_string()) {
                    continue;
                }

                string first = pair[0];
                string second = pair[1];

                if (IDBySubjectName.count(first) && IDBySubjectName.count(second)) {
                    int firstID = IDBySubjectName[first];
                    int secondID = IDBySubjectName[second];
                    softSubjectPairs.insert({min(firstID, secondID), max(firstID, secondID)});
                }
            }
        }

        // --- Общая нумерация строк графа: преподаватели 1..T, курсы T+1..T+C ---
        for (int idx = 0; idx < (int)teachers.size(); idx++) {
            teacherNameByID[idx + 1] = teachers[idx];
            IDByTeacherName[teachers[idx]] = idx + 1;
        }

        for (int idx = 0; idx < (int)classes.size(); idx++) {
            classNameByID[teachers.size() + idx + 1] = classes[idx];
            IDByClassName[classes[idx]] = teachers.size() + idx + 1;
        }

        scheduledClasses.clear();

        for (int idx = 0; idx < (int)classes.size(); idx++) {
            scheduledClasses.push_back(teachers.size() + idx + 1);
        }

        // --- Данные поэтапной генерации и собственные штрафы (необязательные ключи) ---
        // custom_penalties_compiled разбирается позже, в main(), когда известны все id
        if (settings.contains("custom_penalties_compiled") && settings["custom_penalties_compiled"].is_object()) {
            customPenalties = settings["custom_penalties_compiled"];
        }

        if (settings.contains("teacher_busy_days") && settings["teacher_busy_days"].is_object()) {
            for (auto& [name, days] : settings["teacher_busy_days"].items()) {
                for (const auto& day : days) {
                    busyDaysByTeacher[name].push_back(day.get<int>());
                }
            }
        }

        if (settings.contains("keep_teacher_courses") && settings["keep_teacher_courses"].is_array()) {
            for (const auto& name : settings["keep_teacher_courses"]) {
                if (name.is_string()) {
                    keepTeacherCourses.insert(name.get<string>());
                }
            }
        }

        if (settings.contains("blocked_slots") && settings["blocked_slots"].is_object()) {
            for (auto& [name, slots] : settings["blocked_slots"].items()) {
                for (const auto& slot : slots) {
                    if (slot.is_array() && slot.size() == 2) {
                        blockedSlotsByClass[name].push_back(MAX_LESSON_IN_DAY * slot[0].get<int>() + slot[1].get<int>());
                    }
                }
            }
        }

        if (settings.contains("existing_courses_by_teacher") && settings["existing_courses_by_teacher"].is_object()) {
            for (auto& [name, count] : settings["existing_courses_by_teacher"].items()) {
                if (count.is_number_integer()) {
                    existingCoursesByTeacher[name] = count.get<int>();
                }
            }
        }

        // Пары программ, которые не пересекаются (например, семинар и ЕГЭ продвинутый):
        // кладём пару в обе стороны, чтобы проверять без учёта порядка
        if (settings.contains("non_overlapping_programs") && settings["non_overlapping_programs"].is_array()) {
            for (const auto& pair : settings["non_overlapping_programs"]) {
                if (pair.is_array() && pair.size() == 2 && pair[0].is_string() && pair[1].is_string()) {
                    string first = pair[0].get<string>();
                    string second = pair[1].get<string>();

                    nonOverlappingPrograms.insert({first, second});
                    nonOverlappingPrograms.insert({second, first});
                }
            }
        }

        // Есть ли у двух курсов общий предмет (хотя бы один урок у обоих) — запрет пересечения
        // программ действует только между курсами с общим предметом
        auto shareSubject = [&](const string& first, const string& second) {
            for (auto& [subject, count] : settings["classes"]["lessons"][first].items()) {
                if (count.get<int>() > 0 && settings["classes"]["lessons"][second].value(subject, 0) > 0) {
                    return true;
                }
            }

            return false;
        };

        // --- Отношения между курсами (индексы — общие id строк графа) ---
        linePeers.assign(teachers.size() + classes.size() + 1, vector<int>());
        hardBlockers.assign(teachers.size() + classes.size() + 1, vector<int>());
        levelPeers.assign(teachers.size() + classes.size() + 1, vector<int>());

        // Главный (первый с ненулевой нагрузкой) предмет курса — у онлайн-курсов он один
        auto mainSubject = [&](const string& name) {
            for (auto& [subject, count] : settings["classes"]["lessons"][name].items()) {
                if (count.get<int>() > 0) {
                    return subject;
                }
            }

            return string();
        };

        for (int a = 0; a < (int)classes.size(); a++) {
            for (int b = 0; b < (int)classes.size(); b++) {
                if (a == b) {
                    continue;
                }

                const string& first = classes[a];
                const string& second = classes[b];
                int id = teachers.size() + a + 1;

                // Курсы без потока (семинары) стоят особняком: соседей по линейке у них нет
                if (streamByClass[first] >= 0 && streamByClass[first] == streamByClass[second] && lineByClass[first] == lineByClass[second]) {
                    // Тот же предмет на другом уровне — не «пересечение», а пара уровней
                    if (courseProgramByClass[first] != courseProgramByClass[second] && !mainSubject(first).empty() && mainSubject(first) == mainSubject(second)) {
                        levelPeers[id].push_back(teachers.size() + b + 1);
                    } else {
                        linePeers[id].push_back(teachers.size() + b + 1);
                    }
                }

                // Например, семинар по математике никогда не идёт одновременно с математикой
                // ЕГЭ продвинутого: на оба ходят одни и те же ученики
                if (nonOverlappingPrograms.count({courseProgramByClass[first], courseProgramByClass[second]}) && shareSubject(first, second)) {
                    hardBlockers[id].push_back(teachers.size() + b + 1);
                }
            }
        }

        // --- Закреплённые уроки ---
        // settings["constants"][курс]["день-урок"] = "предмет".
        // Битые записи (плохой ключ, вне сетки, неизвестный предмет) пропускаются с предупреждением;
        // значения не-строки молча пропускаются; "-" или пустая строка — «закреплено пусто»,
        // тоже пропускается.
        for (auto& [cls, items] : settings["constants"].items()) {
            if (!IDByClassName.count(cls)) {
                continue;
            }

            if (!items.is_object()) {
                continue;
            }

            for (auto& [key, value] : items.items()) {
                int day = -1, lesson = -1;

                if (sscanf(key.c_str(), "%d-%d", &day, &lesson) != 2) {
                    cout << "[WARNING] constants: bad key \"" << key << "\" for " << cls << "\n";

                    continue;
                }

                if (day < 0 || day >= JOB_WEEK_LENGHT || lesson < 0 || lesson >= MAX_LESSON_IN_DAY) {
                    cout << "[WARNING] constants: key \"" << key << "\" out of range for " << cls << "\n";

                    continue;
                }

                if (!value.is_string()) {
                    continue;
                }

                string subject = value;

                if (subject.empty() || subject == "-") {
                    continue;
                }

                if (!IDBySubjectName.count(subject)) {
                    cout << "[WARNING] constants: unknown subject \"" << subject << "\" for " << cls << "\n";

                    continue;
                }

                int slot = day * MAX_LESSON_IN_DAY + lesson;

                constants.push_back(Constant{IDByClassName[cls], slot, IDBySubjectName[subject]});
            }
        }
    }
};

// Единственный экземпляр Data: создаётся (и читает --input) при первом вызове.
// Поэтому в main() getData() вызывается только после разбора флагов.
Data& getData() {
    static Data instance;

    return instance;
}

// Ребро графа = одна запись об уроке в строке graph[строка][слот].
// В строке курса: id = преподаватель, value = предмет.
// В строке преподавателя: id = курс, value = предмет.
struct edge {
    int id = 0, value = 0;

    edge(int id_, int value_) {
        id = id_;
        value = value_;
    }
};

// ТЕКУЩЕЕ СОСТОЯНИЕ РАСПИСАНИЯ: graph[id строки][слот] = уроки в этой клетке (см. edge).
// Пустой вектор = в этом слоте ничего нет.
vector<vector<vector<edge>>> graph;
// Быстрые таблицы, заполняются в main():
//   teacherIsAllowed[преп][слот]      — преподаватель может вести в этот слот (не «не может»);
//   teacherIsInconvenient[преп][слот] — слот «может» (разрешён, но штрафуется);
//   teacherWorksOnDay[преп][день]     — в этот день преподаватель уже работает на другом этапе;
//   classIsBlocked[курс][слот]        — слот закрыт для курса (blocked_slots: дыры сетки дня,
//                                       уроки конфликтующей программы того же предмета в других
//                                       этапах и у курсов-копий этого этапа, время курсов, которых
//                                       нет во входе, — начавшихся без преподавателя и курсов-копий
//                                       присоединённых линеек, — с которыми курсу нельзя совпадать).
vector<vector<bool>> teacherIsAllowed;
vector<vector<bool>> teacherIsInconvenient;
vector<vector<bool>> teacherWorksOnDay;
vector<vector<bool>> classIsBlocked;

// Собственные штрафы пользователя, переведённые в id: цена урока в слоте, дневные лимиты,
// соседние дни, предметы в один день.
// DailyGroup — «у этих курсов вместе не больше limit уроков в день»; за каждый урок сверх
// лимита в каждый день берётся weight.
struct DailyGroup {
    vector<int> classes;
    int limit;
    float weight;
};

// customSlotPrice[строка][слот]       — доплата за урок курса/преподавателя в этом слоте;
// customTeacherDaily[преп]            — пары (лимит уроков в день, цена за каждый урок сверх);
// customDailyGroups / ...ByClass      — групповые дневные лимиты и индексы групп каждого курса;
// customAdjacent[курс]                — цена за каждую пару соседних дней, когда у курса уроки в оба;
// customSameDay[курс]                 — (курс-партнёр, цена) за каждый день, когда уроки у обоих
//                                       (запись хранится у обоих курсов пары).
vector<vector<float>> customSlotPrice;
vector<vector<pair<int, float>>> customTeacherDaily;
vector<DailyGroup> customDailyGroups;
vector<vector<int>> customDailyGroupsByClass;
vector<float> customAdjacent;
vector<vector<pair<int, float>>> customSameDay;
// Есть ли вообще хоть одна цена слота: в большинстве проектов нет, и тогда проход по слотам пропускается
bool customSlotsUsed = false;

// Занята ли клетка (строка = курс или преподаватель, слот)
inline bool occupied(int row, int slot) {
    return !graph[row][slot].empty();
}

// Предмет урока в клетке (строка, слот); 0 — клетка пуста (id предметов начинаются с 1)
inline int cellSubject(int row, int slot) {
    return graph[row][slot].empty() ? 0 : graph[row][slot][0].value;
}

// Можно ли дать преподавателю урок в слоте (жёсткое правило): слот не «не может», и в нём
// у преподавателя ещё нет урока — он ведёт один урок за раз
bool teacherCanAccept(int teacher, int slot) {
    return teacherIsAllowed[teacher][slot] && !occupied(teacher, slot);
}

// Закреплённые уроки (constants): locked[курс][слот] — id закреплённого в этом слоте предмета
// (0 — ничего не закреплено). Отжиг никогда не двигает закреплённый урок и не ставит ничего на его место.
vector<vector<int>> locked;

// Есть ли в слоте курса закреплённый урок
inline bool slotLocked(int cls, int slot) {
    return locked[cls][slot] != 0;
}

// Образуют ли два разных предмета пару «нельзя» (порядок не важен; предмет сам с собой — нет)
bool areJointSubjects(int first, int second) {
    if (first == second) {
        return false;
    }

    return getData().jointSubjectPairs.count({min(first, second), max(first, second)}) > 0;
}

// Проверка ЖЁСТКИХ правил при постановке урока предмета `incoming` курса `incomingCls` в слот `slot`:
//   * пары «нельзя» не встречаются внутри одной линейки и потока (с уроками соседей по линейке
//     в этом слоте);
//   * курсы непересекающихся программ (например, семинар и ЕГЭ продвинутый) с общим предметом
//     не делят слот (hardBlockers, см. shareSubject в Data).
// incoming = 0 — урока нет (переносить нечего, конфликта нет).
// replacedA / replacedB — курсы, чьи уроки в `slot` уходят вместе с этим ходом (их текущие
// уроки не считаются помехой). Это простые int, без выделения памяти: функция вызывается для
// каждого слота каждого хода.
// Возвращает true, если есть конфликт (ставить нельзя).
bool jointSubjectConflict(int slot, int incomingCls, int incoming, int replacedA, int replacedB) {
    Data& data = getData();

    if (incoming == 0) {
        return false;
    }

    auto replaced = [&](int cls) {
        return cls == replacedA || cls == replacedB;
    };

    for (int cls : data.hardBlockers[incomingCls]) {
        if (!replaced(cls) && occupied(cls, slot)) {
            return true;
        }
    }

    for (int cls : data.linePeers[incomingCls]) {
        if (replaced(cls) || !occupied(cls, slot)) {
            continue;
        }

        if (areJointSubjects(incoming, cellSubject(cls, slot))) {
            return true;
        }
    }

    return false;
}

// Есть ли у курса хоть один урок в дне; dayStart — номер ПЕРВОГО слота дня (день * MAX_LESSON_IN_DAY),
// а не номер дня
bool courseHasLessonOnDay(int cls, int dayStart) {
    for (int lesson = 0; lesson < MAX_LESSON_IN_DAY; lesson++) {
        if (occupied(cls, dayStart + lesson)) {
            return true;
        }
    }

    return false;
}

// Можно ли поставить урок предмета subjectID курсу cls в слот (жёсткие правила со стороны курса):
// слот открыт для курса, в нём ещё нет урока (у курса один урок в слоте),
// и не нарушаются пара «нельзя» и правило семинаров. Преподавателя здесь НЕ проверяют —
// это делает вызывающий код через teacherCanAccept.
bool canPlaceLesson(int cls, int slot, int subjectID) {
    if (classIsBlocked[cls][slot] || occupied(cls, slot)) {
        return false;
    }

    return !jointSubjectConflict(slot, cls, subjectID, cls, cls);
}

// Один урок курса, который нужно поставить: курс, предмет, его преподаватель (один и тот же
// для всех уроков курса по предмету) и имена курса и предмета (для сообщений)
struct Lesson {
    int cls, teacher, subjectID;
    string className, subjectName;
};

// Ставит урок в слот: записывает его и в строку преподавателя, и в строку курса.
// Проверок не делает — допустимость слота должна быть проверена заранее.
void placeLesson(const Lesson& item, int slot) {
    graph[item.teacher][slot].push_back(edge(item.cls, item.subjectID));
    graph[item.cls][slot].push_back(edge(item.teacher, item.subjectID));
}

// Сколько рёбер списка (клетки курса) ведёт данный преподаватель
int assignmentCount(const vector<edge>& assignments, int teacher) {
    return count_if(assignments.begin(), assignments.end(), [&](const edge& item) {
        return item.id == teacher;
    });
}

// Убирает из строки преподавателя ОДНУ запись «курс cls, предмет subjectID» в слоте
// (строку курса не трогает — это делает вызывающий код)
void removeTeacherAssignment(int teacher, int slot, int cls, int subjectID) {
    vector<edge>& assignments = graph[teacher][slot];

    for (auto it = assignments.begin(); it != assignments.end(); ++it) {
        if (it->id == cls && it->value == subjectID) {
            assignments.erase(it);
            return;
        }
    }
}

// Можно ли обменять содержимое клеток (clsA, slotA) и (clsB, slotB): урок A переедет в slotB,
// урок B — в slotA (любая из клеток может быть пустой, тогда это просто перенос).
// Проверяет жёсткие правила: закрытые слоты курсов, пары «нельзя» / семинары и
// преподавателей (слот не «не может», нет двух уроков одновременно).
// clsA может совпадать с clsB (перестановка внутри одного курса).
bool canSwapClassSlots(int clsA, int slotA, int clsB, int slotB) {
    const vector<edge>& groupA = graph[clsA][slotA];
    const vector<edge>& groupB = graph[clsB][slotB];

    if ((!groupA.empty() && classIsBlocked[clsA][slotB]) || (!groupB.empty() && classIsBlocked[clsB][slotA])) {
        return false;
    }

    if (jointSubjectConflict(slotA, clsB, cellSubject(clsB, slotB), clsA, clsB) ||
        jointSubjectConflict(slotB, clsA, cellSubject(clsA, slotA), clsA, clsB)) {
        return false;
    }

    // Каждый преподаватель обоих уроков (встреченный дважды просто проверяется дважды):
    // считаем, сколько уроков будет у него в slotA и slotB после обмена
    // (было − уходит + приходит), и сверяем с «не может» и с правилом «один урок за раз»
    for (int k = 0; k < (int)(groupA.size() + groupB.size()); k++) {
        int teacher = k < (int)groupA.size() ? groupA[k].id : groupB[k - groupA.size()].id;

        int outgoingA = assignmentCount(groupA, teacher);
        int incomingA = assignmentCount(groupB, teacher);
        int outgoingB = assignmentCount(groupB, teacher);
        int incomingB = assignmentCount(groupA, teacher);
        int finalA = graph[teacher][slotA].size() - outgoingA + incomingA;
        int finalB = graph[teacher][slotB].size() - outgoingB + incomingB;

        if ((incomingA > 0 && !teacherIsAllowed[teacher][slotA]) ||
            (incomingB > 0 && !teacherIsAllowed[teacher][slotB]) ||
            finalA > 1 || finalB > 1) {
            return false;
        }
    }

    return true;
}

// Выполняет обмен из canSwapClassSlots (без проверок): переносит записи и в строках
// преподавателей, и в строках курсов. Для одного курса (clsA == clsB) это обмен двух клеток,
// и повторный вызов с теми же аргументами возвращает всё назад.
void swapClassSlots(int clsA, int slotA, int clsB, int slotB) {
    vector<edge> groupA = graph[clsA][slotA];
    vector<edge> groupB = graph[clsB][slotB];

    for (const edge& item : groupA) removeTeacherAssignment(item.id, slotA, clsA, item.value);
    for (const edge& item : groupB) removeTeacherAssignment(item.id, slotB, clsB, item.value);
    for (const edge& item : groupA) graph[item.id][slotB].push_back(edge(clsA, item.value));
    for (const edge& item : groupB) graph[item.id][slotA].push_back(edge(clsB, item.value));

    if (clsA == clsB) {
        graph[clsA][slotA] = groupB;
        graph[clsA][slotB] = groupA;
    } else {
        graph[clsA][slotA].clear();
        graph[clsA][slotB] = groupA;
        graph[clsB][slotB].clear();
        graph[clsB][slotA] = groupB;
    }
}

// ВЕСА ШТРАФОВ («цены» неудобств). Энергия расписания = сумма (количество нарушений × вес).
// Значения ниже — по умолчанию; часть из них перезаписывается из weights.json (init).
// От весов зависит и начальная температура отжига (см. раздел 7 в main()).
struct Weights {
    // Два урока одного курса в один день: по сути жёсткое правило. Ни жадная расстановка, ни ходы
    // отжига второй урок курса в день не ставят, поэтому слагаемое бывает, только если так закреплено
    inline static float equalLessons = 1000000;
    // Урок, который генератор не смог поставить: дороже любого другого неудобства, поэтому отжиг
    // вставляет его, как только находится слот в дне, где у курса ещё нет урока, даже ценой других
    // неудобств. Второй урок курса в день ради вставки не ставится никогда (вставка не предлагает
    // такие дни). Цена фиксирована, из файла весов не читается
    inline static float missingLesson = 2000000;
    // Курс ведёт не тот преподаватель, что выбран до отжига (сменил ход 4): цена за каждый такой курс.
    // Решение заказчика: смены «без выигрыша» нет. Из файла весов не читается: main() ставит её
    // в половину НОД цен неудобств (см. раздел 3); 0,5 — если неудобств с ценой нет
    inline static float teacherChange = 0.5;
    //   teacherFreeTime    — «окна» преподавателя: за день штраф вес × (число пустых уроков
    //                         между первым и последним)^2, т. е. окна, скопившиеся в один день,
    //                         хуже, чем столько же пустых уроков вразброс по разным дням;
    //   teacherPossibleSlot — каждый урок в слоте «может»;
    //   softSubjectPair     — каждая встреча пары «нежелательно» в одном слоте внутри линейки и потока
    inline static float teacherFreeTime = 5;
    inline static float teacherPossibleSlot = 300;
    inline static float softSubjectPair = 1000;
    // Каждый урок в субботу или воскресенье; выключено (0), если файл весов не задаёт
    inline static float weekendLesson = 0;
    // Каждый день, в который преподавателю надо выйти на уроки (дни, уже занятые им на других
    // этапах, бесплатны); выключено (0) по умолчанию
    inline static float teacherWorkDays = 0;
    // Каждый урок пары уровней одного предмета (ЕГЭ осн. и ЕГЭ пр.), у которого нет пары
    // в то же время; выключено (0), если файл весов не задаёт
    inline static float levelsApart = 0;
    // Ползунок «Пары — не в один день»: каждый день, в который стоят уроки обоих курсов пары, которую
    // сдают вместе (кроме русского и математики, pairs.COMMON_SUBJECTS); пары приходят готовым
    // списком same_day_pairs; выключено (0), если вес не задан
    inline static float pairsSameDay = 0;

    // Читает веса из JSON (weights.json); отсутствующие ключи оставляют значение по умолчанию,
    // незнакомые ключи игнорируются. equalLessons и missingLesson отсюда не меняются.
    static void init(const json& data) {
        teacherFreeTime = data.value("teacherFreeTime", teacherFreeTime);
        teacherPossibleSlot = data.value("teacherPossibleSlot", teacherPossibleSlot);
        softSubjectPair = data.value("softSubjectPair", softSubjectPair);
        weekendLesson = data.value("weekendLesson", weekendLesson);
        teacherWorkDays = data.value("teacherWorkDays", teacherWorkDays);
        levelsApart = data.value("levelsApart", levelsApart);
        pairsSameDay = data.value("pairsSameDay", pairsSameDay);
    }
};

// Functions — отдельные слагаемые энергии (штрафные функции). Каждая смотрит только на одну
// строку графа (курс или преподавателя) и возвращает уже умноженную на вес сумму.
class Functions {
public:
    // Штраф за повтор предмета в один день у курса: за каждую пару уроков одного предмета
    // в дне day — Weights::equalLessons (1e6)
    static float equalLessons(int cls, int day) {
        int base = day * MAX_LESSON_IN_DAY;

        float value = 0;

        // Предметы занятых слотов дня, собранные один раз (большинство слотов курса пусты)
        int subjects[16];
        int count = 0;

        for (int i = 0; i < MAX_LESSON_IN_DAY && count < 16; i++) {
            if (occupied(cls, base + i)) {
                subjects[count++] = cellSubject(cls, base + i);
            }
        }

        if (count < 2) {
            return 0;
        }

        for (int i = 0; i < count; i++) {
            for (int j = i + 1; j < count; j++) {
                if (subjects[i] == subjects[j]) {
                    value += 1;
                }
            }
        }

        return Weights::equalLessons * value;
    }

    // Уроки курса в субботу и воскресенье (дни 5 и 6 недели, считая с 0); при 5-дневной
    // неделе таких слотов нет и штраф всегда 0
    static float weekendLesson(int cls) {
        if (Weights::weekendLesson == 0) {
            return 0;
        }

        float value = 0;

        for (int slot = 5 * MAX_LESSON_IN_DAY; slot < SLOTS; slot++) {
            value += occupied(cls, slot);
        }

        return Weights::weekendLesson * value;
    }

    // Пара уровней (a, b) одного предмета: сколько уроков не стоит в одно время с уроками другого
    // уровня — min(уроков a, уроков b) − общих слотов. 0, если меньший курс целиком совпадает с большим
    static int levelMismatch(int a, int b) {
        int own = 0, other = 0, common = 0;

        for (int slot = 0; slot < SLOTS; slot++) {
            bool x = occupied(a, slot), y = occupied(b, slot);
            own += x;
            other += y;
            common += x && y;
        }

        return max(0, min(own, other) - common);
    }

    // Мягкое правило «уровни в разное время»: сумма levelMismatch со всеми курсами другого уровня
    // того же предмета. Пара видна с обеих сторон, поэтому в totalEnergy() половина вычитается
    static float levelsApart(int cls) {
        if (Weights::levelsApart == 0) {
            return 0;
        }

        Data& data = getData();
        float value = 0;

        for (int peer : data.levelPeers[cls]) {
            value += levelMismatch(cls, peer);
        }

        return Weights::levelsApart * value;
    }

    // Число встреч пар «нежелательно» у курса, без веса: предмет курса и предмет соседа по линейке
    // и потоку в одном слоте образуют нежелательную пару. Каждая встреча видна с обоих курсов.
    // Отдельно от штрафа нужно строке хода «Шаг N из M»: при весе 0 штраф равен 0, а пары в
    // расписании остаются, и их число должно совпадать с «Предпросмотром».
    static float softSubjectPairCount(int cls) {
        Data& data = getData();

        if (data.softSubjectPairs.empty()) {
            return 0;
        }

        float value = 0;

        for (int slot = 0; slot < SLOTS; slot++) {
            if (!occupied(cls, slot)) {
                continue;
            }

            int own = cellSubject(cls, slot);

            for (int peer : data.linePeers[cls]) {
                int other = cellSubject(peer, slot);

                if (other != 0) {
                    value += data.softSubjectPairs.count({min(own, other), max(own, other)});
                }
            }
        }

        return value;
    }

    // Мягкое правило «нежелательно»: штраф за встречи пар курса (softSubjectPairCount × вес).
    // Пара видна с обеих сторон, поэтому в totalEnergy() половина вычитается
    static float softSubjectPair(int cls) {
        return Weights::softSubjectPair * softSubjectPairCount(cls);
    }

    // Число занятых слотов строки id (курс или преподаватель) в дне day (номер дня, не слота)
    static int lessonsOnDay(int id, int day) {
        int count = 0;

        for (int lesson = 0; lesson < MAX_LESSON_IN_DAY; lesson++) {
            count += occupied(id, day * MAX_LESSON_IN_DAY + lesson) ? 1 : 0;
        }

        return count;
    }

    // Собственные штрафы пользователя для курса: цена слотов, «уроки в соседние дни»,
    // «в один день с курсом X», групповые дневные лимиты. Пары и группы видны из КАЖДОГО
    // курса, который в них входит, — лишние копии убирает totalEnergy().
    static float customClass(int cls) {
        float value = 0;

        for (int slot = 0; customSlotsUsed && slot < SLOTS; slot++) {
            if (customSlotPrice[cls][slot] != 0 && occupied(cls, slot)) {
                value += customSlotPrice[cls][slot];
            }
        }

        if (customAdjacent[cls] > 0) {
            for (int day = 0; day + 1 < JOB_WEEK_LENGHT; day++) {
                if (lessonsOnDay(cls, day) && lessonsOnDay(cls, day + 1)) {
                    value += customAdjacent[cls];
                }
            }
        }

        for (auto& [partner, weight] : customSameDay[cls]) {
            for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
                if (lessonsOnDay(cls, day) && lessonsOnDay(partner, day)) {
                    value += weight;
                }
            }
        }

        for (int index : customDailyGroupsByClass[cls]) {
            DailyGroup& group = customDailyGroups[index];

            for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
                int count = 0;

                for (int member : group.classes) {
                    count += lessonsOnDay(member, day);
                }

                value += group.weight * max(0, count - group.limit);
            }
        }

        return value;
    }

    // Собственные штрафы пользователя для преподавателя: цена слотов и дневные лимиты
    // (за каждый урок сверх лимита в каждый день)
    static float customTeacher(int teacher) {
        float value = 0;

        for (int slot = 0; customSlotsUsed && slot < SLOTS; slot++) {
            if (customSlotPrice[teacher][slot] != 0 && occupied(teacher, slot)) {
                value += customSlotPrice[teacher][slot];
            }
        }

        for (auto& [limit, weight] : customTeacherDaily[teacher]) {
            for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
                value += weight * max(0, lessonsOnDay(teacher, day) - limit);
            }
        }

        return value;
    }

    // Все штрафы преподавателя за неделю:
    //   * уроки в слотах «может» (teacherPossibleSlot за каждый);
    //   * окна: за день вес × (end − start + 1 − cnt)^2, где start/end — первый и последний урок
    //     дня, cnt — уроков в дне; т. е. квадрат числа пустых уроков между первым и последним;
    //   * лишний рабочий день (teacherWorkDays), если в этот день он ещё не работает на других этапах;
    //   * собственные штрафы пользователя (customTeacher).
    static float teacherFreeTime(int teacher) {
        float value = 0;

        for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
            int base = day * MAX_LESSON_IN_DAY;

            int start = -1, end = -1, cnt = 0;

            for (int lesson = 0; lesson < MAX_LESSON_IN_DAY; lesson++) {
                if (occupied(teacher, base + lesson)) {
                    if (start == -1) {
                        start = lesson;
                    }

                    // Уроки в слотах «может» допустимы, но платные: их берут, только когда больше ничего не подходит
                    if (teacherIsInconvenient[teacher][base + lesson]) {
                        value += Weights::teacherPossibleSlot;
                    }

                    end = lesson;
                    cnt += 1;
                }
            }

            if (cnt == 0) {
                continue;
            }

            value += Weights::teacherFreeTime * pow(end - start - cnt + 1, 2);

            if (!teacherWorksOnDay[teacher][day]) {
                value += Weights::teacherWorkDays;
            }
        }

        value += customTeacher(teacher);

        return value;
    }
};

// Суммы критериев для строки прогресса «Шаг N из M» (по всем курсам этапа):
// [0] — штраф «два урока курса в день» (взвешенный, вес equalLessons зашит в движок и не равен 0);
// [1] — число встреч пар «нежелательно» без веса (каждая встреча видна с обоих курсов, т. е. посчитана
//       дважды); без веса — чтобы при весе пар 0 строка хода всё равно показывала настоящее число пар
array<double, 2> getClassPoint() {
    Data& data = getData();
    array<double, 2> answer = {0, 0};

    for (int cls = data.teachers.size() + 1; cls < (int)(data.teachers.size() + data.classes.size() + 1); cls++) {
        for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
            answer[0] += Functions::equalLessons(cls, day);
        }

        answer[1] += Functions::softSubjectPairCount(cls);
    }

    return answer;
}

// Сумма всех штрафов одного курса (с точки зрения этого курса; парные слагаемые включены целиком).
// Тип double: в сумме float со штрафами порядка 1e6 мелкие слагаемые (5, 10...) терялись бы
double getClassTotal(int cls) {
    double answer = 0;

    for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
        answer += Functions::equalLessons(cls, day);
    }

    answer += Functions::softSubjectPair(cls);
    answer += Functions::levelsApart(cls);
    answer += Functions::weekendLesson(cls);
    answer += Functions::customClass(cls);

    return answer;
}

// Сумма getClassTotal(cls) по всем курсам (парные слагаемые здесь посчитаны дважды)
double getClassTotal() {
    Data& data = getData();

    double answer = 0;

    for (int cls = data.teachers.size() + 1; cls < (int)(data.teachers.size() + data.classes.size() + 1); cls++) {
        answer += getClassTotal(cls);
    }

    return answer;
}

// Уроки, которые жадная расстановка не смогла поставить; отжиг пытается их вставить (ход 3).
// Каждый такой урок добавляет к энергии Weights::missingLesson = 2e6.
vector<Lesson> missingLessons;

// Преподаватель каждой пары «курс + предмет» (индекс — как у списка выбора в main, раздел 4):
// firstTeacher — выбранный до отжига (0 — не достался из-за лимита), choiceTeacher — нынешний (его
// меняет ход 4; вместе с графом входит в лучшее состояние)
vector<int> firstTeacher, choiceTeacher;

// Цена смены у пары choice: Weights::teacherChange, если её ведёт не выбранный до отжига
inline double teacherChangeCost(int choice) {
    return choiceTeacher[choice] != firstTeacher[choice] ? Weights::teacherChange : 0;
}

// Штраф «в один день» именно для пары (cls, partner): цена × число дней, когда уроки у обоих
double sameDayTerm(int cls, int partner) {
    double value = 0;

    for (auto& [other, weight] : customSameDay[cls]) {
        if (other != partner) {
            continue;
        }

        for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
            if (Functions::lessonsOnDay(cls, day) && Functions::lessonsOnDay(partner, day)) {
                value += weight;
            }
        }
    }

    return value;
}

// Штраф одной группы с дневным лимитом: за каждый день вес × (уроков всех курсов группы − лимит), если больше лимита
double dailyGroupTerm(const DailyGroup& group) {
    double value = 0;

    for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
        int count = 0;

        for (int member : group.classes) {
            count += Functions::lessonsOnDay(member, day);
        }

        value += group.weight * max(0, count - group.limit);
    }

    return value;
}

// Слагаемые пары курсов (a, b), которые getClassTotal() кладёт в ОБА курса:
// нежелательные пары между ними, пара уровней, их «в один день» и общие групповые
// дневные лимиты. Нужна localEnergy(), чтобы при ходе с двумя курсами не считать их дважды.
double sharedTerms(int a, int b) {
    Data& data = getData();
    double value = 0;

    if (!data.softSubjectPairs.empty() && find(data.linePeers[a].begin(), data.linePeers[a].end(), b) != data.linePeers[a].end()) {
        for (int slot = 0; slot < SLOTS; slot++) {
            if (!occupied(a, slot) || !occupied(b, slot)) {
                continue;
            }

            int own = cellSubject(a, slot);
            int other = cellSubject(b, slot);

            value += Weights::softSubjectPair * data.softSubjectPairs.count({min(own, other), max(own, other)});
        }
    }

    // Пара уровней одного предмета: её слагаемое тоже лежит в обоих курсах
    if (Weights::levelsApart != 0 && find(data.levelPeers[a].begin(), data.levelPeers[a].end(), b) != data.levelPeers[a].end()) {
        value += Weights::levelsApart * Functions::levelMismatch(a, b);
    }

    value += sameDayTerm(a, b);

    for (int index : customDailyGroupsByClass[a]) {
        const DailyGroup& group = customDailyGroups[index];

        if (find(group.classes.begin(), group.classes.end(), b) != group.classes.end()) {
            value += dailyGroupTerm(group);
        }
    }

    return value;
}

// Все штрафы одного преподавателя (обёртка над Functions::teacherFreeTime)
double teacherTotal(int teacher) {
    return Functions::teacherFreeTime(teacher);
}

// Строка журнала о неудобствах, которые дают одни закреплённые уроки. Слагаемые одного урока —
// урок в выходной (Functions::weekendLesson), час «может» у его преподавателя (teacherFreeTime),
// цена часа из custom_penalties_compiled для курса и для преподавателя (customClass, customTeacher) —
// зависят только от его клетки и у закреплённого урока не меняются никогда. Их сумма — часть
// энергии, которую отжиг уменьшить не может; строка печатается, только если она больше 0.
// Цена часа курса складывается из двух источников, которые во входе не различаются: свои правила
// пользователя и цены соседей курсов-копий (solver_input.priceCopyNeighbours: «нежелательно»,
// «уровни в разное время», «пары — не в один день» с общими уроками присоединённой линейки).
// Поэтому причина в скобках называет оба — иначе при пустых своих правилах строка говорила бы
// о «своих правилах», которых нет.
void printPinnedCost() {
    Data& data = getData();
    double weekend = 0, possible = 0, custom = 0;

    for (int cls : data.scheduledClasses) {
        for (int slot = 0; slot < SLOTS; slot++) {
            if (!slotLocked(cls, slot)) {
                continue;
            }

            int teacher = graph[cls][slot][0].id;

            // Выходные — дни 5 и 6, как в Functions::weekendLesson
            if (slot >= 5 * MAX_LESSON_IN_DAY) {
                weekend += Weights::weekendLesson;
            }

            if (teacherIsInconvenient[teacher][slot]) {
                possible += Weights::teacherPossibleSlot;
            }

            custom += customSlotPrice[cls][slot] + customSlotPrice[teacher][slot];
        }
    }

    long long total = llround(weekend + possible + custom);

    if (total <= 0) {
        return;
    }

    // В скобках — только те причины, которые есть на самом деле
    vector<string> reasons;

    if (weekend > 0) {
        reasons.push_back("уроки в выходные");
    }

    if (possible > 0) {
        reasons.push_back("часы «может»");
    }

    if (custom > 0) {
        reasons.push_back("свои правила или общие уроки присоединённой линейки");
    }

    cout << "Из неудобств " << total << " дают закреплённые уроки — программа их не двигает (";

    for (int i = 0; i < (int)reasons.size(); i++) {
        cout << (i > 0 ? ", " : "") << reasons[i];
    }

    cout << ")\n";
}

// ЭНЕРГИЯ — то, что минимизирует отжиг: общий штраф расписания, где каждое слагаемое учтено
// ровно один раз. getClassTotal() видит парные слагаемые с обеих сторон, поэтому:
//   * половина нежелательных пар, пар уровней и «в один день» вычитается;
//   * групповой лимит из n курсов посчитан n раз — вычитаем (n − 1) копий.
// Плюс штрафы всех преподавателей, цена смены преподавателя за каждый курс, который ведёт не выбранный
// до отжига, и 2e6 за каждый непоставленный урок.
// Вызывается редко (в начале и раз в миллион шагов) — на каждом шаге используется localEnergy().
double totalEnergy() {
    Data& data = getData();

    double value = getClassTotal();

    for (int cls = data.teachers.size() + 1; cls < (int)(data.teachers.size() + data.classes.size() + 1); cls++) {
        value -= 0.5 * ((double)Functions::softSubjectPair(cls) + Functions::levelsApart(cls));

        // Каждая запись «в один день» хранится у обоих курсов пары — половину убираем
        for (auto& [partner, weight] : customSameDay[cls]) {
            for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
                if (Functions::lessonsOnDay(cls, day) && Functions::lessonsOnDay(partner, day)) {
                    value -= 0.5 * weight;
                }
            }
        }
    }

    for (const DailyGroup& group : customDailyGroups) {
        if (!group.classes.empty()) {
            value -= (double)(group.classes.size() - 1) * dailyGroupTerm(group);
        }
    }

    for (int teacher = 1; teacher <= (int)data.teachers.size(); teacher++) {
        value += teacherTotal(teacher);
    }

    for (int choice = 0; choice < (int)choiceTeacher.size(); choice++) {
        value += teacherChangeCost(choice);
    }

    return value + (double)Weights::missingLesson * missingLessons.size();
}

// «Локальная» энергия: только слагаемые, которые касаются данных курсов и преподавателей.
// Идея: если ход меняет только их, то (localEnergy после − localEnergy до) равно изменению
// полной энергии totalEnergy(), а считается в разы быстрее.
// Точна для одного или двух курсов (ходы больше и не затрагивают): общие слагаемые снимаются
// попарно, поэтому для трёх курсов одной дневной группы её слагаемое снялось бы лишний раз.
double localEnergy(const vector<int>& classes, const vector<int>& teachers) {
    double value = 0;

    for (int cls : classes) {
        value += getClassTotal(cls);
    }

    for (int i = 0; i < (int)classes.size(); i++) {
        for (int j = i + 1; j < (int)classes.size(); j++) {
            value -= sharedTerms(classes[i], classes[j]);
        }
    }

    for (int teacher : teachers) {
        value += teacherTotal(teacher);
    }

    return value;
}

// То же для одного курса (без вектора курсов — меньше выделений памяти на горячем пути)
double localEnergy(int cls, const vector<int>& teachers) {
    double value = getClassTotal(cls);

    for (int teacher : teachers) {
        value += teacherTotal(teacher);
    }

    return value;
}

// Превращает текущий graph в JSON ответа: {курс: [день][урок] -> {"subject", "teachers"}}.
// Пустая клетка — {"subject": "#", "teachers": []}; в занятой — предмет урока и его преподаватель.
json save() {
    Data& data = getData();

    json answer;

    for (int cls = data.teachers.size() + 1; cls < (int)(data.teachers.size() + data.classes.size() + 1); cls++) {
        string& name = classNameByID[cls];

        answer[name] = json::array();

        for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
            answer[name].push_back(json::array());

            for (int lesson = 0; lesson < MAX_LESSON_IN_DAY; lesson++) {
                int slot = day * MAX_LESSON_IN_DAY + lesson;

                if (!occupied(cls, slot)) {
                    answer[name][day].push_back(json{{"subject", "#"}, {"teachers", json::array()}});

                    continue;
                }

                const edge& item = graph[cls][slot][0];

                answer[name][day].push_back(json{
                    {"subject", subjectNameByID[item.value]},
                    {"teachers", json::array({teacherNameByID[item.id]})}
                });
            }
        }
    }

    return answer;
}

// Точка входа. Порядок работы:
//   1) разбор флагов и зерна случайности; 2) чтение весов и входных данных;
//   3) построение таблиц (доступность преподавателей, закрытые слоты, собственные штрафы);
//   4) выбор преподавателя для каждого курса; 5) закреплённые уроки; 6) жадная расстановка;
//   7) имитация отжига (переносы уроков и смена преподавателя); 8) возврат к лучшему состоянию
//   и запись ответа.
int main(int argc, char** argv) {
    // stdout без буфера: сервер показывает прогресс сразу, построчно
    setvbuf(stdout, NULL, _IONBF, 0);

    // ===== 1. Флаги командной строки =====
    CLI::App app;

    // Число шагов отжига по умолчанию (50 млн) — только для ручных запусков: сервер всегда передаёт
    // своё (settings.iterations, «Тщательность» на шаге «Запуск», без неё — build.DEFAULT_ITERATIONS)
    int iterations = 5e7;
    app.add_option("--iterations", iterations);

    string weights = "null";
    app.add_option("--weights", weights);

    app.add_option("--input", input);
    app.add_option("--output", output);

    // 0 — случайное зерно; любое другое значение точно повторяет прогон
    long long seed = 0;
    app.add_option("--seed", seed);

    // Температуры отжига (начальная и конечная); 0 — подобрать по весам (см. раздел 7)
    double startTemperature = 0;
    double endTemperature = 0;
    app.add_option("--t0", startTemperature);
    app.add_option("--tend", endTemperature);

    // Шагов в одном цикле отжига (0 — весь прогон один цикл) и откуда начинать новый цикл:
    // 1 — с лучшего найденного расписания, 0 — с того, где закончился прошлый.
    // По умолчанию цикл — 5 млн шагов: замеры на потоке 2 показали, что один долгий прогон
    // застревает в «яме» за первые миллионы шагов, а повторный нагрев от лучшего расписания
    // при том же числе шагов находит заметно лучше
    long long cycleSteps = 5000000;
    int cycleFromBest = 1;
    app.add_option("--cycle", cycleSteps);
    app.add_option("--cycle-from-best", cycleFromBest);

    // При ошибке разбора CLI11_PARSE сам печатает сообщение и выходит с ненулевым кодом
    CLI11_PARSE(app, argc, argv);

    // Случайное зерно: смесь аппаратного источника и текущего времени
    if (seed == 0) {
        seed = ((unsigned long long)std::random_device{}() << 1) ^
               (unsigned long long)std::chrono::high_resolution_clock::now().time_since_epoch().count();
    }

    // Генератор принимает 32-битное зерно: «сворачиваем» 64 бита в 32
    rng.seed((unsigned)(seed ^ (seed >> 32)));

    // ===== 2. Веса и входные данные =====
    // Без --weights остаются веса по умолчанию; нечитаемый файл — исключение (ненулевой код выхода)
    if (weights != "null") {
        ifstream file(weights);

        if (file.is_open()) {
            Weights::init(json::parse(file));

        } else {
            throw runtime_error("Can not open weights");
        }
    }

    // Консоль Windows — в UTF-8, чтобы русские сообщения не превращались в «кракозябры»
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);

    // Здесь читается --input (первый вызов getData())
    Data& data = getData();

    // ===== 3. Таблицы состояния =====
    // Строк графа: 0 (не используется) + T преподавателей + C курсов + небольшой запас
    int size = data.teachers.size() + data.classes.size() + 3;

    graph.assign(size, vector<vector<edge>>(SLOTS));

    teacherIsAllowed.assign(size, vector<bool>(SLOTS, false));
    teacherIsInconvenient.assign(size, vector<bool>(SLOTS, false));
    teacherWorksOnDay.assign(size, vector<bool>(JOB_WEEK_LENGHT, false));

    // Дни, в которые преподаватель уже работает на других этапах (там «лишний день» не штрафуется)
    for (auto& [name, days] : data.busyDaysByTeacher) {
        if (!IDByTeacherName.count(name)) {
            continue;
        }

        for (int day : days) {
            if (day >= 0 && day < JOB_WEEK_LENGHT) {
                teacherWorksOnDay[IDByTeacherName[name]][day] = true;
            }
        }
    }
    classIsBlocked.assign(size, vector<bool>(SLOTS, false));

    // Закрытые для курса слоты (blocked_slots: дыры сетки дня, конфликтующие программы других этапов
    // и курсов-копий этого этапа, время курсов, которых нет во входе, — начавшихся без преподавателя
    // и курсов-копий присоединённых линеек); слоты вне сетки игнорируются
    for (auto& [name, slots] : data.blockedSlotsByClass) {
        if (!IDByClassName.count(name)) {
            continue;
        }

        for (int slot : slots) {
            if (slot >= 0 && slot < SLOTS) {
                classIsBlocked[IDByClassName[name]][slot] = true;
            }
        }
    }

    // Собственные штрафы пользователя: переводим имена в id и раскладываем по таблицам custom*.
    // Записи неизвестных курсов/преподавателей и битые записи молча пропускаются.
    {
        const json& custom = data.customPenalties;

        customSlotPrice.assign(size, vector<float>(SLOTS, 0));
        customTeacherDaily.assign(size, {});
        customDailyGroupsByClass.assign(size, {});
        customAdjacent.assign(size, 0);
        customSameDay.assign(size, {});

        // Проверка: item — массив [n0, n1, ...] минимум из `count` чисел; всё остальное в файле
        // пропускается (operator[] у const json с отсутствующим индексом — неопределённое поведение)
        auto numbers = [](const json& item, size_t count) {
            if (!item.is_array() || item.size() < count) {
                return false;
            }

            for (size_t i = 0; i < count; i++) {
                if (!item.at(i).is_number()) {
                    return false;
                }
            }

            return true;
        };

        // Цены слотов: items[имя] = [[день, урок, цена], ...]; цены одного слота складываются
        auto addSlots = [&](const json& items, map<string, int>& ids) {
            if (!items.is_object()) {
                return;
            }

            for (auto& [name, slots] : items.items()) {
                if (!ids.count(name) || !slots.is_array()) {
                    continue;
                }

                for (const auto& item : slots) {
                    if (!numbers(item, 3)) {
                        continue;
                    }

                    int day = item.at(0).get<int>();
                    int lesson = item.at(1).get<int>();
                    int slot = MAX_LESSON_IN_DAY * day + lesson;

                    if (lesson >= 0 && slot >= 0 && slot < SLOTS && lesson < MAX_LESSON_IN_DAY) {
                        customSlotPrice[ids[name]][slot] += item.at(2).get<float>();
                        customSlotsUsed = true;
                    }
                }
            }
        };

        addSlots(custom.value("class_slots", json::object()), IDByClassName);
        addSlots(custom.value("teacher_slots", json::object()), IDByTeacherName);

        // Сохраняем в локальные переменные: items() у временного json указывал бы на освобождённую память
        json teacherDaily = custom.value("teacher_daily", json::object());
        json adjacent = custom.value("adjacent", json::object());

        // Дневные лимиты преподавателей: [[лимит, цена], ...]
        for (auto& [name, limits] : teacherDaily.items()) {
            if (IDByTeacherName.count(name) && limits.is_array()) {
                for (const auto& item : limits) {
                    if (numbers(item, 2)) {
                        customTeacherDaily[IDByTeacherName[name]].push_back({item.at(0).get<int>(), item.at(1).get<float>()});
                    }
                }
            }
        }

        // Групповые дневные лимиты: {"classes": [...], "limit", "weight"}; каждому курсу группы
        // запоминаем индекс группы, чтобы customClass() находил свои группы быстро
        for (const auto& item : custom.value("group_daily", json::array())) {
            if (!item.is_object()) {
                continue;
            }

            DailyGroup group{{}, item.value("limit", 0), item.value("weight", 0.0f)};

            // Курс, записанный в группу дважды, учитывается один раз: иначе его уроки посчитались бы
            // в лимите дважды, а подсчёт по частям (localEnergy) разошёлся бы с полным (totalEnergy)
            for (const auto& name : item.value("classes", json::array())) {
                if (!name.is_string() || !IDByClassName.count(name.get<string>())) {
                    continue;
                }

                int cls = IDByClassName[name.get<string>()];

                if (find(group.classes.begin(), group.classes.end(), cls) == group.classes.end()) {
                    group.classes.push_back(cls);
                }
            }

            for (int cls : group.classes) {
                customDailyGroupsByClass[cls].push_back(customDailyGroups.size());
            }

            customDailyGroups.push_back(group);
        }

        // «Уроки в соседние дни»: курс -> цена
        for (auto& [name, weight] : adjacent.items()) {
            if (IDByClassName.count(name) && weight.is_number()) {
                customAdjacent[IDByClassName[name]] += weight.get<float>();
            }
        }

        // «В один день»: {"a", "b", "weight"} — записываем пару у обоих курсов
        for (const auto& item : custom.value("same_day", json::array())) {
            if (!item.is_object()) {
                continue;
            }

            string a = item.value("a", ""), b = item.value("b", "");

            if (IDByClassName.count(a) && IDByClassName.count(b)) {
                float weight = item.value("weight", 0.0f);

                customSameDay[IDByClassName[a]].push_back({IDByClassName[b], weight});
                customSameDay[IDByClassName[b]].push_back({IDByClassName[a], weight});
            }
        }

        // «Пары — не в один день» (так ползунок назван на шаге «Запуск»): пары курсов, которые сдают
        // вместе, — тот же механизм «в один день» с весом из weights.json (pairsSameDay).
        // Записи не из двух строк пропускаются, как и битые записи остальных правил выше
        // (get<string>() у не-строки бросил бы исключение и уронил весь запуск)
        if (Weights::pairsSameDay > 0) {
            for (const auto& item : custom.value("same_day_pairs", json::array())) {
                if (!item.is_array() || item.size() != 2 || !item.at(0).is_string() || !item.at(1).is_string()) {
                    continue;
                }

                string a = item.at(0).get<string>(), b = item.at(1).get<string>();

                if (IDByClassName.count(a) && IDByClassName.count(b)) {
                    customSameDay[IDByClassName[a]].push_back({IDByClassName[b], Weights::pairsSameDay});
                    customSameDay[IDByClassName[b]].push_back({IDByClassName[a], Weights::pairsSameDay});
                }
            }
        }
    }

    // Цена смены преподавателя (ход 4) — половина НОД всех цен > 0 среди весов и своих правил.
    // Энергия — сумма цен, умноженных на целые числа (уроки, дни, пары, окна в квадрате), поэтому при
    // целых ценах (других страница не даёт) любая разность энергий кратна НОД: настоящий выигрыш смены
    // не меньше НОД и перевешивает цену, а смена без выигрыша делает энергию хуже. Половины самого
    // лёгкого неудобства для этого мало: выигрыш — разность сумм цен и бывает меньше самой лёгкой
    // (окна «Важно» 30 и рабочий день 100: смена, которая снимает день и добавляет 3 окна, даёт 10, а
    // цена была бы 15 — такая смена не делалась). При весах по умолчанию НОД = 10, цена 5, как у
    // половины самого лёгкого. Если какая-то цена не целая (вход правили руками), НОД не считается —
    // половина самого лёгкого неудобства.
    // Замеры (Поток 2 без «ведёт», 33 курса со сменой, 3 млн шагов): без цены сменялось 14–19 курсов,
    // с ценой 0,5–1 — 6–11, с ценой 5 (половина веса окна 10 по умолчанию) — 4–6, «Итог» тот же
    {
        float lightest = 0;
        long long common = 0;
        bool integral = true;

        auto lighter = [&](float price) {
            if (price <= 0) {
                return;
            }

            if (lightest == 0 || price < lightest) {
                lightest = price;
            }

            if (price == floor(price) && price < 1e9) {
                common = gcd(common, (long long)price);
            } else {
                integral = false;
            }
        };

        for (float weight : {Weights::teacherFreeTime, Weights::teacherPossibleSlot, Weights::softSubjectPair, Weights::weekendLesson,
                             Weights::teacherWorkDays, Weights::levelsApart, Weights::pairsSameDay}) {
            lighter(weight);
        }

        for (const vector<float>& prices : customSlotPrice) {
            for (float price : prices) {
                lighter(price);
            }
        }

        for (const auto& limits : customTeacherDaily) {
            for (auto& [limit, weight] : limits) {
                lighter(weight);
            }
        }

        for (const DailyGroup& group : customDailyGroups) {
            lighter(group.weight);
        }

        for (float weight : customAdjacent) {
            lighter(weight);
        }

        for (const auto& partners : customSameDay) {
            for (auto& [partner, weight] : partners) {
                lighter(weight);
            }
        }

        if (lightest > 0) {
            Weights::teacherChange = integral ? common / 2.0 : lightest / 2;
        }
    }

    locked.assign(size, vector<int>(SLOTS, 0));

    // Доступность преподавателей: в Data индексы с 0, в графе id с 1 (отсюда teacher + 1)
    for (int teacher = 0; teacher < (int)data.teachers.size(); teacher++) {
        for (int slot : data.free[teacher]) {
            teacherIsAllowed[teacher + 1][slot] = true;
        }

        for (int slot : data.possible[teacher]) {
            if (slot >= 0 && slot < SLOTS) {
                teacherIsInconvenient[teacher + 1][slot] = true;
            }
        }
    }

    // ===== 4. Выбор преподавателя для каждого курса =====
    // coursesByTeacher — сколько курсов у преподавателя (вместе с другими этапами), для лимита;
    // ход 4 переносит курс от одного преподавателя к другому, и счётчик идёт за ним
    vector<int> coursesByTeacher(data.teachers.size() + 1, 0);

    // Уроки, которые преподаватель уже ведёт на этом этапе: новому курсу нужны свободные часы сверх них
    vector<int> hoursByTeacher(data.teachers.size() + 1, 0);

    for (auto& [name, count] : data.existingCoursesByTeacher) {
        if (IDByTeacherName.count(name)) {
            coursesByTeacher[IDByTeacherName[name]] += count;
        }
    }

    // Курс (один его предмет) и его преподаватель: все уроки ведёт этот один преподаватель.
    // candidates — кто «может вести»; fixed — преподаватель с отметкой «ведёт» (0 — нет);
    // teacher — итоговый выбор (0 — не выбран).
    struct CourseChoice {
        int cls = 0, subjectID = 0, hours = 0;
        string className, subjectName;
        vector<int> candidates;
        int fixed = 0, teacher = 0;
    };

    vector<CourseChoice> choices;

    for (auto& key : data.classes) {
        int cls = IDByClassName[key];

        for (auto& subject : data.lessons[key]) {
            CourseChoice choice;

            choice.cls = cls;
            choice.className = key;
            choice.subjectName = subject["subject"].get<string>();
            choice.subjectID = IDBySubjectName[choice.subjectName];
            choice.hours = subject["hours"].get<int>();

            for (auto& teacher : subject["teachers"]) {
                choice.candidates.push_back(IDByTeacherName[teacher.get<string>()]);
            }

            const vector<string>& assigned = data.assignedTeachers[key][choice.subjectName];

            if (assigned.size() > 1) {
                cout << "[WARNING] several teachers are fixed to " << key << " / " << choice.subjectName << ", using " << assigned[0] << "\n";
            }

            choice.fixed = assigned.empty() ? 0 : IDByTeacherName[assigned[0]];

            choices.push_back(choice);
        }
    }

    // Назначить преподавателя курсу и учесть его курс и часы в счётчиках
    auto take = [&](CourseChoice& choice, int teacher) {
        choice.teacher = teacher;
        coursesByTeacher[teacher] += 1;
        hoursByTeacher[teacher] += choice.hours;
    };

    // Сначала преподаватели «ведёт», чтобы свободный выбор дальше учитывал лимит курсов
    for (CourseChoice& choice : choices) {
        if (choice.fixed != 0) {
            take(choice, choice.fixed);
        }
    }

    // Отметки «ведёт» лимит не останавливает — только предупреждаем о превышении
    for (int teacher = 1; teacher <= (int)data.teachers.size(); teacher++) {
        if (coursesByTeacher[teacher] > TEACHER_MAX_COURSES) {
            cout << "[Внимание] " << teacherNameByID[teacher] << ": курсов с отметкой «ведёт» (вместе с другими потоками и доп. курсами) " << coursesByTeacher[teacher]
                 << " — больше максимума " << TEACHER_MAX_COURSES << " («Не больше курсов на преподавателя одновременно» в «Настройках»)\n";
        }
    }

    // Свободные часы преподавателя для курса: слоты, которые он может взять и которые открыты
    // для курса, минус уже набранные им уроки. В days возвращается число дней, где такой слот есть
    // (уроки курса ставятся по одному в день, поэтому важны и часы, и дни)
    auto teacherSpareHours = [&](int teacher, const CourseChoice& choice, int& days) {
        int slots = 0;

        days = 0;

        for (int day = 0; day < JOB_WEEK_LENGHT; day++) {
            bool any = false;

            for (int lesson = 0; lesson < MAX_LESSON_IN_DAY; lesson++) {
                int slot = day * MAX_LESSON_IN_DAY + lesson;

                if (teacherIsAllowed[teacher][slot] && !classIsBlocked[choice.cls][slot]) {
                    slots += 1;
                    any = true;
                }
            }

            days += any;
        }

        return slots - hoursByTeacher[teacher];
    };

    // Остальные курсы выбирают среди «может вести»: первыми — курсы с наименьшим числом
    // кандидатов (у них меньше свободы, их надо обслужить, пока кандидаты не заняты).
    // Лучший кандидат: сначала тот, у кого хватает часов и дней; среди таких — с меньшим числом
    // курсов, затем с большим запасом часов; если не хватает никому — с наибольшим min(часы, дни).
    vector<int> order;

    for (int i = 0; i < (int)choices.size(); i++) {
        if (choices[i].teacher == 0) {
            order.push_back(i);
        }
    }

    stable_sort(order.begin(), order.end(), [&](int a, int b) {
        return choices[a].candidates.size() < choices[b].candidates.size();
    });

    for (int index : order) {
        CourseChoice& choice = choices[index];

        int best = 0, bestCourses = 0, bestSpare = 0;
        bool bestEnough = false;

        for (int teacher : choice.candidates) {
            if (coursesByTeacher[teacher] >= TEACHER_MAX_COURSES) {
                continue;
            }

            int days = 0;
            int spare = teacherSpareHours(teacher, choice, days);

            // «Хватает» — есть свободный час на каждый урок, и каждый урок в свой день
            bool enough = spare >= choice.hours && days >= choice.hours;
            int fit = min(spare, days);

            bool better = best == 0 ||
                (enough && !bestEnough) ||
                (enough && bestEnough && (coursesByTeacher[teacher] < bestCourses ||
                                          (coursesByTeacher[teacher] == bestCourses && spare > bestSpare))) ||
                (!enough && !bestEnough && fit > bestSpare);

            if (better) {
                best = teacher;
                bestEnough = enough;
                bestCourses = coursesByTeacher[teacher];
                bestSpare = enough ? spare : fit;
            }
        }

        if (best == 0) {
            cout << "[Внимание] " << choice.className << " / " << choice.subjectName << ": у всех подходящих преподавателей уже максимум курсов («Не больше курсов на преподавателя одновременно» в «Настройках»)\n";
            continue;
        }

        take(choice, best);
    }

    // Список всех уроков к расстановке: по hours штук на каждый курс с выбранным преподавателем
    vector<Lesson> pending;

    for (const CourseChoice& choice : choices) {
        if (choice.teacher == 0) {
            continue;
        }

        for (int i = 0; i < choice.hours; i++) {
            pending.push_back(Lesson{choice.cls, choice.teacher, choice.subjectID, choice.className, choice.subjectName});
        }
    }

    // ===== 5. Закреплённые уроки =====
    // Каждое закрепление забирает один урок этого курса и предмета из pending и ставит его
    // на заданное место, помечая в locked. Если поставить нельзя — понятное предупреждение
    // с причиной, а урок остаётся в pending и будет расставлен как обычный.
    // pinned — сколько закреплений встало на место
    int pinned = 0;

    for (const Constant& constant : data.constants) {
        const string& cls = classNameByID[constant.cls];
        const string& subject = subjectNameByID[constant.subjectID];
        string label = "[Внимание] закреплённый урок " + cls + " / " + subject + " (день " + to_string(constant.slot / MAX_LESSON_IN_DAY + 1) +
                       ", урок " + to_string(constant.slot % MAX_LESSON_IN_DAY + 1) + ") не поставлен: ";

        int idx = -1;

        for (int i = 0; i < (int)pending.size(); i++) {
            if (pending[i].cls == constant.cls && pending[i].subjectID == constant.subjectID) {
                idx = i;

                break;
            }
        }

        if (idx == -1) {
            bool hasTeacher = false;

            for (const CourseChoice& choice : choices) {
                hasTeacher |= choice.cls == constant.cls && choice.subjectID == constant.subjectID && choice.teacher != 0;
            }

            cout << label << (hasTeacher ? "закреплено больше уроков, чем часов у курса" : "у курса нет преподавателя") << "\n";

            continue;
        }

        // Урок ведёт преподаватель, которого решатель выбрал курсу (item.teacher): закрепление задаёт
        // только день и урок
        Lesson item = pending[idx];

        if (!canPlaceLesson(constant.cls, constant.slot, constant.subjectID)) {
            string reason;

            // Причины закрытого слота — ровно то, из чего собран blocked_slots (solver_input.py):
            // дыра сетки дня, урок «непересекающейся» программы того же предмета на другом этапе,
            // урок выброшенного идущего курса без преподавателя или курса-копии присоединённой линейки
            // (у копий — и программа этого этапа)
            if (classIsBlocked[constant.cls][constant.slot]) {
                reason = "это время закрыто для курса: такого урока нет в сетке на шаге «Настройки», или в это время идёт семинар "
                         "либо ЕГЭ продвинутый по тому же предмету, или идущий курс без преподавателя, с которым этот курс не должен совпадать";

            } else if (occupied(constant.cls, constant.slot)) {
                reason = "в это время уже стоит другой закреплённый урок курса";

            } else {
                bool seminar = false;

                for (int other : data.hardBlockers[constant.cls]) {
                    seminar |= occupied(other, constant.slot);
                }

                reason = seminar ? "в это время стоит курс, с которым он не должен пересекаться (семинар и ЕГЭ продвинутый)"
                                 : "в это время у курса той же линейки и потока стоит предмет из пары «нельзя»";
            }

            cout << label << reason << "\n";

            continue;
        }

        if (!teacherIsAllowed[item.teacher][constant.slot]) {
            cout << label << "преподаватель " << teacherNameByID[item.teacher] << " в это время не может или уже ведёт урок в другом потоке или блоке курсов\n";

            continue;
        }

        if (!teacherCanAccept(item.teacher, constant.slot)) {
            cout << label << "преподаватель " << teacherNameByID[item.teacher] << " в это время ведёт другой закреплённый урок\n";

            continue;
        }

        pending.erase(pending.begin() + idx);

        placeLesson(item, constant.slot);
        locked[constant.cls][constant.slot] = constant.subjectID;
        pinned++;
    }

    // Сколько подбирать — строка журнала до расстановки. movable (K) — уроки, которые программа
    // может двигать: всё, что осталось в pending, в том числе закрепления, которые не встали,
    // и уроки, которые потом окажутся непоставленными. withoutTeacher — часы курсов без подходящих
    // преподавателей (Data) и курсов, которым преподаватель не достался из-за лимита курсов:
    // эти уроки не ставятся вовсе. Всего уроков этапа — pinned + movable + withoutTeacher
    int movable = pending.size();
    int withoutTeacher = data.hoursWithoutTeacher;

    for (const CourseChoice& choice : choices) {
        if (choice.teacher == 0) {
            withoutTeacher += choice.hours;
        }
    }

    int lessonsTotal = pinned + movable + withoutTeacher;

    cout << "Закреплено " << pinned << " из " << lessonsTotal << " " << plural(lessonsTotal, "урока", "уроков", "уроков")
         << ", подбирается " << movable;

    if (withoutTeacher > 0) {
        cout << ", без преподавателя (не ставятся): " << withoutTeacher;
    }

    cout << "\n";

    printPinnedCost();

    // K = 0 — отжигу нечего двигать, он не запускается (раздел 7); строка называет причину, чтобы
    // не писать «все уроки закреплены», когда закреплено не всё. K ≤ 2 — у задачи всего несколько
    // допустимых расписаний, и прогоны с разными зёрнами, скорее всего, найдут одно и то же
    if (movable == 0 && lessonsTotal == 0) {
        cout << "Подбирать нечего: в этом потоке или блоке курсов нет уроков\n";

    } else if (movable == 0 && withoutTeacher > 0) {
        cout << "Подбирать нечего: у незакреплённых уроков нет преподавателя\n";

    } else if (movable == 0) {
        cout << "Подбирать нечего: все уроки закреплены, расписание оставлено как есть\n";

    } else if (movable <= 2) {
        cout << "Подбирать почти нечего: варианты, скорее всего, совпадут\n";
    }

    // ===== 6. Жадная начальная расстановка =====
    // На каждом шаге ищем урок с наименьшим числом допустимых слотов («самый стеснённый»)
    // и ставим его первым — так меньше шансов, что для него потом не останется места.
    // Допустимый слот = жёсткие правила курса и преподавателя + не больше одного урока курса в день.
    while (!pending.empty()) {
        int bestIdx = -1;

        vector<int> bestCandidates;

        for (int idx = 0; idx < (int)pending.size(); idx++) {
            Lesson& item = pending[idx];

            vector<int> candidates;

            for (int slot = 0; slot < SLOTS; slot++) {
                if (!canPlaceLesson(item.cls, slot, item.subjectID)) {
                    continue;
                }

                // Один урок курса в день
                if (teacherCanAccept(item.teacher, slot) && !courseHasLessonOnDay(item.cls, slot / MAX_LESSON_IN_DAY * MAX_LESSON_IN_DAY)) {
                    candidates.push_back(slot);
                }
            }

            // Самый стеснённый урок идёт первым; если нашёлся урок без вариантов — дальше не ищем
            if (bestIdx == -1 || candidates.size() < bestCandidates.size()) {
                bestIdx = idx;

                bestCandidates = candidates;
            }

            if (bestCandidates.empty()) {
                break;
            }
        }

        Lesson item = pending[bestIdx];

        pending.erase(pending.begin() + bestIdx);

        if (bestCandidates.empty()) {
            // Урок не теряется: отжиг продолжает пытаться его вставить, а его цена (2e6) входит в энергию
            missingLessons.push_back(item);

            continue;
        }

        // Сначала удобные преподавателю слоты; слоты «может» — только если ничего другого нет
        vector<int> convenient;

        for (int slot : bestCandidates) {
            if (!teacherIsInconvenient[item.teacher][slot]) {
                convenient.push_back(slot);
            }
        }

        if (!convenient.empty()) {
            bestCandidates = convenient;
        }

        // Предпочитаем слоты, где тот же предмет уже идёт у других курсов: если собрать предмет
        // в немногих слотах, остаётся место для курсов, с которыми ему нельзя пересекаться.
        // Среди равных — случайный выбор (поэтому варианты с разными --seed различаются)
        vector<int> clustered;
        int bestShared = -1;

        for (int slot : bestCandidates) {
            int shared = 0;

            for (int cls : data.scheduledClasses) {
                if (cellSubject(cls, slot) == item.subjectID) {
                    shared++;
                }
            }

            if (shared > bestShared) {
                bestShared = shared;
                clustered.clear();
            }

            if (shared == bestShared) {
                clustered.push_back(slot);
            }
        }

        int color = clustered[randint(0, clustered.size() - 1)];

        placeLesson(item, color);
    }

    // ===== 7. Имитация отжига =====
    // Курсы со сменой преподавателя (ход 4) — индексы choices в switchable: без «ведёт», преподаватель
    // выбран, кандидатов больше одного; во входе нет закрепления времени по этому курсу и предмету
    // (по constants, а не по locked: курс с не вставшим закреплением тоже не трогаем — строка
    // «[Внимание] закреплённый урок … не поставлен: преподаватель X …» напечатана до отжига и называет
    // выбранного тогда преподавателя, после смены она назвала бы не того; у вставших закреплений так
    // остаётся верной и строка «Из неудобств … закреплённые уроки»); курса нет в keep_teacher_courses; и хотя
    // бы другому кандидату лимит вообще позволяет взять курс: existing + «ведёт» < максимума. Последнее
    // отсекает заранее курсы, которым сменить преподавателя всё равно нельзя, — на входах без курсов
    // со сменой ход не тратит случайных чисел, и ответ тот же, что до хода 4
    vector<int> fixedCourses(data.teachers.size() + 1, 0);

    for (auto& [name, count] : data.existingCoursesByTeacher) {
        if (IDByTeacherName.count(name)) {
            fixedCourses[IDByTeacherName[name]] += count;
        }
    }

    for (const CourseChoice& choice : choices) {
        if (choice.fixed != 0) {
            fixedCourses[choice.fixed] += 1;
        }
    }

    vector<int> switchable;

    firstTeacher.assign(choices.size(), 0);

    for (int i = 0; i < (int)choices.size(); i++) {
        const CourseChoice& choice = choices[i];

        firstTeacher[i] = choice.teacher;

        if (choice.fixed != 0 || choice.teacher == 0 || choice.candidates.size() < 2 || data.keepTeacherCourses.count(choice.className)) {
            continue;
        }

        bool pinned = false;

        for (const Constant& constant : data.constants) {
            pinned |= constant.cls == choice.cls && constant.subjectID == choice.subjectID;
        }

        bool other = false;

        for (int teacher : choice.candidates) {
            other |= teacher != choice.teacher && fixedCourses[teacher] < TEACHER_MAX_COURSES;
        }

        if (!pinned && other) {
            switchable.push_back(i);
        }
    }

    choiceTeacher = firstTeacher;

    // Энергия текущего состояния (cur) не пересчитывается целиком, а обновляется на Δ каждого
    // принятого хода; в ответ пишется лучшее из увиденных состояний.
    double cur = totalEnergy();
    double bestEnergy = cur;

    // true, пока текущее состояние — лучшее и его копии ещё нет. Копия (дорогая: весь граф)
    // делается только тогда, когда ход «в гору» (ухудшающий) собирается покинуть лучшее
    // состояние, а не при каждом новом рекорде — рекорды на спуске идут очень часто.
    bool bestUnsaved = true;

    // Всё, что читает save(): граф и список ещё не поставленных уроков; и состояние хода 4 —
    // преподаватели курсов и их счётчики курсов (без них после возврата к лучшему счётчики разошлись
    // бы с графом: лимит мог бы нарушиться, а у непоставленных уроков остался бы прежний преподаватель)
    vector<vector<vector<edge>>> bestGraph;
    vector<Lesson> bestMissing;
    vector<int> bestChoiceTeacher;
    vector<int> bestCoursesByTeacher;

    auto saveBest = [&]() {
        bestGraph = graph;
        bestMissing = missingLessons;
        bestChoiceTeacher = choiceTeacher;
        bestCoursesByTeacher = coursesByTeacher;
        bestUnsaved = false;
    };

    // Возврат к лучшему состоянию (новый цикл и раздел 8)
    auto restoreBest = [&]() {
        graph = bestGraph;
        missingLessons = bestMissing;
        choiceTeacher = bestChoiceTeacher;
        coursesByTeacher = bestCoursesByTeacher;
        cur = bestEnergy;
    };

    // Начальная температура по умолчанию (t0 не задана или ≤ 0, NaN) — 0,4 от самого большого
    // веса мягких правил. Температура должна быть соизмерима с весами. При весах по умолчанию
    // (src/files/weights.json) самый большой — пары «нежелательно» (1000), T0 = 0,4 · 1000 = 400,
    // и ход «+1000» в начале цикла принимается с вероятностью e^-2.5 ≈ 8%. Если пользователь
    // поднимет веса, T0 растёт вместе с ними. При постоянной T0 = 100 (так было раньше) такой
    // ход принимался бы с вероятностью e^-10 ≈ 0,005%, т. е. почти никогда, и поиск застревал бы
    // в ближайшей «яме». Не меньше 100 — чтобы и при маленьких весах было куда «бродить»
    if (!(startTemperature > 0)) {
        double heaviest = max({Weights::teacherFreeTime, Weights::teacherPossibleSlot, Weights::softSubjectPair,
                               Weights::weekendLesson, Weights::teacherWorkDays, Weights::levelsApart, Weights::pairsSameDay});

        startTemperature = max(100.0, 0.4 * heaviest);
    }

    // Конечная температура по умолчанию — 1: в конце цикла ход «+Δ» принимается с вероятностью e^-Δ.
    // При весах по умолчанию (src/files/weights.json) самое лёгкое неудобство — окно у преподавателя
    // (10): такой ход принимается с вероятностью e^-10 ≈ 0,005 %, и поиск только спускается. При более
    // лёгких весах конец цикла не совсем холодный (окно с весом 3 — около 5 %), но замеры с tend = 0,3
    // разницы в итоге не показали, поэтому tend не зависит от весов
    if (!(endTemperature > 0) || endTemperature > startTemperature) {
        endTemperature = min(1.0, startTemperature);
    }

    // Геометрическое охлаждение от T0 до Tend за один цикл (cycleSteps шагов): на каждом шаге
    // T умножается на alpha = (Tend/T0)^(1/cycleSteps), так что к концу цикла T = Tend.
    // Прогон короче цикла — один цикл на весь прогон, он тоже успевает «остыть».
    double temperature = startTemperature;

    if (cycleSteps <= 0 || cycleSteps > iterations) {
        cycleSteps = max(1, iterations);
    }

    // Число шагов не делится на длину цикла: циклы становятся равными и чуть короче, чтобы
    // последний тоже остыл до Tend (иначе он обрывается горячим, и его шаги почти ничего не дают).
    // При 3, 10, 30 и 100 млн шагов и цикле 5 млн длина цикла не меняется
    long long cycles = (iterations + cycleSteps - 1) / cycleSteps;

    if (cycles > 1) {
        cycleSteps = (iterations + cycles - 1) / cycles;
    }

    double alpha = pow(endTemperature / startTemperature, 1.0 / cycleSteps);

    // count — сколько изменений оценено (ход прошёл жёсткие правила, посчитана Δ; смены преподавателя
    // тоже); stepsDone — сколько шагов сделано (меньше iterations, если подбирать нечего или поиск
    // остановлен раньше). Оба печатаются в конце; type — вид текущего хода
    long long count = 0;
    int stepsDone = 0;
    int type = 0;

    // Ранняя остановка, когда подбирать почти нечего: подбирается не больше EARLY_STOP_LESSONS уроков,
    // и лучшее не менялось EARLY_STOP_WINDOW шагов (проверяется раз в миллион шагов, вместе со строкой
    // «Шаг N из M»). Замеры на потоке 2 с закреплениями: при K ≤ 5 последнее улучшение было не позже
    // 286 тыс. шага (при K = 1 — не позже 6 тыс.), окно больше этого в 3,5 раза; при K = 10 улучшение
    // бывало и на 6-м млн шагов, поэтому порог не выше 5. На обычном подборе (свободны все уроки)
    // между улучшениями бывает до 25 млн шагов, и остановка по застою там ухудшала бы расписание
    const int EARLY_STOP_LESSONS = 5;
    const int EARLY_STOP_WINDOW = 1000000;

    // Частота хода 4: |switchable| / (SWAP_SHARE · число курсов) — когда сменить можно всем курсам,
    // около 1 шага из 20, у одного курса из 33 — 1 из 660. Замеры: качество почти одинаково при
    // частоте от 1/5 до 1/50
    const int SWAP_SHARE = 20;

    // iter — номер текущего шага, lastImprovement — шаг последнего улучшения лучшего (0 — лучшее
    // всё ещё жадная расстановка); iter объявлен здесь, потому что accept запоминает по нему улучшение
    int iter = 0;
    int lastImprovement = 0;

    // ПРАВИЛО МЕТРОПОЛИСА. Ход уже применён к graph; delta — изменение энергии.
    //   * delta ≤ 0 — ход принимается всегда;
    //   * delta > 0 — принимается с вероятностью exp(−delta / T): сравниваем её со случайным
    //     числом из [0, 1); если не повезло — undo() откатывает ход, возвращаем false.
    // Если принимаемый худший ход уводит из ещё не сохранённого лучшего состояния, то сначала
    // откатываемся (undo), копируем лучшее (saveBest), и снова делаем ход (redo).
    // Затем обновляем cur и, если это новый рекорд, bestEnergy (с допуском 1e-6 на округление)
    // и шаг последнего улучшения (для ранней остановки).
    auto accept = [&](double delta, auto&& undo, auto&& redo) {
        if (delta > 0 && randreal() >= exp(-delta / temperature)) {
            undo();

            return false;
        }

        if (delta > 0 && bestUnsaved) {
            undo();
            saveBest();
            redo();
        }

        cur += delta;

        if (cur < bestEnergy - 1e-6) {
            bestEnergy = cur;
            bestUnsaved = true;
            lastImprovement = iter;
        }

        return true;
    };

    auto& classList = data.scheduledClasses;

    // Буферы, общие для всех ходов, чтобы не выделять память на каждом шаге
    vector<int> involvedTeachers;
    vector<int> slotsBuffer, targetCandidates, courseCells;

    // Ход 4 и доводка после отжига (раздел 8). canTakeCells: собирает в courseCells клетки курса index
    // и проверяет, что преподаватель to в каждой из них не «не может» и не занят (лимит курсов проверяет
    // вызывающий код). handOver: курс index (клетки — courseCells) переходит от преподавателя a к b —
    // рёбра в строках обоих преподавателей и id в клетках курса, преподаватель непоставленных уроков
    // (иначе ход 3 вставил бы урок с прежним), счётчики курсов
    auto canTakeCells = [&](int index, int to) {
        const CourseChoice& choice = choices[index];

        courseCells.clear();

        for (int slot = 0; slot < SLOTS; slot++) {
            if (cellSubject(choice.cls, slot) == choice.subjectID) {
                courseCells.push_back(slot);

                if (!teacherCanAccept(to, slot)) {
                    return false;
                }
            }
        }

        return true;
    };

    auto handOver = [&](int index, int a, int b) {
        int cls = choices[index].cls;
        int subjectID = choices[index].subjectID;

        for (int slot : courseCells) {
            removeTeacherAssignment(a, slot, cls, subjectID);
            graph[b][slot].push_back(edge(cls, subjectID));

            for (edge& item : graph[cls][slot]) {
                if (item.value == subjectID) {
                    item.id = b;
                }
            }
        }

        for (Lesson& item : missingLessons) {
            if (item.cls == cls && item.subjectID == subjectID) {
                item.teacher = b;
            }
        }

        coursesByTeacher[a]--;
        coursesByTeacher[b]++;
        choiceTeacher[index] = b;
    };

    // Занятые слоты строки, уроки которых отжигу можно двигать (skipLocked — пропускать
    // закреплённые). Возвращает ссылку на общий буфер slotsBuffer: следующий вызов его перезапишет!
    auto movableSlots = [&](int row, bool skipLocked) -> vector<int>& {
        slotsBuffer.clear();

        for (int slot = 0; slot < SLOTS; slot++) {
            if (occupied(row, slot) && !(skipLocked && slotLocked(row, slot))) {
                slotsBuffer.push_back(slot);
            }
        }

        return slotsBuffer;
    };

#ifdef CHECK_ENERGY
    // Отладочная проверка (см. шапку): checks — сколько проверок, badChecks — сколько раз энергия
    // по частям (cur) разошлась с полным пересчётом, badState — сколько раз состояние было неверным,
    // limitRejects — сколько смен не сделано из-за лимита курсов. Первые расхождения печатаются
    const int CHECK_EVERY = 50000;
    long long checks = 0, badChecks = 0, badState = 0, limitRejects = 0;
    double maxDiff = 0;

    // Есть ли в клетке (row, slot) ребро (id, value)
    auto hasEdge = [&](int row, int slot, int id, int value) {
        for (const edge& item : graph[row][slot]) {
            if (item.id == id && item.value == value) {
                return true;
            }
        }

        return false;
    };

    // Что не так с состоянием (пустая строка — всё в порядке)
    auto stateProblem = [&]() -> string {
        int rows = data.teachers.size() + data.classes.size();

        for (int row = 1; row <= rows; row++) {
            for (int slot = 0; slot < SLOTS; slot++) {
                if (graph[row][slot].size() > 1) {
                    return "two lessons in one cell";
                }

                for (const edge& item : graph[row][slot]) {
                    bool teacherRow = row <= (int)data.teachers.size();

                    if (!hasEdge(item.id, slot, row, item.value)) {
                        return teacherRow ? "teacher edge without course edge" : "course edge without teacher edge";
                    }

                    if (!teacherRow && !teacherIsAllowed[item.id][slot]) {
                        return "teacher cannot teach in this slot";
                    }
                }
            }
        }

        vector<int> recount(data.teachers.size() + 1, 0);

        for (auto& [name, count] : data.existingCoursesByTeacher) {
            if (IDByTeacherName.count(name)) {
                recount[IDByTeacherName[name]] += count;
            }
        }

        for (int i = 0; i < (int)choices.size(); i++) {
            const CourseChoice& choice = choices[i];
            int teacher = choiceTeacher[i];

            if (teacher == 0) {
                continue;
            }

            recount[teacher]++;

            if (find(choice.candidates.begin(), choice.candidates.end(), teacher) == choice.candidates.end()) {
                return "teacher is not a candidate";
            }

            for (int slot = 0; slot < SLOTS; slot++) {
                if (cellSubject(choice.cls, slot) == choice.subjectID && graph[choice.cls][slot][0].id != teacher) {
                    return "cell teacher differs from course teacher";
                }
            }

            for (const Lesson& item : missingLessons) {
                if (item.cls == choice.cls && item.subjectID == choice.subjectID && item.teacher != teacher) {
                    return "missing lesson teacher differs from course teacher";
                }
            }
        }

        for (int teacher = 1; teacher <= (int)data.teachers.size(); teacher++) {
            if (recount[teacher] != coursesByTeacher[teacher]) {
                return "course counter differs from recount";
            }
        }

        for (int i = 0; i < (int)choices.size(); i++) {
            if (choiceTeacher[i] != firstTeacher[i] && coursesByTeacher[choiceTeacher[i]] > TEACHER_MAX_COURSES) {
                return "course limit exceeded by teacher change";
            }
        }

        return "";
    };

    // Одна проверка: энергия по частям против полного пересчёта и состояние
    auto check = [&](const char* where) {
        double full = totalEnergy();
        double diff = fabs(full - cur);

        checks++;
        maxDiff = max(maxDiff, diff);

        if (diff > 1e-3) {
            badChecks++;

            if (badChecks <= 5) {
                cout << "MISMATCH " << where << " step=" << iter << " type=" << type << " cur=" << cur << " full=" << full << "\n";
            }

            cur = full;
        }

        string problem = stateProblem();

        if (!problem.empty()) {
            badState++;

            if (badState <= 5) {
                cout << "BADSTATE " << where << " step=" << iter << " type=" << type << ": " << problem << "\n";
            }
        }
    };
#endif

    // Главный цикл отжига. Температура снижается на каждой итерации, даже если ход не удалось
    // сделать (continue) — поэтому итерации = «попытки», а count = оценённые изменения.
    // При movable = 0 (всё закреплено) цикл не идёт вовсе; movable > 0 значит и то, что курсы есть
    for (iter = 0; iter < iterations && movable > 0; iter++) {
        stepsDone = iter + 1;
        temperature *= alpha;

        // Начало нового цикла: снова «горячо»; по умолчанию поиск продолжается с лучшего расписания
        if (iter > 0 && iter % cycleSteps == 0) {
            temperature = startTemperature;

            if (cycleFromBest && !bestUnsaved && cur > bestEnergy + 1e-6) {
                restoreBest();
            }
        }

#ifdef CHECK_ENERGY
        if (iter % CHECK_EVERY == 0) {
            check("step");
        }
#endif

        // Раз в миллион шагов — строка прогресса для сервера
        if ((iter + 1) % 1000000 == 0) {
            // Время от времени пересчитываем энергию целиком, чтобы ошибки округления дельт не накапливались
            cur = totalEnergy();

            array<double, 2> points = getClassPoint();

            // Пары «нежелательно» посчитаны без веса, но каждая встреча видна с обоих курсов — делим на 2.
            // «Два урока в день» — взвешенная сумма: делим на вес equalLessons (он зашит и не равен 0)
            long long softPairs = llround(points[1] / 2);
            long long sameDay = llround(points[0] / Weights::equalLessons);

            // Считаются так же, как строки таблицы «Предпросмотра», но для текущего расписания, а в вариант
            // пишется лучшее, поэтому числа могут отличаться. Собственный «штраф» генератора включает также
            // непоставленные уроки, два урока в день и цену смены преподавателя, поэтому он не равен итогу
            // «Предпросмотра»
            cout << "Шаг " << iter + 1 << " из " << iterations
                 << " | пары «нежелательно»: " << softPairs
                 << " | 2 урока курса в день: " << sameDay;

            if (!missingLessons.empty()) {
                cout << " | не поставлено уроков: " << missingLessons.size();
            }

            cout << " | неудобства: " << llround(cur) << " (лучшее пока " << llround(min(cur, bestEnergy)) << ")\n";

            // Ранняя остановка (см. EARLY_STOP_LESSONS): раздел 8 вернёт лучшее расписание как обычно.
            // На последнем шаге прогон кончается и так — строка «Остановлено» там не нужна
            if (movable <= EARLY_STOP_LESSONS && iter + 1 < iterations && iter + 1 - lastImprovement >= EARLY_STOP_WINDOW) {
                cout << "Остановлено на шаге " << iter + 1 << " из " << iterations << ": подбирается только " << movable << " "
                     << plural(movable, "урок", "урока", "уроков") << ", лучшее не менялось " << EARLY_STOP_WINDOW / 1000000 << " млн шагов\n";

                break;
            }
        }

        // Выбор вида хода: пока есть непоставленные уроки — с вероятностью 1/10 пробуем вставку
        // (ход 3); иначе, если есть курсы со сменой, — смена преподавателя (ход 4) с частотой
        // SWAP_SHARE; иначе один из трёх ходов перемещения (ходы 0, 1, 2). Без курсов со сменой
        // лишнее случайное число не берётся: ответы на тех же зёрнах прежние
        if (!missingLessons.empty() && randint(0, 9) == 0) {
            type = 3;

        } else if (!switchable.empty() && randint(0, SWAP_SHARE * (int)choices.size() - 1) < (int)switchable.size()) {
            type = 4;

        } else {
            type = randint(0, 2);
        }

        // ХОД 0: перенести урок курса в другой слот того же курса (или поменять местами два его урока).
        // Схема каждого хода одинакова: выбрать → проверить жёсткие правила → энергия «до» →
        // применить → энергия «после» → accept(Δ, откат, повтор).
        if (type == 0) {
            int cls = classList[randint(0, classList.size() - 1)];

            vector<int>& own = movableSlots(cls, true);

            if (own.empty()) {
                continue;
            }

            int slotA = own[randint(0, own.size() - 1)];
            int slotB = randint(0, SLOTS - 1);

            if (slotA == slotB || slotLocked(cls, slotB)) {
                continue;
            }

            int dayA = slotA / MAX_LESSON_IN_DAY;
            int dayB = slotB / MAX_LESSON_IN_DAY;

            // Перенос в другой день, где у курса уже есть урок, дал бы два урока в день — пропускаем
            if (!occupied(cls, slotB) && dayA != dayB && courseHasLessonOnDay(cls, dayB * MAX_LESSON_IN_DAY)) {
                continue;
            }

            if (!canSwapClassSlots(cls, slotA, cls, slotB)) {
                continue;
            }

            // Преподаватели обоих слотов (без повторов) — их штрафы тоже меняются
            involvedTeachers.clear();

            for (auto& e : graph[cls][slotA]) {
                if (find(involvedTeachers.begin(), involvedTeachers.end(), e.id) == involvedTeachers.end()) {
                    involvedTeachers.push_back(e.id);
                }
            }

            for (auto& e : graph[cls][slotB]) {
                if (find(involvedTeachers.begin(), involvedTeachers.end(), e.id) == involvedTeachers.end()) {
                    involvedTeachers.push_back(e.id);
                }
            }

            double before = localEnergy(cls, involvedTeachers);

            // Обмен двух клеток одного курса обратен сам себе: им же и откатываем, им же и повторяем
            auto intraSwapper = [&]() {
                swapClassSlots(cls, slotA, cls, slotB);
            };

            count++;
            intraSwapper();

            double delta = localEnergy(cls, involvedTeachers) - before;

            accept(delta, intraSwapper, intraSwapper);
        }

        // ХОД 1: обменять время уроков двух разных курсов (урок курса 1 едет в слот урока курса 2
        // и наоборот). В половине случаев второй урок берётся у того же преподавателя — так
        // преподаватель «переставляет» свои уроки, что хорошо убирает окна.
        // Оба целевых слота должны быть пустыми у «чужого» курса, и ни один не закреплён.
        if (type == 1) {
            if (classList.size() < 2) {
                continue;
            }

            int cls1 = classList[randint(0, classList.size() - 1)];

            vector<int>& own = movableSlots(cls1, true);

            if (own.empty()) {
                continue;
            }

            int color1 = own[randint(0, own.size() - 1)];
            int cls2 = 0, color2 = 0;

            if (randint(0, 1) == 0) {
                const vector<edge>& lesson = graph[cls1][color1];
                int teacher = lesson[randint(0, lesson.size() - 1)].id;

                vector<int>& busy = movableSlots(teacher, false);

                if (busy.size() < 2) {
                    continue;
                }

                color2 = busy[randint(0, busy.size() - 1)];

                const vector<edge>& other = graph[teacher][color2];

                cls2 = other[randint(0, other.size() - 1)].id;

            } else {
                cls2 = classList[randint(0, classList.size() - 1)];

                vector<int>& theirs = movableSlots(cls2, true);

                if (theirs.empty()) {
                    continue;
                }

                color2 = theirs[randint(0, theirs.size() - 1)];
            }

            if (cls1 == cls2 || color1 == color2) {
                continue;
            }

            if (slotLocked(cls1, color1) || slotLocked(cls2, color2) ||
                slotLocked(cls1, color2) || slotLocked(cls2, color1)) {
                continue;
            }

            if (occupied(cls1, color2) || occupied(cls2, color1)) {
                continue;
            }

            int day1 = color1 / MAX_LESSON_IN_DAY;
            int day2 = color2 / MAX_LESSON_IN_DAY;

            if (day1 != day2 && (courseHasLessonOnDay(cls1, day2 * MAX_LESSON_IN_DAY) || courseHasLessonOnDay(cls2, day1 * MAX_LESSON_IN_DAY))) {
                continue;
            }

            if (!canSwapClassSlots(cls1, color1, cls2, color2)) {
                continue;
            }

            involvedTeachers.clear();

            for (auto& e : graph[cls1][color1]) {
                if (find(involvedTeachers.begin(), involvedTeachers.end(), e.id) == involvedTeachers.end()) {
                    involvedTeachers.push_back(e.id);
                }
            }

            for (auto& e : graph[cls2][color2]) {
                if (find(involvedTeachers.begin(), involvedTeachers.end(), e.id) == involvedTeachers.end()) {
                    involvedTeachers.push_back(e.id);
                }
            }

            // Общие слагаемые двух курсов учитываются один раз (см. localEnergy)
            vector<int> both = {cls1, cls2};

            double before = localEnergy(both, involvedTeachers);

            auto swapper = [&]() {
                swapClassSlots(cls1, color1, cls2, color2);
            };

            // После хода урок cls1 стоит в color2, а урок cls2 — в color1,
            // поэтому обратный ход начинается с переставленных слотов
            auto unswapper = [&]() {
                swapClassSlots(cls1, color2, cls2, color1);
            };

            count++;
            swapper();

            double delta = localEnergy(both, involvedTeachers) - before;

            accept(delta, unswapper, swapper);
        }

        // ХОД 2: перенести урок курса в любой слот, где соблюдены все жёсткие правила
        // (в отличие от хода 0, слот выбирается только среди заведомо допустимых)
        if (type == 2) {
            int cls = classList[randint(0, classList.size() - 1)];

            vector<int>& own = movableSlots(cls, false);

            if (own.empty()) {
                continue;
            }

            int slotA = own[randint(0, own.size() - 1)];

            // Урок клетки (случайный выбор из клетки — как в ходе 1)
            const vector<edge>& cell = graph[cls][slotA];
            edge lesson = cell[randint(0, cell.size() - 1)];
            int teacher = lesson.id;
            int subjectID = lesson.value;

            if (slotLocked(cls, slotA)) {
                continue;
            }

            involvedTeachers.assign(1, teacher);

            // Дни, где у курса уже есть урок, не предлагаются (кроме собственного дня переносимого урока)
            int dayA = slotA / MAX_LESSON_IN_DAY;
            bool busyDay[32] = {false};

            for (int day = 0; day < JOB_WEEK_LENGHT && day < 32; day++) {
                busyDay[day] = day != dayA && courseHasLessonOnDay(cls, day * MAX_LESSON_IN_DAY);
            }

            // Допустимые слоты: сначала дешёвые проверки (день, преподаватель), потом canPlaceLesson,
            // которая смотрит ещё и на соседей курса по линейке
            targetCandidates.clear();

            for (int slot = 0; slot < SLOTS; slot++) {
                if (slot == slotA || busyDay[slot / MAX_LESSON_IN_DAY]) {
                    continue;
                }

                if (teacherCanAccept(teacher, slot) && canPlaceLesson(cls, slot, subjectID)) {
                    targetCandidates.push_back(slot);
                }
            }

            if (targetCandidates.empty()) {
                continue;
            }

            int slotB = targetCandidates[randint(0, targetCandidates.size() - 1)];

            double before = localEnergy(cls, involvedTeachers);

            // Перенос урока из слота from в слот to — и в строке курса, и в строке преподавателя
            auto moveLesson = [&](int from, int to) {
                graph[cls][from].clear();
                graph[teacher][from].clear();
                graph[cls][to].push_back(edge(teacher, subjectID));
                graph[teacher][to].push_back(edge(cls, subjectID));
            };

            auto applyMove = [&]() {
                moveLesson(slotA, slotB);
            };

            auto revertMove = [&]() {
                moveLesson(slotB, slotA);
            };

            count += 1;

            applyMove();

            double delta = localEnergy(cls, involvedTeachers) - before;

            accept(delta, revertMove, applyMove);
        }

        // ХОД 3: вставить непоставленный урок в слот, где соблюдены все жёсткие правила и у курса
        // в этот день ещё нет урока. Если таких слотов нет — пропуск (возможно, другие ходы
        // позже освободят место).
        if (type == 3) {
            int idx = randint(0, missingLessons.size() - 1);
            Lesson item = missingLessons[idx];

            targetCandidates.clear();

            for (int slot = 0; slot < SLOTS; slot++) {
                if (courseHasLessonOnDay(item.cls, slot / MAX_LESSON_IN_DAY * MAX_LESSON_IN_DAY) || !canPlaceLesson(item.cls, slot, item.subjectID)) {
                    continue;
                }

                if (teacherCanAccept(item.teacher, slot)) {
                    targetCandidates.push_back(slot);
                }
            }

            if (targetCandidates.empty()) {
                continue;
            }

            int slot = targetCandidates[randint(0, targetCandidates.size() - 1)];

            involvedTeachers.assign(1, item.teacher);

            double before = localEnergy(item.cls, involvedTeachers);

            auto insertLesson = [&]() {
                placeLesson(item, slot);
                missingLessons.erase(missingLessons.begin() + idx);
            };

            auto removeLesson = [&]() {
                graph[item.cls][slot].clear();
                graph[item.teacher][slot].clear();
                missingLessons.insert(missingLessons.begin() + idx, item);
            };

            count++;
            insertLesson();

            // Урок перестал быть «непоставленным»: из энергии уходят его 2e6, поэтому вставка
            // почти всегда выгодна (Δ сильно отрицательна) и принимается сразу
            double delta = localEnergy(item.cls, involvedTeachers) - before - Weights::missingLesson;

            accept(delta, removeLesson, insertLesson);
        }

        // ХОД 4: смена преподавателя — все уроки курса по предмету, и поставленные, и непоставленные,
        // отдаются другому кандидату «может вести»; клетки не двигаются. Жёсткие правила: у нового
        // преподавателя меньше максимума курсов, и в каждой клетке курса он не «не может» и не занят (правила
        // со стороны курса не меняются — клетки те же). Слагаемые курса id преподавателя не читают,
        // поэтому Δ = изменение штрафов двух преподавателей и цены смены (teacherChangeCost)
        if (type == 4) {
            int index = switchable[randint(0, switchable.size() - 1)];
            const CourseChoice& choice = choices[index];
            int from = choiceTeacher[index];
            int to = choice.candidates[randint(0, choice.candidates.size() - 1)];

            if (to == from) {
                continue;
            }

            if (coursesByTeacher[to] >= TEACHER_MAX_COURSES) {
#ifdef CHECK_ENERGY
                limitRejects++;
#endif
                continue;
            }

            if (!canTakeCells(index, to)) {
                continue;
            }

            auto applyChange = [&]() {
                handOver(index, from, to);
            };

            auto revertChange = [&]() {
                handOver(index, to, from);
            };

            double before = teacherTotal(from) + teacherTotal(to) + teacherChangeCost(index);

            count++;
            applyChange();

            double delta = teacherTotal(from) + teacherTotal(to) + teacherChangeCost(index) - before;

            accept(delta, revertChange, applyChange);
        }
    }

    // ===== 8. Результат =====
    // Ответ — лучшее увиденное состояние, а не последнее. Если bestUnsaved == true, текущее
    // состояние само и есть лучшее (копии нет и она не нужна).
    if (!bestUnsaved && cur > bestEnergy + 1e-6) {
        restoreBest();
    }

    // Доводка по ходу 4 (решение заказчика 4: смены без выигрыша в ответе нет). Лучшее часто
    // запоминается в горячей части цикла, и в него попадает смена, принятая «в гору» (+ цена смены)
    // рядом с другим большим выигрышем; откатить её потом некому, а завуч увидел бы «Сменится
    // преподаватель» там, где смена ничего не даёт (замер на 10 млн шагов, цикл 5 млн: в 15 прогонах
    // из 56 — до 7 таких смен; там же оставались смены с выигрышем 30). Поэтому — проход без случайных
    // чисел: пока у курсов со сменой есть смена с Δ < 0 (лимит курсов и клетки — как у хода 4), она
    // делается. Возврат к выбранному до отжига, если штрафы преподавателей те же, даёт Δ = −цена смены.
    // Затем — совместный возврат пары сменённых курсов к выбранным до отжига: курсы-уровни в одних и тех
    // же клетках, обменявшиеся преподавателями (X: A → B, Y: B → A), дают те же штрафы преподавателей и
    // две цены смены, а вернуть один курс нельзя — преподаватель оказался бы на двух уроках сразу
    // (замер: b2_free, b2u_free на 10 млн шагов — в 15 и 20 прогонах из 24). Оба курса переводятся без
    // проверок, потом проверяются клетки (один урок, не «не может») и лимит курсов; при Δ ≥ 0 или
    // нарушении — откат. Каждая смена уменьшает энергию, поэтому проход конечен; без курсов со сменой
    // он ничего не делает, и ответ с журналом — те же байты, что до хода 4
    vector<int> pairCells[2];

    auto returnPair = [&](int x, int y) {
        const int course[2] = {x, y};
        int from[2], to[2];

        for (int k = 0; k < 2; k++) {
            from[k] = choiceTeacher[course[k]];
            to[k] = firstTeacher[course[k]];
            pairCells[k].clear();

            for (int slot = 0; slot < SLOTS; slot++) {
                if (cellSubject(choices[course[k]].cls, slot) == choices[course[k]].subjectID) {
                    pairCells[k].push_back(slot);
                }
            }
        }

        vector<int> teachers = {from[0], to[0], from[1], to[1]};

        sort(teachers.begin(), teachers.end());
        teachers.erase(unique(teachers.begin(), teachers.end()), teachers.end());

        vector<int> countsBefore;
        double before = teacherChangeCost(x) + teacherChangeCost(y);

        for (int teacher : teachers) {
            countsBefore.push_back(coursesByTeacher[teacher]);
            before += teacherTotal(teacher);
        }

        for (int k = 0; k < 2; k++) {
            courseCells = pairCells[k];
            handOver(course[k], from[k], to[k]);
        }

        bool valid = true;

        for (int k = 0; k < 2; k++) {
            for (int slot : pairCells[k]) {
                valid &= graph[to[k]][slot].size() == 1 && teacherIsAllowed[to[k]][slot];
            }
        }

        for (int i = 0; i < (int)teachers.size(); i++) {
            int now = coursesByTeacher[teachers[i]];

            valid &= now <= countsBefore[i] || now <= TEACHER_MAX_COURSES;
        }

        if (valid) {
            double delta = teacherChangeCost(x) + teacherChangeCost(y) - before;

            for (int teacher : teachers) {
                delta += teacherTotal(teacher);
            }

            if (delta < -1e-6) {
                cur += delta;
                return true;
            }
        }

        for (int k = 1; k >= 0; k--) {
            courseCells = pairCells[k];
            handOver(course[k], to[k], from[k]);
        }

        return false;
    };

    for (bool improved = !switchable.empty(); improved;) {
        improved = false;

        for (int index : switchable) {
            for (int to : choices[index].candidates) {
                int from = choiceTeacher[index];

                if (to == from || coursesByTeacher[to] >= TEACHER_MAX_COURSES || !canTakeCells(index, to)) {
                    continue;
                }

                double before = teacherTotal(from) + teacherTotal(to) + teacherChangeCost(index);

                handOver(index, from, to);

                double delta = teacherTotal(from) + teacherTotal(to) + teacherChangeCost(index) - before;

                if (delta < -1e-6) {
                    cur += delta;
                    improved = true;
                } else {
                    handOver(index, to, from);
                }
            }
        }

        for (int i = 0; i < (int)switchable.size(); i++) {
            for (int j = i + 1; j < (int)switchable.size(); j++) {
                int x = switchable[i], y = switchable[j];

                if (choiceTeacher[x] != firstTeacher[x] && choiceTeacher[y] != firstTeacher[y] && returnPair(x, y)) {
                    improved = true;
                }
            }
        }
    }

#ifdef CHECK_ENERGY
    check("best");
#endif

    for (const Lesson& item : missingLessons) {
        cout << "[Внимание] " << item.className << " / " << item.subjectName << ": нет свободного времени — у преподавателя всё занято или «не может», либо у курса уже есть урок в каждый свободный день\n";
    }

    if (!missingLessons.empty()) {
        cout << "[Внимание] не удалось поставить уроков: " << missingLessons.size() << "\n";
    }

    // Запись ответа (JSON с отступом 4). Итоговая строка «Готово: ...» — только для журнала:
    // об окончании сервер узнаёт по коду выхода и файлу --output
    std::ofstream file(output);

    file << std::setw(4) << save() << std::endl;
    file.close();

    // Оценено изменений (count) обычно заметно меньше шагов: часть шагов отсеивают жёсткие правила,
    // а при закреплениях шаг часто выбирает курс, у которого двигать нечего
    cout << "Готово: оценено изменений " << count << " из " << stepsDone << " шагов" << endl;

#ifdef CHECK_ENERGY
    cout << "CHECK checks=" << checks << " bad=" << badChecks << " badState=" << badState << " maxDiff=" << maxDiff
         << " limitRejects=" << limitRejects << endl;
#endif

    return 0;
}
