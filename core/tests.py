from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.cache import cache
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from core.models import Project, Tag, Task
from core.services import HolidayService, ProjectService, TaskService


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
        self.user = get_user_model().objects.create_user(
            username="ana",
            password="Clave-Segura-2026!",
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(
            name="TaskFlow",
            description="Proyecto de prueba",
        )
        self.tag = Tag.objects.create(name="backend")
        self.task = Task.objects.create(
            project=self.project,
            owner=self.user,
            title="Crear API",
            priority="alta",
        )
        self.task.tags.add(self.tag)

    def test_project_list_returns_nested_tasks_and_tags(self):
        response = self.client.get("/api/projects/")

        self.assertEqual(response.status_code, 200)
        project = response.data["results"][0]
        self.assertEqual(project["name"], "TaskFlow")
        self.assertEqual(project["tasks"][0]["title"], "Crear API")
        self.assertEqual(project["tasks"][0]["tags"][0]["name"], "backend")

    def test_task_list_returns_project_and_tags(self):
        response = self.client.get("/api/tasks/")

        self.assertEqual(response.status_code, 200)
        task = response.data["results"][0]
        self.assertEqual(task["project"], self.project.id)
        self.assertEqual(task["tags"][0]["name"], "backend")

    def test_task_serializer_includes_holiday_flag(self):
        holiday = date(2026, 5, 25)
        self.task.due_date = holiday
        self.task.save(update_fields=["due_date"])

        with patch(
            "core.serializers.HolidayService.is_holiday",
            return_value=True,
        ) as is_holiday:
            response = self.client.get(f"/api/tasks/{self.task.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["due_on_holiday"])
        is_holiday.assert_called_once_with(holiday)

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
            Task.objects.get(pk=task_id).owner,
            self.user,
        )
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
            owner=self.user,
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

    def test_task_actions_complete_and_list_overdue(self):
        complete_without_deadline = self.client.post(
            f"/api/tasks/{self.task.id}/complete/",
            {},
            format="json",
        )
        self.assertEqual(complete_without_deadline.status_code, 400)

        self.task.due_date = date.today()
        self.task.save(update_fields=["due_date"])
        with patch("core.serializers.HolidayService.is_holiday", return_value=False):
            completed = self.client.post(
                f"/api/tasks/{self.task.id}/complete/",
                {},
                format="json",
            )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.data["status"], "completada")

        past_date = date.today() - timedelta(days=1)
        for index in range(6):
            Task.objects.create(
                project=self.project,
                owner=self.user,
                title=f"Vencida {index}",
                due_date=past_date,
            )
        Task.objects.create(
            project=self.project,
            owner=self.user,
            title="Vencida completada",
            status="completada",
            due_date=past_date,
        )
        with patch("core.serializers.HolidayService.is_holiday", return_value=False):
            overdue = self.client.get("/api/tasks/overdue/")

        self.assertEqual(overdue.status_code, 200)
        self.assertEqual(overdue.data["count"], 6)
        self.assertEqual(len(overdue.data["results"]), 5)

    def test_pagination_filters_search_and_project_summary(self):
        for index in range(5):
            Task.objects.create(
                project=self.project,
                owner=self.user,
                title=f"Reporte {index}",
                priority="media",
            )

        second_page = self.client.get("/api/tasks/?page=2")
        filtered = self.client.get("/api/tasks/?status=pendiente&priority=alta")
        searched = self.client.get("/api/tasks/?search=Reporte")

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(second_page.data["count"], 6)
        self.assertEqual(len(second_page.data["results"]), 1)
        self.assertEqual(filtered.data["count"], 1)
        self.assertEqual(searched.data["count"], 5)

        Task.objects.create(
            project=self.project,
            owner=self.user,
            title="Terminada",
            status="completada",
            due_date=date.today(),
        )
        Task.objects.create(
            project=self.project,
            owner=self.user,
            title="En progreso",
            status="en_progreso",
        )
        summary = self.client.get(f"/api/projects/{self.project.id}/summary/")

        self.assertEqual(summary.status_code, 200)
        self.assertEqual(
            summary.data,
            {"pendiente": 6, "en_progreso": 1, "completada": 1},
        )

    def test_owner_filter_hides_foreign_tasks_and_prevents_project_deletion(self):
        other_user = get_user_model().objects.create_user(
            username="bruno",
            password="Otra-Clave-Segura-2026!",
        )
        foreign_task = Task.objects.create(
            project=self.project,
            owner=other_user,
            title="Tarea privada",
        )

        self.assertEqual(
            self.client.get(f"/api/tasks/{foreign_task.id}/").status_code,
            404,
        )
        project = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(
            [task["title"] for task in project.data["tasks"]],
            ["Crear API"],
        )
        summary = self.client.get(
            f"/api/projects/{self.project.id}/summary/"
        )
        self.assertEqual(summary.data["pendiente"], 1)
        self.assertEqual(
            self.client.delete(f"/api/projects/{self.project.id}/").status_code,
            403,
        )
        self.assertTrue(Task.objects.filter(pk=foreign_task.pk).exists())

    def test_foreign_completion_does_not_authorize_task_progress(self):
        other_user = get_user_model().objects.create_user(
            username="bruno",
            password="Otra-Clave-Segura-2026!",
        )
        Task.objects.create(
            project=self.project,
            owner=other_user,
            title="Tarea completada ajena",
            status="completada",
            due_date=date.today(),
        )

        response = self.client.post(
            "/api/tasks/",
            {
                "project": self.project.id,
                "title": "Iniciar tarea",
                "status": "en_progreso",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class TaskServiceTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Servicios")

    def test_mark_completed_enforces_deadline_and_updates_task(self):
        task = Task.objects.create(project=self.project, title="Sin fecha")
        with self.assertRaises(ValidationError):
            TaskService.mark_completed(task)

        task.due_date = date.today()
        task.save(update_fields=["due_date"])
        completed = TaskService.mark_completed(task)

        self.assertEqual(completed.status, "completada")
        self.assertEqual(
            Task.objects.get(pk=task.pk).status,
            "completada",
        )

    def test_tasks_overdue_excludes_completed_and_future_tasks(self):
        yesterday = date.today() - timedelta(days=1)
        tomorrow = date.today() + timedelta(days=1)
        overdue = Task.objects.create(
            project=self.project,
            title="Vencida",
            due_date=yesterday,
        )
        Task.objects.create(
            project=self.project,
            title="Vencida y completada",
            status="completada",
            due_date=yesterday,
        )
        Task.objects.create(
            project=self.project,
            title="A futuro",
            due_date=tomorrow,
        )

        self.assertEqual(
            list(TaskService.tasks_overdue().values_list("pk", flat=True)),
            [overdue.pk],
        )

    def test_project_summary_counts_each_status(self):
        user = get_user_model().objects.create_user(username="service-user")
        Task.objects.create(
            project=self.project,
            owner=user,
            title="Pendiente",
        )
        Task.objects.create(
            project=self.project,
            owner=user,
            title="En progreso",
            status="en_progreso",
        )

        self.assertEqual(
            ProjectService.project_summary(self.project, user),
            {"pendiente": 1, "en_progreso": 1, "completada": 0},
        )


class HolidayServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("core.services.requests.get")
    def test_holiday_results_are_cached_by_year(self, mock_get):
        response = mock_get.return_value
        response.json.return_value = [{"date": "2026-05-25"}]

        self.assertTrue(HolidayService.is_holiday(date(2026, 5, 25)))
        self.assertFalse(HolidayService.is_holiday(date(2026, 5, 26)))

        mock_get.assert_called_once_with(
            "https://date.nager.at/api/v3/PublicHolidays/2026/AR",
            timeout=5,
        )

    @patch("core.services.requests.get", side_effect=requests.Timeout)
    def test_external_failure_is_cached_as_empty_list(self, mock_get):
        self.assertEqual(HolidayService.get_holidays(2026), [])
        self.assertEqual(HolidayService.get_holidays(2026), [])

        mock_get.assert_called_once()

    @patch("core.services.requests.get")
    def test_invalid_external_response_degrades_to_no_holidays(self, mock_get):
        mock_get.return_value.json.return_value = {"unexpected": "shape"}

        self.assertEqual(HolidayService.get_holidays(2026), [])


class JWTAuthenticationTests(APITestCase):
    def test_api_requires_authentication(self):
        response = self.client.get("/api/tasks/")

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers["WWW-Authenticate"].startswith("Bearer"))

    def test_register_login_refresh_and_access_owned_tasks(self):
        registration = self.client.post(
            "/api/register/",
            {
                "username": "carla",
                "email": "carla@example.com",
                "password": "N3v3rShare-this-Long-Passphrase!",
            },
            format="json",
        )
        self.assertEqual(registration.status_code, 201)
        self.assertNotIn("password", registration.data)

        user = get_user_model().objects.get(username="carla")
        self.assertTrue(
            user.check_password("N3v3rShare-this-Long-Passphrase!")
        )
        project = Project.objects.create(name="Proyecto de Carla")
        Task.objects.create(
            project=project,
            owner=user,
            title="Tarea privada de Carla",
        )

        login = self.client.post(
            "/api/token/",
            {
                "username": "carla",
                "password": "N3v3rShare-this-Long-Passphrase!",
            },
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("access", login.data)
        self.assertIn("refresh", login.data)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}"
        )
        tasks = self.client.get("/api/tasks/")
        self.assertEqual(tasks.status_code, 200)
        self.assertEqual(tasks.data["count"], 1)
        self.assertEqual(
            tasks.data["results"][0]["title"],
            "Tarea privada de Carla",
        )

        refresh = self.client.post(
            "/api/token/refresh/",
            {"refresh": login.data["refresh"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertIn("access", refresh.data)
        self.assertIn("refresh", refresh.data)
