import logging
import json
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_openai_client = None

DOMAIN_GUARDRAIL = (
    "No puedo ayudar con eso. Puedo ayudarte con compras, "
    "recomendaciones y pedidos de libros."
)

FALLBACK_RESPONSE = (
    "Lo siento, hubo un problema al procesar tu solicitud. "
    "¿Podrías intentar de nuevo?"
)


# ── LLM abstraction layer ──────────────────────────────────────────────────

async def _chat_completion(messages: list[dict], temperature: float = 0, max_tokens: int = 250) -> str:
    """
    Unified chat completion that routes to OpenAI or Ollama based on config.
    """
    if settings.llm_provider == "openai":
        return await _openai_chat(messages, temperature, max_tokens)
    elif settings.llm_provider == "ollama":
        return await _ollama_chat(messages, temperature, max_tokens)
    else:
        raise ValueError(f"LLM provider no soportado: {settings.llm_provider}")


async def _openai_chat(messages: list[dict], temperature: float, max_tokens: int) -> str:
    """Chat completion via OpenAI API."""
    from openai import AsyncOpenAI

    global _openai_client
    if _openai_client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no configurada. Cambia a ollama o configura la key en .env")
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await _openai_client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


async def _ollama_chat(messages: list[dict], temperature: float, max_tokens: int) -> str:
    """Chat completion via Ollama local API (compatible con OpenAI format)."""
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()


# ── Public functions ────────────────────────────────────────────────────────

async def classify_intent(
    query: str,
    functions: dict[str, str],
) -> str | None:
    fn_list = "\n".join(f"- {name}: {desc}" for name, desc in functions.items())

    prompt = f"""You are a classifier for a bookstore chatbot.
Given the user query, classify it into ONE of these functions.
If the query is NOT related to a bookstore (buying books, carts, orders, recommendations), respond with "NONE".

Available functions:
{fn_list}

User query: "{query}"

Respond with ONLY the function name or "NONE". No explanation."""

    try:
        result = await _chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=50,
        )
        logger.info("LLM clasificacion resultado: %s", result)

        if result == "NONE" or result not in functions:
            return None
        return result

    except Exception as e:
        logger.error("Error al clasificar intencion con LLM: %s", str(e))
        return None


async def build_natural_response(context: dict) -> str:
    action = context.get("action", "unknown")
    result_data = context.get("result", {})
    query = context.get("query", "")

    result_json = json.dumps(result_data, ensure_ascii=False, default=str)

    prompt = f"""Eres un asistente amigable de una libreria online. Responde en espanol de forma natural y util.

REGLAS IMPORTANTES:
- SIEMPRE incluye los datos concretos del resultado (titulos, autores, precios, cantidades, estados, etc.)
- Si hay una lista de libros, menciona cada uno con su titulo, autor y precio
- Si es un detalle de libro, incluye titulo, autor, genero, precio, stock y descripcion
- Si es stock, di cuantas unidades hay disponibles
- Si es una orden, incluye el numero de orden, estado y total
- Si hay un error en el resultado, explicalo amablemente
- Se conciso pero COMPLETO con la informacion
- NO digas solo "aqui estan los detalles" sin mostrarlos

Accion realizada: {action}
Datos del resultado: {result_json}
Consulta original del usuario: {query}

Responde de forma natural incluyendo TODOS los datos relevantes:"""

    try:
        return await _chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=250,
        )
    except Exception as e:
        logger.error("Error al generar respuesta natural con LLM: %s", str(e))
        return _build_fallback_response(action, result_data)


def _build_fallback_response(action: str, result: dict) -> str:
    """Respuesta de respaldo con datos reales cuando falla el LLM."""

    if action == "search_books_for_sale":
        books = result.get("books", [])
        if not books:
            return "No encontre libros con esos criterios."
        lines = [f"Encontre {len(books)} libro(s):\n"]
        for b in books[:10]:
            lines.append(f"- {b['title']} por {b['author']} -- ${b['price']:.2f}")
        return "\n".join(lines)

    if action == "recommend_books_for_purchase":
        recs = result.get("recommendations", [])
        if not recs:
            return "No tengo recomendaciones por ahora."
        lines = ["Te recomiendo:\n"]
        for b in recs:
            lines.append(f"- {b['title']} por {b['author']} -- ${b['price']:.2f}")
        return "\n".join(lines)

    if action == "get_book_product_details":
        if "error" in result:
            return result["error"]
        return (
            f"{result.get('title', '?')}\n"
            f"Autor: {result.get('author', '?')}\n"
            f"Genero: {result.get('genre', '?')}\n"
            f"Precio: ${result.get('price', 0):.2f}\n"
            f"Stock: {result.get('stock', 0)} unidades\n"
            f"{result.get('description', '')}"
        )

    if action == "check_book_stock":
        if "error" in result:
            return result["error"]
        title = result.get("title", "El libro")
        stock = result.get("stock", 0)
        if stock > 0:
            return f"{title} tiene {stock} unidades disponibles."
        return f"{title} esta agotado."

    if action == "add_book_to_cart":
        if not result.get("success"):
            return result.get("message", "No se pudo agregar al carrito.")
        return f"{result.get('book', 'Libro')} (x{result.get('quantity', 1)}) agregado al carrito."

    if action == "remove_book_from_cart":
        if not result.get("success"):
            return result.get("message", "No se pudo eliminar del carrito.")
        return "Libro eliminado del carrito."

    if action == "checkout_order":
        if not result.get("success"):
            return result.get("message", "No se pudo crear la orden.")
        return f"Orden #{result.get('order_id')} creada. Total: ${result.get('total', 0):.2f}. {result.get('items_count', 0)} item(s)."

    if action == "process_payment":
        if not result.get("success"):
            return result.get("message", "El pago fue rechazado. Intenta de nuevo.")
        return f"Pago aprobado para la orden #{result.get('order_id')}. Monto: ${result.get('amount', 0):.2f}."

    if action == "cancel_order":
        if not result.get("success"):
            return result.get("message", "No se pudo cancelar la orden.")
        return f"Orden #{result.get('order_id')} cancelada."

    if action == "get_order_status":
        if "error" in result:
            return result["error"]
        return f"Orden #{result.get('order_id')}: estado {result.get('status', '?')}, total ${result.get('total', 0):.2f}."

    return FALLBACK_RESPONSE


TRANSACTIONAL_ACTIONS = {
    "add_book_to_cart",
    "remove_book_from_cart",
    "checkout_order",
    "process_payment",
    "confirm_payment",
    "cancel_order",
    "view_cart",
}


def build_transactional_response(action: str, result: dict) -> str:
    """Template-based responses for transactional actions (no LLM needed)."""

    if action == "add_book_to_cart":
        if not result.get("success"):
            return result.get("message", "No se pudo agregar al carrito.")
        book = result.get("book", "Libro")
        qty = result.get("quantity", 1)
        return (
            f"**{book}** (x{qty}) agregado al carrito.\n\n"
            f"¿Qué deseas hacer ahora?\n"
            f"- Escribe **\"ver mi carrito\"** para ver el contenido\n"
            f"- Escribe **\"hacer checkout\"** para crear tu orden"
        )

    if action == "remove_book_from_cart":
        if not result.get("success"):
            return result.get("message", "No se pudo eliminar del carrito.")
        return "Libro eliminado del carrito. Escribe **\"ver mi carrito\"** para ver el contenido actualizado."

    if action == "checkout_order":
        if not result.get("success"):
            return result.get("message", "No se pudo crear la orden.")
        order_id = result.get("order_id")
        total = result.get("total", 0)
        items = result.get("items_count", 0)
        return (
            f"Orden **#{order_id}** creada con {items} item(s).\n"
            f"**Total: ${total:.2f}**\n\n"
            f"Para pagar, escribe **\"pagar orden #{order_id}\"**."
        )

    if action == "process_payment":
        if result.get("needs_confirmation"):
            order_id = result.get("order_id")
            amount = result.get("amount", 0)
            return (
                f"Estás a punto de pagar **${amount:.2f}** para la orden **#{order_id}**.\n\n"
                f"Responde **\"sí, confirmo el pago\"** para procesar el pago."
            )
        if not result.get("success"):
            return result.get("message", "El pago fue rechazado. Intenta de nuevo.")
        return (
            f"Pago **aprobado** para la orden **#{result.get('order_id')}**.\n"
            f"Monto: **${result.get('amount', 0):.2f}**.\n\n"
            f"¡Gracias por tu compra!"
        )

    if action == "confirm_payment":
        if not result.get("success"):
            return result.get("message", "El pago fue rechazado. Intenta de nuevo.")
        return (
            f"Pago **aprobado** para la orden **#{result.get('order_id')}**.\n"
            f"Monto: **${result.get('amount', 0):.2f}**.\n\n"
            f"¡Gracias por tu compra!"
        )

    if action == "cancel_order":
        if not result.get("success"):
            return result.get("message", "No se pudo cancelar la orden.")
        return f"Orden **#{result.get('order_id')}** cancelada exitosamente."

    if action == "view_cart":
        if "error" in result:
            return result["error"]
        items = result.get("items", [])
        if not items:
            return "Tu carrito está vacío. Escribe **\"buscar libros\"** para explorar el catálogo."
        lines = ["**Tu carrito:**\n"]
        for item in items:
            lines.append(f"- {item['title']} (x{item['quantity']}) — ${item['subtotal']:.2f}")
        lines.append(f"\n**Total: ${result.get('total', 0):.2f}**")
        lines.append(f"\nEscribe **\"hacer checkout\"** para crear tu orden.")
        return "\n".join(lines)

    return _build_fallback_response(action, result)


async def check_domain_relevance(query: str) -> bool:
    prompt = f"""Is this query related to a bookstore (buying, searching, recommending books, cart, orders, payments)?
Query: "{query}"
Answer only YES or NO."""

    try:
        answer = await _chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        return answer.upper() == "YES"
    except Exception:
        return True
