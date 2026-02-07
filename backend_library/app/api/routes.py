import hashlib

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.db import get_session
from app.persistence.models import Book, Cart, CartItem, Order, OrderItem, User, ExecutionLog

router = APIRouter()


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/register")
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    existing = await session.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        return {"error": "Este correo ya está registrado"}

    user = User(name=body.name, email=body.email, password_hash=_hash_password(body.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return {"id": user.id, "name": user.name, "email": user.email}


@router.post("/auth/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or user.password_hash != _hash_password(body.password):
        return {"error": "Correo o contraseña incorrectos"}
    return {"id": user.id, "name": user.name, "email": user.email}


@router.get("/auth/me")
async def get_me(user_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"error": "Usuario no encontrado"}
    return {"id": user.id, "name": user.name, "email": user.email}


@router.get("/books")
async def list_books(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Book).order_by(Book.id))
    books = result.scalars().all()
    return [
        {
            "id": b.id, "title": b.title, "author": b.author,
            "genre": b.genre, "price": b.price, "stock": b.stock,
            "image_base64": b.image_base64,
        }
        for b in books
    ]


@router.get("/books/{book_id}")
async def get_book(book_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        return {"error": "Libro no encontrado"}
    return {
        "id": book.id, "title": book.title, "author": book.author,
        "genre": book.genre, "price": book.price, "stock": book.stock,
        "description": book.description, "image_base64": book.image_base64,
    }


@router.get("/cart")
async def get_cart(user_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Cart).where(Cart.user_id == user_id, Cart.status == "active")
    )
    cart = result.scalar_one_or_none()
    if not cart:
        return {"items": [], "total": 0}

    result = await session.execute(select(CartItem).where(CartItem.cart_id == cart.id))
    items = result.scalars().all()

    cart_items = []
    total = 0
    for item in items:
        book_result = await session.execute(select(Book).where(Book.id == item.book_id))
        book = book_result.scalar_one_or_none()
        if book:
            subtotal = book.price * item.quantity
            total += subtotal
            cart_items.append({
                "book_id": book.id, "title": book.title,
                "quantity": item.quantity, "unit_price": book.price,
                "subtotal": subtotal, "image_base64": book.image_base64,
            })

    return {"cart_id": cart.id, "items": cart_items, "total": round(total, 2)}


@router.get("/orders")
async def list_orders(user_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    return [
        {"id": o.id, "status": o.status, "total": o.total, "created_at": str(o.created_at)}
        for o in orders
    ]


@router.get("/orders/{order_id}")
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        return {"error": "Orden no encontrada"}

    result = await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    items = result.scalars().all()

    order_items = []
    for item in items:
        book_result = await session.execute(select(Book).where(Book.id == item.book_id))
        book = book_result.scalar_one_or_none()
        order_items.append({
            "book_id": item.book_id,
            "title": book.title if book else "Unknown",
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "image_base64": book.image_base64 if book else None,
        })

    return {
        "id": order.id, "status": order.status, "total": order.total,
        "items": order_items, "created_at": str(order.created_at),
    }


# ── Cart REST endpoints ─────────────────────────────────────────────────────

class CartAddRequest(BaseModel):
    user_id: int
    book_id: int
    quantity: int = 1


class CartUpdateRequest(BaseModel):
    user_id: int
    book_id: int
    quantity: int


class CartRemoveRequest(BaseModel):
    user_id: int
    book_id: int


@router.post("/cart/add")
async def add_to_cart(body: CartAddRequest, session: AsyncSession = Depends(get_session)):
    # Verify book exists and has stock
    result = await session.execute(select(Book).where(Book.id == body.book_id))
    book = result.scalar_one_or_none()
    if not book:
        return {"error": "Libro no encontrado"}
    if book.stock < body.quantity:
        return {"error": f"Stock insuficiente. Solo hay {book.stock} disponibles."}

    # Get or create active cart
    result = await session.execute(
        select(Cart).where(Cart.user_id == body.user_id, Cart.status == "active")
    )
    cart = result.scalar_one_or_none()
    if not cart:
        cart = Cart(user_id=body.user_id, status="active")
        session.add(cart)
        await session.flush()

    # Check if item already in cart
    result = await session.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.book_id == body.book_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.quantity += body.quantity
    else:
        session.add(CartItem(cart_id=cart.id, book_id=body.book_id, quantity=body.quantity))

    await session.commit()
    return {"success": True, "message": f"'{book.title}' agregado al carrito ({body.quantity} unidad{'es' if body.quantity > 1 else ''})"}


@router.post("/cart/update")
async def update_cart_item(body: CartUpdateRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Cart).where(Cart.user_id == body.user_id, Cart.status == "active")
    )
    cart = result.scalar_one_or_none()
    if not cart:
        return {"error": "No tienes un carrito activo"}

    result = await session.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.book_id == body.book_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"error": "Este libro no está en tu carrito"}

    if body.quantity <= 0:
        await session.delete(item)
    else:
        item.quantity = body.quantity

    await session.commit()
    return {"success": True}


@router.post("/cart/remove")
async def remove_from_cart(body: CartRemoveRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Cart).where(Cart.user_id == body.user_id, Cart.status == "active")
    )
    cart = result.scalar_one_or_none()
    if not cart:
        return {"error": "No tienes un carrito activo"}

    result = await session.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.book_id == body.book_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"error": "Este libro no está en tu carrito"}

    await session.delete(item)
    await session.commit()
    return {"success": True, "message": "Libro eliminado del carrito"}


# ── Logs endpoint ────────────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    user_id: int | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(limit)
    if user_id is not None:
        stmt = select(ExecutionLog).where(
            ExecutionLog.user_id == user_id
        ).order_by(ExecutionLog.created_at.desc()).limit(limit)

    result = await session.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "query": log.query,
            "matched_function": log.matched_function,
            "similarity_score": log.similarity_score,
            "method": log.method,
            "top_candidates": log.top_candidates,
            "created_at": str(log.created_at),
        }
        for log in logs
    ]
