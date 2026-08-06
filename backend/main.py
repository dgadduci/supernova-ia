from fastapi import FastAPI

from backend.routers import (
    admin_product_embeddings,
    categorias_productos,
    clientes,
    comercios,
    configuracion_comercio,
    estados_comercios,
    health,
    incoming_messages,
    medios_pago,
    metodos_entrega,
    pedido_productos,
    pedidos,
    precios,
    presentaciones,
    producto_queries,
    productos,
    sessions,
    twilio_delivery_callback,
    twilio_webhook,
)

app = FastAPI(title="supernova-ia API")
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
app.include_router(producto_queries.router)
app.include_router(pedidos.router)
app.include_router(clientes.router)
app.include_router(sessions.router)
app.include_router(incoming_messages.router)
app.include_router(pedido_productos.router)
app.include_router(admin_product_embeddings.router)
app.include_router(twilio_webhook.router)
app.include_router(twilio_delivery_callback.router)
