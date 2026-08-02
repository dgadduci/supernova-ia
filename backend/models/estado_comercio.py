from sqlalchemy import Column, Integer, String

from backend.models.base import Base


class EstadoComercio(Base):
    __tablename__ = "estado_comercio"

    id = Column(Integer, primary_key=True)
    estado = Column(String, nullable=False)
