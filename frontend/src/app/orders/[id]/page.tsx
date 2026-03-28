"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";

interface Order {
  order_id: string;
  status: string;
  total_amount: number;
  customer_name?: string;
  items?: { product_id: string; quantity: number; unit_price: number }[];
}

async function fetchOrder(id: string): Promise<Order> {
  const url = process.env.NEXT_PUBLIC_PAYMENTS_API_URL || "http://localhost:4001";
  const res = await fetch(`${url}/orders/${id}`);
  if (!res.ok) throw new Error("Order not found");
  return res.json();
}

export default function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: order, isLoading, error } = useQuery({
    queryKey: ["order", id],
    queryFn: () => fetchOrder(id),
  });

  if (isLoading) return <div className="text-center py-20 text-gold-400">Loading order...</div>;
  if (error || !order) {
    return (
      <div className="card text-center py-12 max-w-lg mx-auto">
        <h2 className="text-xl text-red-400 mb-2">Order Not Found</h2>
        <a href="/" className="text-gold-400 hover:underline">← Continue Shopping</a>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="text-center mb-8">
        <div className="text-5xl mb-4">✅</div>
        <h1 className="font-display text-4xl font-bold text-gold-400 mb-2">Order Confirmed!</h1>
        <p className="text-gray-400">Thank you for your purchase</p>
      </div>

      <div className="card">
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div>
            <p className="text-sm text-gray-500">Order ID</p>
            <p className="text-gray-200 font-mono text-sm">{order.order_id}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Status</p>
            <span className={order.status === "FULFILLED" ? "badge-green" : "badge-yellow"}>
              {order.status}
            </span>
          </div>
          <div>
            <p className="text-sm text-gray-500">Total</p>
            <p className="text-gold-400 font-display font-bold text-xl">
              ${Number(order.total_amount).toFixed(2)}
            </p>
          </div>
        </div>

        {order.items && order.items.length > 0 && (
          <div>
            <h3 className="text-sm text-gray-500 mb-2">Items</h3>
            {order.items.map((item, idx) => (
              <div key={idx} className="flex justify-between py-2 border-b border-navy-700/50 last:border-0">
                <span className="text-gray-300">{item.product_id} × {item.quantity}</span>
                <span className="text-gold-400">${(item.quantity * item.unit_price).toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="text-center mt-8">
        <a href="/" className="btn-secondary">Continue Shopping</a>
      </div>
    </div>
  );
}
