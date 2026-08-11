from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.dependencies import get_session, require_admin_token
from backend.schemas.configuracion_comercio import ComercioConfiguracionResponse
from backend.services.configuracion_comercio_service import ConfiguracionComercioService
from backend.services.exceptions import ComercioNotFound

router = APIRouter(
    tags=["comercios"],
    dependencies=[Depends(require_admin_token)],
)


def _service(session: Session = Depends(get_session)) -> ConfiguracionComercioService:
    return ConfiguracionComercioService(session)


@router.get(
    "/comercios/{comercio_id}/configuracion",
    response_model=ComercioConfiguracionResponse,
)
def get_configuracion_comercio(
    comercio_id: int,
    service: ConfiguracionComercioService = Depends(_service),
) -> ComercioConfiguracionResponse:
    try:
        return ComercioConfiguracionResponse.model_validate(
            service.get_by_id(comercio_id)
        )
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
