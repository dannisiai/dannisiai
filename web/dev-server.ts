import express from "express";
import { asterGet } from "./api/_lib/aster-client.js";
import "dotenv/config";

const app = express();
const PORT = 3001;

app.use((_req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  next();
});

app.get("/api/balance", async (_req, res) => {
  try {
    const data = await asterGet("/fapi/v3/balance");
    res.json(data);
  } catch (e: unknown) {
    res.status(500).json({ error: (e as Error).message });
  }
});

app.get("/api/account", async (_req, res) => {
  try {
    const data = await asterGet("/fapi/v3/accountWithJoinMargin");
    res.json(data);
  } catch (e: unknown) {
    res.status(500).json({ error: (e as Error).message });
  }
});

app.get("/api/positions", async (_req, res) => {
  try {
    const data = await asterGet("/fapi/v3/positionRisk");
    res.json(data);
  } catch (e: unknown) {
    res.status(500).json({ error: (e as Error).message });
  }
});

app.get("/api/income", async (req, res) => {
  try {
    const params: Record<string, string> = {};
    if (req.query.limit) params.limit = req.query.limit as string;
    if (req.query.symbol) params.symbol = req.query.symbol as string;
    if (req.query.incomeType) params.incomeType = req.query.incomeType as string;
    const data = await asterGet("/fapi/v3/income", params);
    res.json(data);
  } catch (e: unknown) {
    res.status(500).json({ error: (e as Error).message });
  }
});

app.get("/api/trades", async (req, res) => {
  try {
    const symbol = (req.query.symbol as string) || "BTCUSDT";
    const limit = (req.query.limit as string) || "50";
    const data = await asterGet("/fapi/v3/userTrades", { symbol, limit });
    res.json(data);
  } catch (e: unknown) {
    res.status(500).json({ error: (e as Error).message });
  }
});

app.get("/api/orders", async (req, res) => {
  try {
    const symbol = (req.query.symbol as string) || "BTCUSDT";
    const limit = (req.query.limit as string) || "50";
    const data = await asterGet("/fapi/v3/allOrders", { symbol, limit });
    res.json(data);
  } catch (e: unknown) {
    res.status(500).json({ error: (e as Error).message });
  }
});

app.listen(PORT, () => {
  console.log(`Dev API proxy running on http://localhost:${PORT}`);
});
