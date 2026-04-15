import type { VercelRequest, VercelResponse } from "@vercel/node";
import { asterGet } from "./_lib/aster-client.js";

export default async function handler(_req: VercelRequest, res: VercelResponse) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (_req.method === "OPTIONS") return res.status(200).end();

  try {
    const data = await asterGet("/fapi/v3/balance");
    return res.status(200).json(data);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return res.status(500).json({ error: msg });
  }
}
