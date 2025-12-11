import express, { Request, Response, NextFunction } from "express";
import * as path from "path";
import projectRoutes from "./routes/projectRoutes";
import { structureAutoSync } from "./storage/structureAutoSync";

const app = express();
const PORT = process.env.PORT || 3000;

// JSON パーサーミドルウェア
app.use(express.json());

// リクエストログミドルウェア
app.use((req: Request, res: Response, next: NextFunction) => {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] ${req.method} ${req.path} - IP: ${req.ip}`);
  next();
});

// CORS ヘッダー（必要に応じて調整）
app.use((req: Request, res: Response, next: NextFunction) => {
  res.header("Access-Control-Allow-Origin", "*");
  res.header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
  res.header("Access-Control-Allow-Headers", "Content-Type, Authorization");
  if (req.method === "OPTIONS") {
    res.sendStatus(200);
  } else {
    next();
  }
});

// ルーティング
app.use("/projects", projectRoutes);

// ヘルスチェックエンドポイント
app.get("/health", (req: Request, res: Response) => {
  res.json({ status: "ok" });
});

// 404 ハンドラー
app.use((req: Request, res: Response) => {
  res.status(404).json({
    error: "not_found",
    message: `Route ${req.method} ${req.path} not found`,
  });
});

// エラーハンドラー
app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error("Unhandled error:", err);
  res.status(500).json({
    error: "internal_server_error",
    message: err.message || "An unexpected error occurred",
  });
});

// サーバー起動
app.listen(PORT, () => {
  console.log(`Project State Backend is running on http://localhost:${PORT}`);
  console.log(`Health check: http://localhost:${PORT}/health`);
  console.log(`Projects API: http://localhost:${PORT}/projects`);
  
  // 起動時に自動同期（環境変数で有効化されている場合）
  if (process.env.AUTO_SYNC_ON_START === "true") {
    const rootDir = process.env.PROJECT_ROOT || path.join(__dirname, "../..");
    console.log(`[SYNC] 起動時に構造情報を自動同期します...`);
    structureAutoSync(rootDir).catch((error) => {
      console.error("[SYNC] 起動時の自動同期に失敗しました:", error);
    });
  }
  
  // 定期的な自動同期（環境変数で有効化されている場合）
  const syncInterval = process.env.SYNC_INTERVAL_MINUTES 
    ? parseInt(process.env.SYNC_INTERVAL_MINUTES, 10) * 60 * 1000 
    : null;
  
  if (syncInterval && syncInterval > 0) {
    const rootDir = process.env.PROJECT_ROOT || path.join(__dirname, "../..");
    console.log(`[SYNC] ${syncInterval / 1000 / 60}分ごとに構造情報を自動同期します...`);
    setInterval(() => {
      structureAutoSync(rootDir).catch((error) => {
        console.error("[SYNC] 定期自動同期に失敗しました:", error);
      });
    }, syncInterval);
  }
});

