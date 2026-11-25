from datetime import date

from rest_framework import serializers

from .models import Project, Tag, Task


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name"]


class TaskSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "project",
            "title",
            "description",
            "priority",
            "status",
            "due_date",
            "tags",
            "created_at",
        ]

    def validate_due_date(self, value):
        if value and value < date.today():
            raise serializers.ValidationError(
                "La fecha límite no puede ser en el pasado."
            )
        return value

    def validate(self, data):
        status = data.get("status", self.instance.status if self.instance else None)
        due_date = data.get(
            "due_date",
            self.instance.due_date if self.instance else None,
        )
        project = data.get(
            "project",
            self.instance.project if self.instance else None,
        )

        if status == "completada" and not due_date:
            raise serializers.ValidationError(
                "No se puede marcar una tarea como completada sin fecha límite registrada."
            )

        if status == "en_progreso" and project:
            completed_tasks = Task.objects.filter(
                project=project,
                status="completada",
            )
            if self.instance:
                completed_tasks = completed_tasks.exclude(pk=self.instance.pk)
            if not completed_tasks.exists():
                raise serializers.ValidationError(
                    "El proyecto debe tener una tarea completada antes de iniciar otra."
                )

        return data


class ProjectSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "description", "tasks", "created_at"]
