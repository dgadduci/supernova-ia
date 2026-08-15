from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.comunicacion_flavor import FlavorComunicacionSummary


class ComercioCreate(BaseModel):
    nombre_fantasia: str = Field(min_length=1, max_length=150)
    nombre_corto: str = Field(min_length=1, max_length=80)
    razon_social: str = Field(min_length=1, max_length=200)
    cuit: str = Field(min_length=1, max_length=20)
    whatsapp: str = Field(min_length=1, max_length=30)
    calle: str = Field(min_length=1, max_length=150)
    numero: str = Field(min_length=1, max_length=20)
    piso_departamento: str | None = Field(default=None, max_length=50)
    localidad: str = Field(min_length=1, max_length=100)
    provincia: str = Field(min_length=1, max_length=100)
    codigo_postal: str | None = Field(default=None, max_length=20)
    slug: str = Field(min_length=1, max_length=150)
    estado_id: int
    zona_horaria: str | None = Field(default=None, max_length=100)
    moneda: str | None = Field(default=None, max_length=3)
    idioma: str | None = Field(default=None, max_length=10)


class ComercioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_fantasia: str
    nombre_corto: str
    razon_social: str
    cuit: str
    whatsapp: str
    calle: str
    numero: str
    piso_departamento: str | None
    localidad: str
    provincia: str
    codigo_postal: str | None
    slug: str
    estado_id: int
    zona_horaria: str
    moneda: str
    idioma: str
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    fecha_baja: datetime | None
    flavor_comunicacion: FlavorComunicacionSummary
