# Archivo: logica_fuzzy_pedido_productos.py
#
# ══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
#   detectar_productos(texto: str) -> str  (JSON string)
#
# DESCRIPCIÓN
#   Recibe el texto libre del cliente y devuelve un JSON string con tres listas:
#     - encontrados:                productos detectados y disponibles
#     - encontrados_no_disponibles: productos detectados pero con disponible=False
#     - no_encontrados:             fragmentos del pedido sin match en el catálogo
#   Cada producto encontrado incluye todos los campos de lista_json más "cantidad".
#   Soporta múltiples productos en una misma frase, tamaños y cantidades.
#
# EJEMPLO
#   Entrada : "quiero 2 pizzas muzza grande y una empanada de carne"
#   Salida  : '{
#               "encontrados": [
#                 {
#                   "id": 22,
#                   "nombre_producto": "Pizza Mozzarella con Albahaca",
#                   "tamanio": "grande",
#                   "precio": 10.0,
#                   "disponible": true,
#                   "cantidad": 2
#                 },
#                 {
#                   "id": 37,
#                   "nombre_producto": "Empanada de Carne",
#                   "tamanio": "unidad",
#                   "precio": 1.5,
#                   "disponible": true,
#                   "cantidad": 1
#                 }
#               ],
#               "encontrados_no_disponibles": [],
#               "no_encontrados": []
#             }'
#
#   Entrada : "una cerveza y algo raro"
#   Salida  : '{
#               "encontrados": [...],
#               "encontrados_no_disponibles": [],
#               "no_encontrados": ["algo raro"]
#             }'
# ══════════════════════════════════════════════════════════════════════════════

from backend.data.lista_json import productos as cat_prod_default
from rapidfuzz import fuzz, process
import re
import unicodedata

STOPWORDS = {
    "de", "con", "y", "la", "el", "un", "una", "unos", "unas",
    "los", "las", "mandame", "quiero", "quisiera", "dame", "trae",
    "traeme", "me", "por", "favor", "del", "para", "pero", "si",
    "que", "al", "en", "mi", "mis", "hola", "buenas", "buenos",
    "dias", "tardes", "noches", "necesito", "pedido", "pedir"
}

PALABRAS_CANTIDAD = {
    "un": "1", "uno": "1", "una": "1", "dos": "2", "tres": "3",
    "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7",
    "ocho": "8", "nueve": "9", "diez": "10"
}

TAMANIOS = {
    "chica", "chico", "grande", "mediana", "mediano",
    "familiar", "individual", "porcion", "porciones",
    "lata", "litro", "litros", "medio", "medios",
    "docena", "docenas",
}

# Aliases de palabras — normalizan variantes informales o mal escritas de
# ingredientes/productos a su forma canónica, token a token.
# Se aplican ANTES del matching fonético.
# Agregá acá cualquier variante que el sistema no resuelva solo.
ALIASES_PALABRAS: dict[str, str] = {
    # mozzarella y sus variantes
    "muza":        "mozzarella",
    "muzza":       "mozzarella",
    "muzarela":    "mozzarella",
    "muzarella":   "mozzarella",
    "mozarela":    "mozzarella",
    "mozarella":   "mozzarella",
    "muzzarela":   "mozzarella",
    "muzzarella":  "mozzarella",
    "musarela":    "mozzarella",
    "musarella":   "mozzarella",
    "mozarela":    "mozzarella",
    # fugazeta / fugazzeta
    "fugazeta":    "fugazzeta",
    "fugazetta":   "fugazzeta",
    # napolitana
    "napoli":      "napolitana",
    # calabresa
    "calabreza":   "calabresa",
}

# Sustituciones fonéticas del español — convierte todo a forma canónica
# para que "bizza", "pissa", "piza" → todos queden como "pisa" (clave interna)
_FONETICA = [
    (r"qu", "k"),
    (r"güe", "ge"),  (r"güi", "gi"),
    (r"gue", "ge"),  (r"gui", "gi"),
    (r"ue", "ue"),
    (r"ll", "y"),
    (r"v", "b"),
    (r"z", "s"),
    (r"ce", "se"),   (r"ci", "si"),
    (r"ch", "x"),    # canal de un solo caracter
    (r"ph", "f"),
    (r"h", ""),      # la h es muda en español
    (r"x(?=[aeiou])", "s"),  # "examen" → "esamen"
    (r"([bcdfghjklmnpqrstvwxyz])\1+", r"\1"),  # dobles consonantes → simple
]

def normalizar_texto(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = texto.encode("ascii", "ignore").decode("utf-8")
    texto = re.sub(r"[^a-z0-9ñ\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto

def normalizar_fonetico(texto: str) -> str:
    """
    Aplica sustituciones fonéticas del español para igualar variantes
    como b/v, ll/y, c/s/z, h muda, dobles consonantes, etc.
    Útil para comparar palabras mal escritas fonéticamente.
    """
    texto = normalizar_texto(texto)
    for patron, reemplazo in _FONETICA:
        texto = re.sub(patron, reemplazo, texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto

def singularizar_simple(palabra: str) -> str:
    if len(palabra) <= 4:
        return palabra
    if palabra.endswith("es") and len(palabra) > 5:
        return palabra[:-2]
    if palabra.endswith("s") and len(palabra) > 4:
        return palabra[:-1]
    return palabra

def aplicar_aliases(palabra: str) -> str:
    """Reemplaza variantes informales/mal escritas por su forma canónica."""
    return ALIASES_PALABRAS.get(palabra, palabra)

def normalizar_palabras_pedido(texto: str) -> str:
    palabras = normalizar_texto(texto).split()
    resultado = []
    for palabra in palabras:
        palabra = PALABRAS_CANTIDAD.get(palabra, palabra)
        palabra = singularizar_simple(palabra)
        palabra = aplicar_aliases(palabra)
        resultado.append(palabra)
    return " ".join(resultado)

def limpiar_nombre_producto(nombre: str) -> str:
    return normalizar_palabras_pedido(nombre)

# ── Prefijos fuzzy ────────────────────────────────────────────────────────────

def _score_prefijo_token(palabra: str, token: str) -> int:
    """
    Devuelve un score (0-100) basado en qué tan bien `palabra` es un
    prefijo de `token`, con tolerancia a 1 carácter de diferencia.

    Ejemplos:
        "pizz"   vs "pizza"     → 95
        "empan"  vs "empanada"  → 90
        "diab"   vs "diabolica" → 88
        "muzza"  vs "muzzarella"→ 88
        "abc"    vs "xyz"       → 0
    """
    if not palabra or not token:
        return 0

    min_len = min(len(palabra), len(token))

    # La palabra no puede ser más larga que el token
    if len(palabra) > len(token):
        return 0

    # Demasiado corta para ser significativa (menos de 3 chars)
    if len(palabra) < 3:
        return 0

    # Coincidencia exacta de prefijo
    if token.startswith(palabra):
        # Bonus por cobertura: cuánto del token cubre la palabra
        cobertura = len(palabra) / len(token)
        return round(85 + cobertura * 12)  # 85–97

    # Prefijo con 1 error (Levenshtein simplificado por ventana)
    errores = sum(1 for a, b in zip(palabra, token) if a != b)
    if errores <= 1 and len(palabra) >= 4:
        cobertura = len(palabra) / len(token)
        return round(75 + cobertura * 10)  # 75–85

    return 0

def score_prefijo_fragmento(fragmento: str, nombre_producto: str) -> int:
    """
    Busca si algún token del fragmento es prefijo de algún token del producto.
    Devuelve el score máximo encontrado, 0 si ninguno aplica.
    """
    tokens_frag = fragmento.split()
    tokens_prod = nombre_producto.split()
    mejor = 0
    for tf in tokens_frag:
        for tp in tokens_prod:
            s = _score_prefijo_token(tf, tp)
            if s > mejor:
                mejor = s
    return mejor

# ── Scoring combinado ─────────────────────────────────────────────────────────

def calcular_score(fragmento: str, nombre_producto: str) -> int:
    """
    Score combinado que incluye:
    - Fuzzy estándar (WRatio, partial, token_set, token_sort)
    - Bonus por prefijo (palabras truncadas)
    - Matching fonético (palabras mal escritas fonéticamente)
    """
    # -- Fuzzy estándar --
    score_wratio     = fuzz.WRatio(fragmento, nombre_producto)
    score_partial    = fuzz.partial_ratio(fragmento, nombre_producto)
    score_token_set  = fuzz.token_set_ratio(fragmento, nombre_producto)
    score_token_sort = fuzz.token_sort_ratio(fragmento, nombre_producto)

    mejor = max(score_wratio, score_partial, score_token_set, score_token_sort)

    # -- Matching fonético --
    frag_fonetico = normalizar_fonetico(fragmento)
    prod_fonetico = normalizar_fonetico(nombre_producto)
    score_fonetico_wratio  = fuzz.WRatio(frag_fonetico, prod_fonetico)
    score_fonetico_partial = fuzz.partial_ratio(frag_fonetico, prod_fonetico)
    score_fonetico = max(score_fonetico_wratio, score_fonetico_partial)
    # Pesa 85% del score fonético para no inflar demasiado
    mejor = max(mejor, round(score_fonetico * 0.85))

    # -- Prefijo (palabras truncadas) --
    score_pref = score_prefijo_fragmento(fragmento, nombre_producto)
    if score_pref > 0:
        # Lo ponderamos 90% para no superar coincidencias exactas
        mejor = max(mejor, round(score_pref * 0.90))

    bonus = 0
    tokens_fragmento = set(fragmento.split())
    tokens_producto  = set(nombre_producto.split())

    interseccion = tokens_fragmento.intersection(tokens_producto)
    if interseccion:
        bonus += min(10, len(interseccion) * 5)

    if fragmento in nombre_producto or nombre_producto in fragmento:
        bonus += 8

    # Penalizaciones
    if len(fragmento) <= 3:
        mejor = round(mejor * 0.75)

    palabras_genericas = {"pizza", "empanada", "empanadas", "grande", "chico", "chica"}
    if tokens_fragmento.issubset(palabras_genericas):
        mejor = round(mejor * 0.60)

    return min(100, round(mejor + bonus))

# ── Catálogo ──────────────────────────────────────────────────────────────────

def preparar_catalogo(productos: list[dict]) -> list[dict]:
    catalogo = []
    for producto in productos:
        nombre_original    = producto["nombre_producto"]
        nombre_normalizado = limpiar_nombre_producto(nombre_original)
        nombre_fonetico    = normalizar_fonetico(nombre_original)
        catalogo.append({
            "id": producto["id"],
            "nombre_producto":   nombre_original,
            "nombre_normalizado": nombre_normalizado,
            "nombre_fonetico":   nombre_fonetico,
            "producto_completo": producto
        })
    return catalogo

# ── Fragmentos candidatos ─────────────────────────────────────────────────────

def extraer_fragmentos_candidatos(texto_usuario: str, max_ngram: int = 4) -> list[str]:
    texto    = normalizar_palabras_pedido(texto_usuario)
    palabras = texto.split()
    palabras_filtradas = [
        p for p in palabras
        if p not in STOPWORDS and p not in TAMANIOS and not p.isdigit()
    ]
    if not palabras_filtradas:
        return []

    fragmentos = set()
    for palabra in palabras_filtradas:
        if len(palabra) > 2:
            fragmentos.add(palabra)

    for n in range(2, max_ngram + 1):
        for i in range(len(palabras_filtradas) - n + 1):
            grama = palabras_filtradas[i:i + n]
            if all(p in TAMANIOS for p in grama):
                continue
            fragmentos.add(" ".join(grama))

    return sorted(fragmentos, key=lambda x: (len(x.split()), len(x)), reverse=True)

# ── Segmentador de pedidos ────────────────────────────────────────────────────

# Palabras que indican el inicio de un nuevo item en el pedido.
# "empanada de carne Y PIZZA muzza" → "y" separa porque "pizza" es categoría.
# "empanada de jamón Y QUESO"       → "y" NO separa porque "queso" no es categoría.
CATEGORIAS_PRODUCTO = {
    "pizza", "empanada", "fugazza", "fugazzeta", "faina",
    "coca", "milanesa", "lomito", "sandwich", "tarta",
    "medialunas", "medialuna", "facturas", "factura",
    "bebida", "gaseosa", "agua", "cerveza", "vino",
    "postre", "helado", "alfajor", "brownie",
}

def segmentar_pedido(texto: str) -> list[str]:
    """
    Divide un pedido con múltiples productos en sub-pedidos individuales.

    Separadores fuertes (siempre dividen):
        coma, "+", "mas", "más", "también", "tmb"

    Separador débil ("y"):
        Solo divide si la palabra que sigue es una cantidad (número o palabra)
        o una categoría de producto conocida.
        Así "jamón y queso" no se parte, pero "pizza y empanada" sí.

    Ejemplo:
        "2 pizzas muzza y 3 empanadas de carne y una de verdura"
        → ["2 pizzas muzza", "3 empanadas de carne", "una de verdura"]
    """
    texto_norm = normalizar_texto(texto)

    # 1. Separadores fuertes → siempre parten
    partes = re.split(r'[,+]|\btambien\b|\btmb\b|\bmas\b', texto_norm)

    resultado: list[str] = []

    for parte in partes:
        parte = parte.strip()
        if not parte:
            continue

        # 2. Intentar partir por "y" o por cantidad implícita
        tokens = parte.split()
        segmentos: list[list[str]] = []
        buffer: list[str] = []

        def _buffer_tiene_contenido(buf: list[str]) -> bool:
            """True si el buffer ya tiene al menos un token significativo."""
            return any(
                t not in STOPWORDS and t not in PALABRAS_CANTIDAD
                and not t.isdigit() and len(t) > 2
                for t in buf
            )

        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Separador por "y"
            if token == "y" and buffer:
                siguiente  = tokens[i + 1] if i + 1 < len(tokens) else ""
                subsiguiente = tokens[i + 2] if i + 2 < len(tokens) else ""
                # Mira un token adelante; si es artículo, mira el siguiente también
                _ARTICULOS = {"un", "una", "el", "la", "los", "las", "unos", "unas"}
                token_ref = subsiguiente if siguiente in _ARTICULOS else siguiente
                es_cantidad  = siguiente.isdigit() or siguiente in PALABRAS_CANTIDAD
                es_categoria = token_ref in CATEGORIAS_PRODUCTO
                if es_cantidad or es_categoria:
                    segmentos.append(buffer)
                    buffer = []
                    i += 1  # saltar el "y"
                    continue
                else:
                    buffer.append(token)

            # Separador implícito: cantidad en medio de la frase
            # "una empanada de carne UNA de verdura" → cortar antes de la segunda "una"
            # Excepción: no cortar si el token anterior es "de" (ej: "coca cola DE un litro")
            elif (token.isdigit() or token in PALABRAS_CANTIDAD) and _buffer_tiene_contenido(buffer):
                ultimo = buffer[-1] if buffer else ""
                if ultimo in ("de", "con", "a"):
                    buffer.append(token)
                else:
                    segmentos.append(buffer)
                    buffer = [token]

            else:
                buffer.append(token)

            i += 1

        if buffer:
            segmentos.append(buffer)

        for seg in segmentos:
            texto_seg = " ".join(seg).strip()
            if texto_seg:
                resultado.append(texto_seg)

    return resultado if resultado else [texto]

# ── Filtro por tokens clave ───────────────────────────────────────────────────

def filtrar_por_tokens_clave(
    candidatos: list[dict],
    texto_usuario: str,
    fuzzy_threshold: int = 82
) -> list[dict]:
    """
    Post-filtro bidireccional:

    1. Pedido → Producto: todos los tokens clave del pedido deben estar en
       el nombre del producto. ("empanada carne" no matchea "Pizza Carnívora")

    2. Producto → Pedido: los tokens distintivos del producto (los que no son
       categoría genérica) deben estar en el pedido. ("Empanada de Carne Mechada"
       no matchea "empanada de carne" porque "mechada" no está en el pedido).

    Parámetros:
        fuzzy_threshold: score mínimo por token para considerar que está presente.
    """
    def _tokens_significativos(texto: str) -> list[str]:
        return [
            t for t in normalizar_palabras_pedido(texto).split()
            if t not in STOPWORDS
            and t not in TAMANIOS
            and not t.isdigit()
            and len(t) > 2
        ]

    def _token_presente(token: str, tokens_destino: list[str]) -> bool:
        if token in tokens_destino:
            return True
        return max((fuzz.ratio(token, t) for t in tokens_destino), default=0) >= fuzzy_threshold

    tokens_pedido = _tokens_significativos(texto_usuario)
    if not tokens_pedido:
        return candidatos

    resultado = []
    for candidato in candidatos:
        nombre_norm   = limpiar_nombre_producto(candidato["producto_completo"]["nombre_producto"])
        tokens_nombre = _tokens_significativos(nombre_norm)

        # Todos los tokens del pedido deben estar en el nombre del producto.
        # No aplicamos la dirección inversa (tokens del producto en el pedido)
        # porque el usuario puede pedir "pizza de mozzarella" y esperar
        # "Pizza Mozzarella con Albahaca" — el ingrediente extra no invalida el match.
        if all(_token_presente(tp, tokens_nombre) for tp in tokens_pedido):
            resultado.append(candidato)

    return resultado

# ── Score mínimo dinámico ─────────────────────────────────────────────────────

def score_minimo_para(fragmento: str, score_minimo_base: int) -> int:
    """
    Reduce el umbral mínimo para fragmentos cortos (posibles truncamientos).
    Un fragmento de 3–4 chars que matchea como prefijo merece pasar aunque
    el WRatio sea bajo.
    """
    largo = len(fragmento.replace(" ", ""))
    if largo <= 4:
        return max(55, score_minimo_base - 15)
    if largo <= 6:
        return max(60, score_minimo_base - 8)
    return score_minimo_base

# ── Función principal ─────────────────────────────────────────────────────────

def extract_intentos_pedido(
    texto_usuario: str,
    productos: list[dict] | None = None,
    limite_por_fragmento: int = 5,
    score_minimo: int = 68,
    score_fuerte: int = 84
) -> list[dict]:
    """
    Extrae candidatos de productos usando RapidFuzz + matching fonético + prefijos.
    Maneja palabras truncadas ("pizz", "empan") y mal escritas ("bizza", "piza").
    """
    productos = productos or cat_prod_default
    catalogo  = preparar_catalogo(productos)

    texto_original = texto_usuario
    texto_limpio   = normalizar_palabras_pedido(texto_usuario)
    fragmentos     = extraer_fragmentos_candidatos(texto_usuario)

    if not fragmentos:
        return []

    nombres_catalogo   = [p["nombre_normalizado"] for p in catalogo]
    nombres_foneticos  = [p["nombre_fonetico"]    for p in catalogo]

    candidatos_por_id: dict = {}

    for fragmento in fragmentos:
        umbral = score_minimo_para(fragmento, score_minimo)
        frag_fonetico = normalizar_fonetico(fragmento)

        # Búsqueda 1: sobre nombres normalizados
        matches = process.extract(
            fragmento,
            nombres_catalogo,
            scorer=fuzz.WRatio,
            limit=limite_por_fragmento
        )

        # Búsqueda 2: sobre nombres fonéticos (captura errores tipo b/v, h muda, etc.)
        matches_foneticos = process.extract(
            frag_fonetico,
            nombres_foneticos,
            scorer=fuzz.WRatio,
            limit=limite_por_fragmento
        )
        # Unificamos ambas listas (índice → score máximo)
        matches_por_indice: dict[int, tuple] = {}
        for nombre_match, score_base, indice in matches:
            matches_por_indice[indice] = (nombre_match, score_base)
        for nombre_fon_match, score_fon, indice in matches_foneticos:
            if indice not in matches_por_indice:
                matches_por_indice[indice] = (nombres_catalogo[indice], score_fon)
            else:
                nombre_prev, score_prev = matches_por_indice[indice]
                if score_fon > score_prev:
                    matches_por_indice[indice] = (nombre_prev, score_fon)

        for indice, (nombre_match, score_base) in matches_por_indice.items():
            producto_cat    = catalogo[indice]
            score_combinado = calcular_score(fragmento, nombre_match)

            # Bonus por prefijo directo (permite pasar palabras truncadas)
            score_pref = score_prefijo_fragmento(fragmento, nombre_match)

            score_final = max(round(score_base), score_combinado)
            if score_pref > 0:
                score_final = max(score_final, round(score_pref * 0.90))

            if score_final < umbral:
                continue

            producto_id = producto_cat["id"]
            detalle = {
                "fragmento":        fragmento,
                "score_base":       round(score_base),
                "score_combinado":  score_combinado,
                "score_prefijo":    score_pref,
                "score_final":      score_final,
                "nombre_normalizado": nombre_match
            }

            if producto_id not in candidatos_por_id:
                candidatos_por_id[producto_id] = {
                    "producto_completo":        producto_cat["producto_completo"],
                    "score_confianza":          score_final,
                    "palabra_detectada":        fragmento,
                    "texto_original_usuario":   texto_original,
                    "texto_normalizado":        texto_limpio,
                    "tipo_match": "fuerte" if score_final >= score_fuerte else "posible",
                    "detalles_score": [detalle]
                }
            else:
                if score_final > candidatos_por_id[producto_id]["score_confianza"]:
                    candidatos_por_id[producto_id]["score_confianza"]  = score_final
                    candidatos_por_id[producto_id]["palabra_detectada"] = fragmento
                    candidatos_por_id[producto_id]["tipo_match"] = (
                        "fuerte" if score_final >= score_fuerte else "posible"
                    )
                candidatos_por_id[producto_id]["detalles_score"].append(detalle)

    candidatos = list(candidatos_por_id.values())
    candidatos.sort(
        key=lambda x: (
            x["score_confianza"],
            len(x["palabra_detectada"].split()),
            len(x["palabra_detectada"])
        ),
        reverse=True
    )
    return candidatos


# ── Wrapper multi-producto ────────────────────────────────────────────────────

def extract_pedido_completo(
    texto_usuario: str,
    productos: list[dict] | None = None,
    limite_por_fragmento: int = 5,
    score_minimo: int = 68,
    score_fuerte: int = 84,
    fuzzy_threshold: int = 82
) -> list[dict]:
    """
    Punto de entrada principal. Maneja pedidos con múltiples productos.

    1. Segmenta el texto en sub-pedidos ("pizza muzza y empanada de carne"
       → ["pizza muzza", "empanada de carne"]).
    2. Por cada sub-pedido: extrae candidatos + aplica filtro de tokens clave.
    3. Mergea resultados evitando duplicados (mismo ID → conserva mayor score).

    Devuelve la lista unificada ordenada por score descendente.
    """
    segmentos = segmentar_pedido(texto_usuario)

    vistos: dict[int, dict] = {}  # id → candidato con mayor score

    for segmento in segmentos:
        candidatos = extract_intentos_pedido(
            segmento,
            productos=productos,
            limite_por_fragmento=limite_por_fragmento,
            score_minimo=score_minimo,
            score_fuerte=score_fuerte,
        )
        filtrados = filtrar_por_tokens_clave(candidatos, segmento, fuzzy_threshold)

        for c in filtrados:
            pid = c["producto_completo"]["id"]
            if pid not in vistos or c["score_confianza"] > vistos[pid]["score_confianza"]:
                # Anotamos de qué segmento vino para debug
                c["segmento_origen"] = segmento
                vistos[pid] = c

    resultado = list(vistos.values())
    resultado.sort(key=lambda x: x["score_confianza"], reverse=True)
    return resultado


# ── Detección de cantidad ─────────────────────────────────────────────────────

def extraer_cantidad(texto: str) -> int:
    """
    Extrae la cantidad mencionada en un segmento de pedido.
    Soporta:
      - Números dígitos: "2 pizzas"
      - Palabras numéricas: "tres empanadas"
      - Docenas: "una docena", "2 docenas", "dos docenas" → multiplica por 12
    Devuelve 1 si no se menciona cantidad.
    """
    palabras = normalizar_texto(texto).split()

    for i, palabra in enumerate(palabras):
        # Detecta "N docena(s)" donde N es dígito o palabra numérica
        if palabra in ("docena", "docenas"):
            anterior = palabras[i - 1] if i > 0 else ""
            if anterior.isdigit():
                return int(anterior) * 12
            if anterior in PALABRAS_CANTIDAD:
                return int(PALABRAS_CANTIDAD[anterior]) * 12
            # "docena" sola sin número previo → 1 docena
            return 12

    for palabra in palabras:
        if palabra.isdigit():
            return int(palabra)
        if palabra in PALABRAS_CANTIDAD:
            return int(PALABRAS_CANTIDAD[palabra])

    return 1

# ── Detección de tamaño ──────────────────────────────────────────────────────

# Mapeo de lo que dice el cliente → valor exacto del campo `tamanio` en lista_json.
# Agregá acá sinónimos si el cliente usa otras formas.
TAMANIO_ALIASES: dict[str, str] = {
    # tamaños estándar
    "grande":    "grande",
    # lata y litros
    "lata":      "lata",
    "litro":     "1 litro",
    "litros":    "1 litro",
    "medio":     "medio litro",
    "gran":      "grande",
    "grandi":    "grande",
    "chica":     "chica",
    "chico":     "chica",
    "chiqui":    "chica",
    "pequeña":   "chica",
    "pequeño":   "chica",
    "familiar":  "familiar",
    "fami":      "familiar",
    "individual":"unidad",
    "unidad":    "unidad",
}

def extraer_tamanio(texto: str) -> str | None:
    """
    Detecta si el texto menciona un tamaño y devuelve el valor
    normalizado del campo `tamanio` (como está en lista_json).
    Devuelve None si no se menciona ningún tamaño.
    """
    palabras = normalizar_texto(texto).split()
    for palabra in palabras:
        if palabra in TAMANIO_ALIASES:
            return TAMANIO_ALIASES[palabra]
    return None

def filtrar_por_tamanio(productos: list[dict], tamanio: str) -> list[dict]:
    """
    De una lista de productos completos, devuelve solo los que tienen
    el tamaño indicado en su campo `tamanio`.
    """
    return [p for p in productos if p.get("tamanio") == tamanio]

# ── Punto de entrada público ──────────────────────────────────────────────────

def debug_deteccion(texto: str, productos: list[dict] | None = None) -> None:
    """
    Muestra el pipeline completo paso a paso para diagnosticar por qué
    un pedido no encuentra resultados.

    Uso: llamar desde __main__ en lugar de detectar_productos cuando algo falla.
    """
    print(f"\n{'='*60}")
    print(f"DEBUG: '{texto}'")
    print(f"{'='*60}")

    segmentos = segmentar_pedido(texto)
    print(f"\n[1] Segmentos: {segmentos}")

    for segmento in segmentos:
        print(f"\n{'─'*60}")
        print(f"  Segmento: '{segmento}'")
        texto_norm = normalizar_palabras_pedido(segmento)
        print(f"  Normalizado: '{texto_norm}'")
        fragmentos = extraer_fragmentos_candidatos(segmento)
        print(f"  Fragmentos: {fragmentos}")

        candidatos = extract_intentos_pedido(segmento, productos=productos)
        print(f"\n[2] Candidatos antes del filtro ({len(candidatos)}):")
        for c in candidatos[:8]:
            prod = c["producto_completo"]
            print(f"    score={c['score_confianza']:>3} | {prod['nombre_producto']} (ID {prod['id']}) | frag='{c['palabra_detectada']}'")

        if not candidatos:
            print("    → extract_intentos_pedido devolvió vacío. Revisar score_minimo o catálogo.")
            continue

        filtrados = filtrar_por_tokens_clave(candidatos, segmento)
        print(f"\n[3] Tras filtrar por tokens clave ({len(filtrados)}):")
        if filtrados:
            for c in filtrados:
                prod = c["producto_completo"]
                print(f"    ✓ {prod['nombre_producto']} (ID {prod['id']})")
        else:
            print("    → filtrar_por_tokens_clave eliminó todos los candidatos.")
            tokens_pedido_raw = normalizar_palabras_pedido(segmento).split()
            tokens_clave = [
                t for t in tokens_pedido_raw
                if t not in STOPWORDS and t not in TAMANIOS
                and not t.isdigit() and len(t) > 2
            ]
            print(f"    Tokens clave del pedido: {tokens_clave}")
            for c in candidatos[:5]:
                prod = c["producto_completo"]
                nombre_norm = limpiar_nombre_producto(prod["nombre_producto"])
                tokens_nombre = [
                    t for t in nombre_norm.split()
                    if t not in STOPWORDS and t not in TAMANIOS
                    and not t.isdigit() and len(t) > 2
                ]
                tokens_dist = [t for t in tokens_nombre if t not in CATEGORIAS_PRODUCTO]
                print(f"    Producto '{prod['nombre_producto']}' → norm='{nombre_norm}' | tokens={tokens_nombre} | distintivos={tokens_dist}")


def detectar_productos(texto: str, productos: list[dict] | None = None) -> str:
    """
    Punto de entrada principal.

    Recibe el texto libre del usuario y devuelve un dict con:
      - "encontrados":   lista de productos detectados (datos completos de lista_json)
      - "no_encontrados": lista de sub-frases del pedido que no matchearon ningún producto

    Ejemplo de salida:
        {
            "encontrados": [
                {"id": 37, "nombre_producto": "Empanada de Carne", "precio": 850, ...},
                {"id": 40, "nombre_producto": "Empanada de Verduras", "precio": 850, ...}
            ],
            "no_encontrados": ["una de jamon con ananá"]
        }
    """
    segmentos = segmentar_pedido(texto)

    vistos: dict[int, dict] = {}   # id → {candidato, cantidad}
    no_encontrados: list[str] = []

    for segmento in segmentos:
        candidatos = extract_intentos_pedido(segmento, productos=productos)
        filtrados  = filtrar_por_tokens_clave(candidatos, segmento)

        if not filtrados:
            no_encontrados.append(segmento)
            continue

        # Filtrar por tamaño si se menciona uno
        tamanio = extraer_tamanio(segmento)
        if tamanio:
            filtrados = [
                c for c in filtrados
                if c["producto_completo"].get("tamanio") == tamanio
            ]
            if not filtrados:
                no_encontrados.append(segmento)
                continue

        cantidad = extraer_cantidad(segmento)

        for c in filtrados:
            pid = c["producto_completo"]["id"]
            if pid not in vistos or c["score_confianza"] > vistos[pid]["candidato"]["score_confianza"]:
                vistos[pid] = {"candidato": c, "cantidad": cantidad, "segmento": segmento}

    # Separar disponibles de no disponibles y armar los productos con sus keys
    disponibles: list[dict] = []
    encontrados_no_disponibles: list[dict] = []

    for entry in sorted(vistos.values(), key=lambda x: x["candidato"]["score_confianza"], reverse=True):
        producto = dict(entry["candidato"]["producto_completo"])
        producto["cantidad"] = entry["cantidad"]
        producto["texto_origen"] = entry["segmento"]
        disponible = producto.get("disponible", True)
        no_disponible = disponible is False or str(disponible).lower() in ("false", "0", "no")
        if no_disponible:
            encontrados_no_disponibles.append(producto)
        else:
            disponibles.append(producto)

    # Separar encontrados (texto_origen único) de encontrados_posibles (texto_origen repetido)
    from collections import defaultdict
    grupos: dict[str, list[dict]] = defaultdict(list)
    for p in disponibles:
        grupos[p["texto_origen"]].append(p)

    encontrados: list[dict] = []
    encontrados_posibles: list[dict] = []

    for texto_origen, productos_grupo in grupos.items():
        if len(productos_grupo) == 1:
            encontrados.append(productos_grupo[0])
        else:
            encontrados_posibles.append({
                "texto_origen": texto_origen,
                "productos":    productos_grupo,
            })

    no_encontrados_out = [{"texto_origen": s} for s in no_encontrados]

    import json
    return json.dumps({
        "encontrados":               encontrados,
        "encontrados_posibles":      encontrados_posibles,
        "encontrados_no_disponibles": encontrados_no_disponibles,
        "no_encontrados":            no_encontrados_out,
    }, ensure_ascii=False)


if __name__ == "__main__":
    import json

    # Poné DEBUG = True para ver el pipeline completo cuando algo no funciona
    DEBUG = False

    while True:
        pedido = input("\nIngrese su pedido (o 'exit' para salir): ")
        if pedido.lower() == "exit":
            break

        if DEBUG:
            debug_deteccion(pedido)
        else:
            print(f"\nAnalizando: '{pedido}'")
            print("-" * 60)
            resultado = detectar_productos(pedido)  # ya es JSON string
            # Pretty-print para legibilidad en consola
            print(json.dumps(json.loads(resultado), ensure_ascii=False, indent=2))
