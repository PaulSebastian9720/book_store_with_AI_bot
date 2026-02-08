"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { BotIcon, UserIcon, SendIcon, CloseIcon } from "./Icons";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

interface BookCard {
  id: number;
  title: string;
  author?: string;
  price?: number;
  image_base64?: string;
}

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  books?: BookCard[];
  timestamp?: number;
}

interface ChatWidgetProps {
  userId: number;
  userName: string;
  isOpen: boolean;
  onToggle: () => void;
}

const STORAGE_KEY = "bookstore_chat_history";

function loadHistory(userId: number): ChatMessage[] {
  try {
    const raw = localStorage.getItem(`${STORAGE_KEY}_${userId}`);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch {
    // ignore
  }
  return [];
}

function saveHistory(userId: number, messages: ChatMessage[]) {
  try {
    const toSave = messages.filter((m) => m.content !== "...").slice(-100);
    localStorage.setItem(`${STORAGE_KEY}_${userId}`, JSON.stringify(toSave));
  } catch {
    // ignore
  }
}

export default function ChatWidget({ userId, userName, isOpen, onToggle }: ChatWidgetProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    const history = loadHistory(userId);
    if (history.length > 0) return history;
    return [
      {
        id: 0,
        role: "assistant" as const,
        content: `Hola ${userName}! Soy tu asistente de la librería. Puedo ayudarte a buscar libros, darte recomendaciones, agregar al carrito y más. ¿Qué necesitas?`,
        timestamp: Date.now(),
      },
    ];
  });
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const msgIdRef = useRef(
    Math.max(...(loadHistory(userId).map((m) => m.id)), 0) + 1
  );

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Focus input when panel opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 300);
    }
  }, [isOpen]);

  useEffect(() => {
    saveHistory(userId, messages);
  }, [messages, userId]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setConnecting(true);

    const ws = new WebSocket(`${WS_BASE}/ws/chat?user_id=${userId}`);

    ws.onopen = () => {
      setConnected(true);
      setConnecting(false);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const msg: ChatMessage = {
          id: msgIdRef.current++,
          role: "assistant",
          content: data.response || "Sin respuesta",
          books: data.books || undefined,
          timestamp: Date.now(),
        };
        setMessages((prev) => prev.filter((m) => m.content !== "...").concat(msg));
      } catch {
        setMessages((prev) =>
          prev.filter((m) => m.content !== "...").concat({
            id: msgIdRef.current++,
            role: "assistant",
            content: event.data,
            timestamp: Date.now(),
          })
        );
      }
    };

    ws.onclose = () => {
      setConnected(false);
      setConnecting(false);
    };

    ws.onerror = () => {
      setConnected(false);
      setConnecting(false);
    };

    wsRef.current = ws;
  }, [userId]);

  // Connect on mount, keep alive regardless of panel state
  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = (text?: string) => {
    const msg = (text || input).trim();
    if (!msg || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const userMsg: ChatMessage = {
      id: msgIdRef.current++,
      role: "user",
      content: msg,
      timestamp: Date.now(),
    };

    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: msgIdRef.current++, role: "assistant", content: "..." },
    ]);
    setInput("");

    wsRef.current.send(JSON.stringify({ message: msg }));
  };

  const clearHistory = () => {
    const welcome: ChatMessage = {
      id: msgIdRef.current++,
      role: "assistant",
      content: `Historial limpiado. ¿En qué puedo ayudarte, ${userName}?`,
      timestamp: Date.now(),
    };
    setMessages([welcome]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const quickActions = [
    { label: "Ver catálogo", query: "Buscar libros disponibles" },
    { label: "Recomendaciones", query: "Recomiéndame un buen libro" },
    { label: "Mi carrito", query: "Ver mi carrito" },
    { label: "Checkout", query: "Hacer checkout de mi carrito" },
    { label: "Mi pedido", query: "Estado de mi pedido" },
    { label: "Pagar", query: "Procesar pago de mi orden" },
  ];

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-40 sm:hidden"
          onClick={onToggle}
        />
      )}

      {/* Chat panel */}
      <div
        className={`fixed top-0 right-0 h-full w-full sm:w-[400px] z-50 flex flex-col bg-white shadow-2xl transition-transform duration-300 ease-in-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)] bg-[var(--primary)] text-white">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center">
              <BotIcon size={18} />
            </div>
            <div>
              <h3 className="font-semibold text-sm">Asistente Bookstore</h3>
              <p className="text-[11px] text-white/70">
                {connected ? "En línea" : connecting ? "Conectando..." : "Sin conexión"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                connected ? "bg-green-300" : "bg-red-300"
              }`}
            />
            {!connected && !connecting && (
              <button
                onClick={connect}
                className="text-[11px] text-white/80 hover:text-white underline"
              >
                Reconectar
              </button>
            )}
            <button
              onClick={clearHistory}
              className="text-[11px] text-white/70 hover:text-white ml-1"
            >
              Limpiar
            </button>
            <button
              onClick={onToggle}
              className="ml-1 p-1 rounded hover:bg-white/20 transition-colors"
            >
              <CloseIcon size={18} />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 chat-scroll">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-2 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "assistant" && (
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[var(--primary)] flex items-center justify-center text-white mt-0.5">
                  <BotIcon size={14} />
                </div>
              )}
              <div
                className={`max-w-[80%] rounded-2xl text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-[var(--primary)] text-white rounded-br-md px-4 py-2.5"
                    : "bg-[var(--chat-bot)] text-[var(--foreground)] rounded-bl-md px-4 py-2.5"
                }`}
              >
                {msg.content === "..." ? (
                  <span className="flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-[var(--muted)] rounded-full animate-bounce" />
                    <span
                      className="w-1.5 h-1.5 bg-[var(--muted)] rounded-full animate-bounce"
                      style={{ animationDelay: "0.1s" }}
                    />
                    <span
                      className="w-1.5 h-1.5 bg-[var(--muted)] rounded-full animate-bounce"
                      style={{ animationDelay: "0.2s" }}
                    />
                  </span>
                ) : (
                  <>
                    <p className="whitespace-pre-wrap">{msg.content}</p>

                    {msg.books && msg.books.length > 0 && (
                      <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
                        {msg.books.map((book) => (
                          <div
                            key={book.id}
                            className="flex-shrink-0 w-28 bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm"
                          >
                            {book.image_base64 && (
                              <img
                                src={book.image_base64}
                                alt={book.title}
                                className="w-full h-36 object-cover"
                              />
                            )}
                            <div className="p-2">
                              <p className="text-[10px] font-semibold text-gray-800 leading-tight line-clamp-2">
                                {book.title}
                              </p>
                              {book.author && (
                                <p className="text-[9px] text-gray-500 mt-0.5 truncate">
                                  {book.author}
                                </p>
                              )}
                              {book.price != null && (
                                <p className="text-[10px] font-bold text-[#2563eb] mt-1">
                                  ${book.price.toFixed(2)}
                                </p>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
              {msg.role === "user" && (
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center text-gray-600 mt-0.5">
                  <UserIcon size={14} />
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick actions */}
        <div className="px-4 py-2 border-t border-[var(--border)] flex gap-2 overflow-x-auto">
          {quickActions.map((action) => (
            <button
              key={action.label}
              onClick={() => sendMessage(action.query)}
              disabled={!connected}
              className="whitespace-nowrap px-3 py-1 text-xs rounded-full border border-[var(--border)] text-[var(--muted)] hover:border-[var(--primary)] hover:text-[var(--primary)] disabled:opacity-40 transition-colors"
            >
              {action.label}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="p-3 border-t border-[var(--border)]">
          <div className="flex gap-2 items-center">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                connected ? "Escribe tu mensaje..." : "Conectando al servidor..."
              }
              disabled={!connected}
              className="flex-1 px-4 py-2.5 bg-[var(--chat-bot)] rounded-full text-sm outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-opacity-50 disabled:opacity-50 placeholder:text-[var(--muted)]"
            />
            <button
              onClick={() => sendMessage()}
              disabled={!connected || !input.trim()}
              className="w-10 h-10 flex items-center justify-center bg-[var(--primary)] text-white rounded-full hover:bg-[var(--primary-hover)] disabled:opacity-40 transition-colors flex-shrink-0"
            >
              <SendIcon size={16} />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
