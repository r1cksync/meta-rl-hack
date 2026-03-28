"use client";

import { useQuery } from "@tanstack/react-query";

interface ServiceHealth {
  name: string;
  status: "ok" | "error";
  details?: Record<string, string>;
}

async function fetchHealth(): Promise<ServiceHealth[]> {
  const res = await fetch("/api/health-aggregate");
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export default function HealthPage() {
  const { data: services, isLoading, error, refetch } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 10_000,
  });

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="font-display text-4xl font-bold text-gold-400 mb-2">System Status</h1>
      <p className="text-gray-400 mb-8">Real-time health of all AcmeCorp backend services</p>

      {isLoading && <p className="text-gold-400">Checking services...</p>}
      {error && <p className="text-red-400">Failed to fetch health status</p>}

      <div className="space-y-3">
        {services?.map((svc) => (
          <div key={svc.name} className="card flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <div className={`w-3 h-3 rounded-full ${svc.status === "ok" ? "bg-emerald-400" : "bg-red-400"}`} />
              <span className="text-gray-200 font-medium">{svc.name}</span>
            </div>
            <span className={svc.status === "ok" ? "badge-green" : "badge-red"}>
              {svc.status === "ok" ? "Healthy" : "Unhealthy"}
            </span>
          </div>
        ))}
      </div>

      <button onClick={() => refetch()} className="btn-secondary mt-6">
        Refresh Status
      </button>
    </div>
  );
}
