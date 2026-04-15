import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { IncomeInfo } from "../lib/api";

export default function PnlChart({ income }: { income: IncomeInfo[] }) {
  const pnlEntries = income
    .filter((i) => i.incomeType === "REALIZED_PNL")
    .sort((a, b) => a.time - b.time);

  if (pnlEntries.length < 2) {
    return (
      <div className="rounded-2xl border border-gray-100 bg-white p-6">
        <h2 className="mb-4 text-base font-semibold text-gray-900">
          Cumulative PnL
        </h2>
        <p className="py-12 text-center text-sm text-gray-400">
          Not enough data to display chart
        </p>
      </div>
    );
  }

  let cumulative = 0;
  const data = pnlEntries.map((entry) => {
    cumulative += parseFloat(entry.income);
    return {
      time: new Date(entry.time).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
      pnl: parseFloat(cumulative.toFixed(2)),
    };
  });

  const isPositive = cumulative >= 0;

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">
          Cumulative PnL
        </h2>
        <span
          className={`text-lg font-semibold ${
            isPositive ? "text-orange-500" : "text-red-500"
          }`}
        >
          {isPositive ? "+" : ""}${cumulative.toFixed(2)}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor={isPositive ? "#f97316" : "#ef4444"}
                stopOpacity={0.12}
              />
              <stop
                offset="100%"
                stopColor={isPositive ? "#f97316" : "#ef4444"}
                stopOpacity={0}
              />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#f3f4f6"
            vertical={false}
          />
          <XAxis
            dataKey="time"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#9ca3af", fontSize: 12 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#9ca3af", fontSize: 12 }}
            tickFormatter={(v: number) => `$${v}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#fff",
              border: "1px solid #e5e7eb",
              borderRadius: "12px",
              boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.05)",
              padding: "8px 12px",
            }}
            formatter={(value) => [`$${Number(value).toFixed(2)}`, "PnL"]}
          />
          <Area
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? "#f97316" : "#ef4444"}
            strokeWidth={2}
            fill="url(#pnlGrad)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
