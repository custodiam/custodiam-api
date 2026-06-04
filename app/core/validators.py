"""Validadores de dominio reutilizables para los schemas Pydantic.

Centraliza reglas de validación que aplican a varios schemas de entrada
para no duplicarlas. Las comprobaciones de formato simples (longitud,
``EmailStr``) viven en los propios campos; aquí van las que necesitan
lógica, pensadas para usarse desde un ``@field_validator``.
"""

from datetime import date


def fecha_no_futura(valor: date) -> date:
    """Rechaza fechas posteriores a hoy (p. ej. una fecha de nacimiento).

    Devuelve el valor sin cambios si es válido para encadenarlo en un
    ``@field_validator``; lanza ``ValueError`` (que Pydantic convierte en
    error de validación 422) si la fecha es futura.
    """

    if valor > date.today():
        raise ValueError("La fecha no puede ser futura")
    return valor
