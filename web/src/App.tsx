import Header from "./components/Header";
import BalanceCard from "./components/BalanceCard";
import StatsCard from "./components/StatsCard";
import PositionsTable from "./components/PositionsTable";
import IncomeTable from "./components/IncomeTable";
import PnlChart from "./components/PnlChart";
import LoadingSpinner from "./components/LoadingSpinner";
import { useAccount, usePositions, useIncome } from "./hooks/useAsterData";

export default function App() {
  const account = useAccount();
  const positions = usePositions();
  const income = useIncome(200);

  const isLoading = account.loading && positions.loading && income.loading;
  const hasError = account.error || positions.error || income.error;
  const isConnected = !account.error && !account.loading;

  if (isLoading) return <Shell><LoadingSpinner /></Shell>;

  return (
    <Shell>
      <Header connected={isConnected} />

      {hasError && (
        <div className="rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-600">
          {account.error || positions.error || income.error}
        </div>
      )}

      <div className="grid gap-5 md:grid-cols-3">
        <div className="md:col-span-1">
          <BalanceCard account={account.data} />
        </div>
        <div className="md:col-span-2">
          <StatsCard income={income.data} />
        </div>
      </div>

      <PnlChart income={income.data} />

      <PositionsTable positions={positions.data} />

      <IncomeTable income={income.data} />

      <footer className="pb-8 pt-4 text-center text-xs text-gray-300">
        Auto-refreshes every 30s &middot; Data from Aster DEX
      </footer>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50/50">
      <div className="mx-auto max-w-4xl space-y-5 px-4 sm:px-6">
        {children}
      </div>
    </div>
  );
}
