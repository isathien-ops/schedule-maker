"""Действия вкладки «Версии» (`src/web/tabs/save.py`): сохранение, возврат и удаление версий.

Перед возвратом текущее состояние сохраняется версией «Перед возвратом к версии от <когда>»,
её комментарий — имя восстановленной версии.

Основа — `RealProjectCase` из `tests/real_project.py`: копия реального проекта 2026/27, «сегодня»
04.10.2026, действия идут через сервер, как со страницы (POST /api/project/<имя>/action).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import datetime
import json
import os

from src.modules.translate import translate
from src.modules.functions.variants import loadVariants, saveVariant
from src.modules.functions.versions import saveVersion
from tests.real_project import RealProjectCase


class SaveTabTests(RealProjectCase):
    """Вкладка «Версии»."""
    NAME = "__test_versions__"

    def test_save_restore_remove(self):
        """Версия без имени получает имя «Версия от …»; восстановление возвращает настройки, само
        сохраняет «Перед возвратом к версии от …» и стирает варианты; удалённую версию не восстановить.
        """
        self.ok("newVersion", name="  ", comment="до правок")
        saved = self.state()["versions"][0]
        self.assertTrue(saved["name"].startswith("Версия от"))
        self.assertEqual((saved["comment"], saved["lessons"]), ("до правок", 116))

        self.ok("setLimit", key="max_courses_per_teacher", value=3)
        saveVariant(self.folder, "2", 1, {})

        self.ok("restore", version=saved["id"])
        self.assertEqual(self.state()["limits"]["max_courses_per_teacher"], 10)
        self.assertTrue(self.versions()[0].startswith("Перед возвратом к версии от"))
        self.assertEqual(loadVariants(self.folder, "2"), [])

        self.ok("removeVersion", version=saved["id"])
        self.assertNotIn(saved["id"], [item["id"] for item in self.state()["versions"]])
        self.refused("restore", version=saved["id"])
        self.refused("removeVersion", version=saved["id"])
        self.refused("restore", version="../../settings")

    def test_restore_names_version_by_date_of_restored(self):
        """Перед возвратом сохраняется версия «Перед возвратом к версии от дд.мм чч:мм»; комментарий — имя
        восстановленной версии.
        """
        version = saveVersion(self.folder, "Тестовая версия", "", [], now=datetime.datetime(2025, 3, 7, 9, 5))
        before = set(self.versionList())

        self.ok("restore", version=version)

        after = self.versionList()
        new = [after[key] for key in set(after) - before]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["name"], translate("web.version.before_restore").replace("{when}", "07.03 09:05"))
        self.assertEqual(new[0]["comment"], "Тестовая версия")

    def test_restore_of_version_without_date_uses_its_name(self):
        """У версии нет даты создания (meta.json правили руками): в имени версии «Перед возвратом…»
        вместо даты — имя восстановленной версии.
        """
        version = saveVersion(self.folder, "Без даты", "", [])
        meta = os.path.join(self.folder, "versions", version, "meta.json")

        with open(meta, encoding="utf-8") as file:
            data = json.load(file)

        del data["created"]

        with open(meta, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)

        before = set(self.versionList())
        self.ok("restore", version=version)
        new = [item for key, item in self.versionList().items() if key not in before]

        self.assertEqual([item["name"] for item in new], [translate("web.version.before_restore").replace("{when}", "Без даты")])

    def test_restore_unknown_version(self):
        """Восстановить или удалить несуществующую версию нельзя; проект не меняется, новых версий нет."""
        versions = self.versions()
        before = self.raw("settings.json")

        self.assertEqual(self.refused("restore", version="20000101-000000"), translate("web.error.no_version"))
        self.assertEqual(self.refused("restore", version="../.."), translate("web.error.no_version"))
        self.assertEqual(self.refused("removeVersion", version="20000101-000000"), translate("web.error.no_version"))

        self.assertEqual(self.versions(), versions)
        self.assertEqual(self.raw("settings.json"), before)
