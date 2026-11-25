from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Project, ProjectMembership, Task
from .permissions import IsProjectAdminOrReadOnly
from .repositories import TaskRepository
from .serializers import ProjectSerializer, TaskSerializer
from .serializers_auth import RegisterSerializer
from .services import MembershipService, ProjectService, TaskService


def health_check(request):
    return JsonResponse({"status": "ok", "service": "TaskFlow API"})


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all().order_by("id")
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, IsProjectAdminOrReadOnly]

    def get_queryset(self):
        return MembershipService.projects_for(self.request.user)

    def perform_create(self, serializer):
        with transaction.atomic():
            project = serializer.save()
            ProjectMembership.objects.create(
                project=project,
                user=self.request.user,
                role="admin",
            )

    @action(detail=True, methods=["post"])
    def add_member(self, request, pk=None):
        project = self.get_object()
        if not MembershipService.is_admin(request.user, project):
            raise PermissionDenied(
                "Solo un admin puede agregar miembros al proyecto."
            )

        username = request.data.get("username")
        role = request.data.get("role", "miembro")
        if role not in ("admin", "miembro"):
            return Response(
                {"detail": "El rol debe ser 'admin' o 'miembro'."},
                status=400,
            )

        try:
            user = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist:
            return Response(
                {"detail": "No existe un usuario con ese nombre."},
                status=404,
            )

        membership, created = ProjectMembership.objects.get_or_create(
            project=project,
            user=user,
            defaults={"role": role},
        )
        if not created:
            return Response(
                {"detail": "El usuario ya pertenece al proyecto."},
                status=400,
            )
        return Response(
            {
                "id": membership.id,
                "username": user.username,
                "role": membership.role,
            },
            status=201,
        )

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        project = self.get_object()
        return Response(ProjectService.project_summary(project))


class TaskViewSet(viewsets.ModelViewSet):
    queryset = TaskRepository.get_queryset()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated, IsProjectAdminOrReadOnly]
    filterset_fields = ["status", "priority", "project"]
    ordering_fields = ["due_date", "created_at", "priority"]
    search_fields = ["title", "description"]

    def get_queryset(self):
        return super().get_queryset().filter(
            project__memberships__user=self.request.user,
        ).distinct()

    def check_project_admin(self, project):
        if not MembershipService.is_admin(self.request.user, project):
            raise PermissionDenied(
                "Solo un admin del proyecto puede crear o mover tareas en él."
            )

    def perform_create(self, serializer):
        self.check_project_admin(serializer.validated_data["project"])
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        if "project" in serializer.validated_data:
            self.check_project_admin(serializer.validated_data["project"])
        serializer.save()

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


class SocialLoginJWTView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        refresh = RefreshToken.for_user(request.user)
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }
        )
