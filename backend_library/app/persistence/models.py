import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON,
    func,
)
from sqlalchemy.orm import relationship
from app.persistence.db import Base


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    author = Column(String(200), nullable=False)
    genre = Column(String(100))
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    description = Column(Text)
    image_base64 = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    password_hash = Column(String(300), nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())

    carts = relationship("Cart", back_populates="user")
    orders = relationship("Order", back_populates="user")


class Cart(Base):
    __tablename__ = "carts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="active")  # active, checked_out
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="carts")
    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey("carts.id"), nullable=False)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    quantity = Column(Integer, default=1)

    cart = relationship("Cart", back_populates="items")
    book = relationship("Book")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="created")  # created, paid, cancelled
    total = Column(Float, default=0.0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payment = relationship("Payment", back_populates="order", uselist=False)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    book = relationship("Book")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)
    amount = Column(Float, nullable=False)
    status = Column(String(20), default="approved")  # approved, rejected
    created_at = Column(DateTime, server_default=func.now())

    order = relationship("Order", back_populates="payment")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


class SemanticFunction(Base):
    __tablename__ = "semantic_functions"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    examples = Column(JSON, nullable=False)
    embedding = Column(JSON)  # stored as list of floats (combined, for compatibility)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    individual_embeddings = relationship("SemanticFunctionEmbedding", back_populates="function", cascade="all, delete-orphan")


class SemanticFunctionEmbedding(Base):
    __tablename__ = "semantic_function_embeddings"

    id = Column(Integer, primary_key=True)
    function_id = Column(Integer, ForeignKey("semantic_functions.id"), nullable=False)
    text = Column(Text, nullable=False)
    embedding_type = Column(String(20), nullable=False)  # "example" | "description"
    embedding = Column(JSON)  # vector 384 dims

    function = relationship("SemanticFunction", back_populates="individual_embeddings")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    session_id = Column(Integer)
    query = Column(Text)
    matched_function = Column(String(100))
    similarity_score = Column(Float)
    method = Column(String(30))  # semantic, llm_fallback, clarification
    top_candidates = Column(JSON)  # top-3 candidates [{name, score}]
    state_trace = Column(JSON)
    result = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
