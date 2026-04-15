import type { VercelRequest, VercelResponse } from "@vercel/node";
import { asterGet } from "./_lib/aster-client.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") return res.status(200).end();

  try {
    const params: Record<string, string> = {};
    if (req.query.symbol) params.symbol = req.query.symbol as string;
    if (req.query.incomeType) params.incomeType = req.query.incomeType as string;
    if (req.query.limit) params.limit = req.query.limit as string;
    if (req.query.startTime) params.startTime = req.query.startTime as string;
    if (req.query.endTime) params.endTime = req.query.endTime as string;

    const data = await asterGet("/fapi/v3/income", params);
    return res.status(200).json(data);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return res.status(500).json({ error: msg });
  }
}
