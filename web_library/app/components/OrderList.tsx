"use client";

import { useState, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface OrderSummary {
  id: number;
  status: string;
  total: number;
  created_at: string;
}

interface OrderDetail {
  id: number;
  status: string;
  total: number;
  items: {
    book_id: number;
    title: string;
    quantity: number;
    unit_price: number;
    image_base64?: string;
  }[];
  created_at: string;
}

const STATUS_STYLES: Record<string, string> = {
  created: "bg-yellow-50 text-yellow-700",
  paid: "bg-green-50 text-green-700",
  cancelled: "bg-red-50 text-red-700",
};

interface OrderListProps {
  userId: number;
}

export default function OrderList({ userId }: OrderListProps) {
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedOrder, setSelectedOrder] = useState<OrderDetail | null>(null);

  useEffect(() => {
    fetchOrders();
  }, []);

  const fetchOrders = async () => {
    try {
      const res = await fetch(`${API_BASE}/orders?user_id=${userId}`);
      const data = await res.json();
      setOrders(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const fetchOrderDetail = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/orders/${id}`);
      const data = await res.json();
      setSelectedOrder(data);
    } catch {
      // ignore
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-3 border-[var(--primary)] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (orders.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-4xl mb-3">&#128230;</p>
        <p className="text-[var(--muted)] text-sm">No tienes órdenes</p>
        <p className="text-xs text-[var(--muted)] mt-2">
          Agrega libros al carrito y haz checkout desde el chat
        </p>
        <button
          onClick={fetchOrders}
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
          Órdenes ({orders.length})
        </h3>
        <button
          onClick={fetchOrders}
          className="text-xs text-[var(--primary)] hover:underline"
        >
          Actualizar
        </button>
      </div>

      <div className="space-y-3">
        {orders.map((order) => (
          <div
            key={order.id}
            onClick={() => fetchOrderDetail(order.id)}
            className="bg-white border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:shadow-md transition-shadow"
          >
            <div className="flex justify-between items-center">
              <div>
                <p className="font-medium text-sm">Orden #{order.id}</p>
                <p className="text-xs text-[var(--muted)]">
                  {new Date(order.created_at).toLocaleString("es")}
                </p>
              </div>
              <div className="text-right">
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                    STATUS_STYLES[order.status] || "bg-gray-50 text-gray-600"
                  }`}
                >
                  {order.status}
                </span>
                <p className="font-bold text-sm text-[var(--primary)] mt-1">
                  ${order.total.toFixed(2)}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Order detail modal */}
      {selectedOrder && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedOrder(null)}
        >
          <div
            className="bg-white rounded-2xl p-6 max-w-md w-full shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-start mb-4">
              <div>
                <h2 className="text-lg font-bold">Orden #{selectedOrder.id}</h2>
                <span
                  className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                    STATUS_STYLES[selectedOrder.status] || "bg-gray-50 text-gray-600"
                  }`}
                >
                  {selectedOrder.status}
                </span>
              </div>
              <button
                onClick={() => setSelectedOrder(null)}
                className="text-[var(--muted)] hover:text-[var(--foreground)] text-lg leading-none"
              >
                &times;
              </button>
            </div>

            <div className="space-y-2 mb-4">
              {selectedOrder.items.map((item, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 py-2 border-b border-[var(--border)] last:border-0"
                >
                  {/* Thumbnail */}
                  {item.image_base64 ? (
                    <img
                      src={item.image_base64}
                      alt={item.title}
                      className="w-10 h-14 rounded object-cover shadow-sm flex-shrink-0"
                    />
                  ) : (
                    <div className="w-10 h-14 rounded bg-gray-100 flex-shrink-0" />
                  )}

                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm truncate">{item.title}</p>
                    <p className="text-xs text-[var(--muted)]">
                      {item.quantity} x ${item.unit_price.toFixed(2)}
                    </p>
                  </div>
                  <span className="font-medium text-sm flex-shrink-0">
                    ${(item.quantity * item.unit_price).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>

            <div className="flex justify-between items-center pt-3 border-t border-[var(--border)]">
              <span className="text-sm text-[var(--muted)]">Total</span>
              <span className="text-xl font-bold text-[var(--primary)]">
                ${selectedOrder.total.toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
