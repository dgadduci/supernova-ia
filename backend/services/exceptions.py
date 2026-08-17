class ComercioNotFound(Exception):
    pass


class EstadoComercioNotFound(Exception):
    pass


class EstadoComercioInUse(Exception):
    pass


class DuplicateWhatsapp(Exception):
    pass


class DuplicateSlug(Exception):
    pass


class DuplicateEstado(Exception):
    pass


class InvalidEstado(Exception):
    pass


class InvalidTrialConfiguration(ValueError):
    """Raised when the trial configuration supplied to a commerce
    mutation is invalid.

    The validation requires either:

    * the selected state has a non-PRUEBA operating mode and no
      trial columns are supplied (``prueba_hasta`` and
      ``prueba_max_pedidos`` are both ``None``);
    * the selected state has the PRUEBA operating mode, a future
      ``prueba_hasta`` and a positive ``prueba_max_pedidos``.

    Any other combination is rejected with a bounded ``400``
    feedback so the panel can re-render the form with the documented
    error and a fresh path-bound CSRF nonce.
    """


class EstadoComercioNotSelectable(ValueError):
    """Raised when an admin mutation targets a non-selectable state.

    The commerce lifecycle policy marks SUSPENDIDO / BAJA (and any
    other legacy row) as ``seleccionable=False``. The create and
    update services must reject those ids before any staging so a
    forged or stale ``estado_id`` payload cannot move a commerce to
    a historical / blocked configuration through the documented
    admin seams.

    The exception is a typed ``ValueError`` so callers see a
    bounded, panel-renderable feedback instead of a generic 5xx
    trace.
    """


class CommerceUnavailable(Exception):
    """Raised when the commerce availability policy rejects a
    confirmation attempt.

    The exception is the typed signal every
    ``BORRADOR -> INGRESADO`` seam raises when the commerce is
    blocked, missing, expired or quota-exhausted. The router / panel
    translates it to the documented ``409`` / panel feedback. The
    reservation is staged in the same transaction so a ``commit``
    failure rolls back both the pedido transition and the counter
    increment together.
    """


class MediosPagoNotFound(Exception):
    pass


class DuplicateMedioPago(Exception):
    pass


class InvalidMedioPago(Exception):
    pass


class MetodoEntregaNotFound(Exception):
    pass


class DuplicateMetodoEntrega(Exception):
    pass


class InvalidMetodoEntrega(Exception):
    pass


class CategoriaProductoNotFound(Exception):
    pass


class InvalidCategoriaProducto(Exception):
    pass


class PresentacionNotFound(Exception):
    pass


class DuplicatePresentacionCodigo(Exception):
    pass


class DuplicatePresentacionDescripcion(Exception):
    pass


class InvalidPresentacion(Exception):
    pass


class ProductoNotFound(Exception):
    pass


class DuplicateProductoNombre(Exception):
    pass


class InvalidProducto(Exception):
    pass


class ProductoPresentacionNotFound(Exception):
    pass


class PrecioNotFound(Exception):
    pass


class DuplicatePrecio(Exception):
    pass


class InvalidPrecio(Exception):
    pass


class PedidoNotFound(Exception):
    pass


class PedidoNotEditable(Exception):
    pass


class InvalidEstadoTransition(Exception):
    pass


class InvalidEstadoPedido(Exception):
    pass


class ClienteNotFound(Exception):
    pass


class InvalidWhatsApp(Exception):
    pass


class SessionNotFound(Exception):
    pass


class DuplicateActiveSession(Exception):
    pass


class SessionNotActive(Exception):
    pass


class IncompatiblePedidoAssociation(Exception):
    pass


class SessionAlreadyClosed(Exception):
    pass


class PedidoProductoNotFound(Exception):
    pass


class PedidoProductoNotEditable(Exception):
    pass


class PedidoSessionMismatch(Exception):
    """Raised when a pedido does not belong to the supplied conversation
    session.

    The original ``set_observacion_producto`` seam was the only
    caller that raised this sentinel when ``Pedido.id_session``
    differed from the supplied ``session_id``. The seam has been
    removed (the product-line observation capability is no longer an
    active feature), but the sentinel remains as a domain marker
    because the validation contract is shared with the rest of the
    transactional services.
    """


class InvalidCantidad(Exception):
    pass


class ModificationFailed(Exception):
    """Sentinel raised by `PedidoProductoService.modify_product` when an
    unexpected technical failure must be propagated to the handler as a
    deterministic `failed` outcome without rolling back the caller's
    transaction.

    The handler translates this sentinel to `processed_intent.status =
    "failed"`. Any other exception propagates unchanged so the transactional
    wrapper's `db.rollback()` is preserved.
    """


class ProductoAliasNotFound(Exception):
    pass


class InvalidProductoAlias(Exception):
    pass


class DuplicateProductoAlias(Exception):
    pass


class ProductoAliasPresentationMismatch(Exception):
    pass


class UnsafeAliasSeederMapping(Exception):
    pass


class ProductoPresentacionEmbeddingNotFound(LookupError):
    pass


class InvalidProductoPresentacionEmbedding(ValueError):
    pass


class ProductoPresentacionEmbeddingPersistenceError(Exception):
    pass


class DuplicateProductoPresentacionEmbedding(Exception):
    pass


class InvalidEmbeddingStatusTransition(ValueError):
    """Raised when ``mark_status`` is called with a forbidden transition."""


class DuplicateEmbeddingDocument(Exception):
    """Raised when a partial unique index conflict is detected."""


EmbeddingNotFound = ProductoPresentacionEmbeddingNotFound
InvalidEmbedding = InvalidProductoPresentacionEmbedding


class LocalAdminEndpointsDisabled(Exception):
    """Sentinel for the local-admin endpoint gate.

    Subphase 4.7 does NOT raise this exception on the HTTP path — the
    router installs a ``404`` short-circuit before any service call so
    the disabled surface is indistinguishable from a missing route. The
    exception remains available for callers that want to expose the
    same gate programmatically (e.g., a CLI helper).
    """


class InvalidProductEmbeddingAdminScope(ValueError):
    """Raised when the supplied ``producto_id`` / ``producto_presentacion_id``
    does not belong to the requested ``comercio_id``.

    Covers ONLY the scope-filter case. It MUST NOT wrap the non-positive
    ``batch_size`` validation — that case is raised separately as
    :class:`InvalidBatchSize`. The two exceptions are independent and
    map to ``HTTP 400`` at the router.
    """


class InvalidBatchSize(ValueError):
    """Raised when ``batch_size`` is supplied through the admin endpoint
    and is not a positive integer.

    The Pydantic request schema does NOT validate ``batch_size``; the
    rejection is performed at the service layer so the operator gets
    ``400 InvalidBatchSize`` instead of ``422 pydantic.ValidationError``.
    """


class InvalidVectorSearchDimension(ValueError):
    """Raised when ``search_similar(query_embedding=...)`` is called with
    a vector whose length differs from ``Settings.embedding_dimension``.

    The dimension check is performed by the 4.9 search service AFTER
    the ``top_k`` check and BEFORE the repository is invoked. It is
    independent of :class:`InvalidProductoPresentacionEmbedding` and
    :class:`InvalidVectorSearchTopK` so the search path has its own
    domain error vocabulary.
    """


class InvalidVectorSearchTopK(ValueError):
    """Raised when ``search_similar(top_k=...)`` is called with a
    non-positive integer.

    The ``top_k`` check is the FIRST validation performed by the 4.9
    search service and runs BEFORE the dimension check and BEFORE the
    empty-candidate-list short-circuit. It is independent of
    :class:`InvalidVectorSearchDimension` so the search path has its
    own domain error vocabulary.
    """


class ShadowComparisonUnavailable(RuntimeError):
    """Raised internally by the 4.10 shadow recorder path when the
    comparison cannot be persisted.

    Subphase 4.10 NEVER raises this exception to the product-recognition
    caller — the shadow service catches every exception and translates
    it to a sanitized failure category. The exception is reserved for
    callers that want to expose the gate programmatically (e.g., a CLI
    helper or a future audit subphase).
    """


class InvalidProductRecognizerMode(ValueError):
    """Reserved internal marker for the product-recognizer mode validation.

    The env-var resolver in ``backend.config.settings`` no longer
    raises this exception for an unrecognised
    ``PRODUCT_RECOGNIZER_MODE``; it falls back to the safe default
    ``"fuzzy"`` and emits a sanitized structured warning instead.

    The class is retained as a reserved marker so callers that want
    to validate settings coming from a non-env source can still
    raise / catch the documented exception without importing any
    new name.
    """


class InvalidShadowVectorTopK(ValueError):
    """Raised when ``Settings.shadow_vector_top_k`` is not a positive
    integer.

    The check is performed at ``Settings.load()`` time. The shadow
    service uses ``settings.shadow_vector_top_k`` as the ``top_k``
    argument for the 4.9 ``ProductPresentationVectorSearchService
    .search_similar`` call.
    """


class InvalidShadowHybridMinScoreGap(ValueError):
    """Raised when ``Settings.shadow_hybrid_min_score_gap`` is outside
    the closed interval ``[0.0, 1.0]`` (including ``NaN``).

    The check is performed at ``Settings.load()`` time. The setting
    is **provisional** and **non-authoritative**: it is used only by
    the shadow-mode observational hybrid decision recorded on
    ``ProductRecognitionHybridObservation.min_score_gap`` so Subphase
    4.11 calibration can replace it without changing the observation
    surface.
    """


class InvalidHybridAuthoritativePolicyPath(ValueError):
    """Raised when ``Settings.hybrid_authoritative_policy_path`` is
    supplied with a value that is not usable in
    ``hybrid_authoritative`` mode.

    The validator runs ONLY when the effective
    ``product_recognizer_mode`` is ``"hybrid_authoritative"``. In
    that mode, the value must be either ``None`` or a non-empty
    ``str`` pointing at a JSON calibration report. Any other value
    (non-``None`` non-``str`` or empty ``str``) raises this
    exception so the operator can correct the value before the
    factory tries to load the policy file.

    When the effective mode is ``"fuzzy"`` (including the safe-fuzzy
    fallback case) or ``"shadow"``, the validator does NOT run and
    a non-``None`` value is silently ignored.
    """


class HybridAuthoritativePolicyError(Exception):
    """Raised when the hybrid authoritative policy loader cannot
    produce a usable ``HybridDecisionPolicy`` instance.

    The loader wraps every load-time failure (missing file,
    unparsable JSON, ineligible eligibility status, malformed
    ``selected_policy`` block, or constructor failure) in this
    exception so the factory raises a single exception type for the
    orchestrator-import-time ``get_product_recognizer(load_settings())``
    call to fail closed.

    The exception is intentionally NOT a ``ValueError`` so callers
    can distinguish it from the existing ``InvalidProductRecognizerMode``
    and ``InvalidHybridAuthoritativePolicyPath`` validation errors.
    """


class HybridAuthoritativeCommerceIdMissing(RuntimeError):
    """Raised by the hybrid authoritative recognizer when neither the
    ``intent_metadata`` context nor the factory-injected
    ``commerce_id_resolver`` can produce the ``id_comercio`` the
    vector-search pipeline needs.

    The OpenSpec contract for Subphase 4.12B requires every
    production entry point (``agregar_producto``,
    ``quitar_producto``, ``modificar_producto``, pending product
    selection, and pending modification destination) to thread the
    ``commerce_id`` through ``RecognizeContext.commerce_id``. When
    that contract is honoured the resolver is irrelevant and this
    exception is unreachable.

    The exception is the explicit boundary for the integration
    contract: a silent fallback to fuzzy would mask a configuration
    bug, and the OpenSpec only authorises fallback for technical
    failures (embedding/vector/repository/malformed/unexpected).
    Surfacing the missing-commerce-id condition immediately is the
    minimum safe behaviour compatible with the documented contract.

    The exception never carries the customer text, the catalog
    payload, the embedding prompt, the database credentials, a
    Python stack trace, or any internal infrastructure exception
    text.
    """


class InvalidCanalWhatsappDestination(ValueError):
    """Raised when a destination number is not a canonical E.164 value.

    The 5.1 channel service requires the canonical form: ``+`` followed
    by digits only, no transport prefix (``whatsapp:``), no whitespace
    and no leading zeros. Equivalent representations must normalize to
    the same value so provider + destination identity is stable.
    """


class InvalidCanalWhatsappProvider(ValueError):
    """Raised when a provider identifier is not a known closed-set value.

    Phase 5.1 only persists the provider as an identity (no credentials)
    and recognizes ``twilio``. Unknown providers are rejected so the
    resolver never silently conflates two provider scopes.
    """


class DuplicateCanalWhatsappDestination(Exception):
    """Raised when an active channel already exists for the same
    provider + canonical destination pair.

    The uniqueness rule applies only to active rows: deactivating a
    channel releases the (provider, destination_e164) pair for a new
    registration. Attempting to register a duplicate active channel
    is rejected before it reaches the database so callers receive a
    typed exception rather than an opaque IntegrityError.
    """


class CanalWhatsappNotFound(LookupError):
    """Raised when a referenced ``CanalWhatsapp`` row does not exist."""


class InvalidRoutingCode(ValueError):
    """Raised when a routing code is empty, contains whitespace only,
    or otherwise fails the opaque-public-identifier contract.

    The 5.1 service normalizes routing codes to a stable canonical
    form so equivalent QR slugs / short-link identifiers map to the
    same reservation row. Internal commerce IDs MUST NOT be reused
    as routing codes; the rejection is performed at the normalization
    boundary so the database never sees a malformed value.
    """


class DuplicateRoutingCodeReservation(Exception):
    """Raised when a (canal_id, routing_code_normalizado) pair is
    already reserved in the shared-channel history, including by a
    deactivated row.

    The reservation rule has no active predicate: deactivating a code
    revokes it and prevents a stale link/QR from being reassigned to
    another commerce. This exception is raised before any mutation so
    callers receive a typed signal rather than an opaque IntegrityError.
    """


class DedicatedChannelCannotHaveSharedMembership(Exception):
    """Raised when a caller attempts to register a shared-channel
    membership against a dedicated ``CanalWhatsapp``.

    The two ownership paths are intentionally distinct: dedicated
    channels own their exclusive ``Comercio`` through a direct FK;
    shared channels own their memberships through
    ``ComercioCanalCompartido``. Mixing them would break commerce
    isolation, so the service rejects the attempt.
    """


class SharedChannelCannotHaveExclusiveComercio(Exception):
    """Raised when a caller attempts to set ``id_comercio_exclusivo``
    on a shared ``CanalWhatsapp``.

    A shared channel carries no exclusive ``Comercio``; memberships
    live in ``ComercioCanalCompartido``. The cross-entity invariant is
    enforced at the service boundary so the database invariant
    (the ``canal_whatsapp_mode_comercio_exclusivo_chk`` check) is
    never violated.
    """


class InvalidSharedRoutingContext(ValueError):
    """Raised when the Phase-5.2 activation service receives an unusable
    ``canal_id``, ``cliente_id`` or ``mensaje_original_pendiente``.

    The caller must supply a positive integer ``canal_id`` and
    ``cliente_id`` and a non-empty ``str`` ``mensaje_original_pendiente``.
    Anything else is a contract violation and is rejected before any
    channel / membership / context lookup or mutation. Business-level
    outcomes (unknown channel, revoked code, inactive commerce, etc.)
    are NOT raised: the service returns them as typed outcomes so the
    caller can branch on a single attribute.
    """


class InvalidSharedChannelMembershipSelection(ValueError):
    """Raised when the Phase-5.3 manual-selection or switch service
    receives an unusable ``canal_id``, ``cliente_id`` or
    ``membership_id``.

    The caller must supply a positive integer for each identifier. Any
    other contract violation is rejected before any channel /
    membership / context lookup or mutation. Business-level outcomes
    (unknown channel, inactive membership, unavailable commerce, etc.)
    are NOT raised: the service returns them as typed outcomes so the
    caller can branch on a single attribute.
    """


class InvalidProviderInboundMessageCommand(ValueError):
    """Raised when the Phase-5.4 inbound coordinator receives an
    unusable command: a non-positive ``canal_id``, ``cliente_id`` or
    ``comercio_id``, a missing or empty ``proveedor`` /
    ``identificador_recepcion`` / ``mensaje`` or a non-string value
    where a string is required.

    The caller MUST supply a validated active routing decision. The
    coordinator does not parse provider payloads, perform signature
    validation or infer identity from any other field: contract
    violations are rejected before any database lookup or receipt
    claim so the receipt boundary can never observe a malformed
    input. Business-level outcomes (unknown channel, inactive
    commerce, missing shared context, etc.) are NOT raised: the
    coordinator returns them as typed outcomes so the caller can
    branch on a single attribute.
    """


class InvalidTwilioWebhookAuthToken(ValueError):
    """Raised when the Phase-5.5 Twilio ingress receives an unusable
    ``TWILIO_AUTH_TOKEN`` value: a value other than ``None`` /
    missing or a non-empty stripped string.

    The token is required only for the new Twilio inbound webhook
    surface; unrelated local API startup must not depend on it. A
    non-empty stripped string is the only accepted shape so the SDK
    ``RequestValidator`` can never be constructed with empty
    credentials.
    """


class InvalidTwilioWebhookBaseUrl(ValueError):
    """Raised when the Phase-5.5 Twilio ingress receives an unusable
    ``TWILIO_WEBHOOK_BASE_URL`` value: a non-absolute, non-HTTPS URL,
    a URL containing a query string or fragment, or a non-empty
    stripped string that is otherwise malformed.

    The base URL is required only for the new Twilio inbound webhook
    surface; unrelated local API startup must not depend on it. The
    validator rejects anything that would let an attacker rewrite
    the canonical signature-URL outside the configured scope.
    """


class InvalidTwilioInboundForm(ValueError):
    """Raised when a validly signed Twilio inbound request supplies
    a malformed ``MessageSid``, ``From``, ``To`` or ``Body`` value.

    The exception is raised by the Phase-5.5 adapter AFTER the
    Twilio signature has been validated; it is therefore a
    business-level rejection that the router translates into a safe
    control TwiML reply without invoking the Phase-5.4 coordinator.
    """


class TwilioSignatureUnavailable(RuntimeError):
    """Raised when the Twilio signature cannot be validated because
    the configured base URL is missing or the constructed canonical
    URL is malformed.

    The router treats this signal identically to an invalid
    signature: it returns ``403`` with no TwiML and no downstream
    call. The exception is reserved for callers that want to
    distinguish "configuration missing" from "request forged".
    """


class InvalidOutboundProviderMessage(ValueError):
    """Raised when the Phase-5.6 outbox staging receives an unusable
    argument: an empty ``proveedor`` / ``destinatario_e164`` /
    ``cuerpo``, a non-positive ``recepcion_mensaje_proveedor_id`` or
    a non-negative ``sequence`` that is not actually an integer.

    The caller MUST supply a valid immutable rendered customer
    response plus its zero-based position. The mapper does not parse
    provider payloads, perform signature validation or rebuild
    customer responses: contract violations are rejected before any
    database lookup so the outbox boundary can never observe a
    malformed input.
    """


class InvalidTwilioOutboundDispatchConfig(ValueError):
    """Raised when the Phase-5.6 outbound dispatcher settings are
    unusable: a missing ``twilio_outbound_sender_e164``, a missing
    ``twilio_callback_status_url``, non-positive retry bounds or a
    non-positive lease window.

    The dispatcher reads its configuration at process time so the
    operator gets a single, typed error instead of a runtime failure
    in the middle of a network call.
    """


class InvalidProviderProcessingWorkerConfig(ValueError):
    """Raised when the automatic provider-processing worker settings are
    unusable: an enabled worker with a non-positive poll interval, a
    non-positive inbound bound, a non-positive outbound bound, or a
    missing / invalid existing outbound dispatch configuration.

    The check is performed during the worker startup validation step
    that the Railway entrypoint invokes before ``uvicorn`` accepts
    traffic. A failure here surfaces as a typed exit code so the
    operator gets a single actionable error instead of a silent
    disablement or a runtime failure inside the first cycle.
    """


class InvalidTwilioDeliveryCallbackForm(ValueError):
    """Raised when a validly signed Twilio status callback supplies a
    malformed ``MessageSid`` or ``MessageStatus`` value.

    The exception is raised by the Phase-5.6 callback adapter AFTER the
    Twilio signature has been validated; it is therefore a
    business-level rejection that the router translates into a safe
    no-op reply (``204``) without mutating an outbound row.
    """


class InvalidWhatsappPilotProvisioningInput(ValueError):
    """Raised when the controlled-WhatsApp pilot routing CLI receives
    unusable inputs: a non-positive ``--comercio-id``, an empty
    ``--cliente-e164``, a sender setting missing from ``Settings`` or
    a value that fails canonical E.164 normalization.

    The exception is the single boundary for CLI-level input and
    configuration rejection. The CLI translates it into exit code ``2``
    with a sanitized ``input_invalid`` status that never leaks the
    supplied address, sender or any message body.
    """


class WhatsappPilotProvisioningCommerceUnavailable(LookupError):
    """Raised when the requested pilot commerce is missing or not
    in the ``ACTIVO`` ``EstadoComercio``.

    The CLI is the sole owner of the routing-provisioning transaction.
    A missing or inactive commerce is the only validation outcome that
    is translated into a typed ``commerce_unavailable`` status
    BEFORE any staging, so the CLI rolls back without staging any
    client or channel row.
    """


class FlavorComunicacionNotFound(LookupError):
    """Raised when the supplied flavor ID does not match any global
    ``FlavorComunicacion`` row.

    The Phase-1 selection service translates this exception to
    ``HTTP 404`` without mutating the target ``Comercio``.
    """


class FlavorComunicacionInactivo(Exception):
    """Raised when the supplied flavor ID is a known global
    ``FlavorComunicacion`` but is currently inactive.

    The Phase-1 selection service translates this exception to
    ``HTTP 409`` without mutating the target ``Comercio``.
    """


class InvalidPaymentField(ValueError):
    """Raised when the panel submits a per-commerce payment field
    that the global ``MediosPago`` flags disable.

    The Phase-1 administrative panel configuration service rejects
    the submission and preserves the stored value. The router
    translates this exception to a bounded ``400`` panel feedback
    without ever touching the bridge row.
    """


class InvalidDeliveryOrden(ValueError):
    """Raised when a per-commerce ``orden`` is not a non-negative
    integer.

    The database check constraint enforces the same gate; the
    service-level rejection is the documented adapter boundary
    so the panel can render a closed validation error before any
    persistence attempt.
    """
