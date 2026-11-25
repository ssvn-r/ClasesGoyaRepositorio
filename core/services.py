import requests
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Project, ProjectMembership, Task
from .repositories import TaskRepository


logger = logging.getLogger(__name__)


class TaskService:
    @staticmethod
    def mark_completed(task: Task) -> Task:
        if not task.due_date:
            raise ValidationError(
                "No se puede marcar una tarea como completada sin fecha límite registrada."
            )
        task.status = "completada"
        task.save(update_fields=["status"])
        return task

    @staticmethod
    def tasks_overdue(queryset=None):
        if queryset is None:
            queryset = TaskRepository.get_queryset()
        today = timezone.localdate()
        return queryset.filter(due_date__lt=today).exclude(status="completada")


class HolidayService:
    API_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/AR"

    @classmethod
    def get_holidays(cls, year: int) -> list[str]:
        cache_key = f"holidays_{year}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            response = requests.get(
                cls.API_URL.format(year=year),
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or any(
                not isinstance(item, dict)
                or not isinstance(item.get("date"), str)
                for item in payload
            ):
                raise ValueError("La respuesta de feriados tiene un formato inválido.")
            dates = [item["date"] for item in payload]
            cache.set(cache_key, dates, timeout=60 * 60 * 24)
        except (requests.RequestException, ValueError, KeyError):
            dates = []
            cache.set(cache_key, dates, timeout=60 * 5)
        return dates

    @classmethod
    def is_holiday(cls, some_date) -> bool:
        return some_date.isoformat() in cls.get_holidays(some_date.year)


class ProjectService:
    @staticmethod
    def project_summary(project: Project, owner=None) -> dict[str, int]:
        totals = dict(
            project.tasks.all()
            .values("status")
            .annotate(total=Count("id"))
            .values_list("status", "total")
        )
        return {
            status: totals.get(status, 0)
            for status, _ in Task.STATUS_CHOICES
        }


class MembershipService:
    @staticmethod
    def is_member(user, project) -> bool:
        project_id = getattr(project, "id", project)
        return ProjectMembership.objects.filter(
            project_id=project_id,
            user=user,
        ).exists()

    @staticmethod
    def is_admin(user, project) -> bool:
        return ProjectMembership.objects.filter(
            project=project,
            user=user,
            role="admin",
        ).exists()

    @staticmethod
    def projects_for(user):
        return Project.objects.filter(
            memberships__user=user,
        ).distinct().order_by("id")


class NotificationService:
    @staticmethod
    def notify_task_created(task):
        NotificationService._send(
            task.project_id,
            {
                "event": "task_created",
                "task_id": task.id,
                "title": task.title,
            },
        )

    @staticmethod
    def notify_task_updated(task):
        NotificationService._send(
            task.project_id,
            {
                "event": "task_updated",
                "task_id": task.id,
                "title": task.title,
            },
        )

    @staticmethod
    def notify_task_completed(task):
        NotificationService._send(
            task.project_id,
            {
                "event": "task_completed",
                "task_id": task.id,
                "title": task.title,
            },
        )

    @staticmethod
    def _send(project_id, payload):
        channel_layer = get_channel_layer()
        try:
            async_to_sync(channel_layer.group_send)(
                f"project_{project_id}",
                {
                    "type": "task_notification",
                    "payload": payload,
                },
            )
        except Exception:
            logger.exception(
                "No se pudo enviar la notificación en tiempo real"
            )
