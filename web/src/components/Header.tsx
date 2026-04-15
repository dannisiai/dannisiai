const EXPLORER_URL = "https://www.asterdex.com/zh-CN/explorer";

export default function Header({ connected }: { connected: boolean }) {
  return (
    <header className="flex items-center justify-between py-6">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-orange-500 flex items-center justify-center">
          <span className="text-white font-bold text-sm">A</span>
        </div>
        <h1 className="text-xl font-semibold tracking-tight text-gray-900">
          Aster Trading Vault
        </h1>
        <span
          className={`ml-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            connected
              ? "bg-emerald-50 text-emerald-700"
              : "bg-gray-100 text-gray-500"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              connected ? "bg-emerald-500" : "bg-gray-400"
            }`}
          />
          {connected ? "Live" : "Offline"}
        </span>
      </div>

      <a
        href={EXPLORER_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 hover:border-gray-300"
      >
        Verify on Explorer
        <svg
          className="h-3.5 w-3.5"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4.5 19.5l15-15m0 0H8.25m11.25 0v11.25"
          />
        </svg>
      </a>
    </header>
  );
}
