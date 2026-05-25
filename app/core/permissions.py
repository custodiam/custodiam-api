"""Catálogo de permisos RBAC y mapa rol → permisos.

Espeja exactamente la sección 3 de docs/trabajo/backlog/RBAC_v0.1.0.md.
Cuando esa matriz cambie, este módulo cambia en el mismo PR.

Diseño:
- ``Permission`` es un str-enum: el valor coincide con el identificador
  textual del permiso para que aparezca tal cual en logs y respuestas
  HTTP, y para que el frontend pueda compararlo como string plano.
- ``ROLE_PERMISSIONS`` mapea cada rol de Keycloak a un frozenset de
  permisos. El frozenset es deliberado: la matriz es inmutable en
  tiempo de ejecución y queremos error si alguien intenta mutarla.
- ``permissions_for_roles`` agrega los permisos de una lista de roles
  (un usuario puede tener varios). Es la función que consume
  ``has_permission`` en ``security.py``.
"""

from enum import StrEnum


class Permission(StrEnum):
    # E02 — Voluntarios
    VOLUNTARIOS_CREAR = "voluntarios.crear"
    VOLUNTARIOS_EDITAR = "voluntarios.editar"
    VOLUNTARIOS_EDITAR_PROPIO = "voluntarios.editar_propio"
    VOLUNTARIOS_DISPONIBILIDAD_PROPIA = "voluntarios.disponibilidad_propia"
    VOLUNTARIOS_VER_PROPIO = "voluntarios.ver_propio"
    VOLUNTARIOS_DAR_BAJA = "voluntarios.dar_baja"
    VOLUNTARIOS_LISTAR = "voluntarios.listar"
    VOLUNTARIOS_VER_FICHA = "voluntarios.ver_ficha"

    # E03 — Servicios
    SERVICIOS_CREAR_PREVENTIVO = "servicios.crear_preventivo"
    SERVICIOS_CREAR_EMERGENCIA = "servicios.crear_emergencia"
    SERVICIOS_PUBLICAR = "servicios.publicar"
    SERVICIOS_CONVOCAR = "servicios.convocar"
    SERVICIOS_VER_PUBLICADOS = "servicios.ver_publicados"
    SERVICIOS_APUNTARSE_PROPIO = "servicios.apuntarse_propio"
    SERVICIOS_DESAPUNTARSE_PROPIO = "servicios.desapuntarse_propio"
    SERVICIOS_CERRAR = "servicios.cerrar"

    # E04 — Fichaje
    FICHAJE_FICHAR_PROPIO = "fichaje.fichar_propio"
    FICHAJE_VER_PROPIO = "fichaje.ver_propio"
    FICHAJE_VER_VOLUNTARIOS_EN_SERVICIO = "fichaje.ver_voluntarios_en_servicio"

    # E05 — Inventario
    INVENTARIO_REGISTRAR_MATERIAL = "inventario.registrar_material"
    INVENTARIO_REGISTRAR_VEHICULO = "inventario.registrar_vehiculo"
    INVENTARIO_ASIGNAR_EQUIPAMIENTO_PERSONAL = "inventario.asignar_equipamiento_personal"
    INVENTARIO_PRESTAR_TEMPORAL = "inventario.prestar_temporal"
    INVENTARIO_REGISTRAR_DEVOLUCION = "inventario.registrar_devolucion"
    INVENTARIO_ASIGNAR_A_SERVICIO = "inventario.asignar_a_servicio"
    INVENTARIO_REPORTAR_INCIDENCIA = "inventario.reportar_incidencia"
    INVENTARIO_VER = "inventario.ver"

    # E06 — Notificaciones
    NOTIFICACIONES_RECIBIR_EMERGENCIA = "notificaciones.recibir_emergencia"
    NOTIFICACIONES_RECIBIR_NUEVO_SERVICIO = "notificaciones.recibir_nuevo_servicio"
    NOTIFICACIONES_CONFIGURAR_PROPIAS = "notificaciones.configurar_propias"
    NOTIFICACIONES_REGISTRAR_TOKEN = "notificaciones.registrar_token"

    # E07 — Offline
    OFFLINE_CONSULTAR_SERVICIOS = "offline.consultar_servicios"
    OFFLINE_FICHAR_PROPIO = "offline.fichar_propio"
    OFFLINE_VER_ESTADO_CONEXION = "offline.ver_estado_conexion"

    # Administración del sistema
    SISTEMA_PANEL_ADMIN = "sistema.panel_admin"
    SISTEMA_CONFIGURACION = "sistema.configuracion"
    SISTEMA_LOGS_AUDITORIA = "sistema.logs_auditoria"
    SISTEMA_EXPORTAR_RGPD = "sistema.exportar_rgpd"
    SISTEMA_BACKUPS = "sistema.backups"
    ECONOMICO_GESTIONAR = "economico.gestionar"
    DOCUMENTAL_GESTIONAR = "documental.gestionar"


# Atajos de conjuntos de permisos compartidos por varios roles.
_TODOS_LOS_OPERATIVOS_BASE: frozenset[Permission] = frozenset({
    Permission.VOLUNTARIOS_EDITAR_PROPIO,
    Permission.VOLUNTARIOS_DISPONIBILIDAD_PROPIA,
    Permission.VOLUNTARIOS_VER_PROPIO,
    Permission.SERVICIOS_VER_PUBLICADOS,
    Permission.SERVICIOS_APUNTARSE_PROPIO,
    Permission.SERVICIOS_DESAPUNTARSE_PROPIO,
    Permission.FICHAJE_FICHAR_PROPIO,
    Permission.FICHAJE_VER_PROPIO,
    Permission.INVENTARIO_REPORTAR_INCIDENCIA,
    Permission.NOTIFICACIONES_RECIBIR_EMERGENCIA,
    Permission.NOTIFICACIONES_RECIBIR_NUEVO_SERVICIO,
    Permission.NOTIFICACIONES_CONFIGURAR_PROPIAS,
    Permission.NOTIFICACIONES_REGISTRAR_TOKEN,
    Permission.OFFLINE_CONSULTAR_SERVICIOS,
    Permission.OFFLINE_FICHAR_PROPIO,
    Permission.OFFLINE_VER_ESTADO_CONEXION,
})

_BASE_VOLUNTARIO: frozenset[Permission] = _TODOS_LOS_OPERATIVOS_BASE | frozenset({
    Permission.VOLUNTARIOS_LISTAR,
})

_BASE_JEFE_EQUIPO: frozenset[Permission] = _BASE_VOLUNTARIO | frozenset({
    Permission.VOLUNTARIOS_VER_FICHA,
    Permission.SERVICIOS_CREAR_PREVENTIVO,
    Permission.SERVICIOS_CREAR_EMERGENCIA,
    Permission.SERVICIOS_PUBLICAR,
    Permission.SERVICIOS_CONVOCAR,
    Permission.SERVICIOS_CERRAR,
    Permission.FICHAJE_VER_VOLUNTARIOS_EN_SERVICIO,
    Permission.INVENTARIO_REGISTRAR_MATERIAL,
    Permission.INVENTARIO_PRESTAR_TEMPORAL,
    Permission.INVENTARIO_REGISTRAR_DEVOLUCION,
    Permission.INVENTARIO_ASIGNAR_A_SERVICIO,
    Permission.INVENTARIO_VER,
})

_BASE_JEFE_SECCION: frozenset[Permission] = _BASE_JEFE_EQUIPO | frozenset({
    Permission.INVENTARIO_ASIGNAR_EQUIPAMIENTO_PERSONAL,
})

_BASE_JEFE_UNIDAD: frozenset[Permission] = _BASE_JEFE_SECCION | frozenset({
    Permission.INVENTARIO_REGISTRAR_VEHICULO,
})

_BASE_SUBJEFE: frozenset[Permission] = _BASE_JEFE_UNIDAD | frozenset({
    Permission.VOLUNTARIOS_CREAR,
    Permission.VOLUNTARIOS_EDITAR,
    Permission.VOLUNTARIOS_DAR_BAJA,
})

_BASE_JEFE_AGRUPACION: frozenset[Permission] = _BASE_SUBJEFE | frozenset({
    Permission.SISTEMA_LOGS_AUDITORIA,
    Permission.SISTEMA_EXPORTAR_RGPD,
    Permission.ECONOMICO_GESTIONAR,
    Permission.DOCUMENTAL_GESTIONAR,
})

# Coordinador = líder institucional. Equivale a jefe_agrupacion en
# capacidades operativas (decisión 2 del documento RBAC).
_BASE_COORDINADOR: frozenset[Permission] = _BASE_JEFE_AGRUPACION

# Secretario = gestión documental + administrativa + escritura de
# inventario (papeleo formal). NO opera servicios ni convoca.
_BASE_SECRETARIO: frozenset[Permission] = frozenset({
    Permission.VOLUNTARIOS_CREAR,
    Permission.VOLUNTARIOS_EDITAR,
    Permission.VOLUNTARIOS_EDITAR_PROPIO,
    Permission.VOLUNTARIOS_VER_PROPIO,
    Permission.VOLUNTARIOS_DAR_BAJA,
    Permission.VOLUNTARIOS_LISTAR,
    Permission.VOLUNTARIOS_VER_FICHA,
    Permission.SERVICIOS_CREAR_PREVENTIVO,
    Permission.SERVICIOS_VER_PUBLICADOS,
    Permission.FICHAJE_VER_VOLUNTARIOS_EN_SERVICIO,
    Permission.INVENTARIO_REGISTRAR_MATERIAL,
    Permission.INVENTARIO_REGISTRAR_VEHICULO,
    Permission.INVENTARIO_REGISTRAR_DEVOLUCION,
    Permission.INVENTARIO_REPORTAR_INCIDENCIA,
    Permission.INVENTARIO_VER,
    Permission.NOTIFICACIONES_RECIBIR_EMERGENCIA,
    Permission.NOTIFICACIONES_RECIBIR_NUEVO_SERVICIO,
    Permission.NOTIFICACIONES_CONFIGURAR_PROPIAS,
    Permission.NOTIFICACIONES_REGISTRAR_TOKEN,
    Permission.OFFLINE_VER_ESTADO_CONEXION,
    Permission.SISTEMA_EXPORTAR_RGPD,
    Permission.DOCUMENTAL_GESTIONAR,
})

# Tesorero = lectura amplia + gestión económica paraguas. Sin altas/bajas
# ni operativa táctica (decisión 8 del documento RBAC).
_BASE_TESORERO: frozenset[Permission] = frozenset({
    Permission.VOLUNTARIOS_EDITAR_PROPIO,
    Permission.VOLUNTARIOS_VER_PROPIO,
    Permission.VOLUNTARIOS_LISTAR,
    Permission.VOLUNTARIOS_VER_FICHA,
    Permission.SERVICIOS_VER_PUBLICADOS,
    Permission.INVENTARIO_REPORTAR_INCIDENCIA,
    Permission.INVENTARIO_VER,
    Permission.NOTIFICACIONES_RECIBIR_EMERGENCIA,
    Permission.NOTIFICACIONES_RECIBIR_NUEVO_SERVICIO,
    Permission.NOTIFICACIONES_CONFIGURAR_PROPIAS,
    Permission.NOTIFICACIONES_REGISTRAR_TOKEN,
    Permission.OFFLINE_VER_ESTADO_CONEXION,
    Permission.ECONOMICO_GESTIONAR,
})

# Admin = técnico puro. Sin permisos operativos por sí solo
# (decisión 1 del documento RBAC).
_BASE_ADMIN: frozenset[Permission] = frozenset({
    Permission.NOTIFICACIONES_CONFIGURAR_PROPIAS,
    Permission.NOTIFICACIONES_REGISTRAR_TOKEN,
    Permission.OFFLINE_VER_ESTADO_CONEXION,
    Permission.SISTEMA_PANEL_ADMIN,
    Permission.SISTEMA_CONFIGURACION,
    Permission.SISTEMA_LOGS_AUDITORIA,
    Permission.SISTEMA_EXPORTAR_RGPD,
    Permission.SISTEMA_BACKUPS,
})


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "voluntario_practicas": _TODOS_LOS_OPERATIVOS_BASE,
    "voluntario": _BASE_VOLUNTARIO,
    "jefe_equipo": _BASE_JEFE_EQUIPO,
    "jefe_grupo": _BASE_JEFE_EQUIPO,
    "jefe_seccion": _BASE_JEFE_SECCION,
    "jefe_unidad": _BASE_JEFE_UNIDAD,
    "subjefe_agrupacion": _BASE_SUBJEFE,
    "jefe_agrupacion": _BASE_JEFE_AGRUPACION,
    "coordinador": _BASE_COORDINADOR,
    "secretario": _BASE_SECRETARIO,
    "tesorero": _BASE_TESORERO,
    "admin": _BASE_ADMIN,
}


def permissions_for_roles(roles: list[str]) -> frozenset[Permission]:
    """Unión de permisos de todos los roles que tiene el usuario.

    Roles desconocidos se ignoran silenciosamente: si Keycloak emite
    un rol que no está en la matriz, no aporta permisos. Esto evita
    fallos cuando se añade un rol nuevo en Keycloak antes de
    actualizar la matriz.
    """

    result: set[Permission] = set()
    for role in roles:
        result |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(result)
