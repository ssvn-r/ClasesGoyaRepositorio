from datetime import date, timedelta
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


class CrudApiTests(APITestCase):
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

    def test_task_list_returns_project_and_tags(self):
        response = self.client.get("/api/tasks/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["project"], self.project.id)
        self.assertEqual(response.data[0]["tags"][0]["name"], "backend")

    def test_task_crud_returns_expected_http_statuses(self):
        created = self.client.post(
            "/api/tasks/",
            {
                "project": self.project.id,
                "title": "Nueva tarea",
                "priority": "media",
                "status": "pendiente",
            },
            format="json",
        )

        self.assertEqual(created.status_code, 201)
        task_id = created.data["id"]
        self.assertEqual(
            self.client.get(f"/api/tasks/{task_id}/").status_code,
            200,
        )
        updated = self.client.patch(
            f"/api/tasks/{task_id}/",
            {"title": "Tarea actualizada"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["title"], "Tarea actualizada")
        replaced = self.client.put(
            f"/api/tasks/{task_id}/",
            {
                "project": self.project.id,
                "title": "Tarea reemplazada",
                "description": "Reemplazo completo",
                "priority": "alta",
                "status": "pendiente",
                "due_date": None,
            },
            format="json",
        )
        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(replaced.data["title"], "Tarea reemplazada")
        self.assertEqual(
            self.client.delete(f"/api/tasks/{task_id}/").status_code,
            204,
        )
        self.assertEqual(
            self.client.get(f"/api/tasks/{task_id}/").status_code,
            404,
        )

    def test_invalid_input_returns_400_with_error_envelope(self):
        response = self.client.post(
            "/api/tasks/",
            {"project": self.project.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.data["error"])
        self.assertIn("title", response.data["detail"])

    def test_business_validations_reject_invalid_tasks(self):
        past_date = (date.today() - timedelta(days=1)).isoformat()
        past_deadline = self.client.post(
            "/api/tasks/",
            {
                "project": self.project.id,
                "title": "Fecha vencida",
                "due_date": past_date,
            },
            format="json",
        )
        completed_without_date = self.client.post(
            "/api/tasks/",
            {
                "project": self.project.id,
                "title": "Sin fecha",
                "status": "completada",
            },
            format="json",
        )
        in_progress_without_completed = self.client.post(
            "/api/tasks/",
            {
                "project": self.project.id,
                "title": "En progreso prematuro",
                "status": "en_progreso",
            },
            format="json",
        )

        self.assertEqual(past_deadline.status_code, 400)
        self.assertEqual(completed_without_date.status_code, 400)
        self.assertEqual(in_progress_without_completed.status_code, 400)

        Task.objects.create(
            project=self.project,
            title="Tarea completada",
            status="completada",
            due_date=date.today(),
        )
        allowed_in_progress = self.client.post(
            "/api/tasks/",
            {
                "project": self.project.id,
                "title": "En progreso permitido",
                "status": "en_progreso",
            },
            format="json",
        )
        self.assertEqual(allowed_in_progress.status_code, 201)

    def test_project_viewset_supports_create_update_and_delete(self):
        created = self.client.post(
            "/api/projects/",
            {"name": "Proyecto nuevo", "description": "Prueba CRUD"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        project_id = created.data["id"]
        self.assertEqual(
            self.client.get(f"/api/projects/{project_id}/").status_code,
            200,
        )

        updated = self.client.put(
            f"/api/projects/{project_id}/",
            {"name": "Proyecto actualizado", "description": ""},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["name"], "Proyecto actualizado")
        self.assertEqual(
            self.client.delete(f"/api/projects/{project_id}/").status_code,
            204,
        )

    def test_unknown_api_exception_returns_consistent_500(self):
        with patch(
            "core.views.ProjectViewSet.list",
            side_effect=RuntimeError("error simulado"),
        ):
            response = self.client.get("/api/projects/")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.data,
            {"error": True, "detail": "Error interno del servidor."},
        )

    def test_health_check_remains_available(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "TaskFlow API"})
