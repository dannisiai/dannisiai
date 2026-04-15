import { useState, useEffect, useCallback } from "react";
import {
  getAccount,
  getPositions,
  getIncome,
  type AccountInfo,
  type PositionInfo,
  type IncomeInfo,
} from "../lib/api";

const POLL_INTERVAL = 30_000;

function useFetch<T>(
  fetcher: () => Promise<T>,
  fallback: T,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T>(fallback);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await fetcher();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fetch failed");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [refresh]);

  return { data, loading, error, refresh };
}

export function useAccount() {
  return useFetch<AccountInfo | null>(
    () => getAccount(),
    null,
  );
}

export function usePositions() {
  return useFetch<PositionInfo[]>(
    async () => {
      const positions = await getPositions();
      return positions.filter((p) => parseFloat(p.positionAmt) !== 0);
    },
    [],
  );
}

export function useIncome(limit = 100) {
  return useFetch<IncomeInfo[]>(
    () => getIncome({ limit }),
    [],
    [limit],
  );
}
