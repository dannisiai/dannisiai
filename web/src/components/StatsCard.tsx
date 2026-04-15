import type { IncomeInfo } from "../lib/api";
import { formatUSD } from "../lib/format";

export default function StatsCard({ income }: { income: IncomeInfo[] }) {
  const pnlEntries = income.filter((i) => i.incomeType === "REALIZED_PNL");
  const totalPnl = pnlEntries.reduce(
    (sum, i) => sum + parseFloat(i.income),
    0
  );
  const wins = pnlEntries.filter((i) => parseFloat(i.income) > 0).length;
  const winRate =
    pnlEntries.length > 0 ? ((wins / pnlEntries.length) * 100).toFixed(1) : "—";

  const totalFees = income
    .filter((i) => i.incomeType === "COMMISSION")
    .reduce((sum, i) => sum + parseFloat(i.income), 0);

  const fundingIncome = income
    .filter((i) => i.incomeType === "FUNDING_FEE")
    .reduce((sum, i) => sum + parseFloat(i.income), 0);

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <StatItem
        label="Realized PnL"
        value={formatUSD(totalPnl)}
        positive={totalPnl >= 0}
      />
      <StatItem label="Win Rate" value={`${winRate}%`} neutral />
      <StatItem
        label="Fees Paid"
        value={formatUSD(Math.abs(totalFees))}
        neutral
      />
      <StatItem
        label="Funding Income"
        value={formatUSD(fundingIncome)}
        positive={fundingIncome >= 0}
      />
    </div>
  );
}

function StatItem({
  label,
  value,
  positive,
  neutral,
}: {
  label: string;
  value: string;
  positive?: boolean;
  neutral?: boolean;
}) {
  let color = "text-gray-900";
  if (!neutral) {
    color = positive ? "text-orange-500" : "text-red-500";
  }

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-5">
      <p className="text-sm font-medium text-gray-400">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${color}`}>{value}</p>
    </div>
  );
}
