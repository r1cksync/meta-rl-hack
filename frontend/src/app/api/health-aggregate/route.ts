import { NextResponse } from "next/server";

const SERVICES = [
  { name: "payments-api", url: process.env.NEXT_PUBLIC_PAYMENTS_API_URL || "http://localhost:4001" },
  { name: "inventory-service", url: process.env.NEXT_PUBLIC_INVENTORY_API_URL || "http://localhost:4002" },
  { name: "notification-service", url: process.env.NEXT_PUBLIC_NOTIFICATION_SERVICE_URL || "http://localhost:4003" },
];

export async function GET() {
  const results = await Promise.all(
    SERVICES.map(async (svc) => {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        const res = await fetch(`${svc.url}/health`, { signal: controller.signal });
        clearTimeout(timeout);
        const data = await res.json().catch(() => ({}));
        return {
          name: svc.name,
          status: res.ok ? "ok" as const : "error" as const,
          details: data,
        };
      } catch {
        return { name: svc.name, status: "error" as const, details: {} };
      }
    })
  );

  return NextResponse.json(results);
}
