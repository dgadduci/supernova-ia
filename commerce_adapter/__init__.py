"""Commerce Twilio (T-C) adapter package marker.

The package exposes the FastAPI application via
``commerce_adapter.app.main``. Local development runs:

.. code-block:: bash

    PYTHONPATH=commerce_adapter venv/bin/uvicorn \\
        commerce_adapter.app.main:app --host 0.0.0.0 --port 8000

See ``commerce_adapter/README.md`` for the operator-facing setup notes
and the documented environment variables.
"""
__all__: list[str] = []