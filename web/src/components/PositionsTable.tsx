import type { PositionInfo } from "../lib/api";
import { formatUSD, formatNumber } from "../lib/format";

export default function PositionsTable({
  positions,
}: {
  positions: PositionInfo[];
}) {
  if (positions.length === 0) {
    return (
      <Section title="Open Positions">
        <p className="py-8 text-center text-sm text-gray-400">
          No open positions
        </p>
      </Section>
    );
  }

  return (
    <Section title="Open Positions">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
              <th className="pb-3 pr-4">Symbol</th>
              <th className="pb-3 pr-4">Side</th>
              <th className="pb-3 pr-4 text-right">Size</th>
              <th className="pb-3 pr-4 text-right">Entry</th>
              <th className="pb-3 pr-4 text-right">Mark</th>
              <th className="pb-3 pr-4 text-right">PnL</th>
              <th className="pb-3 text-right">Leverage</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const amt = parseFloat(p.positionAmt);
              const pnl = parseFloat(p.unRealizedProfit);
              const entry = parseFloat(p.entryPrice);
              const mark = parseFloat(p.markPrice);
              const pnlPct =
                entry > 0 && amt !== 0
                  ? ((mark - entry) / entry) * (amt > 0 ? 1 : -1)
                  : 0;
              const isLong = amt > 0;

              return (
                <tr
                  key={`${p.symbol}-${p.positionSide}`}
                  className="border-b border-gray-50 last:border-0"
                >
                  <td className="py-3.5 pr-4 font-medium text-gray-900">
                    {p.symbol.replace("USDT", "")}
                    <span className="text-gray-400">/USDT</span>
                  </td>
                  <td className="py-3.5 pr-4">
                    <span
                      className={`inline-flex rounded-md px-2 py-0.5 text-xs font-semibold ${
                        isLong
                          ? "bg-orange-50 text-orange-600"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {isLong ? "LONG" : "SHORT"}
                    </span>
                  </td>
                  <td className="py-3.5 pr-4 text-right font-mono text-gray-700">
                    {formatNumber(Math.abs(amt), 4)}
                  </td>
                  <td className="py-3.5 pr-4 text-right font-mono text-gray-700">
                    {formatNumber(entry, 2)}
                  </td>
                  <td className="py-3.5 pr-4 text-right font-mono text-gray-700">
                    {formatNumber(mark, 2)}
                  </td>
                  <td className="py-3.5 pr-4 text-right">
                    <span
                      className={`font-mono font-medium ${
                        pnl >= 0 ? "text-orange-500" : "text-red-500"
                      }`}
                    >
                      {pnl >= 0 ? "+" : ""}
                      {formatUSD(pnl)}
                    </span>
                    <span className="ml-1 text-xs text-gray-400">
                      ({(pnlPct * 100).toFixed(2)}%)
                    </span>
                  </td>
                  <td className="py-3.5 text-right font-mono text-gray-500">
                    {p.leverage}x
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
