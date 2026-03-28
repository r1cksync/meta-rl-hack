"use client";

import { useCartStore } from "@/lib/store";

export default function CartPage() {
  const items = useCartStore((s) => s.items);
  const removeItem = useCartStore((s) => s.removeItem);
  const updateQuantity = useCartStore((s) => s.updateQuantity);
  const total = useCartStore((s) => s.total);

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="font-display text-4xl font-bold text-gold-400 mb-8">Your Cart</h1>

      {items.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg mb-4">Your cart is empty</p>
          <a href="/" className="btn-primary">Start Shopping</a>
        </div>
      ) : (
        <>
          <div className="space-y-4">
            {items.map((item) => (
              <div key={item.product_id} className="card flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div className="w-16 h-16 bg-navy-800 rounded-lg flex items-center justify-center">
                    <span className="text-2xl">📦</span>
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-100">{item.name}</h3>
                    <p className="text-gold-400 font-display">${item.price.toFixed(2)}</p>
                  </div>
                </div>
                <div className="flex items-center space-x-4">
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => updateQuantity(item.product_id, item.quantity - 1)}
                      className="w-8 h-8 rounded-lg bg-navy-800 text-gray-300 hover:bg-navy-700"
                    >
                      −
                    </button>
                    <span className="w-8 text-center font-medium">{item.quantity}</span>
                    <button
                      onClick={() => updateQuantity(item.product_id, item.quantity + 1)}
                      className="w-8 h-8 rounded-lg bg-navy-800 text-gray-300 hover:bg-navy-700"
                    >
                      +
                    </button>
                  </div>
                  <span className="text-gold-300 font-display font-bold w-24 text-right">
                    ${(item.price * item.quantity).toFixed(2)}
                  </span>
                  <button
                    onClick={() => removeItem(item.product_id)}
                    className="text-red-400 hover:text-red-300 text-sm"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="card mt-6">
            <div className="flex items-center justify-between mb-6">
              <span className="text-lg text-gray-300">Subtotal</span>
              <span className="text-2xl font-display font-bold text-gold-400">
                ${total().toFixed(2)}
              </span>
            </div>
            <a href="/checkout" className="btn-primary block text-center w-full text-lg py-3">
              Proceed to Checkout
            </a>
          </div>
        </>
      )}
    </div>
  );
}
