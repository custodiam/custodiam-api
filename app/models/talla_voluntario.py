"""Talla de un voluntario para un tipo de equipamiento concreto."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.tipo_equipamiento import TipoEquipamiento
    from app.models.voluntario import Voluntario


class TallaVoluntario(SQLModel, table=True):
    """Talla declarada por un voluntario para un item de equipamiento.

    Constraint `uq_talla_voluntario_tipo`: un voluntario solo tiene una
    talla por tipo de equipamiento (la talla de camisa es una y única).
    """

    __tablename__ = "tallas_voluntario"

    __table_args__ = (
        UniqueConstraint(
            "voluntario_id", "tipo_id", name="uq_talla_voluntario_tipo"
        ),
    )

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    tipo_id: uuid.UUID = Field(foreign_key="tipos_equipamiento.id", index=True)
    valor: str = Field(max_length=20)

    voluntario: Optional["Voluntario"] = Relationship(back_populates="tallas")
    tipo: Optional["TipoEquipamiento"] = Relationship(back_populates="tallas")

    def __repr__(self) -> str:
        return (
            f"<TallaVoluntario voluntario={self.voluntario_id} "
            f"tipo={self.tipo_id} valor={self.valor}>"
        )
