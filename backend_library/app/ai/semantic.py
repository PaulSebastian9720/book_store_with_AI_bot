import logging
import re
from dataclasses import dataclass, field

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.persistence.models import SemanticFunction, SemanticFunctionEmbedding

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Cargando modelo de embeddings: %s", settings.embedding_model_name)
        _model = SentenceTransformer(settings.embedding_model_name, device="cpu")
        logger.info("Modelo de embeddings cargado correctamente (CPU)")
    return _model


@dataclass
class SemanticMatch:
    function_name: str
    similarity: float
    method: str  # "rule" | "semantic" | "llm_fallback" | "clarification"
    top_candidates: list[dict] = field(default_factory=list)


# ── Rule-based matching (FIRST line of defense, no ML/LLM needed) ────────────

INTENT_RULES: list[tuple[str, list[str]]] = [
    ("add_book_to_cart", [
        r"agrega[r]?.*(?:carrito|compra|karr?ito)",
        r"añad[ei]r?.*(?:carrito|compra)",
        r"pon(?:er|me|lo)?.*carrito",
        r"(?:quiero|deseo)\s+comprar",
        r"me\s+llevo",
        r"sumar.*(?:carrito|compra)",
        r"guardar.*carrito",
        r"(?:meter|poner).*carrito",
        r"comprar\s+(?:el\s+)?(?:libro\s+)?(?:de\s+)?\w+",
        r"al\s+carrito",
        r"(?:mi\s+)?carrit[oa].*agrega",
        r"(?:a\s+mi\s+)?(?:carrito|karr?ito)",
        r"(?:libro|este).*(?:carrito|karr?ito)",
        # Informal: "compra 3 The Alchemist", "dame Dune", "ponme 1984"
        r"compra\s+\d+\s+",
        r"(?:dame|ponme|tráeme|traeme)\s+\w+",
        r"me\s+das\s+\w+",
        # English informal
        r"buy\s+\w+",
        r"add\s+.*(?:to\s+)?cart",
        r"i\s+want\s+\w+",
    ]),
    ("remove_book_from_cart", [
        r"(?:quita|elimina|borra|saca|remueve)[r]?.*(?:carrito|compra)",
        r"(?:no\s+quiero|ya\s+no).*(?:libro|carrito|comprar)",
        r"(?:cancelar|quitar).*(?:carrito|producto)",
        # English
        r"remove\s+.*(?:from\s+)?cart",
        r"delete\s+.*(?:from\s+)?cart",
        r"take\s+.*out\s+(?:of\s+)?cart",
    ]),
    ("search_books_for_sale", [
        r"(?:busca|busco|buscar)\s+libros?",
        r"(?:muestra|mostrar|ver|dame).*libros?",
        r"(?:qué|que)\s+libros?\s+(?:tienen|hay)",
        r"libros?\s+(?:de|sobre|disponibles)",
        r"(?:catálogo|catalogo|opciones)\s+(?:de\s+)?libros?",
        r"(?:qué|que)\s+(?:opciones|libros?)\s+hay",
        r"tienen.*(?:libros?|novelas?)",
        # Informal: "busca fantasía", "buscar algo de terror"
        r"(?:busca|busco|buscar)\s+\w+",
        # English
        r"search\s+(?:for\s+)?books?",
        r"find\s+(?:me\s+)?books?",
        r"show\s+(?:me\s+)?books?",
    ]),
    ("recommend_books_for_purchase", [
        r"(?:recomiend[ae]|sugi[eé]r[ae]|sugiere)",
        r"(?:qué|que)\s+(?:libro|me)\s+(?:recomiendas|sugieres)",
        r"(?:no\s+sé|no\s+se)\s+qu[eé]\s+leer",
        r"(?:dame|dime)\s+(?:una?\s+)?(?:recomendaci[oó]n|sugerencia)",
        r"(?:algo|libro)\s+(?:bueno|interesante|entretenido)",
        r"(?:qué|que)\s+(?:puedo|debería)\s+leer",
        r"sorpr[eé]ndeme",
    ]),
    ("get_book_product_details", [
        r"(?:cuéntame|cuentame|dime|info|información|informacion)\s+(?:sobre|de|del)",
        r"(?:de\s+)?qu[eé]\s+trata",
        r"(?:detalles?|detalle)\s+(?:de|del|sobre)",
        r"(?:acerca|respecto)\s+(?:de|del)",
        r"(?:quién|quien)\s+(?:es\s+)?(?:el\s+)?autor",
        r"(?:cuál|cual)\s+es\s+(?:el\s+)?precio",
        r"(?:vale\s+la\s+pena|es\s+bueno)",
        r"(?:qué|que)\s+(?:género|genero)\s+es",
    ]),
    ("check_book_stock", [
        r"(?:está|esta)\s+disponible",
        r"(?:hay|tienen|queda).*(?:stock|disponible|ejemplar|copia)",
        r"(?:cuántos?|cuantos?)\s+(?:libros?|ejemplares?|copias?)",
        r"(?:stock|disponibilidad)",
        r"(?:está|esta)\s+agotado",
        r"(?:puedo\s+comprar).*(?:ahora|ya)",
    ]),
    ("checkout_order", [
        r"(?:hacer|realizar)\s+(?:el\s+)?check\s*out",
        r"check\s*out",
        r"(?:finalizar|terminar|completar|cerrar)\s+(?:la\s+)?compra",
        r"(?:proceder|pasar)\s+al\s+pago",
        r"(?:confirmar|realizar)\s+(?:mi\s+)?(?:pedido|orden)",
        r"(?:quiero|deseo)\s+(?:pagar|comprar\s+todo)",
        r"hacer\s+(?:el\s+)?pedido",
    ]),
    ("process_payment", [
        r"(?:pagar|pago)\s+(?:mi\s+)?(?:pedido|orden|compra)",
        r"(?:realizar|procesar|confirmar|autorizar|completar)\s+(?:el\s+)?pago",
        r"(?:ya\s+)?quiero\s+pagar",
        r"pagar\s+ahora",
    ]),
    ("cancel_order", [
        r"(?:cancelar|anular)\s+(?:mi\s+)?(?:pedido|orden|compra)",
        r"(?:no\s+quiero)\s+(?:esta\s+)?(?:orden|pedido|compra)",
        r"(?:detener|parar)\s+(?:la\s+)?compra",
        r"(?:eliminar|borrar)\s+(?:mi\s+)?(?:pedido|orden)",
    ]),
    ("get_order_status", [
        r"(?:estado|status)\s+(?:de\s+)?(?:mi\s+)?(?:pedido|orden|compra)",
        r"(?:cómo|como)\s+va\s+(?:mi\s+)?(?:pedido|orden)",
        r"(?:revisar|consultar|ver)\s+(?:mi\s+)?(?:pedido|orden)",
        r"(?:qué|que)\s+pas[oó]\s+con\s+(?:mi\s+)?(?:pedido|orden)",
        r"(?:mi\s+)?(?:pedido|orden|compra)\s+(?:está|esta|sigue|fue)",
    ]),
]


def _rule_based_match(query: str) -> str | None:
    """
    Intenta clasificar el query usando patrones regex.
    Retorna el nombre de la función o None si no coincide.
    """
    q = query.lower().strip()

    for fn_name, patterns in INTENT_RULES:
        for pattern in patterns:
            if re.search(pattern, q):
                logger.info("Regla detectó intención: %s (patrón: %s)", fn_name, pattern)
                return fn_name

    return None


# ── Main selection function ──────────────────────────────────────────────────

async def select_function(
    query: str,
    session: AsyncSession,
) -> SemanticMatch:
    """
    Selecciona la función semántica más cercana al query del usuario.
    Cadena de prioridad:
      1. Reglas/patrones (determinístico, sin ML)
      2. Embeddings multi-vector o combinados
      3. LLM fallback (solo si hay LLM disponible)
      4. Último recurso: pedir aclaración
    """

    # === PASO 1: Rule-based matching (funciona SIEMPRE, sin ML ni LLM) ===
    rule_match = _rule_based_match(query)
    if rule_match:
        return SemanticMatch(
            function_name=rule_match,
            similarity=1.0,
            method="rule",
            top_candidates=[{"name": rule_match, "score": 1.0}],
        )

    # === PASO 2: Embedding-based matching ===
    model = get_embedding_model()
    query_embedding = model.encode([query], normalize_embeddings=True)[0]
    query_vec = query_embedding.reshape(1, -1)

    # Load all semantic functions
    result = await session.execute(select(SemanticFunction))
    functions = result.scalars().all()

    if not functions:
        logger.warning("No hay funciones semánticas en la base de datos")
        return SemanticMatch(function_name="", similarity=0.0, method="clarification")

    # Load individual embeddings (multi-vector)
    try:
        result = await session.execute(select(SemanticFunctionEmbedding))
        all_individual = result.scalars().all()
    except Exception:
        all_individual = []

    # Group individual embeddings by function_id
    fn_individual: dict[int, list[SemanticFunctionEmbedding]] = {}
    for emb in all_individual:
        fn_individual.setdefault(emb.function_id, []).append(emb)

    has_individual = len(fn_individual) > 0

    # Compute scores per function
    scores: list[tuple[SemanticFunction, float]] = []

    for fn in functions:
        indiv = fn_individual.get(fn.id, [])

        if indiv:
            # Multi-vector: separate description and example embeddings
            desc_embs = [e for e in indiv if e.embedding_type == "description"]
            example_embs = [e for e in indiv if e.embedding_type == "example"]

            desc_sim = 0.0
            if desc_embs:
                desc_vecs = np.array([e.embedding for e in desc_embs])
                desc_sim = float(cosine_similarity(query_vec, desc_vecs).max())

            max_example_sim = 0.0
            if example_embs:
                ex_vecs = np.array([e.embedding for e in example_embs])
                max_example_sim = float(cosine_similarity(query_vec, ex_vecs).max())

            score = 0.6 * max_example_sim + 0.4 * desc_sim
        else:
            # Fallback to combined embedding
            if fn.embedding:
                fn_vec = np.array(fn.embedding).reshape(1, -1)
                score = float(cosine_similarity(query_vec, fn_vec)[0, 0])
            else:
                score = 0.0

        scores.append((fn, score))

    # Sort descending
    scores.sort(key=lambda x: x[1], reverse=True)

    # Top-3 for logging
    top_candidates = [
        {"name": fn.name, "score": round(s, 4)}
        for fn, s in scores[:3]
    ]

    best_fn, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else 0.0

    logger.info(
        "Embedding matching — top-3: %s (individual=%s)",
        ", ".join(f"{c['name']}={c['score']}" for c in top_candidates),
        has_individual,
    )

    # Use different thresholds depending on embedding type
    threshold = settings.similarity_threshold if has_individual else settings.combined_similarity_threshold

    # High confidence: accept directly
    if best_score >= settings.high_confidence_threshold:
        logger.info("Alta confianza: %s (%.4f)", best_fn.name, best_score)
        return SemanticMatch(
            function_name=best_fn.name,
            similarity=best_score,
            method="semantic",
            top_candidates=top_candidates,
        )

    # Above threshold with good gap: accept
    if best_score >= threshold:
        gap = best_score - second_score
        if gap >= settings.confidence_gap_threshold:
            logger.info("Semántico aceptado: %s (%.4f, gap=%.4f)", best_fn.name, best_score, gap)
            return SemanticMatch(
                function_name=best_fn.name,
                similarity=best_score,
                method="semantic",
                top_candidates=top_candidates,
            )
        else:
            # Low gap — still accept the best one but log it
            logger.info("Gap bajo pero aceptando best: %s (%.4f, gap=%.4f)", best_fn.name, best_score, gap)
            return SemanticMatch(
                function_name=best_fn.name,
                similarity=best_score,
                method="semantic",
                top_candidates=top_candidates,
            )

    # === PASO 3: LLM fallback (only if score is somewhat close) ===
    if best_score >= 0.25:
        logger.info("Score bajo (%.4f < %.2f), intentando LLM fallback", best_score, threshold)
        try:
            from app.ai.llm import classify_intent
            fn_descriptions = {fn.name: fn.description for fn in functions}
            llm_result = await classify_intent(query, fn_descriptions)

            if llm_result:
                logger.info("LLM clasificó: %s", llm_result)
                return SemanticMatch(
                    function_name=llm_result,
                    similarity=best_score,
                    method="llm_fallback",
                    top_candidates=top_candidates,
                )
        except Exception as e:
            logger.warning("LLM fallback falló: %s", str(e))

    # === PASO 4: Nothing matched ===
    logger.info("No se pudo clasificar (best=%.4f), solicitando aclaración", best_score)
    return SemanticMatch(
        function_name="",
        similarity=best_score,
        method="clarification",
        top_candidates=top_candidates,
    )
