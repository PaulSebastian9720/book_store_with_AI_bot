"use client";

import { useState, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Book {
  id: number;
  title: string;
  author: string;
  genre: string;
  price: number;
  stock: number;
  description?: string;
  image_base64?: string;
}

interface BookListProps {
  userId?: number;
}

export default function BookList({ userId }: BookListProps) {
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [selectedBook, setSelectedBook] = useState<Book | null>(null);
  const [addingToCart, setAddingToCart] = useState<number | null>(null);
  const [cartMessage, setCartMessage] = useState<{ id: number; text: string; ok: boolean } | null>(null);

  useEffect(() => {
    fetchBooks();
  }, []);

  const fetchBooks = async () => {
    try {
      const res = await fetch(`${API_BASE}/books`);
      if (!res.ok) throw new Error("Error al cargar libros");
      const data = await res.json();
      setBooks(data);
    } catch {
      setError("No se pudo conectar al servidor. Asegúrate de que el backend está corriendo.");
    } finally {
      setLoading(false);
    }
  };

  const fetchBookDetail = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/books/${id}`);
      const data = await res.json();
      setSelectedBook(data);
    } catch {
      // ignore
    }
  };

  const addToCart = async (bookId: number, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (!userId) return;
    setAddingToCart(bookId);
    try {
      const res = await fetch(`${API_BASE}/cart/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, book_id: bookId, quantity: 1 }),
      });
      const data = await res.json();
      if (data.success) {
        setCartMessage({ id: bookId, text: "Agregado", ok: true });
      } else {
        setCartMessage({ id: bookId, text: data.error || "Error", ok: false });
      }
    } catch {
      setCartMessage({ id: bookId, text: "Error de conexión", ok: false });
    } finally {
      setAddingToCart(null);
      setTimeout(() => setCartMessage(null), 2000);
    }
  };

  const filtered = books.filter(
    (b) =>
      b.title.toLowerCase().includes(search.toLowerCase()) ||
      b.author.toLowerCase().includes(search.toLowerCase()) ||
      b.genre.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-3 border-[var(--primary)] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-10">
        <p className="text-[var(--danger)] text-sm">{error}</p>
        <button
          onClick={() => {
            setError("");
            setLoading(true);
            fetchBooks();
          }}
          className="mt-3 text-sm text-[var(--primary)] hover:underline"
        >
          Reintentar
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Search */}
      <div className="mb-5">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar por título, autor o género..."
          className="w-full px-4 py-2.5 bg-white border border-[var(--border)] rounded-lg text-sm outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-opacity-50 placeholder:text-[var(--muted)]"
        />
      </div>

      <p className="text-xs text-[var(--muted)] mb-3">
        {filtered.length} libro{filtered.length !== 1 ? "s" : ""} encontrado
        {filtered.length !== 1 ? "s" : ""}
      </p>

      {/* Book grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {filtered.map((book) => (
          <div
            key={book.id}
            onClick={() => fetchBookDetail(book.id)}
            className="bg-white border border-[var(--border)] rounded-xl overflow-hidden hover:shadow-lg transition-shadow cursor-pointer group"
          >
            {/* Cover image */}
            <div className="relative bg-gray-50 flex items-center justify-center p-3">
              {book.image_base64 ? (
                <img
                  src={book.image_base64}
                  alt={book.title}
                  className="h-44 w-auto rounded shadow-md group-hover:scale-105 transition-transform"
                />
              ) : (
                <div className="h-44 w-28 bg-gray-200 rounded flex items-center justify-center text-gray-400 text-xs">
                  Sin imagen
                </div>
              )}
              <span
                className={`absolute top-2 right-2 text-[9px] px-1.5 py-0.5 rounded-full font-medium ${
                  book.stock > 0
                    ? "bg-green-100 text-green-700"
                    : "bg-red-100 text-red-700"
                }`}
              >
                {book.stock > 0 ? `${book.stock}` : "0"}
              </span>
            </div>

            {/* Info */}
            <div className="p-3">
              <span className="text-[9px] px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded-full font-medium">
                {book.genre}
              </span>
              <h3 className="font-semibold text-xs leading-tight mt-1.5 line-clamp-2">
                {book.title}
              </h3>
              <p className="text-[10px] text-[var(--muted)] mt-0.5 truncate">{book.author}</p>
              <p className="text-sm font-bold text-[var(--primary)] mt-1.5">
                ${book.price.toFixed(2)}
              </p>
              {userId && book.stock > 0 && (
                <button
                  onClick={(e) => addToCart(book.id, e)}
                  disabled={addingToCart === book.id}
                  className="w-full mt-2 py-1.5 text-[10px] font-medium rounded-lg bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 transition-colors"
                >
                  {addingToCart === book.id
                    ? "..."
                    : cartMessage?.id === book.id
                      ? cartMessage.text
                      : "Agregar al carrito"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Book detail modal */}
      {selectedBook && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedBook(null)}
        >
          <div
            className="bg-white rounded-2xl max-w-lg w-full shadow-xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal top: cover */}
            <div className="bg-gradient-to-br from-gray-50 to-gray-100 flex items-center justify-center py-8">
              {selectedBook.image_base64 ? (
                <img
                  src={selectedBook.image_base64}
                  alt={selectedBook.title}
                  className="h-52 w-auto rounded-lg shadow-lg"
                />
              ) : (
                <div className="h-52 w-36 bg-gray-200 rounded-lg flex items-center justify-center text-gray-400">
                  Sin imagen
                </div>
              )}
            </div>

            {/* Modal body */}
            <div className="p-6">
              <div className="flex justify-between items-start mb-2">
                <span className="text-xs px-2.5 py-1 bg-blue-50 text-blue-600 rounded-full font-medium">
                  {selectedBook.genre}
                </span>
                <button
                  onClick={() => setSelectedBook(null)}
                  className="text-[var(--muted)] hover:text-[var(--foreground)] text-xl leading-none -mt-1"
                >
                  &times;
                </button>
              </div>
              <h2 className="text-xl font-bold mb-1">{selectedBook.title}</h2>
              <p className="text-sm text-[var(--muted)] mb-3">
                por {selectedBook.author}
              </p>
              {selectedBook.description && (
                <p className="text-sm text-gray-600 mb-4 leading-relaxed">
                  {selectedBook.description}
                </p>
              )}
              <div className="flex items-center justify-between">
                <span className="text-2xl font-bold text-[var(--primary)]">
                  ${selectedBook.price.toFixed(2)}
                </span>
                <span
                  className={`text-sm font-medium ${
                    selectedBook.stock > 0
                      ? "text-[var(--success)]"
                      : "text-[var(--danger)]"
                  }`}
                >
                  {selectedBook.stock > 0
                    ? `${selectedBook.stock} disponibles`
                    : "Sin stock"}
                </span>
              </div>
              {userId && selectedBook.stock > 0 && (
                <button
                  onClick={() => addToCart(selectedBook.id)}
                  disabled={addingToCart === selectedBook.id}
                  className="w-full mt-4 py-2.5 text-sm font-medium rounded-xl bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 transition-colors"
                >
                  {addingToCart === selectedBook.id
                    ? "Agregando..."
                    : cartMessage?.id === selectedBook.id
                      ? cartMessage.text
                      : "Agregar al carrito"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
