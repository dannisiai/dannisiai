export function formatUSD(value: number | string): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(n)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatNumber(value: number | string, decimals = 2): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(n)) return "0";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

export function formatPercent(value: number | string): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(n)) return "0.00%";
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(2)}%`;
}

export function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTimeShort(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function timeAgo(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
