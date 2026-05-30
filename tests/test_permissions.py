"""Tests del catálogo de permisos y del mapa rol → permisos.

Cruza casos representativos por rol contra la sección 3 del documento
``docs/trabajo/backlog/RBAC_v0.1.0.md``. Cuando esa matriz cambie, los
asserts de aquí cambian en el mismo PR — así una desincronización entre
documento y código sale a la luz inmediatamente.
"""

from app.core.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    permissions_for_roles,
)


class TestRoleMatrix:
    """Casos representativos de la matriz canónica (decisiones 1-12).

    Cada test cubre una celda no trivial. Lo no trivial es lo que
    distingue Custodiam de un RBAC genérico: dónde aplican los cortes
    jerárquicos y dónde no.
    """

    def test_admin_es_tecnico_puro_sin_operativa(self):
        perms = ROLE_PERMISSIONS["admin"]
        # Decisión 1: admin no tiene permisos operativos por sí solo.
        assert Permission.VOLUNTARIOS_CREAR not in perms
        assert Permission.SERVICIOS_CREAR_PREVENTIVO not in perms
        assert Permission.SERVICIOS_CONVOCAR not in perms
        assert Permission.FICHAJE_FICHAR_PROPIO not in perms
        assert Permission.INVENTARIO_REGISTRAR_MATERIAL not in perms
        # Pero sí los permisos técnicos.
        assert Permission.SISTEMA_PANEL_ADMIN in perms
        assert Permission.SISTEMA_BACKUPS in perms
        assert Permission.SISTEMA_CONFIGURACION in perms

    def test_admin_mas_coordinador_da_operativa_completa(self):
        # En el piloto Bajo Gállego la cuenta admin lleva además
        # coordinador (verificado en EN-01-03). La unión debe darle
        # todo lo operativo de coordinador + lo técnico de admin.
        perms = permissions_for_roles(["admin", "coordinador"])
        assert Permission.SISTEMA_PANEL_ADMIN in perms
        assert Permission.SERVICIOS_CREAR_EMERGENCIA in perms
        assert Permission.VOLUNTARIOS_CREAR in perms

    def test_coordinador_equivale_a_jefe_agrupacion_en_operativa(self):
        # Decisión 2: coordinador es líder institucional, no transversal
        # administrativo. Misma matriz operativa que jefe_agrupacion.
        assert ROLE_PERMISSIONS["coordinador"] == ROLE_PERMISSIONS["jefe_agrupacion"]

    def test_jefe_equipo_puede_crear_servicios(self):
        # Decisión 3: los jefes intermedios sí lideran servicios.
        perms = ROLE_PERMISSIONS["jefe_equipo"]
        assert Permission.SERVICIOS_CREAR_PREVENTIVO in perms
        assert Permission.SERVICIOS_CREAR_EMERGENCIA in perms
        assert Permission.SERVICIOS_PUBLICAR in perms
        assert Permission.SERVICIOS_CONVOCAR in perms
        assert Permission.SERVICIOS_CERRAR in perms

    def test_jefe_equipo_no_puede_dar_de_alta_voluntarios(self):
        # Decisión 4: la gestión orgánica de personas se sube a subjefe+.
        perms = ROLE_PERMISSIONS["jefe_equipo"]
        assert Permission.VOLUNTARIOS_CREAR not in perms
        assert Permission.VOLUNTARIOS_EDITAR not in perms
        assert Permission.VOLUNTARIOS_DAR_BAJA not in perms

    def test_subjefe_si_puede_dar_de_alta_voluntarios(self):
        perms = ROLE_PERMISSIONS["subjefe_agrupacion"]
        assert Permission.VOLUNTARIOS_CREAR in perms
        assert Permission.VOLUNTARIOS_EDITAR in perms
        assert Permission.VOLUNTARIOS_DAR_BAJA in perms

    def test_voluntario_practicas_puede_apuntarse_a_servicios(self):
        # Decisión 5: la organización del rol "acompañante" se hace in
        # situ, no por el RBAC.
        perms = ROLE_PERMISSIONS["voluntario_practicas"]
        assert Permission.SERVICIOS_APUNTARSE_PROPIO in perms
        assert Permission.SERVICIOS_DESAPUNTARSE_PROPIO in perms

    def test_voluntario_practicas_recibe_notificaciones_de_emergencia(self):
        # Decisión 6: todos los humanos reciben la notificación, hasta
        # los de prácticas.
        perms = ROLE_PERMISSIONS["voluntario_practicas"]
        assert Permission.NOTIFICACIONES_RECIBIR_EMERGENCIA in perms
        assert Permission.NOTIFICACIONES_RECIBIR_NUEVO_SERVICIO in perms

    def test_secretario_recibe_notificaciones_de_emergencia(self):
        # Decisión 6 también aplica a los administrativos.
        perms = ROLE_PERMISSIONS["secretario"]
        assert Permission.NOTIFICACIONES_RECIBIR_EMERGENCIA in perms

    def test_admin_puro_no_recibe_notificaciones_operativas(self):
        # Excepción a la decisión 6: el técnico sin rol operativo no
        # recibe pushes operativos.
        perms = ROLE_PERMISSIONS["admin"]
        assert Permission.NOTIFICACIONES_RECIBIR_EMERGENCIA not in perms
        assert Permission.NOTIFICACIONES_RECIBIR_NUEVO_SERVICIO not in perms

    def test_secretario_escribe_inventario_pero_no_asigna(self):
        # Decisión 8: secretario hace papeleo de inventario, no
        # operativa.
        perms = ROLE_PERMISSIONS["secretario"]
        assert Permission.INVENTARIO_REGISTRAR_MATERIAL in perms
        assert Permission.INVENTARIO_REGISTRAR_VEHICULO in perms
        assert Permission.INVENTARIO_REGISTRAR_DEVOLUCION in perms
        assert Permission.INVENTARIO_ASIGNAR_A_SERVICIO not in perms
        assert Permission.INVENTARIO_ASIGNAR_EQUIPAMIENTO_PERSONAL not in perms
        assert Permission.INVENTARIO_PRESTAR_TEMPORAL not in perms

    def test_tesorero_solo_lectura_en_inventario(self):
        # Decisión 8: tesorero solo lectura.
        perms = ROLE_PERMISSIONS["tesorero"]
        assert Permission.INVENTARIO_VER in perms
        assert Permission.INVENTARIO_REGISTRAR_MATERIAL not in perms
        assert Permission.INVENTARIO_REGISTRAR_VEHICULO not in perms
        # Y gestión económica como permiso paraguas.
        assert Permission.ECONOMICO_GESTIONAR in perms

    def test_tesorero_no_da_de_alta_ni_baja_voluntarios(self):
        perms = ROLE_PERMISSIONS["tesorero"]
        assert Permission.VOLUNTARIOS_CREAR not in perms
        assert Permission.VOLUNTARIOS_DAR_BAJA not in perms
        # Pero sí lectura amplia.
        assert Permission.VOLUNTARIOS_LISTAR in perms
        assert Permission.VOLUNTARIOS_VER_FICHA in perms

    def test_registrar_vehiculo_requiere_jefe_unidad_o_superior(self):
        # Decisión 9: el corte se sube por criticidad del activo.
        assert Permission.INVENTARIO_REGISTRAR_VEHICULO not in ROLE_PERMISSIONS["jefe_equipo"]
        assert Permission.INVENTARIO_REGISTRAR_VEHICULO not in ROLE_PERMISSIONS["jefe_grupo"]
        assert Permission.INVENTARIO_REGISTRAR_VEHICULO not in ROLE_PERMISSIONS["jefe_seccion"]
        assert Permission.INVENTARIO_REGISTRAR_VEHICULO in ROLE_PERMISSIONS["jefe_unidad"]
        assert Permission.INVENTARIO_REGISTRAR_VEHICULO in ROLE_PERMISSIONS["subjefe_agrupacion"]

    def test_asignar_equipamiento_personal_requiere_jefe_seccion_o_superior(self):
        # Decisión 10: trazabilidad RGPD y coste justifican subir el corte.
        assert (
            Permission.INVENTARIO_ASIGNAR_EQUIPAMIENTO_PERSONAL
            not in ROLE_PERMISSIONS["jefe_equipo"]
        )
        assert (
            Permission.INVENTARIO_ASIGNAR_EQUIPAMIENTO_PERSONAL
            not in ROLE_PERMISSIONS["jefe_grupo"]
        )
        assert (
            Permission.INVENTARIO_ASIGNAR_EQUIPAMIENTO_PERSONAL
            in ROLE_PERMISSIONS["jefe_seccion"]
        )

    def test_gestionar_dotacion_vehiculo_requiere_jefe_seccion_o_superior(self):
        # PR3 (SP-09): la dotación fija de material a vehículo se gestiona
        # con `inventario.gestionar_dotacion_vehiculo`, añadido en
        # `_BASE_JEFE_SECCION` y heredado por jefe_unidad / subjefe /
        # jefe_agrupacion / coordinador. No lo tienen los jefes de equipo
        # / grupo ni los roles administrativos (secretario / tesorero).
        for rol_sin in (
            "voluntario",
            "voluntario_practicas",
            "jefe_equipo",
            "jefe_grupo",
            "secretario",
            "tesorero",
            "admin",
        ):
            assert (
                Permission.INVENTARIO_GESTIONAR_DOTACION_VEHICULO
                not in ROLE_PERMISSIONS[rol_sin]
            ), f"El rol {rol_sin} no debería gestionar dotación de vehículo"
        for rol_con in (
            "jefe_seccion",
            "jefe_unidad",
            "subjefe_agrupacion",
            "jefe_agrupacion",
            "coordinador",
        ):
            assert (
                Permission.INVENTARIO_GESTIONAR_DOTACION_VEHICULO
                in ROLE_PERMISSIONS[rol_con]
            ), f"El rol {rol_con} debería gestionar dotación de vehículo"

    def test_crear_ubicacion_requiere_jefe_seccion_o_superior(self):
        # PR2 (E10): el catálogo de ubicaciones se escribe con
        # `ubicaciones.crear`, añadido en `_BASE_JEFE_SECCION` y heredado
        # por jefe_unidad / subjefe / jefe_agrupacion / coordinador. No lo
        # tienen los jefes de equipo / grupo ni los roles administrativos
        # (secretario / tesorero / admin) — decisión RBAC v0.2.0.
        for rol_sin in (
            "voluntario",
            "voluntario_practicas",
            "jefe_equipo",
            "jefe_grupo",
            "secretario",
            "tesorero",
            "admin",
        ):
            assert (
                Permission.UBICACIONES_CREAR not in ROLE_PERMISSIONS[rol_sin]
            ), f"El rol {rol_sin} no debería crear ubicaciones"
        for rol_con in (
            "jefe_seccion",
            "jefe_unidad",
            "subjefe_agrupacion",
            "jefe_agrupacion",
            "coordinador",
        ):
            assert (
                Permission.UBICACIONES_CREAR in ROLE_PERMISSIONS[rol_con]
            ), f"El rol {rol_con} debería crear ubicaciones"

    def test_reportar_incidencia_la_puede_hacer_cualquiera(self):
        # Decisión 11: cuanto más capilar, mejor.
        for role, perms in ROLE_PERMISSIONS.items():
            if role == "admin":
                # admin puro no opera por la decisión 1; si en la
                # práctica un admin necesita reportar, se le añade
                # un rol operativo además.
                continue
            assert Permission.INVENTARIO_REPORTAR_INCIDENCIA in perms, (
                f"El rol {role} debería poder reportar incidencias"
            )


class TestPermissionAggregation:
    """``permissions_for_roles`` une los permisos de varios roles."""

    def test_union_de_dos_roles(self):
        perms = permissions_for_roles(["voluntario", "tesorero"])
        # Operativos del voluntario.
        assert Permission.SERVICIOS_APUNTARSE_PROPIO in perms
        assert Permission.FICHAJE_FICHAR_PROPIO in perms
        # Económicos del tesorero.
        assert Permission.ECONOMICO_GESTIONAR in perms

    def test_lista_vacia_no_da_permisos(self):
        assert permissions_for_roles([]) == frozenset()

    def test_rol_desconocido_se_ignora_silenciosamente(self):
        # Si Keycloak emite un rol no registrado en la matriz, no
        # aporta permisos y no rompe la app.
        perms = permissions_for_roles(["rol_que_no_existe", "voluntario"])
        assert Permission.SERVICIOS_APUNTARSE_PROPIO in perms

    def test_rol_desconocido_solo_da_frozenset_vacio(self):
        assert permissions_for_roles(["rol_inventado"]) == frozenset()


class TestPermissionEnumIsStringValued:
    """``Permission`` es ``StrEnum`` para que el frontend pueda compararlo
    como string plano y para que aparezca tal cual en logs."""

    def test_enum_value_es_string(self):
        assert Permission.VOLUNTARIOS_CREAR.value == "voluntarios.crear"
        assert isinstance(Permission.VOLUNTARIOS_CREAR.value, str)

    def test_enum_es_comparable_con_string(self):
        # StrEnum permite comparar directamente con strings.
        assert Permission.VOLUNTARIOS_CREAR == "voluntarios.crear"


class TestMatrixCoverage:
    """Sanidad: todos los 12 roles del realm tienen entrada en la matriz."""

    def test_los_12_roles_del_realm_estan_mapeados(self):
        roles_realm = {
            "voluntario_practicas",
            "voluntario",
            "jefe_equipo",
            "jefe_grupo",
            "jefe_seccion",
            "jefe_unidad",
            "subjefe_agrupacion",
            "jefe_agrupacion",
            "secretario",
            "tesorero",
            "coordinador",
            "admin",
        }
        assert set(ROLE_PERMISSIONS.keys()) == roles_realm
