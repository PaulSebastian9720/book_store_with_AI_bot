"""
Orquestador — Coordina selección semántica, ejecución directa o LangGraph,
y manejo de interacción con el usuario.
"""
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Book, Cart, CartItem, Order, OrderItem, ExecutionLog
from app.ai.semantic import select_function, SemanticMatch
from app.ai.llm import build_natural_response, DOMAIN_GUARDRAIL
from app.flow.graph import run_flow

logger = logging.getLogger(__name__)

# Functions that require LangGraph (stateful flows)
LANGGRAPH_FUNCTIONS = {
    "add_book_to_cart",
    "remove_book_from_cart",
    "checkout_order",
    "process_payment",
    "cancel_order",
}

# Functions handled with direct execution
DIRECT_FUNCTIONS = {
    "search_books_for_sale",
    "recommend_books_for_purchase",
    "get_book_product_details",
    "check_book_stock",
    "get_order_status",
}


@dataclass
class OrchestratorResult:
    response: str
    function_name: str
    method: str  # semantic, llm_fallback, clarification, guardrail
    similarity: float
    state_trace: list | None = None
    books: list | None = None  # book data with images for frontend display
    top_candidates: list | None = None  # top-3 semantic candidates


async def handle_query(
    query: str,
    user_id: int,
    session: AsyncSession,
    session_id: int | None = None,
) -> OrchestratorResult:
    """
    Punto de entrada principal del orquestador.
    1. Selección semántica
    2. Decide ejecución directa o LangGraph
    3. Maneja interacción por datos faltantes
    4. Coordina logs y respuesta final
    """
    logger.info("Orquestador recibió consulta de usuario %d: '%s'", user_id, query)

    # Step 0: Handle help/greeting queries directly
    help_response = _check_help_query(query)
    if help_response:
        await _log_execution(session, user_id, session_id, query, "", 1.0, "help", None, help_response)
        return OrchestratorResult(
            response=help_response,
            function_name="",
            method="help",
            similarity=1.0,
        )

    # Step 1: Semantic selection
    match: SemanticMatch = await select_function(query, session)

    # Handle clarification needed
    if match.method == "clarification":
        if not _is_domain_relevant(query):
            logger.info("Consulta fuera del dominio detectada")
            await _log_execution(session, user_id, session_id, query, "", 0.0, "guardrail", None, DOMAIN_GUARDRAIL, match.top_candidates)
            return OrchestratorResult(
                response=DOMAIN_GUARDRAIL,
                function_name="",
                method="guardrail",
                similarity=match.similarity,
                top_candidates=match.top_candidates,
            )
        response = (
            "No estoy seguro de entender tu solicitud. Puedo ayudarte con:\n\n"
            "- Buscar libros por género, autor o tema\n"
            "- Recomendaciones personalizadas\n"
            "- Ver detalles de un libro\n"
            "- Verificar stock/disponibilidad\n"
            "- Agregar o quitar libros del carrito\n"
            "- Hacer checkout y pagar\n"
            "- Consultar estado de pedidos\n\n"
            "¿Qué te gustaría hacer?"
        )
        await _log_execution(session, user_id, session_id, query, "", match.similarity, "clarification", None, response, match.top_candidates)
        return OrchestratorResult(
            response=response,
            function_name="",
            method="clarification",
            similarity=match.similarity,
            top_candidates=match.top_candidates,
        )

    fn_name = match.function_name
    logger.info("Función seleccionada: %s (método: %s)", fn_name, match.method)

    # Step 2: Extract params from query
    params = _extract_params(query, fn_name, session)

    # Step 3: Execute
    if fn_name in LANGGRAPH_FUNCTIONS:
        logger.info("Ejecutando flujo LangGraph para: %s", fn_name)
        extracted = await params

        # Book name resolution for cart operations
        if fn_name in ("add_book_to_cart", "remove_book_from_cart") and "book_id" not in extracted:
            resolution = await _resolve_book_smart(query, session)
            if resolution["status"] == "found":
                extracted["book_id"] = resolution["book_id"]
            elif resolution["status"] == "ambiguous":
                # Return disambiguation response with book options
                books_data = resolution["books"]
                titles = "\n".join(f"  {i+1}) {b['title']} — {b['author']}" for i, b in enumerate(books_data))
                response = f"Encontré varios libros que coinciden. ¿Te refieres a alguno de estos?\n\n{titles}\n\nDime el número o nombre del libro."
                await _log_execution(
                    session, user_id, session_id, query, fn_name,
                    match.similarity, match.method, None, response, match.top_candidates,
                )
                return OrchestratorResult(
                    response=response,
                    function_name=fn_name,
                    method=match.method,
                    similarity=match.similarity,
                    books=[{
                        "id": b["id"], "title": b["title"],
                        "author": b.get("author", ""), "price": b.get("price"),
                        "image_base64": b.get("image_base64"),
                    } for b in books_data],
                    top_candidates=match.top_candidates,
                )
            elif resolution["status"] == "not_found":
                response = "No encontré ningún libro con ese nombre. ¿Podrías darme más detalles o el nombre exacto?"
                await _log_execution(
                    session, user_id, session_id, query, fn_name,
                    match.similarity, match.method, None, response, match.top_candidates,
                )
                return OrchestratorResult(
                    response=response,
                    function_name=fn_name,
                    method=match.method,
                    similarity=match.similarity,
                    top_candidates=match.top_candidates,
                )

        flow_state = await run_flow(fn_name, user_id, query, extracted, session)

        await _log_execution(
            session, user_id, session_id, query, fn_name,
            match.similarity, match.method,
            flow_state.get("state_trace"), flow_state.get("response", ""),
            match.top_candidates,
        )

        return OrchestratorResult(
            response=flow_state.get("response", ""),
            function_name=fn_name,
            method=match.method,
            similarity=match.similarity,
            state_trace=flow_state.get("state_trace"),
            top_candidates=match.top_candidates,
        )

    elif fn_name in DIRECT_FUNCTIONS:
        logger.info("Ejecución directa para: %s", fn_name)
        result = await _execute_direct(fn_name, query, user_id, session)

        # Extract books data for frontend (with images)
        books_for_frontend = _extract_books_from_result(result)

        # Build response: try LLM, fallback to template
        llm_context = _strip_images_for_llm(result)
        response = await _build_response_safe(fn_name, llm_context, query)

        await _log_execution(
            session, user_id, session_id, query, fn_name,
            match.similarity, match.method, None, response,
            match.top_candidates,
        )

        return OrchestratorResult(
            response=response,
            function_name=fn_name,
            method=match.method,
            similarity=match.similarity,
            books=books_for_frontend,
            top_candidates=match.top_candidates,
        )

    # Should not reach here
    return OrchestratorResult(
        response="Error interno del orquestador.",
        function_name=fn_name,
        method="error",
        similarity=match.similarity,
    )


# ── Direct execution functions ───────────────────────────────────────────────

async def _execute_direct(
    fn_name: str, query: str, user_id: int, session: AsyncSession,
) -> dict:
    if fn_name == "search_books_for_sale":
        return await _search_books(query, session)

    elif fn_name == "recommend_books_for_purchase":
        return await _recommend_books(query, session)

    elif fn_name == "get_book_product_details":
        return await _get_book_details(query, session)

    elif fn_name == "check_book_stock":
        return await _check_stock(query, session)

    elif fn_name == "get_order_status":
        return await _get_order_status(user_id, query, session)

    return {"error": "Función no implementada"}


async def _search_books(query: str, session: AsyncSession) -> dict:
    keywords = _extract_keywords(query)
    stmt = select(Book)

    if keywords:
        conditions = []
        for kw in keywords:
            conditions.append(Book.title.ilike(f"%{kw}%"))
            conditions.append(Book.genre.ilike(f"%{kw}%"))
            conditions.append(Book.author.ilike(f"%{kw}%"))

        from sqlalchemy import or_
        stmt = stmt.where(or_(*conditions))

    result = await session.execute(stmt.limit(10))
    books = result.scalars().all()
    logger.info("Búsqueda de libros: %d resultados", len(books))

    return {
        "books": [
            {"id": b.id, "title": b.title, "author": b.author,
             "genre": b.genre, "price": b.price, "stock": b.stock,
             "image_base64": b.image_base64}
            for b in books
        ],
        "count": len(books),
    }


async def _recommend_books(query: str, session: AsyncSession) -> dict:
    # Simple recommendation: random selection with optional genre filter
    keywords = _extract_keywords(query)
    stmt = select(Book)

    if keywords:
        from sqlalchemy import or_
        conditions = []
        for kw in keywords:
            conditions.append(Book.genre.ilike(f"%{kw}%"))
        stmt = stmt.where(or_(*conditions))

    result = await session.execute(stmt.limit(5))
    books = result.scalars().all()
    logger.info("Recomendaciones generadas: %d libros", len(books))

    return {
        "recommendations": [
            {"id": b.id, "title": b.title, "author": b.author,
             "genre": b.genre, "price": b.price,
             "image_base64": b.image_base64}
            for b in books
        ],
    }


async def _get_book_details(query: str, session: AsyncSession) -> dict:
    resolution = await _resolve_book_smart(query, session)

    if resolution["status"] == "not_found":
        return {"error": "No pude identificar el libro"}
    if resolution["status"] == "ambiguous":
        return {"error": "Encontré varios libros, sé más específico", "options": resolution["books"]}

    book = resolution["book"]
    logger.info("Detalles del libro: %s", book.title)
    return {
        "id": book.id, "title": book.title, "author": book.author,
        "genre": book.genre, "price": book.price, "stock": book.stock,
        "description": book.description, "image_base64": book.image_base64,
    }


async def _check_stock(query: str, session: AsyncSession) -> dict:
    resolution = await _resolve_book_smart(query, session)

    if resolution["status"] == "not_found":
        return {"error": "No pude identificar el libro"}
    if resolution["status"] == "ambiguous":
        return {"error": "Encontré varios libros, sé más específico", "options": resolution["books"]}

    book = resolution["book"]
    logger.info("Stock consultado: %s = %d unidades", book.title, book.stock)
    return {
        "id": book.id, "title": book.title, "stock": book.stock,
        "available": book.stock > 0, "image_base64": book.image_base64,
    }


async def _get_order_status(user_id: int, query: str, session: AsyncSession) -> dict:
    # Try to extract order ID from query
    order_id = _extract_number(query, context="order_id")

    if order_id:
        result = await session.execute(
            select(Order).where(Order.id == order_id, Order.user_id == user_id)
        )
        order = result.scalar_one_or_none()
    else:
        # Get latest order
        result = await session.execute(
            select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(1)
        )
        order = result.scalar_one_or_none()

    if not order:
        return {"error": "No se encontró la orden"}

    logger.info("Estado de orden #%d: %s", order.id, order.status)
    return {
        "order_id": order.id, "status": order.status,
        "total": order.total,
    }


# ── Parameter extraction ─────────────────────────────────────────────────────

async def _extract_params(query: str, fn_name: str, session: AsyncSession) -> dict:
    """Extrae parámetros del query según la función."""
    params = {}

    # Resolve book using smart 3-tier matching
    if fn_name in ("add_book_to_cart", "remove_book_from_cart",
                    "get_book_product_details", "check_book_stock"):
        resolution = await _resolve_book_smart(query, session)
        if resolution["status"] == "found":
            params["book_id"] = resolution["book_id"]
            logger.info("Libro identificado (smart): %s (ID: %d)",
                        resolution["book"].title, resolution["book_id"])

    # Extract quantity (context-aware)
    if fn_name == "add_book_to_cart":
        qty = _extract_number(query, context="quantity")
        if qty:
            params["quantity"] = qty

    # Extract order_id (context-aware)
    if fn_name in ("process_payment", "cancel_order", "get_order_status"):
        order_id = _extract_number(query, context="order_id")
        if order_id:
            params["order_id"] = order_id

    return params


def _extract_keywords(query: str) -> list[str]:
    """
    Extrae palabras clave del query con sistema de 3 fases:
    1. Detectar strings entre comillas como título exacto
    2. Detectar frases de título (secuencias capitalizadas con conectores)
    3. Stop words reducidas (mantener "the", "of", "a" cuando son parte de títulos)
    """
    # Phase 1: Quoted strings → return as single keyword
    quoted = re.findall(r'"([^"]+)"', query)
    if quoted:
        return quoted[:3]

    # Phase 2: Detect title phrases — capitalized words with connectors (the, of, a, and)
    # e.g., "The Great Gatsby", "One Hundred Years of Solitude"
    title_connectors = {"the", "of", "a", "an", "and", "in", "to", "for", "del", "de", "la", "el", "los", "las", "y"}
    title_phrases = []
    # Find sequences of capitalized words (with connectors between them)
    title_pattern = re.findall(
        r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]*(?:\s+(?:the|of|a|an|and|in|to|for|del|de|la|el|los|las|y)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]*|(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]*))*)\b',
        query
    )
    for phrase in title_pattern:
        words_in_phrase = phrase.split()
        # Only consider phrases with 2+ words or single proper nouns (not action verbs)
        if len(words_in_phrase) >= 2:
            title_phrases.append(phrase)
        elif len(words_in_phrase) == 1 and words_in_phrase[0].lower() not in _ACTION_WORDS:
            title_phrases.append(phrase)

    # Phase 3: Remaining keywords with reduced stop words
    stop_words = {
        "is", "are", "was", "were", "be", "been",
        "do", "does", "did", "have", "has", "had", "will", "would",
        "could", "should", "may", "might", "can", "shall",
        "i", "me", "my", "you", "your", "we", "our", "they", "them",
        "this", "that", "these", "those", "it", "its",
        "for", "to", "from", "with", "about", "in", "on", "at",
        "by", "and", "or", "but", "not", "no", "if", "so", "as",
        "what", "which", "who", "whom", "how", "when", "where", "why",
        "want", "need", "like", "get", "find", "show", "give", "tell",
        "search", "look", "looking", "please", "help", "book", "books",
        "buy", "purchase", "recommend", "recommendation", "available",
        "stock", "cart", "add", "remove", "order", "pay", "cancel",
        "check", "status", "details", "detail", "information", "info",
        # Spanish stop words (reduced — keep title-relevant words)
        "quiero", "buscar", "ver", "dame", "muestra", "mostrar",
        "tiene", "tienen", "hay", "del", "de", "el", "la", "los", "las",
        "un", "una", "unos", "unas", "mi", "mis", "tu", "tus",
        "por", "para", "con", "sin", "que", "como", "donde", "cuando",
        "porque", "pero", "este", "esta", "estos", "estas", "ese", "esa",
        "libro", "libros", "comprar", "agregar", "añadir", "carrito",
        "pagar", "cancelar", "recomendar", "recomendación", "disponible",
        "estado", "pedido", "orden", "quitar", "eliminar", "sacar",
        "también", "algo", "algún", "alguna", "más", "menos",
        "puedo", "puedes", "puede", "podría", "necesito", "necesitas",
        "favor", "gracias", "hola", "buenas",
        "cuánto", "cuántos", "cuál", "cuáles", "sobre",
        "quisiera", "deseo", "gustaría", "prefiero",
        "tienda", "venta", "catálogo", "precio",
        "cuesta", "cuanto", "cuantos", "cual", "cuales",
        "esos", "esas", "aquel", "aquella",
        "mío", "tuyo", "suyo", "nuestro", "vuestro",
        "ser", "estar", "tener", "hacer", "poder", "decir",
        "saber", "dar", "llegar", "llevar",
        "ponme", "tráeme", "traeme", "compra", "agrega",
    }

    # If we found title phrases, use them as primary keywords
    if title_phrases:
        result = list(title_phrases)
        # Also grab non-title words that pass stop word filter (e.g., genre words)
        title_words_lower = {w.lower() for phrase in title_phrases for w in phrase.split()}
        remaining = re.findall(r'\b[a-zA-ZáéíóúñÁÉÍÓÚÑ]{3,}\b', query.lower())
        extras = [w for w in remaining if w not in stop_words and w not in title_words_lower]
        return (result + extras)[:5]

    # No title phrases found — standard keyword extraction
    words = re.findall(r'\b[a-zA-ZáéíóúñÁÉÍÓÚÑ0-9]{2,}\b', query.lower())
    # Keep numbers like "1984" as keywords
    keywords = [w for w in words if w not in stop_words]

    return keywords[:5]


# Action words that should not be treated as title keywords
_ACTION_WORDS = {
    "busca", "busco", "buscar", "compra", "comprar", "agrega", "agregar",
    "dame", "ponme", "muestra", "mostrar", "quiero", "deseo", "ver",
    "añadir", "eliminar", "quitar", "sacar", "pagar", "cancelar",
    "recomienda", "sugiere", "hola", "buenas", "gracias",
    "buy", "add", "remove", "search", "find", "show", "get", "want",
}


def _extract_number(query: str, context: str = "any") -> int | None:
    """
    Context-aware number extraction.
    context="quantity": busca N copias/unidades o número antes de título (1-99)
    context="order_id": busca "orden #N" o "pedido N"
    context="any": primer número encontrado
    """
    if context == "quantity":
        # Pattern: "N copias/unidades/ejemplares"
        m = re.search(r'(\d+)\s*(?:copias?|unidades?|ejemplares?)', query, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n
        # Pattern: number before a title-like word (e.g., "compra 3 The Alchemist")
        m = re.search(r'(?:compra|dame|ponme|tráeme|traeme|agrega|añade|buy|add|get)\s+(\d+)\s+', query, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n
        # Pattern: number at start or standalone small number
        m = re.search(r'\b(\d{1,2})\b', query)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n
        return None

    if context == "order_id":
        # Pattern: "orden/pedido/order #N" or "orden N"
        m = re.search(r'(?:orden|pedido|order)\s*#?\s*(\d+)', query, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None

    # context="any" — first number found
    m = re.search(r'\b(\d+)\b', query)
    if m:
        return int(m.group(1))
    return None


# ── Smart book resolution (3-tier) ────────────────────────────────────────────

async def _resolve_book_smart(query: str, session: AsyncSession) -> dict:
    """
    Resolve a book from query using 3-tier matching:
    TIER 1: Exact title match as substring (case-insensitive)
    TIER 2: AND keywords (title must contain ALL keywords)
    TIER 3: OR keywords with scoring (more matches = better)
    """
    # Load all books
    result = await session.execute(select(Book))
    all_books = result.scalars().all()
    if not all_books:
        return {"status": "not_found"}

    query_lower = query.lower()

    # TIER 1: Exact title substring match
    # Sort by title length descending so "The Great Gatsby" matches before "The"
    exact_matches = []
    for book in sorted(all_books, key=lambda b: len(b.title), reverse=True):
        if book.title.lower() in query_lower:
            exact_matches.append(book)

    if len(exact_matches) == 1:
        logger.info("TIER 1 — exact match: %s (ID: %d)", exact_matches[0].title, exact_matches[0].id)
        return {"status": "found", "book_id": exact_matches[0].id, "book": exact_matches[0]}
    if len(exact_matches) > 1:
        # Multiple exact matches — return the longest title (most specific)
        best = max(exact_matches, key=lambda b: len(b.title))
        logger.info("TIER 1 — best exact match: %s (ID: %d)", best.title, best.id)
        return {"status": "found", "book_id": best.id, "book": best}

    # TIER 2 & 3: Keyword-based
    keywords = _extract_keywords(query)
    if not keywords:
        return {"status": "not_found"}

    # Score each book
    scored = []
    for book in all_books:
        title_lower = book.title.lower()
        matches = sum(1 for kw in keywords if kw.lower() in title_lower)
        if matches > 0:
            scored.append((book, matches))

    if not scored:
        return {"status": "not_found"}

    scored.sort(key=lambda x: x[1], reverse=True)

    # TIER 2: Check if top result matches ALL keywords
    best_book, best_count = scored[0]
    if best_count == len(keywords):
        logger.info("TIER 2 — AND match: %s (ID: %d, %d/%d kw)", best_book.title, best_book.id, best_count, len(keywords))
        return {"status": "found", "book_id": best_book.id, "book": best_book}

    # TIER 3: OR with scoring
    if len(scored) == 1:
        logger.info("TIER 3 — single OR match: %s (ID: %d, %d kw)", best_book.title, best_book.id, best_count)
        return {"status": "found", "book_id": best_book.id, "book": best_book}

    # Multiple partial matches — check if top is clearly better
    second_count = scored[1][1]
    if best_count > second_count:
        logger.info("TIER 3 — best OR match: %s (ID: %d, %d vs %d kw)", best_book.title, best_book.id, best_count, second_count)
        return {"status": "found", "book_id": best_book.id, "book": best_book}

    # Ambiguous — return top options
    top_books = [b for b, c in scored[:5] if c == best_count]
    logger.info("TIER 3 — ambiguous: %s", [b.title for b in top_books])
    return {
        "status": "ambiguous",
        "books": [
            {"id": b.id, "title": b.title, "author": b.author,
             "price": b.price, "image_base64": b.image_base64}
            for b in top_books
        ],
    }


# ── Help/greeting detection ──────────────────────────────────────────────────

_HELP_PATTERNS = [
    r"(?:qu[eé]|que)\s+(?:puedes?|puede)\s+hacer",
    r"(?:qu[eé]|que)\s+(?:sabes?|sabe)\s+hacer",
    r"(?:ayuda|help)\b",
    r"(?:c[oó]mo|como)\s+(?:funciona|te\s+uso)",
    r"(?:qu[eé]|que)\s+(?:opciones|funciones|servicios)",
    r"(?:para\s+)?(?:qu[eé]|que)\s+(?:sirves?|eres)",
]

_GREETING_PATTERNS = [
    r"^(?:hola|hey|buenas?|buenos?\s+d[ií]as?|buenas?\s+tardes?|buenas?\s+noches?)[\s!.?]*$",
    r"^(?:hi|hello|saludos?)[\s!.?]*$",
]

_HELP_RESPONSE = (
    "Puedo ayudarte con todo lo relacionado a nuestra librería:\n\n"
    "- Buscar libros por género, autor o tema\n"
    "- Darte recomendaciones personalizadas\n"
    "- Mostrarte detalles de un libro específico\n"
    "- Verificar stock y disponibilidad\n"
    "- Agregar libros a tu carrito\n"
    "- Hacer checkout y procesar pagos\n"
    "- Consultar el estado de tus pedidos\n\n"
    "Prueba escribiendo algo como: \"Buscar libros de fantasía\" o \"Agregar Dune al carrito\""
)

def _check_help_query(query: str) -> str | None:
    """Detect help/greeting queries and return canned response."""
    q = query.lower().strip()

    for pattern in _GREETING_PATTERNS:
        if re.search(pattern, q):
            return (
                "Hola! Soy tu asistente de la librería. "
                "Puedo buscar libros, darte recomendaciones, agregar al carrito y más. "
                "¿Qué te gustaría hacer?"
            )

    for pattern in _HELP_PATTERNS:
        if re.search(pattern, q):
            return _HELP_RESPONSE

    return None


# ── Domain relevance (local, no LLM) ─────────────────────────────────────────

_DOMAIN_KEYWORDS = {
    "libro", "libros", "leer", "lectura", "autor", "autora",
    "novela", "novelas", "comprar", "compra", "carrito", "pedido",
    "orden", "pago", "pagar", "checkout", "stock", "disponible",
    "recomend", "buscar", "busca", "busco", "catálogo", "catalogo",
    "precio", "tienda", "librería", "libreria", "genero", "género",
    "ficción", "ficcion", "fantasia", "fantasía", "ciencia",
    "clásico", "clasico", "romance", "terror", "horror",
    "book", "cart", "order", "pay", "search", "recommend",
    "agregar", "añadir", "eliminar", "quitar", "cancelar",
    "detalle", "detalles", "información", "informacion",
    "hola", "ayuda", "ayudar", "help", "qué puedes", "que puedes",
}

def _is_domain_relevant(query: str) -> bool:
    """Check if query is related to bookstore domain (no LLM needed)."""
    q = query.lower()
    for kw in _DOMAIN_KEYWORDS:
        if kw in q:
            return True
    # Short queries are likely domain-related (greetings, etc.)
    if len(query.split()) <= 3:
        return True
    return False


# ── Response building (LLM-safe) ─────────────────────────────────────────────

async def _build_response_safe(fn_name: str, result_data: dict, query: str) -> str:
    """Try LLM for natural response, fallback to template if unavailable."""
    try:
        response = await build_natural_response({
            "action": fn_name,
            "result": result_data,
            "query": query,
        })
        if response:
            return response
    except Exception as e:
        logger.warning("LLM no disponible para respuesta, usando plantilla: %s", str(e))

    # Fallback: use template from llm.py
    from app.ai.llm import _build_fallback_response
    return _build_fallback_response(fn_name, result_data)


# ── Image helpers ────────────────────────────────────────────────────────────

def _extract_books_from_result(result: dict) -> list | None:
    """Extract book entries with images from a direct execution result."""
    books = []

    # From search_books
    if "books" in result:
        for b in result["books"]:
            if b.get("image_base64"):
                books.append({
                    "id": b["id"], "title": b["title"], "author": b.get("author", ""),
                    "price": b.get("price"), "image_base64": b["image_base64"],
                })

    # From recommend_books
    if "recommendations" in result:
        for b in result["recommendations"]:
            if b.get("image_base64"):
                books.append({
                    "id": b["id"], "title": b["title"], "author": b.get("author", ""),
                    "price": b.get("price"), "image_base64": b["image_base64"],
                })

    # From get_book_details / check_stock (single book)
    if "id" in result and "title" in result and result.get("image_base64"):
        books.append({
            "id": result["id"], "title": result["title"],
            "author": result.get("author", ""), "price": result.get("price"),
            "image_base64": result["image_base64"],
        })

    return books if books else None


def _strip_images_for_llm(result: dict) -> dict:
    """Remove image_base64 fields to keep LLM context small."""
    import copy
    clean = copy.deepcopy(result)

    clean.pop("image_base64", None)

    for key in ("books", "recommendations"):
        if key in clean:
            for item in clean[key]:
                item.pop("image_base64", None)

    return clean


# ── Logging ──────────────────────────────────────────────────────────────────

async def _log_execution(
    session: AsyncSession,
    user_id: int,
    session_id: int | None,
    query: str,
    fn_name: str,
    similarity: float,
    method: str,
    state_trace: list | None,
    result: str,
    top_candidates: list | None = None,
):
    try:
        log = ExecutionLog(
            user_id=user_id,
            session_id=session_id,
            query=query,
            matched_function=fn_name,
            similarity_score=similarity,
            method=method,
            top_candidates=top_candidates,
            state_trace=state_trace,
            result=result,
        )
        session.add(log)
        await session.commit()
    except Exception as e:
        logger.error("Error al guardar log de ejecución: %s", str(e))
        try:
            await session.rollback()
        except Exception:
            pass
