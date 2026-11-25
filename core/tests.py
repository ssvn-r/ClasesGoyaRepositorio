from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.models import Task


class ImportTasksCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)

    def write_provider(self, filename, content):
        (self.data_dir / filename).write_text(content, encoding="utf-8")

    def run_import(self):
        with patch("core.management.commands.import_tasks.DATA_DIR", self.data_dir):
            call_command("import_tasks")

    def test_imports_tasks_from_json_csv_and_xml(self):
        self.write_provider(
            "tasks_provider_a.json",
            '[{"title":"Inválida","priority":[],"status":"pendiente"},'
            '{"title":"JSON","priority":"alta","status":"pendiente"}]',
        )
        self.write_provider(
            "tasks_provider_b.csv",
            "title,priority,status\nCSV,media,pendiente\n",
        )
        self.write_provider(
            "tasks_provider_c.xml",
            "<tasks><task><title>XML</title><priority>baja</priority>"
            "<status>completada</status></task></tasks>",
        )

        self.run_import()

        self.assertEqual(Task.objects.count(), 3)
        self.assertSetEqual(
            set(Task.objects.values_list("source", flat=True)),
            {"proveedor_a", "proveedor_b", "proveedor_c"},
        )

    def test_import_continues_when_one_provider_has_invalid_json(self):
        self.write_provider("tasks_provider_a.json", "{invalid json")
        self.write_provider(
            "tasks_provider_b.csv",
            "title,priority,status\nCSV,media,pendiente\n",
        )
        self.write_provider(
            "tasks_provider_c.xml",
            "<tasks><task><title>XML</title><priority>baja</priority>"
            "<status>completada</status></task></tasks>",
        )

        self.run_import()

        self.assertEqual(Task.objects.count(), 2)
        self.assertSetEqual(
            set(Task.objects.values_list("source", flat=True)),
            {"proveedor_b", "proveedor_c"},
        )
