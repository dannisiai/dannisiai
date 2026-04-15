const API_BASE = import.meta.env.VITE_API_URL || "/api";

async function fetchJSON<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export interface BalanceInfo {
  asset: string;
  balance: string;
  availableBalance: string;
  crossWalletBalance: string;
  crossUnPnl: string;
}

export interface PositionInfo {
  symbol: string;
  positionSide: string;
  positionAmt: string;
  entryPrice: string;
  markPrice: string;
  unRealizedProfit: string;
  leverage: string;
  marginType: string;
  liquidationPrice: string;
}

export interface TradeInfo {
  id: number;
  symbol: string;
  side: string;
  positionSide: string;
  price: string;
  qty: string;
  quoteQty: string;
  realizedPnl: string;
  commission: string;
  commissionAsset: string;
  time: number;
  buyer: boolean;
  maker: boolean;
}

export interface IncomeInfo {
  symbol: string;
  incomeType: string;
  income: string;
  asset: string;
  time: number;
  tranId: string;
  info: string;
}

export interface AccountInfo {
  totalWalletBalance: string;
  totalUnrealizedProfit: string;
  totalMarginBalance: string;
  availableBalance: string;
  positions: PositionInfo[];
}

export function getBalance(): Promise<BalanceInfo[]> {
  return fetchJSON("/balance");
}

export function getPositions(): Promise<PositionInfo[]> {
  return fetchJSON("/positions");
}

export function getAccount(): Promise<AccountInfo> {
  return fetchJSON("/account");
}

export function getTrades(symbol: string, limit = 50): Promise<TradeInfo[]> {
  return fetchJSON("/trades", { symbol, limit: String(limit) });
}

export function getIncome(params?: {
  symbol?: string;
  incomeType?: string;
  limit?: number;
}): Promise<IncomeInfo[]> {
  const p: Record<string, string> = {};
  if (params?.symbol) p.symbol = params.symbol;
  if (params?.incomeType) p.incomeType = params.incomeType;
  if (params?.limit) p.limit = String(params.limit);
  return fetchJSON("/income", p);
}
