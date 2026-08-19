"""T-C adapter routes package.

Each route is a small FastAPI ``APIRouter`` so the test suite can mount
them in isolation and the runtime ``main`` module can compose the
three documented surfaces:

* :mod:`.health` — public health probe;
* :mod:`.webhook` — merchant Twilio webhook that forwards the canonical
  event to NovaOrders;
* :mod:`.outbound` — authenticated command endpoint that performs one
  ``messages.create`` per accepted command.

The routes never log body, phone, token, signature or credential.
"""