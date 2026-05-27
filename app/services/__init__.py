"""Capa de Service de Custodiam.

Orquesta los repositorios, valida reglas de negocio y traduce errores
de dominio a excepciones específicas que el Router transforma en
respuestas HTTP. La autorización declarativa (`require_permission`)
vive en el Router; los servicios solo refuerzan reglas de propiedad
(p.ej. "solo puede editar a sí mismo") que el RBAC declarativo no
puede expresar.
"""
