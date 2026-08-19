import logging

from fastapi import FastAPI

from backend.admin import index_routes as admin_index_routes
from backend.admin import routes as admin_catalog_routes
from backend.config.settings import load_settings
from backend.routers import (
    admin_pilot_orders,
    admin_product_embeddings,
    categorias_productos,
    clientes,
    comercios,
    configuracion_comercio,
    estados_comercios,
    flavors_comunicacion,
    health,
    incoming_messages,
    internal_commerce_installation,
    medios_pago,
    metodos_entrega,
    owner_onboarding,
    pedido_productos,
    pedidos,
    precios,
    presentaciones,
    producto_queries,
    productos,
    public_onboarding,
    sessions,
    twilio_delivery_callback,
    twilio_webhook,
)
from backend.services.instalacion_secret_envelope import (
    resolve_master_keys_from_env,
)

logger = logging.getLogger(__name__)


def _validate_startup_configuration() -> None:
    """Refuse to start the process when the documented invariants
    are violated.

    The validator runs at import time so the operator gets a
    single typed error before ``uvicorn`` accepts traffic instead
    of a ``503`` on the first request. The validator covers:

    * ``COMMERCE_INSTALLATION_MASTER_KEY`` must resolve to a valid
      Fernet URL-safe base64 key whenever the internal commerce
      installation ingress is mounted (the router is
      unconditionally registered below) OR when the
      ``COMMERCE_ISOLATED_OUTBOUND_ENABLED`` feature flag is on.
      Either condition is sufficient to fail closed so the operator
      cannot accidentally deploy the core without the master key
      while a T-C adapter is live.

    A missing or malformed master key raises the typed
    :class:`backend.services.exceptions.InvalidInstallationMasterKey`
    exception so the Railway entrypoint surfaces a single typed
    exit code instead of silently failing on the first request.
    """
    settings = load_settings()
    ingress_mounted = True
    needs_master_key = bool(
        settings.commerce_isolated_outbound_enabled
    ) or ingress_mounted
    if not needs_master_key:
        return
    resolve_master_keys_from_env()
    logger.info(
        "startup_configuration_validated",
        extra={
            "isolated_outbound_enabled": bool(
                settings.commerce_isolated_outbound_enabled
            ),
            "ingress_mounted": bool(ingress_mounted),
        },
    )


_validate_startup_configuration()


app = FastAPI(title="supernova-ia API")
app.include_router(public_onboarding.router)
app.include_router(owner_onboarding.router)
app.include_router(health.router)
app.include_router(comercios.router)
app.include_router(estados_comercios.router)
app.include_router(medios_pago.router)
app.include_router(metodos_entrega.router)
app.include_router(categorias_productos.router)
app.include_router(presentaciones.router)
app.include_router(productos.router)
app.include_router(precios.router)
app.include_router(configuracion_comercio.router)
app.include_router(flavors_comunicacion.router)
app.include_router(producto_queries.router)
app.include_router(pedidos.router)
app.include_router(clientes.router)
app.include_router(sessions.router)
app.include_router(incoming_messages.router)
app.include_router(pedido_productos.router)
app.include_router(admin_product_embeddings.router)
app.include_router(admin_pilot_orders.router)
app.include_router(admin_catalog_routes.router)
app.include_router(admin_index_routes.router)
app.include_router(twilio_webhook.router)
app.include_router(twilio_delivery_callback.router)
app.include_router(internal_commerce_installation.router)
