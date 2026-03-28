import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "AcmeCorp — Premium Online Retailer",
  description: "Shop premium products at AcmeCorp",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <nav className="border-b border-navy-700/50 bg-navy-900/80 backdrop-blur-sm sticky top-0 z-50">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex items-center justify-between h-16">
                <a href="/" className="font-display text-2xl font-bold text-gold-400 tracking-wide">
                  AcmeCorp
                </a>
                <div className="flex items-center space-x-8">
                  <a href="/" className="text-gray-300 hover:text-gold-400 transition-colors font-medium">
                    Shop
                  </a>
                  <a href="/cart" className="text-gray-300 hover:text-gold-400 transition-colors font-medium">
                    Cart
                  </a>
                  <a href="/health" className="text-gray-300 hover:text-gold-400 transition-colors font-medium text-sm">
                    System Status
                  </a>
                </div>
              </div>
            </div>
          </nav>
          <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {children}
          </main>
          <footer className="border-t border-navy-700/50 mt-16 py-8 text-center text-gray-500 text-sm">
            © 2026 AcmeCorp. Premium retail experience.
          </footer>
        </Providers>
      </body>
    </html>
  );
}
