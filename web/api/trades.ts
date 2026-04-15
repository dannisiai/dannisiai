import type { VercelRequest, VercelResponse } from "@vercel/node";
import { asterGet } from "./_lib/aster-client.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") return res.status(200).end();

  try {
    const symbol = (req.query.symbol as string) || "BTCUSDT";
    const limit = (req.query.limit as string) || "50";
    const data = await asterGet("/fapi/v3/userTrades", { symbol, limit });
    return res.status(200).json(data);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return res.status(500).json({ error: msg });
  }
}
