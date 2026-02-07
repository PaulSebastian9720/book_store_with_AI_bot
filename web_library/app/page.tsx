"use client";

import { useState, useEffect } from "react";
import AuthScreen, { UserData } from "./components/AuthScreen";
import ChatWidget from "./components/ChatBot";
import BookList from "./components/BookList";
import CartView from "./components/CartView";
import OrderList from "./components/OrderList";
import { BookIcon, CartIcon, OrderIcon, BotIcon } from "./components/Icons";

type Tab = "books" | "cart" | "orders";

export default function Home() {
  const [user, setUser] = useState<UserData | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("books");
  const [chatOpen, setChatOpen] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem("bookstore_user");
    if (stored) {
      try {
        setUser(JSON.parse(stored));
      } catch {
        localStorage.removeItem("bookstore_user");
      }
    }
    setChecking(false);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("bookstore_user");
    setUser(null);
    setActiveTab("books");
    setChatOpen(false);
  };

  if (checking) return null;

  if (!user) {
    return <AuthScreen onLogin={setUser} />;
  }

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "books", label: "Libros", icon: <BookIcon size={16} /> },
    { key: "cart", label: "Carrito", icon: <CartIcon size={16} /> },
    { key: "orders", label: "Órdenes", icon: <OrderIcon size={16} /> },
  ];

  return (
    <div className="min-h-screen bg-[var(--background)]">
      {/* Header */}
      <header className="bg-white border-b border-[var(--border)] sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[var(--primary)] flex items-center justify-center text-white text-xs font-bold">
              BS
            </div>
            <h1 className="font-bold text-sm">Bookstore</h1>
          </div>

          {/* Tabs */}
          <nav className="flex gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-4 py-2 text-sm rounded-lg transition-colors flex items-center gap-1.5 ${
                  activeTab === tab.key
                    ? "bg-[var(--primary)] text-white font-medium"
                    : "text-[var(--muted)] hover:bg-gray-100"
                }`}
              >
                {tab.icon}
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
            ))}
          </nav>

          {/* Chat toggle + User menu */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setChatOpen((v) => !v)}
              className={`relative p-2 rounded-lg transition-colors ${
                chatOpen
                  ? "bg-[var(--primary)] text-white"
                  : "text-[var(--muted)] hover:bg-gray-100"
              }`}
              title="Abrir chat"
            >
              <BotIcon size={20} />
            </button>
            <div className="text-right hidden sm:block">
              <p className="text-xs font-medium">{user.name}</p>
              <p className="text-[10px] text-[var(--muted)]">{user.email}</p>
            </div>
            <button
              onClick={handleLogout}
              className="text-xs text-[var(--muted)] hover:text-[var(--danger)] transition-colors"
            >
              Salir
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {activeTab === "books" && (
          <div>
            <div className="mb-4">
              <h2 className="text-lg font-bold">Catálogo</h2>
              <p className="text-xs text-[var(--muted)]">
                Explora nuestro catálogo de libros.
              </p>
            </div>
            <BookList userId={user.id} />
          </div>
        )}

        {activeTab === "cart" && (
          <div className="max-w-lg mx-auto">
            <div className="mb-4">
              <h2 className="text-lg font-bold">Mi Carrito</h2>
            </div>
            <CartView userId={user.id} visible={activeTab === "cart"} />
          </div>
        )}

        {activeTab === "orders" && (
          <div className="max-w-lg mx-auto">
            <div className="mb-4">
              <h2 className="text-lg font-bold">Mis Órdenes</h2>
            </div>
            <OrderList userId={user.id} />
          </div>
        )}
      </main>

      {/* Floating chat widget — always mounted for persistent WebSocket */}
      <ChatWidget
        userId={user.id}
        userName={user.name}
        isOpen={chatOpen}
        onToggle={() => setChatOpen((v) => !v)}
      />
    </div>
  );
}
