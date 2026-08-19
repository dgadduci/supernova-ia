"""Bounded CLI that provisions a single commerce Twilio installation.

This is the only entry point that creates an
``InstalacionTwilioComercio`` row. It loads the configured Fernet
master key from ``COMMERCE_INSTALLATION_MASTER_KEY`` (failing closed
when missing or malformed), asks the bounded
``InstalacionTwilioComercioService`` to provision a new installation and
prints the opaque ``instalacion_id`` plus the plain shared secret
exactly once on stdout.

The CLI owns the single setup transaction: the service and the
repository never ``commit`` / ``rollback`` / ``flush``; the CLI may
``flush`` once to surface the staged row id and then commits once or
rolls back on every exception.

The CLI never logs or prints the database URL, the master key, the
plain secret after the first stdout emission, the inbound body, the
configured sender, the configured webhook URL or any Twilio field
name. It only emits one bounded summary line per successful
provisioning.

The CLI fails closed at startup when:

* ``COMMERCE_INSTALLATION_MASTER_KEY`` is missing or not a valid
  Fernet URL-safe base64 key;
* ``--comercio-id`` is not a positive integer;
* ``--tc-service-url`` is missing, malformed or fails the documented
  HTTPS / Railway-private-network contract.

Usage:

.. code-block:: bash

    PYTHONPATH=. venv/bin/python -m backend.cli.instalacion_twilio_provision \\
        --comercio-id 7 --tc-service-url https://tc.example.test
"""
from __future__ import annotations

import argparse
import sys

from backend.dependencies import get_session as _default_get_session
from backend.services.exceptions import (
    DuplicateInstalacionTwilioComercio,
    InvalidInstallationIdentificador,
    InvalidInstallationMasterKey,
    InvalidInstallationTcServiceUrl,
)
from backend.services.instalacion_secret_envelope import (
    resolve_master_keys_from_env,
)
from backend.services.instalacion_twilio_comercio_service import (
    InstalacionTwilioComercioService,
    validate_tc_service_url,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="backend.cli.instalacion_twilio_provision",
        description=(
            "Provision a single commerce Twilio installation. The "
            "opaque instalacion_id and the plain shared secret are "
            "printed exactly once on stdout."
        ),
    )
    parser.add_argument(
        "--comercio-id",
        type=int,
        required=True,
        help="Internal comercio PK the installation will be bound to.",
    )
    parser.add_argument(
        "--tc-service-url",
        type=str,
        required=True,
        help=(
            "Per-installation T-C service URL. The CLI fails closed "
            "when the URL is missing, malformed or not aligned with the "
            "documented HTTPS / Railway-private-network contract."
        ),
    )
    return parser.parse_args(argv)


def _validate_inputs(args: argparse.Namespace) -> tuple[int, str]:
    if (
        not isinstance(args.comercio_id, int)
        or isinstance(args.comercio_id, bool)
        or args.comercio_id <= 0
    ):
        raise InvalidInstallationIdentificador(
            "--comercio-id must be a positive integer"
        )
    if not isinstance(args.tc_service_url, str):
        raise InvalidInstallationIdentificador(
            "--tc-service-url must be a string"
        )
    cleaned_url = validate_tc_service_url(args.tc_service_url)
    return int(args.comercio_id), cleaned_url


def _run(
    *,
    args: argparse.Namespace,
    session_factory,
) -> int:
    comercio_id, tc_service_url = _validate_inputs(args)
    bundle = resolve_master_keys_from_env()
    session = session_factory()
    try:
        service = InstalacionTwilioComercioService(
            session=session, master_keys=bundle
        )
        provisioned = service.create_installation(
            comercio_id=comercio_id,
            tc_service_url=tc_service_url,
        )
        session.commit()
    except DuplicateInstalacionTwilioComercio as exc:
        session.rollback()
        sys.stderr.write(f"error: {exc}\n")
        return 3
    except (
        InvalidInstallationIdentificador,
        InvalidInstallationMasterKey,
        InvalidInstallationTcServiceUrl,
    ) as exc:
        session.rollback()
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    sys.stdout.write(
        f"instalacion_id={provisioned.instalacion_id}\n"
    )
    sys.stdout.write(
        f"comercio_id={int(provisioned.comercio_id)}\n"
    )
    sys.stdout.write(
        f"plain_secret={provisioned.plain_secret}\n"
    )
    sys.stdout.write(
        f"tc_service_url={provisioned.tc_service_url}\n"
    )
    sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    def _session_factory():
        gen = _default_get_session()
        return next(gen)

    return _run(args=args, session_factory=_session_factory)


if __name__ == "__main__":
    raise SystemExit(main())