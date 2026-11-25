import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import Task


DATA_DIR = Path(settings.BASE_DIR) / "data"


class Command(BaseCommand):
    help = "Importa tareas desde proveedores JSON, CSV y XML"

    def handle(self, *args, **options):
        total = 0
        total += self._import_json("tasks_provider_a.json", "proveedor_a")
        total += self._import_csv("tasks_provider_b.csv", "proveedor_b")
        total += self._import_xml("tasks_provider_c.xml", "proveedor_c")
        self.stdout.write(
            self.style.SUCCESS(f"Importación finalizada: {total} tareas cargadas")
        )

    def _import_json(self, filename, source):
        path = DATA_DIR / filename
        try:
            with path.open(encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, list):
                raise ValueError("El contenido debe ser una lista JSON.")
            return sum(self._create_task(item, source) for item in data)
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
        ) as error:
            self.stderr.write(self.style.ERROR(f"Error importando {path}: {error}"))
            return 0

    def _import_csv(self, filename, source):
        path = DATA_DIR / filename
        try:
            with path.open(encoding="utf-8", newline="") as file:
                return sum(
                    self._create_task(row, source)
                    for row in csv.DictReader(file)
                )
        except (FileNotFoundError, UnicodeDecodeError, csv.Error) as error:
            self.stderr.write(self.style.ERROR(f"Error importando {path}: {error}"))
            return 0

    def _import_xml(self, filename, source):
        path = DATA_DIR / filename
        try:
            root = ET.parse(path).getroot()
            return sum(
                self._create_task(
                    {
                        "title": task.findtext("title"),
                        "priority": task.findtext("priority"),
                        "status": task.findtext("status"),
                    },
                    source,
                )
                for task in root.findall("task")
            )
        except (FileNotFoundError, ET.ParseError, UnicodeDecodeError) as error:
            self.stderr.write(self.style.ERROR(f"Error importando {path}: {error}"))
            return 0

    def _create_task(self, item, source):
        if not isinstance(item, dict):
            self.stderr.write(self.style.WARNING("Item inválido, se ignora"))
            return 0

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            self.stderr.write(self.style.WARNING("Item sin título, se ignora"))
            return 0

        priority = item.get("priority", "media")
        status = item.get("status", "pendiente")
        if priority in (None, ""):
            priority = "media"
        if status in (None, ""):
            status = "pendiente"
        if (
            not isinstance(priority, str)
            or priority not in dict(Task.PRIORITY_CHOICES)
        ):
            self.stderr.write(
                self.style.WARNING(f"Prioridad inválida, se ignora: {title}")
            )
            return 0
        if not isinstance(status, str) or status not in dict(Task.STATUS_CHOICES):
            self.stderr.write(
                self.style.WARNING(f"Estado inválido, se ignora: {title}")
            )
            return 0

        Task.objects.create(
            title=title.strip(),
            priority=priority,
            status=status,
            source=source,
        )
        return 1
