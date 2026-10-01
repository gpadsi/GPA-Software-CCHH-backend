# apps/core/permissions.py
# Permisos por rol, compartidos por todas las apps. Los 3 roles (Colaborador,
# Capital Humano, Admin) viven en apps.users.UserRole como catálogo (no
# enum), pero el CONJUNTO de roles es una regla de negocio cerrada
# (confirmado con el usuario 2026-09-22/23) — por eso aquí se compara contra
# el `code` fijo de cada uno, igual que otros valores de negocio fijos del
# proyecto (ej. NOMINA_TYPOS en apps.imports).
from rest_framework import permissions

CODE_CAPITAL_HUMANO = "capital-humano"
CODE_ADMIN = "admin"
ROLES_GESTION = (CODE_CAPITAL_HUMANO, CODE_ADMIN)


def _role_code(user):
    return user.role.code if getattr(user, "role_id", None) else None


def es_gestion_rrhh(user):
    return bool(user and user.is_authenticated and _role_code(user) in ROLES_GESTION)


class IsCapitalHumanoOrAdmin(permissions.BasePermission):
    """
    Acceso total (lectura y escritura) solo para Capital Humano y Admin.
    Cualquier otro usuario autenticado (ej. Colaborador) no tiene acceso ni
    de lectura — úsalo en datos que un Colaborador no debe ver ni de sí
    mismo por ahora (ej. HistorialSalarial, Attachment).
    """

    def has_permission(self, request, view):
        return es_gestion_rrhh(request.user)


class IsCapitalHumanoOrAdminOrReadOnly(permissions.BasePermission):
    """
    Capital Humano/Admin: lectura y escritura de cualquier registro.
    Cualquier otro usuario autenticado: solo lectura (GET/HEAD/OPTIONS).
    Úsalo tanto en catálogos estructurales que todos necesitan leer
    (Puesto, Área, OrganizationNode, Posición, Catorcena...) como en datos
    personales combinado con `scope_to_own_unless_management` en
    `get_queryset` para limitar esa lectura al propio registro.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return es_gestion_rrhh(user)


class IsOwnerOrGestionRRHH(permissions.BasePermission):
    """
    Cualquier usuario autenticado puede CREAR (ej. Requisicion: confirmado
    2026-10-01 que un Gerente/Director puede levantar una, y en este
    sistema sigue siendo rol "Colaborador" — no existe un rol de gerencia
    aparte, el filtro real de legitimidad es el flujo de aprobación, no el
    permiso de creación). Leer/editar su propio registro también se
    permite a quien lo creó (combínalo con `scope_to_own_unless_management`
    usando `"created_by"` como owner_lookup en `get_queryset`, igual que ya
    se hace con "user"/"empleado__user" en otras apps); borrar (incluido el
    soft-delete) queda reservado a Capital Humano/Admin, igual que el
    resto del proyecto.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if es_gestion_rrhh(request.user):
            return True
        if view.action == "destroy":
            return False
        return obj.created_by_id == request.user.id


def scope_to_own_unless_management(queryset, user, owner_lookup):
    """
    Capital Humano/Admin ven el queryset completo. Cualquier otro usuario
    (ej. Colaborador) solo ve las filas donde `owner_lookup` (ej.
    "empleado__user" o "user") apunta a sí mismo.
    """
    if es_gestion_rrhh(user):
        return queryset
    return queryset.filter(**{owner_lookup: user})
