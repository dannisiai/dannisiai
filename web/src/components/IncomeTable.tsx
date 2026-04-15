import type { IncomeInfo } from "../lib/api";
import { formatUSD, formatTime } from "../lib/format";

const TYPE_LABELS: Record<string, string> = {
  REALIZED_PNL: "Realized PnL",
  COMMISSION: "Commission",
  FUNDING_FEE: "Funding Fee",
  TRANSFER: "Transfer",
  WELCOME_BONUS: "Bonus",
  INSURANCE_CLEAR: "Insurance",
};

export default function IncomeTable({ income }: { income: IncomeInfo[] }) {
  const filtered = income.filter(
    (i) => i.incomeType === "REALIZED_PNL" || i.incomeType === "FUNDING_FEE"
  );

  if (filtered.length === 0) {
    return (
      <Section title="Recent Activity">
        <p className="py-8 text-center text-sm text-gray-400">
          No recent activity
        </p>
      </Section>
    );
  }

  return (
    <Section title="Recent Activity">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
              <th className="pb-3 pr-4">Time</th>
              <th className="pb-3 pr-4">Type</th>
              <th className="pb-3 pr-4">Symbol</th>
              <th className="pb-3 text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 30).map((item, idx) => {
              const amount = parseFloat(item.income);
              return (
                <tr
                  key={`${item.tranId}-${idx}`}
                  className="border-b border-gray-50 last:border-0"
                >
                  <td className="py-3 pr-4 text-gray-500">
                    {formatTime(item.time)}
                  </td>
                  <td className="py-3 pr-4">
                    <span className="rounded-md bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-600">
                      {TYPE_LABELS[item.incomeType] || item.incomeType}
                    </span>
                  </td>
                  <td className="py-3 pr-4 font-medium text-gray-700">
                    {item.symbol || "—"}
                  </td>
                  <td className="py-3 text-right">
                    <span
                      className={`font-mono font-medium ${
                        amount >= 0 ? "text-orange-500" : "text-red-500"
                      }`}
                    >
                      {amount >= 0 ? "+" : ""}
                      {formatUSD(amount)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6">
      <h2 className="mb-4 text-base font-semibold text-gray-900">{title}</h2>
      {children}
    </div>
  );
}
