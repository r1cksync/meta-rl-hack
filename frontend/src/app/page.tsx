"use client";

import { useQuery } from "@tanstack/react-query";
import { useCartStore } from "@/lib/store";

interface Product {
  product_id: string;
  name: string;
  description: string;
  price: number;
  stock_count: number;
}

async function fetchProducts(): Promise<Product[]> {
  const url = process.env.NEXT_PUBLIC_INVENTORY_API_URL || "http://localhost:4002";
  const res = await fetch(`${url}/products`);
  if (!res.ok) throw new Error("Failed to fetch products");
  return res.json();
}

export default function HomePage() {
  const { data: products, isLoading, error } = useQuery({
    queryKey: ["products"],
    queryFn: fetchProducts,
  });
  const addItem = useCartStore((s) => s.addItem);

  return (
    <div>
      <div className="text-center mb-12">
        <h1 className="text-5xl font-display font-bold text-gold-400 mb-4">
          Premium Collection
        </h1>
        <p className="text-gray-400 text-lg max-w-2xl mx-auto">
          Discover our curated selection of premium products, crafted for the discerning buyer.
        </p>
      </div>

      {isLoading && (
        <div className="text-center py-20">
          <div className="animate-pulse text-gold-400 text-lg">Loading products...</div>
        </div>
      )}

      {error && (
        <div className="card text-center py-12 border-red-500/30">
          <p className="text-red-400">Failed to load products. Backend may be unavailable.</p>
          <p className="text-gray-500 text-sm mt-2">{String(error)}</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {products?.map((product) => (
          <div key={product.product_id} className="card group hover:border-gold-500/30 transition-all duration-300">
            <div className="h-48 bg-navy-800 rounded-lg mb-4 flex items-center justify-center">
              <span className="text-4xl">📦</span>
            </div>
            <h3 className="font-display text-lg font-semibold text-gray-100 mb-1">
              <a href={`/product/${product.product_id}`} className="hover:text-gold-400 transition-colors">
                {product.name}
              </a>
            </h3>
            <p className="text-gray-400 text-sm mb-3 line-clamp-2">{product.description}</p>
            <div className="flex items-center justify-between mt-auto">
              <span className="text-gold-400 font-display text-xl font-bold">
                ${product.price.toFixed(2)}
              </span>
              {product.stock_count > 0 ? (
                <button
                  onClick={() => addItem({ ...product, quantity: 1 })}
                  className="btn-primary text-sm py-1.5 px-4"
                >
                  Add to Cart
                </button>
              ) : (
                <span className="badge-red">Out of Stock</span>
              )}
            </div>
            <div className="mt-2 text-xs text-gray-500">
              {product.stock_count > 0 ? `${product.stock_count} in stock` : "Sold out"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
