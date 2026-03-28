"use client";

import { useState } from "react";
import { useCartStore } from "@/lib/store";
import { useRouter } from "next/navigation";

export default function CheckoutPage() {
  const items = useCartStore((s) => s.items);
  const total = useCartStore((s) => s.total);
  const clearCart = useCartStore((s) => s.clearCart);
  const router = useRouter();

  const [form, setForm] = useState({ name: "", email: "", address: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (items.length === 0) {
    return (
      <div className="card text-center py-12 max-w-lg mx-auto">
        <p className="text-gray-400 mb-4">Nothing to checkout</p>
        <a href="/" className="btn-primary">Browse Products</a>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError("");

    try {
      const url = process.env.NEXT_PUBLIC_PAYMENTS_API_URL || "http://localhost:4001";
      const res = await fetch(`${url}/orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_name: form.name,
          customer_email: form.email,
          items: items.map((i) => ({
            product_id: i.product_id,
            quantity: i.quantity,
            unit_price: i.price,
          })),
        }),
      });

      if (!res.ok) throw new Error("Order submission failed");
      const data = await res.json();
      clearCart();
      router.push(`/orders/${data.order_id}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="font-display text-4xl font-bold text-gold-400 mb-8">Checkout</h1>

      <div className="card mb-6">
        <h2 className="font-display text-xl font-semibold text-gray-100 mb-4">Order Summary</h2>
        {items.map((item) => (
          <div key={item.product_id} className="flex justify-between py-2 border-b border-navy-700/50 last:border-0">
            <span className="text-gray-300">{item.name} × {item.quantity}</span>
            <span className="text-gold-400">${(item.price * item.quantity).toFixed(2)}</span>
          </div>
        ))}
        <div className="flex justify-between pt-4 mt-2 border-t border-gold-500/20">
          <span className="text-lg font-semibold">Total</span>
          <span className="text-xl font-display font-bold text-gold-400">
            ${total().toFixed(2)}
          </span>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="card space-y-4">
        <h2 className="font-display text-xl font-semibold text-gray-100 mb-2">Shipping Details</h2>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Full Name</label>
          <input
            type="text"
            required
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="w-full bg-navy-800 border border-navy-600 rounded-lg px-4 py-2 text-gray-100 focus:outline-none focus:border-gold-500"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Email</label>
          <input
            type="email"
            required
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            className="w-full bg-navy-800 border border-navy-600 rounded-lg px-4 py-2 text-gray-100 focus:outline-none focus:border-gold-500"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Shipping Address</label>
          <textarea
            required
            value={form.address}
            onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
            rows={3}
            className="w-full bg-navy-800 border border-navy-600 rounded-lg px-4 py-2 text-gray-100 focus:outline-none focus:border-gold-500"
          />
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button type="submit" disabled={submitting} className="btn-primary w-full text-lg py-3 disabled:opacity-50">
          {submitting ? "Processing..." : "Place Order"}
        </button>
      </form>
    </div>
  );
}
