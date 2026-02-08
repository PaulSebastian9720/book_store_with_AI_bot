"""
LangGraph — Máquina de estados para flujos complejos de la tienda de libros.

Nodos:
  VALIDATE_INPUT → LOAD_CONTEXT → APPLY_ACTION → PERSIST → BUILD_RESPONSE → DONE
  (con rama ASK_INPUT cuando faltan datos)

Flujos soportados: carrito, checkout, pago, cancelación.
"""
import logging
import random
from typing import TypedDict, Literal

from langgraph.graph import StateGraph, END
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import (
    Book, Cart, CartItem, Order, OrderItem, Payment,
)
from app.ai.llm import build_natural_response, build_transactional_response, TRANSACTIONAL_ACTIONS

logger = logging.getLogger(__name__)


# ── State definition ─────────────────────────────────────────────────────────

class FlowState(TypedDict, total=False):
    user_id: int
    function_name: str
    query: str
    params: dict          # extracted params (book_id, quantity, order_id, etc.)
    context: dict         # loaded data from DB
    action_result: dict   # result of apply_action
    response: str         # final natural language response
    state_trace: list     # list of executed states
    needs_input: bool     # True if data is missing
    missing_fields: list  # which fields are missing
    error: str | None


# ── Node functions ───────────────────────────────────────────────────────────

async def validate_input(state: FlowState) -> FlowState:
    logger.info("Ejecutando estado: VALIDATE_INPUT")
    trace = list(state.get("state_trace", []))
    trace.append("VALIDATE_INPUT")

    fn = state["function_name"]
    params = state.get("params", {})
    missing = []

    # Check required fields per function
    if fn == "add_book_to_cart":
        if not params.get("book_id"):
            missing.append("book_id")
        if not params.get("quantity"):
            params["quantity"] = 1  # default

    elif fn == "remove_book_from_cart":
        if not params.get("book_id"):
            missing.append("book_id")

    elif fn == "process_payment":
        pass  # order_id optional — will use latest "created" order if missing

    elif fn == "confirm_payment":
        pass  # order_id optional — will use latest "created" order if missing

    elif fn == "cancel_order":
        if not params.get("order_id"):
            missing.append("order_id")

    if missing:
        logger.info("Datos faltantes: %s", missing)
        return {
            **state,
            "state_trace": trace,
            "needs_input": True,
            "missing_fields": missing,
            "params": params,
        }

    return {
        **state,
        "state_trace": trace,
        "needs_input": False,
        "missing_fields": [],
        "params": params,
    }


async def load_context(state: FlowState, session: AsyncSession) -> FlowState:
    logger.info("Ejecutando estado: LOAD_CONTEXT")
    trace = list(state.get("state_trace", []))
    trace.append("LOAD_CONTEXT")

    fn = state["function_name"]
    params = state.get("params", {})
    user_id = state["user_id"]
    ctx = {}

    if fn in ("add_book_to_cart", "remove_book_from_cart"):
        # Load book
        if params.get("book_id"):
            result = await session.execute(
                select(Book).where(Book.id == params["book_id"])
            )
            book = result.scalar_one_or_none()
            if book:
                ctx["book"] = {"id": book.id, "title": book.title, "price": book.price, "stock": book.stock}

        # Load or create active cart
        result = await session.execute(
            select(Cart).where(Cart.user_id == user_id, Cart.status == "active")
        )
        cart = result.scalar_one_or_none()
        if cart:
            ctx["cart_id"] = cart.id
        else:
            ctx["cart_id"] = None  # will create in apply

    elif fn == "checkout_order":
        result = await session.execute(
            select(Cart).where(Cart.user_id == user_id, Cart.status == "active")
        )
        cart = result.scalar_one_or_none()
        if cart:
            result_items = await session.execute(
                select(CartItem).where(CartItem.cart_id == cart.id)
            )
            items = result_items.scalars().all()
            ctx["cart_id"] = cart.id
            ctx["cart_items"] = []
            for item in items:
                book_result = await session.execute(select(Book).where(Book.id == item.book_id))
                book = book_result.scalar_one_or_none()
                ctx["cart_items"].append({
                    "book_id": item.book_id,
                    "quantity": item.quantity,
                    "title": book.title if book else "Unknown",
                    "price": book.price if book else 0,
                })

    elif fn in ("process_payment", "confirm_payment", "cancel_order", "get_order_status"):
        order_id = params.get("order_id")
        if order_id:
            result = await session.execute(
                select(Order).where(Order.id == order_id, Order.user_id == user_id)
            )
            order = result.scalar_one_or_none()
        else:
            # Auto-resolve: get latest "created" order for the user
            result = await session.execute(
                select(Order).where(Order.user_id == user_id, Order.status == "created")
                .order_by(Order.created_at.desc()).limit(1)
            )
            order = result.scalar_one_or_none()
        if order:
            ctx["order"] = {
                "id": order.id, "status": order.status, "total": order.total,
            }

    logger.info("Contexto cargado: %s", list(ctx.keys()))
    return {**state, "state_trace": trace, "context": ctx}


async def apply_action(state: FlowState, session: AsyncSession) -> FlowState:
    logger.info("Ejecutando estado: APPLY_ACTION")
    trace = list(state.get("state_trace", []))
    trace.append("APPLY_ACTION")

    fn = state["function_name"]
    params = state.get("params", {})
    ctx = state.get("context", {})
    user_id = state["user_id"]
    result = {}

    try:
        if fn == "add_book_to_cart":
            result = await _action_add_to_cart(session, user_id, params, ctx)

        elif fn == "remove_book_from_cart":
            result = await _action_remove_from_cart(session, params, ctx)

        elif fn == "checkout_order":
            result = await _action_checkout(session, user_id, ctx)

        elif fn == "process_payment":
            result = _build_payment_confirmation(ctx)

        elif fn == "confirm_payment":
            result = await _action_process_payment(session, ctx)

        elif fn == "cancel_order":
            result = await _action_cancel_order(session, ctx)

        elif fn == "get_order_status":
            result = {"order": ctx.get("order", {})}

        logger.info("Acción completada: %s", fn)
        return {**state, "state_trace": trace, "action_result": result, "error": None}

    except Exception as e:
        logger.error("Error en acción %s: %s", fn, str(e))
        return {**state, "state_trace": trace, "action_result": {}, "error": str(e)}


async def persist_state(state: FlowState, session: AsyncSession) -> FlowState:
    logger.info("Ejecutando estado: PERSIST")
    trace = list(state.get("state_trace", []))
    trace.append("PERSIST")

    try:
        await session.commit()
        logger.info("Cambios persistidos correctamente")
    except Exception as e:
        logger.error("Error al persistir: %s", str(e))
        await session.rollback()

    return {**state, "state_trace": trace}


async def build_response(state: FlowState) -> FlowState:
    logger.info("Ejecutando estado: BUILD_RESPONSE")
    trace = list(state.get("state_trace", []))
    trace.append("BUILD_RESPONSE")

    fn = state["function_name"]
    action_result = state.get("action_result", {})

    if state.get("error"):
        response = f"Hubo un error al procesar tu solicitud: {state['error']}"
    elif fn in TRANSACTIONAL_ACTIONS:
        response = build_transactional_response(fn, action_result)
    else:
        try:
            response = await build_natural_response({
                "action": fn,
                "result": action_result,
                "query": state.get("query", ""),
            })
        except Exception as e:
            logger.warning("LLM no disponible, usando plantilla: %s", str(e))
            from app.ai.llm import _build_fallback_response
            response = _build_fallback_response(fn, action_result)

    logger.info("Respuesta construida para: %s", state["function_name"])
    return {**state, "state_trace": trace, "response": response}


# ── Action implementations ───────────────────────────────────────────────────

async def _action_add_to_cart(
    session: AsyncSession, user_id: int, params: dict, ctx: dict,
) -> dict:
    book = ctx.get("book")
    if not book:
        return {"success": False, "message": "Libro no encontrado"}

    if book["stock"] < params.get("quantity", 1):
        return {"success": False, "message": "Stock insuficiente"}

    cart_id = ctx.get("cart_id")
    if not cart_id:
        new_cart = Cart(user_id=user_id, status="active")
        session.add(new_cart)
        await session.flush()
        cart_id = new_cart.id

    # Check if item already in cart
    result = await session.execute(
        select(CartItem).where(
            CartItem.cart_id == cart_id, CartItem.book_id == params["book_id"]
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.quantity += params.get("quantity", 1)
    else:
        session.add(CartItem(
            cart_id=cart_id,
            book_id=params["book_id"],
            quantity=params.get("quantity", 1),
        ))

    logger.info("Libro agregado al carrito: %s (x%d)", book["title"], params.get("quantity", 1))
    return {
        "success": True,
        "book": book["title"],
        "quantity": params.get("quantity", 1),
        "cart_id": cart_id,
    }


async def _action_remove_from_cart(
    session: AsyncSession, params: dict, ctx: dict,
) -> dict:
    cart_id = ctx.get("cart_id")
    if not cart_id:
        return {"success": False, "message": "No tienes un carrito activo"}

    result = await session.execute(
        select(CartItem).where(
            CartItem.cart_id == cart_id, CartItem.book_id == params["book_id"]
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"success": False, "message": "El libro no está en tu carrito"}

    await session.delete(item)
    logger.info("Libro eliminado del carrito")
    return {"success": True, "message": "Libro eliminado del carrito"}


async def _action_checkout(
    session: AsyncSession, user_id: int, ctx: dict,
) -> dict:
    cart_id = ctx.get("cart_id")
    cart_items = ctx.get("cart_items", [])

    if not cart_id or not cart_items:
        return {"success": False, "message": "Tu carrito está vacío"}

    total = sum(item["price"] * item["quantity"] for item in cart_items)

    order = Order(user_id=user_id, status="created", total=total)
    session.add(order)
    await session.flush()

    for item in cart_items:
        session.add(OrderItem(
            order_id=order.id,
            book_id=item["book_id"],
            quantity=item["quantity"],
            unit_price=item["price"],
        ))

    # Mark cart as checked out
    result = await session.execute(select(Cart).where(Cart.id == cart_id))
    cart = result.scalar_one()
    cart.status = "checked_out"

    logger.info("Orden creada: #%d, total: $%.2f", order.id, total)
    return {
        "success": True,
        "order_id": order.id,
        "total": total,
        "items_count": len(cart_items),
    }


def _build_payment_confirmation(ctx: dict) -> dict:
    """Return a confirmation prompt instead of processing payment directly."""
    order = ctx.get("order")
    if not order:
        return {"success": False, "message": "No se encontró una orden pendiente de pago. Primero haz checkout de tu carrito."}

    if order["status"] == "paid":
        return {"success": False, "message": f"La orden **#{order['id']}** ya fue pagada anteriormente."}
    if order["status"] == "cancelled":
        return {"success": False, "message": f"La orden **#{order['id']}** fue cancelada y no se puede pagar."}
    if order["status"] != "created":
        return {"success": False, "message": f"La orden **#{order['id']}** está en estado '{order['status']}' y no se puede pagar."}

    return {
        "needs_confirmation": True,
        "order_id": order["id"],
        "amount": order["total"],
    }


async def _action_process_payment(session: AsyncSession, ctx: dict) -> dict:
    order = ctx.get("order")
    if not order:
        return {"success": False, "message": "No se encontró una orden pendiente de pago. Primero haz checkout de tu carrito."}

    if order["status"] == "paid":
        return {"success": False, "message": f"La orden **#{order['id']}** ya fue pagada anteriormente."}
    if order["status"] == "cancelled":
        return {"success": False, "message": f"La orden **#{order['id']}** fue cancelada y no se puede pagar."}
    if order["status"] != "created":
        return {"success": False, "message": f"La orden **#{order['id']}** está en estado '{order['status']}' y no se puede pagar."}

    # Mock payment: 85% approved, 15% rejected
    approved = random.random() < 0.85
    status = "approved" if approved else "rejected"

    payment = Payment(
        order_id=order["id"],
        amount=order["total"],
        status=status,
    )
    session.add(payment)

    # Update order status
    result = await session.execute(select(Order).where(Order.id == order["id"]))
    db_order = result.scalar_one()
    db_order.status = "paid" if approved else "created"

    if approved:
        logger.info("Pago aprobado para orden #%d", order["id"])
    else:
        logger.info("Pago rechazado para orden #%d", order["id"])

    result = {
        "success": approved,
        "payment_status": status,
        "order_id": order["id"],
        "amount": order["total"],
    }
    if not approved:
        result["message"] = f"El pago para la orden **#{order['id']}** fue rechazado. Intenta de nuevo."
    return result


async def _action_cancel_order(session: AsyncSession, ctx: dict) -> dict:
    order = ctx.get("order")
    if not order:
        return {"success": False, "message": "Orden no encontrada"}

    if order["status"] == "paid":
        return {"success": False, "message": f"No se puede cancelar la orden **#{order['id']}** porque ya fue pagada."}

    if order["status"] == "cancelled":
        return {"success": False, "message": f"La orden **#{order['id']}** ya está cancelada."}

    result = await session.execute(select(Order).where(Order.id == order["id"]))
    db_order = result.scalar_one()
    db_order.status = "cancelled"

    logger.info("Orden cancelada: #%d", order["id"])
    return {"success": True, "order_id": order["id"]}


# ── Graph builder ────────────────────────────────────────────────────────────

def build_flow_graph() -> StateGraph:
    """
    Construye el grafo de estados de LangGraph.
    Los nodos se ejecutan externamente con la sesión de DB inyectada.
    Este grafo define la estructura y las transiciones.
    """
    graph = StateGraph(FlowState)

    # Add nodes (wrappers, real execution happens in run_flow)
    graph.add_node("VALIDATE_INPUT", _noop)
    graph.add_node("LOAD_CONTEXT", _noop)
    graph.add_node("APPLY_ACTION", _noop)
    graph.add_node("PERSIST", _noop)
    graph.add_node("BUILD_RESPONSE", _noop)
    graph.add_node("ASK_INPUT", _noop)

    # Entry point
    graph.set_entry_point("VALIDATE_INPUT")

    # Conditional: validation may need more input
    graph.add_conditional_edges(
        "VALIDATE_INPUT",
        _route_after_validation,
        {"needs_input": "ASK_INPUT", "valid": "LOAD_CONTEXT"},
    )

    graph.add_edge("ASK_INPUT", END)
    graph.add_edge("LOAD_CONTEXT", "APPLY_ACTION")

    graph.add_conditional_edges(
        "APPLY_ACTION",
        _route_after_action,
        {"success": "PERSIST", "error": "BUILD_RESPONSE"},
    )

    graph.add_edge("PERSIST", "BUILD_RESPONSE")
    graph.add_edge("BUILD_RESPONSE", END)

    return graph


def _noop(state: FlowState) -> FlowState:
    return state


def _route_after_validation(state: FlowState) -> str:
    if state.get("needs_input"):
        return "needs_input"
    return "valid"


def _route_after_action(state: FlowState) -> str:
    if state.get("error"):
        return "error"
    return "success"


# ── Flow runner (executes the actual async logic step by step) ───────────────

async def run_flow(
    function_name: str,
    user_id: int,
    query: str,
    params: dict,
    session: AsyncSession,
) -> FlowState:
    """
    Ejecuta el flujo LangGraph paso a paso, inyectando la sesión de DB.
    Retorna el estado final con la respuesta y el trace.
    """
    logger.info("Flujo ejecutado con LangGraph: %s", function_name)

    state: FlowState = {
        "user_id": user_id,
        "function_name": function_name,
        "query": query,
        "params": params,
        "context": {},
        "action_result": {},
        "response": "",
        "state_trace": [],
        "needs_input": False,
        "missing_fields": [],
        "error": None,
    }

    # Step 1: Validate
    state = await validate_input(state)

    if state.get("needs_input"):
        missing = state.get("missing_fields", [])
        field_names = {
            "book_id": "el ID del libro",
            "order_id": "el número de orden",
            "quantity": "la cantidad",
        }
        missing_str = ", ".join(field_names.get(f, f) for f in missing)
        state["response"] = f"Para continuar, necesito que me indiques {missing_str}."
        state["state_trace"].append("ASK_INPUT")
        logger.info("Datos faltantes, solicitando al usuario: %s", missing)
        return state

    # Step 2: Load context
    state = await load_context(state, session)

    # Step 3: Apply action
    state = await apply_action(state, session)

    # Step 4: Persist (if no error)
    if not state.get("error"):
        state = await persist_state(state, session)

    # Step 5: Build response
    state = await build_response(state)

    logger.info("Trace de estados: %s", " → ".join(state["state_trace"]))
    return state
