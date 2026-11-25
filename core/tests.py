from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APITestCase

from core.models import Project, Tag, Task


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
            set(Task.objects.values_list("title", flat=True)),
            {"JSON", "CSV", "XML"},
        )
        self.assertEqual(Project.objects.get(name="Importaciones").tasks.count(), 3)

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
            set(Task.objects.values_list("title", flat=True)),
            {"CSV", "XML"},
        )


class ReadOnlyApiTests(APITestCase):
    def setUp(self):
        self.project = Project.objects.create(
            name="TaskFlow",
            description="Proyecto de prueba",
        )
        self.tag = Tag.objects.create(name="backend")
        self.task = Task.objects.create(
            project=self.project,
            title="Crear API",
            priority="alta",
        )
        self.task.tags.add(self.tag)

    def test_project_list_returns_nested_tasks_and_tags(self):
        response = self.client.get("/api/projects/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["name"], "TaskFlow")
        self.assertEqual(response.data[0]["tasks"][0]["title"], "Crear API")
        self.assertEqual(response.data[0]["tasks"][0]["tags"][0]["name"], "backend")

    def test_task_list_is_read_only(self):
        response = self.client.get("/api/tasks/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["project"], self.project.id)
        self.assertEqual(response.data[0]["tags"][0]["name"], "backend")
        self.assertEqual(
            self.client.post("/api/tasks/", {"title": "No permitido"}).status_code,
            405,
        )

    def test_project_detail_returns_project_or_404(self):
        response = self.client.get(f"/api/projects/{self.project.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "TaskFlow")
        self.assertEqual(
            self.client.get("/api/projects/999/").status_code,
            404,
        )

    def test_health_check_remains_available(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "TaskFlow API"})
