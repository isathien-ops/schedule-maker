"""Вкладка «Экспорт»: каждая кнопка «Скачать» отдаёт файл с понятным русским именем и нужным содержимым."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import io
import re
import zipfile

import openpyxl

from tests.ui.base import UICase, expect, t


class ExportTest(UICase):
    """Скачивания с вкладки «Экспорт» (вариантов в проекте нет)."""

    def download(self, index):
        """Нажимает «Скачать» в карточке index и возвращает (имя файла, путь к скачанному)."""
        button = self.page.locator(".tile-grid .tile").nth(index).locator("button", has_text=t("web.common.download"))

        with self.page.expect_download() as info:
            button.click()

        # На время скачивания кнопка неактивна, потом снова доступна
        expect(button).to_be_enabled()

        return info.value.suggested_filename, info.value.path()

    def cellsOf(self, path):
        """Все непустые значения ячеек книги Excel."""
        with open(path, "rb") as file:
            book = openpyxl.load_workbook(io.BytesIO(file.read()))  # у скачанного файла нет расширения

        return {str(cell.value) for sheet in book.worksheets for row in sheet.iter_rows() for cell in row if cell.value is not None}

    def test_excel_books(self):
        """Книги по курсам, преподавателям, список преподавателей и календарь: имена файлов и данные проекта внутри."""
        self.open("export")
        state = self.state()
        teacher = next(name for course in state["courses"] if course["scheduled"] for name in course["scheduled"])
        names = [
            f"{self.NAME}-курсы.xlsx",
            f"{self.NAME}-преподаватели.xlsx",
            f"{self.NAME}-{t('menu.main.tab.export.teacher_list_file')}.xlsx",
            f"{self.NAME}-календарь.xlsx",
        ]

        for index, expected in enumerate(names):
            with self.subTest(file=expected):
                name, path = self.download(index)
                self.assertEqual(name, expected)
                cells = " ".join(self.cellsOf(path))
                # Во всех книгах есть преподаватель из принятого расписания
                self.assertIn(teacher.split(" ")[0], cells)

    def test_project_archive(self):
        """«Весь проект»: ZIP с файлами проекта, который снова импортируется как проект."""
        self.open("export")
        name, path = self.download(5)
        self.assertEqual(name, f"{self.NAME}.zip")

        with zipfile.ZipFile(path) as archive:
            files = archive.namelist()

        self.assertTrue(any(item.endswith("settings.json") for item in files), files)
        self.assertTrue(any(item.endswith("answer.json") for item in files), files)

        copy = "__test_ui_reimported__"
        self.extra.append(copy)

        with open(path, "rb") as file:
            response = self.client.post("/api/projects/import", data={"file": (file, "project.zip"), "name": copy}, content_type="multipart/form-data")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.state(copy)["answer"], self.state()["answer"])

    def test_variants_need_variants(self):
        """Выгрузка вариантов без вариантов: кнопка неактивна, вместо выбора потока — пояснение."""
        self.open("export")
        card = self.page.locator(".tile-grid .tile").nth(4)
        expect(card).to_contain_text(t("menu.main.tab.export.save_variants"))
        expect(card.locator("button")).to_be_disabled()
        expect(card).to_contain_text(t("web.export_variants.none"))

    def test_download_refused(self):
        """Сервер отказал в выгрузке: его текст — во всплывающем сообщении (api() из core.js
        с raw: true), файл не скачивается, кнопка снова доступна."""
        self.allowRefusals()
        self.open("export")
        refusal = "Выгрузка не получилась"
        self.page.route("**/export/courses", lambda route: route.fulfill(status=400, json={"error": refusal}))
        downloads = []
        self.page.on("download", lambda download: downloads.append(download))

        button = self.page.locator(".tile-grid .tile").nth(0).locator("button", has_text=t("web.common.download"))
        button.click()

        self.toast(refusal)
        expect(self.page.locator("#toast")).to_have_class(re.compile(r"\berror-toast\b"))
        expect(button).to_be_enabled()
        self.assertEqual(downloads, [])
