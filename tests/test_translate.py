"""Тексты интерфейса (`src/modules/translate.py`, `src/files/bundles/ru.hjson`).

* ``TranslateTests`` — ключи, которые предметная логика показывает людям, есть в ru.hjson;
* ``TrTests`` — ``tr``: подстановка значений в текст за один проход.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import glob
import os
import re
import unittest

from src.modules.translate import BUNDLE, fill, tr, translate
from src.modules.functions.penalties import TARGETS, TEMPLATES, describePenalty
from src.modules.functions.stages import stageLabel
from src.modules import translate as translate_module

FUNCTIONS_DIR = os.path.join("src", "modules", "functions")


class TranslateTests(unittest.TestCase):
    """Тексты интерфейса: ключи, которые предметная логика показывает людям, есть в ru.hjson."""
    def test_known_and_unknown_keys(self):
        """Известный ключ — русский текст; неизвестный — сам ключ, чтобы пропуск был виден."""
        self.assertEqual(translate("stage.stream"), BUNDLE["stage.stream"])
        self.assertNotEqual(translate("stage.stream"), "stage.stream")
        self.assertEqual(translate("нет.такого.ключа"), "нет.такого.ключа")

    def test_literal_keys_of_functions_exist(self):
        """Каждый ключ translate("…") и ValueError("…") в src/modules/functions есть в ru.hjson."""
        missing = []

        for path in glob.glob(os.path.join(FUNCTIONS_DIR, "*.py")):
            with open(path, "r", encoding="utf-8") as file:
                text = file.read()

            keys = re.findall(r"translate\(\s*[\"']([^\"'{}]+)[\"']\s*\)", text) + re.findall(r"ValueError\(\s*\"([a-z_]+\.[a-z_.]+)\"\s*\)", text)
            missing += [(os.path.basename(path), key) for key in keys if key not in translate_module.BUNDLE]

        self.assertEqual(missing, [])

    def test_rule_descriptions_have_no_raw_keys(self):
        """Описание правила любого вида и цели (с выбранным значением и «каждый…», где он бывает)
        собирается из текстов, без ключей и заготовок {…}.
        """
        for template in TEMPLATES:
            for target in TARGETS.get(template, (None,)):
                # «Каждый …» бывает у преподавателя и у линейки в «не больше N в день» (как в диалоге правила)
                values = ["Химия"] + ([""] if target == "teacher" or (template == "daily_limit" and target == "line") else [])

                for value in values:
                    params = {"target": target, "value": value, "days": [0, 6], "times": ["16:20 - 17:50"], "limit": 2,
                              "first": "Химия", "second": "Биология"}

                    text = describePenalty({"template": template, "params": params}, translate)

                    with self.subTest(template=template, target=target, value=value):
                        self.assertTrue(text)
                        self.assertNotRegex(text, r"penalty\.|abbreviate\.|\{[a-z]+\}")

    def test_stage_labels(self):
        """Название этапа: поток — «<Поток> N», блоки — их собственные названия."""
        self.assertEqual(stageLabel("2", translate), f"{translate('stage.stream')} 2")

        for block in ("extra", "may", "summer"):
            self.assertNotEqual(stageLabel(block, translate), f"stage.{block}")


class TrTests(unittest.TestCase):
    """tr: подстановка значений в текст из ru.hjson."""
    def test_values_are_substituted_once(self):
        """{code} заменяется значением; фигурные скобки внутри значения не считаются новым местом."""
        self.assertEqual(tr("web.run.solver_failed", code=3), translate("web.run.solver_failed").replace("{code}", "3"))
        self.assertEqual(tr("web.run.solver_failed", code="{code}"), translate("web.run.solver_failed"))

    def test_missing_values_and_unknown_keys(self):
        """Место без значения остаётся как есть; лишние значения не мешают; неизвестный ключ — сам ключ."""
        self.assertEqual(tr("web.run.solver_failed"), translate("web.run.solver_failed"))
        self.assertEqual(tr("web.run.solver_failed", code=1, extra=2), tr("web.run.solver_failed", code=1))
        self.assertEqual(tr("нет.такого.ключа", code=1), "нет.такого.ключа")

    def test_fill_ready_text(self):
        """fill — та же подстановка в готовый текст: за один проход, без значения место остаётся."""
        self.assertEqual(fill("{a} и {b}", a="{b}", b=1), "{b} и 1")
        self.assertEqual(fill("{a} и {c}", a=2), "2 и {c}")
