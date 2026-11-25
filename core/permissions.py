from rest_framework import permissions
import logging

from django.db import transaction

from .models import SecurityLog
from .services import MembershipService


security_logger = logging.getLogger("security")


class IsProjectAdminOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        project = obj.project if hasattr(obj, "project") else obj
        if request.method in permissions.SAFE_METHODS:
            return MembershipService.is_member(request.user, project)
        is_admin = MembershipService.is_admin(request.user, project)
        if not is_admin:
            ip = request.META.get("REMOTE_ADDR")
            with transaction.atomic():
                SecurityLog.objects.create(
                    user=request.user,
                    action="permission_denied",
                    detail=f"método={request.method} recurso={obj.__class__.__name__}",
                    ip_address=ip,
                )
            security_logger.warning(
                "Permiso denegado para usuario %s desde %s",
                request.user,
                ip,
            )
        return is_admin
