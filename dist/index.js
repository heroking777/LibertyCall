"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = __importDefault(require("express"));
const path = __importStar(require("path"));
const projectRoutes_1 = __importDefault(require("./routes/projectRoutes"));
const structureAutoSync_1 = require("./storage/structureAutoSync");
const app = (0, express_1.default)();
const PORT = process.env.PORT || 3000;
// JSON パーサーミドルウェア
app.use(express_1.default.json());
// リクエストログミドルウェア
app.use((req, res, next) => {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] ${req.method} ${req.path} - IP: ${req.ip}`);
    next();
});
// CORS ヘッダー（必要に応じて調整）
app.use((req, res, next) => {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.header("Access-Control-Allow-Headers", "Content-Type, Authorization");
    if (req.method === "OPTIONS") {
        res.sendStatus(200);
    }
    else {
        next();
    }
});
// ルーティング
app.use("/projects", projectRoutes_1.default);
// ヘルスチェックエンドポイント
app.get("/health", (req, res) => {
    res.json({ status: "ok" });
});
// 404 ハンドラー
app.use((req, res) => {
    res.status(404).json({
        error: "not_found",
        message: `Route ${req.method} ${req.path} not found`,
    });
});
// エラーハンドラー
app.use((err, req, res, next) => {
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
        (0, structureAutoSync_1.structureAutoSync)(rootDir).catch((error) => {
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
            (0, structureAutoSync_1.structureAutoSync)(rootDir).catch((error) => {
                console.error("[SYNC] 定期自動同期に失敗しました:", error);
            });
        }, syncInterval);
    }
});
