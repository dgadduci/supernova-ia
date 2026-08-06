"""Product recognizer.

Fuzzy product-matching module. Takes free-text user input and a catalog of
product-presentations; returns a structured dict of confident matches,
possible matches, unavailable matches, and unmatched fragments.

This is a port of the legacy fuzzy pipeline
(backend/old_project/logica_fuzzy_pedido_productos.py) to a new contract:
  - the catalog is passed as an argument (no static JSON file),
  - the result is a Python dict (not a JSON string),
  - the field names are the new product-presentations shape.

Subphase 4.2: product aliases are no longer a hardcoded production source.
The fuzzy pipeline consumes caller-provided alias data through each catalog
row's optional ``aliases`` field. The legacy ``ALIASES_PALABRAS`` map is
retained for documentation, the seeder, and pre-migration characterization
tests, but the runtime normalizer no longer applies it.
"""
import re
import unicodedata
from collections import defaultdict

from rapidfuzz import fuzz, process

STOPWORDS = {
    "de", "con", "y", "la", "el", "un", "una", "unos", "unas",
    "los", "las", "mandame", "quiero", "quisiera", "dame", "trae",
    "traeme", "me", "por", "favor", "del", "para", "pero", "si",
    "que", "al", "en", "mi", "mis", "hola", "buenas", "buenos",
    "dias", "tardes", "noches", "necesito", "pedido", "pedir",
    "quita", "quitar", "saca", "sacame", "sacala", "quitala",
    "quitalas", "quitale", "sacasela", "elimina", "eliminar",
    "remueve", "remover", "borra", "borrar", "suprime", "suprimir",
    "agrega", "agregar",
}

PALABRAS_CANTIDAD = {
    "un": "1", "uno": "1", "una": "1", "dos": "2", "tres": "3",
    "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7",
    "ocho": "8", "nueve": "9", "diez": "10",
}

TAMANIOS = {
    "chica", "chico", "grande", "mediana", "mediano",
    "familiar", "individual", "porcion", "porciones",
    "lata", "litro", "litros", "medio", "medios",
    "docena", "docenas",
}

# Retained for documentation and the idempotent seeder. The runtime
# normalizer no longer applies this map; aliases are read from each
# catalog row's ``aliases`` field.
ALIASES_PALABRAS: dict[str, str] = {
    "muza":        "mozzarella",
    "muzza":       "mozzarella",
    "muzarela":    "mozzarella",
    "muzarella":   "mozzarella",
    "mozarela":    "mozzarella",
    "mozarella":   "mozzarella",
    "muzarrella":  "mozzarella",
    "muzzarela":   "mozzarella",
    "muzzarella":  "mozzarella",
    "musarela":    "mozzarella",
    "musarella":   "mozzarella",
    "fugazeta":    "fugazzeta",
    "fugazetta":   "fugazzeta",
    "napoli":      "napolitana",
    "calabreza":   "calabresa",
}


def _row_aliases(row: dict) -> list[str]:
    aliases = row.get("aliases")
    if not aliases:
        return []
    candidates: list[str] = []
    for key in ("specific_aliases", "general_aliases"):
        value = aliases.get(key) if isinstance(aliases, dict) else None
        if value:
            candidates.extend(str(item) for item in value if item)
    return candidates


def _expand_con_nombres_aliases(nombre: str, aliases: list[str]) -> list[str]:
    if not aliases:
        return [nombre]
    expanded: list[str] = [nombre]
    for alias in aliases:
        candidate = f"{nombre} {alias}".strip()
        if candidate not in expanded:
            expanded.append(candidate)
    return expanded


_FONETICA = [
    (r"qu", "k"),
    (r"güe", "ge"),  (r"güi", "gi"),
    (r"gue", "ge"),  (r"gui", "gi"),
    (r"ue", "ue"),
    (r"ll", "y"),
    (r"v", "b"),
    (r"z", "s"),
    (r"ce", "se"),   (r"ci", "si"),
    (r"ch", "x"),
    (r"ph", "f"),
    (r"h", ""),
    (r"x(?=[aeiou])", "s"),
    (r"([bcdfghjklmnpqrstvwxyz])\1+", r"\1"),
]

CATEGORIAS_PRODUCTO = {
    "pizza", "empanada", "fugazza", "fugazzeta", "faina",
    "coca", "milanesa", "lomito", "sandwich", "tarta",
    "medialunas", "medialuna", "facturas", "factura",
    "bebida", "gaseosa", "agua", "cerveza", "vino",
    "postre", "helado", "alfajor", "brownie",
}

PRESENTACION_ALIASES: dict[str, str] = {
    "grande":      "grande",
    "lata":        "lata",
    "litro":       "1 litro",
    "litros":      "1 litro",
    "medio":       "medio litro",
    "gran":        "grande",
    "grandi":      "grande",
    "chica":       "chica",
    "chico":       "chica",
    "chiqui":      "chica",
    "pequena":     "chica",
    "pequeno":     "chica",
    "familiar":    "familiar",
    "fami":        "familiar",
    "individual":  "unidad",
    "unidad":      "unidad",
    "tradicional": "tradicional",
}


def _normalizar_texto(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = texto.encode("ascii", "ignore").decode("utf-8")
    texto = re.sub(r"[^a-z0-9ñ\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _normalizar_fonetico(texto: str) -> str:
    texto = _normalizar_texto(texto)
    for patron, reemplazo in _FONETICA:
        texto = re.sub(patron, reemplazo, texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _singularizar_simple(palabra: str) -> str:
    if len(palabra) <= 4:
        return palabra
    if palabra.endswith("es") and len(palabra) > 5:
        return palabra[:-2]
    if palabra.endswith("s") and len(palabra) > 4:
        return palabra[:-1]
    return palabra


def _aplicar_aliases(palabra: str) -> str:
    return ALIASES_PALABRAS.get(palabra, palabra)


def _normalizar_palabras_pedido(texto: str) -> str:
    palabras = _normalizar_texto(texto).split()
    resultado = []
    for palabra in palabras:
        palabra = PALABRAS_CANTIDAD.get(palabra, palabra)
        palabra = _singularizar_simple(palabra)
        palabra = _aplicar_aliases(palabra)
        resultado.append(palabra)
    return " ".join(resultado)


def _limpiar_nombre_producto(nombre: str) -> str:
    return _normalizar_palabras_pedido(nombre)


def _score_prefijo_token(palabra: str, token: str) -> int:
    if not palabra or not token:
        return 0
    if len(palabra) > len(token):
        return 0
    if len(palabra) < 3:
        return 0
    if token.startswith(palabra):
        cobertura = len(palabra) / len(token)
        return round(85 + cobertura * 12)
    errores = sum(1 for a, b in zip(palabra, token) if a != b)
    if errores <= 1 and len(palabra) >= 4:
        cobertura = len(palabra) / len(token)
        return round(75 + cobertura * 10)
    return 0


def _score_prefijo_fragmento(fragmento: str, nombre_producto: str) -> int:
    tokens_frag = fragmento.split()
    tokens_prod = nombre_producto.split()
    mejor = 0
    for tf in tokens_frag:
        for tp in tokens_prod:
            s = _score_prefijo_token(tf, tp)
            mejor = max(mejor, s)
    return mejor


def _calcular_score(fragmento: str, nombre_producto: str) -> int:
    score_wratio = fuzz.WRatio(fragmento, nombre_producto)
    score_partial = fuzz.partial_ratio(fragmento, nombre_producto)
    score_token_set = fuzz.token_set_ratio(fragmento, nombre_producto)
    score_token_sort = fuzz.token_sort_ratio(fragmento, nombre_producto)
    mejor = max(score_wratio, score_partial, score_token_set, score_token_sort)
    frag_fonetico = _normalizar_fonetico(fragmento)
    prod_fonetico = _normalizar_fonetico(nombre_producto)
    score_fonetico_wratio = fuzz.WRatio(frag_fonetico, prod_fonetico)
    score_fonetico_partial = fuzz.partial_ratio(frag_fonetico, prod_fonetico)
    score_fonetico = max(score_fonetico_wratio, score_fonetico_partial)
    mejor = max(mejor, round(score_fonetico * 0.85))
    score_pref = _score_prefijo_fragmento(fragmento, nombre_producto)
    if score_pref > 0:
        mejor = max(mejor, round(score_pref * 0.90))
    bonus = 0
    tokens_fragmento = set(fragmento.split())
    tokens_producto = set(nombre_producto.split())
    interseccion = tokens_fragmento.intersection(tokens_producto)
    if interseccion:
        bonus += min(10, len(interseccion) * 5)
    if fragmento in nombre_producto or nombre_producto in fragmento:
        bonus += 8
    if len(fragmento) <= 3:
        mejor = round(mejor * 0.75)
    palabras_genericas = {"pizza", "empanada", "empanadas", "grande", "chico", "chica"}
    if tokens_fragmento.issubset(palabras_genericas):
        mejor = round(mejor * 0.60)
    return min(100, round(mejor + bonus))


def _preparar_catalogo(productos: list[dict]) -> list[dict]:
    catalogo = []
    for producto in productos:
        nombre_original = producto["producto_nombre"]
        aliases = _row_aliases(producto)
        nombres_aliases = _expand_con_nombres_aliases(nombre_original, aliases)
        catalogo.append({
            "id": producto["producto_presentacion_id"],
            "nombre_producto": nombre_original,
            "nombres_aliases": nombres_aliases,
            "aliases": aliases,
            "nombre_normalizado": _limpiar_nombre_producto(nombre_original),
            "nombres_aliases_normalizados": [
                _limpiar_nombre_producto(nombre) for nombre in nombres_aliases
            ],
            "nombre_fonetico": _normalizar_fonetico(nombre_original),
            "producto_completo": producto,
        })
    return catalogo


def _extraer_fragmentos_candidatos(texto_usuario: str, max_ngram: int = 4) -> list[str]:
    texto = _normalizar_palabras_pedido(texto_usuario)
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


def _segmentar_pedido(texto: str) -> list[str]:
    texto_norm = _normalizar_texto(texto)
    partes = re.split(r'[,+]|\btambien\b|\btmb\b|\bmas\b', texto_norm)
    resultado: list[str] = []
    _ARTICULOS = {"un", "una", "el", "la", "los", "las", "unos", "unas"}
    for parte in partes:
        parte = parte.strip()
        if not parte:
            continue
        tokens = parte.split()
        segmentos: list[list[str]] = []
        buffer: list[str] = []
        def _buffer_tiene_contenido(buf: list[str]) -> bool:
            return any(
                t not in STOPWORDS and t not in PALABRAS_CANTIDAD
                and not t.isdigit() and len(t) > 2
                for t in buf
            )
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == "y" and buffer:
                siguiente = tokens[i + 1] if i + 1 < len(tokens) else ""
                subsiguiente = tokens[i + 2] if i + 2 < len(tokens) else ""
                token_ref = subsiguiente if siguiente in _ARTICULOS else siguiente
                es_cantidad = siguiente.isdigit() or siguiente in PALABRAS_CANTIDAD
                es_categoria = token_ref in CATEGORIAS_PRODUCTO
                if es_cantidad or es_categoria:
                    segmentos.append(buffer)
                    buffer = []
                    i += 1
                    continue
                else:
                    buffer.append(token)
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


def _filtrar_por_tokens_clave(
    candidatos: list[dict], texto_usuario: str, fuzzy_threshold: int = 82
) -> list[dict]:
    def _tokens_significativos(texto: str) -> list[str]:
        return [
            t for t in _normalizar_palabras_pedido(texto).split()
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
        nombre_norm = _limpiar_nombre_producto(candidato["producto_completo"]["producto_nombre"])
        tokens_nombre = _tokens_significativos(nombre_norm)
        if all(_token_presente(tp, tokens_nombre) for tp in tokens_pedido):
            resultado.append(candidato)
    return resultado


def _category_singular_variants(name: str) -> set[str]:
    """Return normalized lookup variants of a category name.

    Strips a trailing ``s`` or ``es`` when the result still has at least
    3 characters. Includes the original lowercased form so the original
    plural matches itself (and so input tokens that already are
    singular can match the original plural).
    """
    variants: set[str] = {name}
    if name.endswith("es") and len(name) > 4:
        stem = name[:-2]
        if len(stem) >= 3:
            variants.add(stem)
        stem_s = name[:-1]
        if len(stem_s) >= 3:
            variants.add(stem_s)
    elif name.endswith("s") and len(name) > 4:
        stem = name[:-1]
        if len(stem) >= 3:
            variants.add(stem)
    return variants


def _coincidencia_categoria(texto_segmento: str, catalogo: list[dict]) -> str | None:
    """Return the catalog ``categoria_nombre`` matching a significant user token.

    Builds a per-call index keyed by the lowercased variants of each
    catalog entry's ``categoria_nombre`` (original, ``s``-stripped,
    ``es``-stripped) and returns the original ``categoria_nombre`` when
    a significant user token matches any variant. Excludes stopwords,
    sizes, quantity words, digits, and tokens shorter than 3 characters.
    The helper does NOT consult calibration labels and does NOT return
    the matching catalog entries.
    """
    tokens_significativos = [
        t for t in _normalizar_palabras_pedido(texto_segmento).split()
        if t not in STOPWORDS
        and t not in TAMANIOS
        and not t.isdigit()
        and len(t) > 2
    ]
    if not tokens_significativos:
        return None
    indice_categorias: dict[str, str] = {}
    for producto in catalogo:
        categoria_nombre = producto.get("categoria_nombre")
        if not isinstance(categoria_nombre, str) or not categoria_nombre:
            continue
        cat_lower = categoria_nombre.lower()
        for variante in _category_singular_variants(cat_lower):
            if variante and variante not in indice_categorias:
                indice_categorias[variante] = categoria_nombre
    for token in tokens_significativos:
        token_lower = token.lower()
        if token_lower in indice_categorias:
            return indice_categorias[token_lower]
        for variante in _category_singular_variants(token_lower):
            if variante in indice_categorias:
                return indice_categorias[variante]
    return None


def _score_minimo_para(fragmento: str, score_minimo_base: int) -> int:
    largo = len(fragmento.replace(" ", ""))
    if largo <= 4:
        return max(55, score_minimo_base - 15)
    if largo <= 6:
        return max(60, score_minimo_base - 8)
    return score_minimo_base


def _extraer_cantidad(texto: str) -> int:
    palabras = _normalizar_texto(texto).split()
    for i, palabra in enumerate(palabras):
        if palabra in ("docena", "docenas"):
            anterior = palabras[i - 1] if i > 0 else ""
            if anterior.isdigit():
                return int(anterior) * 12
            if anterior in PALABRAS_CANTIDAD:
                return int(PALABRAS_CANTIDAD[anterior]) * 12
            return 12
    for palabra in palabras:
        if palabra.isdigit():
            return int(palabra)
        if palabra in PALABRAS_CANTIDAD:
            return int(PALABRAS_CANTIDAD[palabra])
    return 1


def _extraer_presentacion(texto: str) -> str | None:
    palabras = _normalizar_texto(texto).split()
    for palabra in palabras:
        if palabra in PRESENTACION_ALIASES:
            return PRESENTACION_ALIASES[palabra]
    return None


def _extraer_candidatos(
    texto_segmento: str,
    catalogo: list[dict],
    limite_por_fragmento: int = 5,
    score_minimo: int = 68,
    score_fuerte: int = 84,
) -> list[dict]:
    texto_original = texto_segmento
    texto_limpio = _normalizar_palabras_pedido(texto_segmento)
    fragmentos = _extraer_fragmentos_candidatos(texto_segmento)
    if not fragmentos:
        return []
    nombres_catalogo = [p["nombre_normalizado"] for p in catalogo]
    nombres_foneticos = [p["nombre_fonetico"] for p in catalogo]
    candidatos_por_id: dict = {}
    for fragmento in fragmentos:
        umbral = _score_minimo_para(fragmento, score_minimo)
        frag_fonetico = _normalizar_fonetico(fragmento)
        matches = process.extract(
            fragmento, nombres_catalogo, scorer=fuzz.WRatio, limit=limite_por_fragmento
        )
        matches_foneticos = process.extract(
            frag_fonetico, nombres_foneticos, scorer=fuzz.WRatio, limit=limite_por_fragmento
        )
        matches_por_indice: dict[int, tuple[str, float]] = {}
        for nombre_match, score_base, indice in matches:
            matches_por_indice[indice] = (nombre_match, score_base)
        for _nombre_fon_match, score_fon, indice in matches_foneticos:
            if indice not in matches_por_indice:
                matches_por_indice[indice] = (nombres_catalogo[indice], score_fon)
            else:
                _nombre_prev, score_prev = matches_por_indice[indice]
                if score_fon > score_prev:
                    matches_por_indice[indice] = (nombres_catalogo[indice], score_fon)
        for indice in list(matches_por_indice.keys()):
            producto_cat = catalogo[indice]
            for nombre_alias in producto_cat.get(
                "nombres_aliases_normalizados", [producto_cat["nombre_normalizado"]]
            ):
                if nombre_alias == producto_cat["nombre_normalizado"]:
                    continue
                score_alias = round(
                    fuzz.WRatio(fragmento, nombre_alias)
                )
                if score_alias < umbral:
                    continue
                _nombre_prev, score_prev = matches_por_indice[indice]
                if score_alias > score_prev:
                    matches_por_indice[indice] = (nombre_alias, score_alias)
        for indice, (nombre_match, score_base) in matches_por_indice.items():
            producto_cat = catalogo[indice]
            score_combinado = _calcular_score(fragmento, nombre_match)
            score_pref = _score_prefijo_fragmento(fragmento, nombre_match)
            score_final = max(round(score_base), score_combinado)
            if score_pref > 0:
                score_final = max(score_final, round(score_pref * 0.90))
            if score_final < umbral:
                continue
            producto_id = producto_cat["id"]
            detalle = {
                "fragmento": fragmento,
                "score_base": round(score_base),
                "score_combinado": score_combinado,
                "score_prefijo": score_pref,
                "score_final": score_final,
                "nombre_normalizado": nombre_match,
            }
            if producto_id not in candidatos_por_id:
                candidatos_por_id[producto_id] = {
                    "producto_completo": producto_cat["producto_completo"],
                    "score_confianza": score_final,
                    "palabra_detectada": fragmento,
                    "texto_original_usuario": texto_original,
                    "texto_normalizado": texto_limpio,
                    "tipo_match": "fuerte" if score_final >= score_fuerte else "posible",
                    "detalles_score": [detalle],
                }
            else:
                if score_final > candidatos_por_id[producto_id]["score_confianza"]:
                    candidatos_por_id[producto_id]["score_confianza"] = score_final
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
            len(x["palabra_detectada"]),
        ),
        reverse=True,
    )
    return candidatos


def detectar_productos(
    texto: str,
    productos_presentaciones: list[dict],
) -> dict:
    segmentos = _segmentar_pedido(texto)
    catalogo = _preparar_catalogo(productos_presentaciones)
    vistos: dict[int, dict] = {}
    no_encontrados: list[str] = []
    coincidencias_categoria: dict[str, str] = {}
    for segmento in segmentos:
        candidatos = _extraer_candidatos(segmento, catalogo)
        filtrados = _filtrar_por_tokens_clave(candidatos, segmento)
        if not filtrados:
            categoria = _coincidencia_categoria(segmento, productos_presentaciones)
            if categoria is not None:
                coincidencias_categoria[segmento] = categoria
            no_encontrados.append(segmento)
            continue
        presentacion = _extraer_presentacion(segmento)
        if presentacion:
            pres_alias_lower = presentacion.lower()
            filtrados = [
                c for c in filtrados
                if str(c["producto_completo"].get("presentacion_codigo", "")).lower() == pres_alias_lower
                or str(c["producto_completo"].get("presentacion_codigo", "")).lower().startswith(pres_alias_lower)
                or pres_alias_lower in str(c["producto_completo"].get("presentacion_codigo", "")).lower().split()
            ]
            if not filtrados:
                no_encontrados.append(segmento)
                continue
        cantidad = _extraer_cantidad(segmento)
        for c in filtrados:
            pid = c["producto_completo"]["producto_presentacion_id"]
            if pid not in vistos or c["score_confianza"] > vistos[pid]["candidato"]["score_confianza"]:
                vistos[pid] = {"candidato": c, "cantidad": cantidad, "segmento": segmento}
    disponibles: list[dict] = []
    encontrados_no_disponibles: list[dict] = []
    for entry in sorted(
        vistos.values(), key=lambda x: x["candidato"]["score_confianza"], reverse=True
    ):
        producto = dict(entry["candidato"]["producto_completo"])
        cantidad = entry["cantidad"]
        segmento = entry["segmento"]
        producto["cantidad"] = cantidad
        producto["texto_origen"] = segmento

        producto_activo = producto.get("producto_activo", True)
        presentacion_activo = producto.get("presentacion_activo", True)
        presentacion_pp_activo = producto.get("activo", True)
        disponible = producto.get("disponible", True)

        if (
            producto_activo is False
            or presentacion_activo is False
            or presentacion_pp_activo is False
            or str(producto_activo).lower() in ("false", "0", "no")
            or str(presentacion_activo).lower() in ("false", "0", "no")
            or str(presentacion_pp_activo).lower() in ("false", "0", "no")
        ):
            continue

        if disponible is False or str(disponible).lower() in ("false", "0", "no"):
            encontrados_no_disponibles.append(producto)
        else:
            disponibles.append(producto)
    grupos: dict[str, list[dict]] = defaultdict(list)
    for p in disponibles:
        grupos[p["texto_origen"]].append(p)
    encontrados: list[dict] = []
    encontrados_posibles: list[dict] = []
    for texto_origen, productos_grupo in grupos.items():
        if len(productos_grupo) == 1:
            encontrados.append(productos_grupo[0])
        else:
            encontrados_posibles.append(
                {"texto_origen": texto_origen, "productos": productos_grupo}
            )
    for texto_origen, categoria in coincidencias_categoria.items():
        encontrados_posibles.append(
            {
                "kind": "category",
                "categoria_nombre": categoria,
                "texto_origen": texto_origen,
            }
        )
    no_encontrados_out = [{"texto_origen": s} for s in no_encontrados]
    return {
        "encontrados": encontrados,
        "encontrados_posibles": encontrados_posibles,
        "encontrados_no_disponibles": encontrados_no_disponibles,
        "no_encontrados": no_encontrados_out,
    }


__all__ = ["detectar_productos"]