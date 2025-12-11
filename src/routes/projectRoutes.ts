import { Router, Request, Response } from "express";
import * as fs from "fs";
import * as path from "path";
import {
  ProjectState,
  ProjectListItem,
  ProjectTask,
  ProjectDecision,
  ProjectIssue,
  ProjectImportantFile,
} from "../types/ProjectState";
import {
  loadProjectStates,
  getProjectState,
  saveProjectState,
} from "../storage/projectStateStorage";
import { structureAutoSync } from "../storage/structureAutoSync";

const router = Router();

/**
 * 簡易バリデーション: 必須フィールドが存在し、型が正しいかチェック
 */
function validateProjectState(body: any): { valid: boolean; error?: string } {
  // 必須フィールドのチェック
  if (typeof body.name !== "string" || body.name.trim() === "") {
    return { valid: false, error: "name must be a non-empty string" };
  }
  if (typeof body.type !== "string") {
    return { valid: false, error: "type must be a string" };
  }
  if (typeof body.summary !== "string") {
    return { valid: false, error: "summary must be a string" };
  }
  if (typeof body.status !== "string") {
    return { valid: false, error: "status must be a string" };
  }
  if (typeof body.currentFocus !== "string") {
    return { valid: false, error: "currentFocus must be a string" };
  }

  // 配列フィールドのチェック
  if (!Array.isArray(body.tasks)) {
    return { valid: false, error: "tasks must be an array" };
  }
  if (!Array.isArray(body.decisions)) {
    return { valid: false, error: "decisions must be an array" };
  }
  if (!Array.isArray(body.issues)) {
    return { valid: false, error: "issues must be an array" };
  }
  if (!Array.isArray(body.importantFiles)) {
    return { valid: false, error: "importantFiles must be an array" };
  }
  if (!Array.isArray(body.techStack)) {
    return { valid: false, error: "techStack must be an array" };
  }

  return { valid: true };
}

/**
 * GET /projects
 * 案件一覧を取得（簡易情報のみ）
 * オプション: ?sync=true で構造情報を自動同期
 */
router.get("/", async (req: Request, res: Response) => {
  try {
    // 自動同期が有効な場合（?sync=true または環境変数で有効化）
    const shouldSync = req.query.sync === "true" || process.env.AUTO_SYNC_STRUCTURE === "true";
    
    if (shouldSync) {
      const rootDir = process.env.PROJECT_ROOT || path.join(__dirname, "../..");
      try {
        await structureAutoSync(rootDir);
      } catch (syncError) {
        console.warn("Structure auto-sync failed (continuing anyway):", syncError);
      }
    }

    const states = loadProjectStates();
    const list: ProjectListItem[] = Object.values(states).map((state) => ({
      projectId: state.projectId,
      name: state.name,
      type: state.type,
    }));

    res.json(list);
  } catch (error) {
    console.error("Error loading project list:", error);
    res.status(500).json({
      error: "internal_server_error",
      message: "Failed to load project list",
    });
  }
});

/**
 * GET /projects/:projectId/state
 * 特定案件の状態を取得
 * オプション: ?sync=true で構造情報を自動同期
 */
router.get("/:projectId/state", async (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    
    // 自動同期が有効な場合
    const shouldSync = req.query.sync === "true" || process.env.AUTO_SYNC_STRUCTURE === "true";
    
    if (shouldSync) {
      const rootDir = process.env.PROJECT_ROOT || path.join(__dirname, "../..");
      try {
        await structureAutoSync(rootDir);
      } catch (syncError) {
        console.warn("Structure auto-sync failed (continuing anyway):", syncError);
      }
    }

    const state = getProjectState(projectId);

    if (!state) {
      res.status(404).json({
        error: "not_found",
        message: `Project with id "${projectId}" not found`,
      });
      return;
    }

    res.json(state);
  } catch (error) {
    console.error("Error loading project state:", error);
    res.status(500).json({
      error: "internal_server_error",
      message: "Failed to load project state",
    });
  }
});

/**
 * POST /projects/:projectId/state
 * 特定案件の状態を保存（新規 or 更新）
 */
router.post("/:projectId/state", (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    const body = req.body;

    // バリデーション
    const validation = validateProjectState(body);
    if (!validation.valid) {
      res.status(400).json({
        error: "validation_error",
        message: validation.error,
      });
      return;
    }

    // 既存の状態を読み込む（マージ用）
    const existingState = getProjectState(projectId);

    // 新しい状態を作成（マージ）
    const newState: ProjectState = {
      ...existingState, // 既存データがあればマージ
      ...body,          // リクエストボディで上書き
      projectId,        // URLのprojectIdを優先
      updatedAt: new Date().toISOString(), // サーバー側で現在時刻をセット
    };

    // 保存
    saveProjectState(newState);

    res.json(newState);
  } catch (error) {
    console.error("Error saving project state:", error);
    res.status(500).json({
      error: "internal_server_error",
      message: error instanceof Error ? error.message : "Failed to save project state",
    });
  }
});

/**
 * POST /projects/:projectId/logs
 * 簡易ログを追記
 */
router.post("/:projectId/logs", (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    const { summary } = req.body;

    if (typeof summary !== "string" || summary.trim() === "") {
      res.status(400).json({
        error: "validation_error",
        message: "summary must be a non-empty string",
      });
      return;
    }

    // ログファイルのパス
    const logFile = path.join(__dirname, "../../project_logs.json");

    // 既存のログを読み込む
    let logs: Record<string, any[]> = {};
    if (fs.existsSync(logFile)) {
      try {
        const content = fs.readFileSync(logFile, "utf-8");
        if (content.trim() !== "") {
          logs = JSON.parse(content);
        }
      } catch (error) {
        // パースエラーは無視して空オブジェクトから開始
        console.warn("Failed to parse existing logs, starting fresh:", error);
      }
    }

    // プロジェクトのログ配列を初期化（存在しない場合）
    if (!logs[projectId]) {
      logs[projectId] = [];
    }

    // 新しいログエントリを追加
    const logEntry = {
      summary,
      createdAt: new Date().toISOString(),
    };
    logs[projectId].push(logEntry);

    // 保存
    fs.writeFileSync(logFile, JSON.stringify(logs, null, 2), "utf-8");

    res.json({
      success: true,
      log: logEntry,
    });
  } catch (error) {
    console.error("Error saving log:", error);
    res.status(500).json({
      error: "internal_server_error",
      message: "Failed to save log",
    });
  }
});

export default router;

