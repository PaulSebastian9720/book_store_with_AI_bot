"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface CartItem {
  book_id: number;
  title: string;
  quantity: number;
  unit_price: number;
  subtotal: number;
  image_base64?: string;
}

interface CartData {
  cart_id?: number;
  items: CartItem[];
  total: number;
}

interface CartViewProps {
  userId: number;
  visible?: boolean;
}

export default function CartView({ userId, visible }: CartViewProps) {
  const [cart, setCart] = useState<CartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState<number | null>(null);

  const fetchCart = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/cart?user_id=${userId}`);
      const data = await res.json();
      setCart(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    fetchCart();
  }, [fetchCart]);

  // Auto-refresh when tab becomes visible
  useEffect(() => {
    if (visible) {
      fetchCart();
    }
  }, [visible, fetchCart]);

  const updateQuantity = async (bookId: number, delta: number) => {
    if (!cart) return;
    const item = cart.items.find((i) => i.book_id === bookId);
    if (!item) return;

    const newQty = item.quantity + delta;
    setUpdating(bookId);
    try {
      await fetch(`${API_BASE}/cart/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, book_id: bookId, quantity: newQty }),
      });
      await fetchCart();
    } catch {
      // ignore
    } finally {
      setUpdating(null);
    }
  };

  const removeItem = async (bookId: number) => {
    setUpdating(bookId);
    try {
      await fetch(`${API_BASE}/cart/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, book_id: bookId }),
      });
      await fetchCart();
    } catch {
      // ignore
    } finally {
      setUpdating(null);
    }
  };

  const sendCheckout = () => {
    // We'll simulate sending "checkout" via a simple approach
    // The user can also type it in the chat
    window.dispatchEvent(new CustomEvent("bookstore:chat-send", { detail: "quiero hacer checkout" }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-3 border-[var(--primary)] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!cart || cart.items.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-4xl mb-3">&#128722;</p>
        <p className="text-[var(--muted)] text-sm">Tu carrito está vacío</p>
        <p className="text-xs text-[var(--muted)] mt-2">
          Usa el chat o el catálogo para agregar libros
        </p>
        <button
          onClick={fetchCart}
          className="mt-4 text-sm text-[var(--primary)] hover:underline"
        >
          Actualizar
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-sm">
          Carrito ({cart.items.length} item{cart.items.length !== 1 ? "s" : ""})
        </h3>
        <button
          onClick={fetchCart}
          className="text-xs text-[var(--primary)] hover:underline"
        >
          Actualizar
        </button>
      </div>

      <div className="space-y-3">
        {cart.items.map((item) => (
          <div
            key={item.book_id}
            className="bg-white border border-[var(--border)] rounded-xl p-3 flex items-center gap-3"
          >
            {/* Thumbnail */}
            {item.image_base64 ? (
              <img
                src={item.image_base64}
                alt={item.title}
                className="w-12 h-16 rounded object-cover shadow-sm flex-shrink-0"
              />
            ) : (
              <div className="w-12 h-16 rounded bg-gray-100 flex-shrink-0" />
            )}

            <div className="flex-1 min-w-0">
              <h4 className="font-medium text-sm truncate">{item.title}</h4>
              <p className="text-xs text-[var(--muted)]">
                ${item.unit_price.toFixed(2)} c/u
              </p>

              {/* Quantity controls */}
              <div className="flex items-center gap-2 mt-1.5">
                <button
                  onClick={() => updateQuantity(item.book_id, -1)}
                  disabled={updating === item.book_id}
                  className="w-6 h-6 flex items-center justify-center rounded-md border border-[var(--border)] text-xs hover:bg-gray-50 disabled:opacity-40"
                >
                  -
                </button>
                <span className="text-sm font-medium min-w-[1.5rem] text-center">
                  {item.quantity}
                </span>
                <button
                  onClick={() => updateQuantity(item.book_id, 1)}
                  disabled={updating === item.book_id}
                  className="w-6 h-6 flex items-center justify-center rounded-md border border-[var(--border)] text-xs hover:bg-gray-50 disabled:opacity-40"
                >
                  +
                </button>
              </div>
            </div>

            <div className="flex flex-col items-end gap-1.5">
              <span className="font-bold text-sm text-[var(--primary)]">
                ${item.subtotal.toFixed(2)}
              </span>
              <button
                onClick={() => removeItem(item.book_id)}
                disabled={updating === item.book_id}
                className="text-[10px] text-[var(--danger)] hover:underline disabled:opacity-40"
              >
                Eliminar
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 pt-4 border-t border-[var(--border)] flex justify-between items-center">
        <span className="text-sm text-[var(--muted)]">Total</span>
        <span className="text-xl font-bold text-[var(--primary)]">
          ${cart.total.toFixed(2)}
        </span>
      </div>

      <button
        onClick={sendCheckout}
        className="w-full mt-4 py-2.5 text-sm font-medium rounded-xl bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-colors"
      >
        Hacer checkout
      </button>
    </div>
  );
}
