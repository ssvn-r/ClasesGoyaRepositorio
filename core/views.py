from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Project, Task
from .repositories import TaskRepository
from .serializers import ProjectSerializer, TaskSerializer
from .serializers_auth import RegisterSerializer
from .services import ProjectService, TaskService


def health_check(request):
    return JsonResponse({"status": "ok", "service": "TaskFlow API"})


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.order_by("id")
    serializer_class = ProjectSerializer

    def get_queryset(self):
        owned_tasks = (
            Task.objects.filter(owner=self.request.user)
            .select_related("project")
            .prefetch_related("tags")
            .order_by("-created_at", "-id")
        )
        return super().get_queryset().prefetch_related(
            Prefetch("tasks", queryset=owned_tasks, to_attr="owned_tasks")
        )

    def perform_destroy(self, instance):
        if instance.tasks.exclude(owner=self.request.user).exists():
            raise PermissionDenied(
                "No se puede eliminar un proyecto con tareas de otros usuarios."
            )
        instance.delete()

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        project = self.get_object()
        return Response(ProjectService.project_summary(project, request.user))


class TaskViewSet(viewsets.ModelViewSet):
    queryset = TaskRepository.get_queryset()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["status", "priority", "project"]
    ordering_fields = ["due_date", "created_at", "priority"]
    search_fields = ["title", "description"]

    def get_queryset(self):
        return super().get_queryset().filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        TaskService.mark_completed(task)
        return Response(self.get_serializer(task).data)

    @action(detail=False, methods=["get"])
    def overdue(self, request):
        tasks = TaskService.tasks_overdue(self.get_queryset())
        page = self.paginate_queryset(tasks)
        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data
            )
        return Response(self.get_serializer(tasks, many=True).data)


class RegisterView(CreateAPIView):
    queryset = get_user_model().objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
