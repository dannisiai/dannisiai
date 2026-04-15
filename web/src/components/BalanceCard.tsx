import type { AccountInfo } from "../lib/api";
import { formatUSD } from "../lib/format";

export default function BalanceCard({
  account,
}: {
  account: AccountInfo | null;
}) {
  const wallet = parseFloat(account?.totalWalletBalance || "0");
  const unrealized = parseFloat(account?.totalUnrealizedProfit || "0");
  const available = parseFloat(account?.availableBalance || "0");

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6">
      <p className="text-sm font-medium text-gray-500">Total Balance</p>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-gray-900">
        {formatUSD(wallet)}
      </p>
      <div className="mt-4 flex items-center gap-4 text-sm">
        <div>
          <span className="text-gray-400">Unrealized </span>
          <span
            className={
              unrealized >= 0 ? "font-medium text-orange-500" : "font-medium text-red-500"
            }
          >
            {unrealized >= 0 ? "+" : ""}
            {formatUSD(unrealized)}
          </span>
        </div>
        <div className="h-4 w-px bg-gray-200" />
        <div>
          <span className="text-gray-400">Available </span>
          <span className="font-medium text-gray-700">
            {formatUSD(available)}
          </span>
        </div>
      </div>
    </div>
  );
}
