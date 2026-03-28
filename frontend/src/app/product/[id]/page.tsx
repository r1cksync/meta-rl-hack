"use client";

import { useQuery } from "@tanstack/react-query";
import { useCartStore } from "@/lib/store";
import { use } from "react";

interface Product {
  product_id: string;
  name: string;
  description: string;
  price: number;
  stock_count: number;
}

async function fetchProduct(id: string): Promise<Product> {
  const url = process.env.NEXT_PUBLIC_INVENTORY_API_URL || "http://localhost:4002";
  const res = await fetch(`${url}/products/${id}`);
  if (!res.ok) throw new Error("Product not found");
  return res.json();
}

export default function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: product, isLoading, error } = useQuery({
    queryKey: ["product", id],
    queryFn: () => fetchProduct(id),
  });
  const addItem = useCartStore((s) => s.addItem);

  if (isLoading) return <div className="text-center py-20 text-gold-400">Loading...</div>;
  if (error || !product) {
    return (
      <div className="card text-center py-12 max-w-lg mx-auto">
        <h2 className="text-xl text-red-400 mb-2">Product Not Found</h2>
        <a href="/" className="text-gold-400 hover:underline">← Back to shop</a>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <a href="/" className="text-gold-400 hover:underline text-sm mb-6 block">← Back to shop</a>
      <div className="card grid md:grid-cols-2 gap-8">
        <div className="h-80 bg-navy-800 rounded-lg flex items-center justify-center">
          <span className="text-6xl">📦</span>
        </div>
        <div>
          <h1 className="font-display text-3xl font-bold text-gold-400 mb-2">{product.name}</h1>
          <p className="text-gray-400 mb-6">{product.description}</p>
          <div className="text-3xl font-display font-bold text-gold-300 mb-4">
            ${product.price.toFixed(2)}
          </div>
          <div className="mb-6">
            {product.stock_count > 0 ? (
              <span className="badge-green">In Stock ({product.stock_count} available)</span>
            ) : (
              <span className="badge-red">Out of Stock</span>
            )}
          </div>
          {product.stock_count > 0 && (
            <button
              onClick={() => {
                addItem({ product_id: product.product_id, name: product.name, price: product.price, quantity: 1 });
              }}
              className="btn-primary w-full text-lg py-3"
            >
              Add to Cart
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
