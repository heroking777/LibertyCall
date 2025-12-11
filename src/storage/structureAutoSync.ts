import * as fs from "fs";
import * as path from "path";
import { ProjectState } from "../types/ProjectState";
import { loadProjectStates, saveProjectState } from "./projectStateStorage";

/**
 * 除外するディレクトリ/ファイルのパターン
 */
const EXCLUDE_PATTERNS = [
  "node_modules",
  "venv",
  "__pycache__",
  ".git",
  "dist",
  "build",
  ".next",
  ".vscode",
  ".idea",
  "*.log",
  "*.pyc",
  ".env",
  ".DS_Store",
];

/**
 * パスが除外パターンにマッチするかチェック
 */
function shouldExclude(filePath: string): boolean {
  const normalizedPath = filePath.replace(/\\/g, "/");
  return EXCLUDE_PATTERNS.some((pattern) => {
    if (pattern.includes("*")) {
      // ワイルドカードパターン
      const regex = new RegExp(pattern.replace(/\*/g, ".*"));
      return regex.test(normalizedPath);
    }
    return normalizedPath.includes(pattern);
  });
}

/**
 * ファイルシステムをスキャンして構造情報を取得
 */
export function scanStructure(rootDir: string): Record<string, string> {
  const result: Record<string, string> = {};

  function walk(current: string, depth: number = 0) {
    // 深さ制限（パフォーマンス向上のため）
    if (depth > 5) {
      return;
    }

    try {
      const entries = fs.readdirSync(current, { withFileTypes: true });

      for (const entry of entries) {
        // ドットファイルをスキップ（.git など）
        if (entry.name.startsWith(".") && entry.name !== ".gitignore") {
          continue;
        }

        const fullPath = path.join(current, entry.name);
        const relPath = path.relative(rootDir, fullPath);

        // 除外パターンチェック
        if (shouldExclude(relPath)) {
          continue;
        }

        if (entry.isDirectory()) {
          result[`${relPath}/`] = "ディレクトリ";
          walk(fullPath, depth + 1);
        } else {
          // ファイルの場合は拡張子に基づいて用途を推測
          const ext = path.extname(entry.name).toLowerCase();
          const purpose = getFilePurpose(ext, entry.name);
          result[relPath] = purpose;
        }
      }
    } catch (error) {
      // 権限エラーなどは無視
      console.warn(`Failed to read directory ${current}:`, error);
    }
  }

  walk(rootDir);
  return result;
}

/**
 * ファイル拡張子と名前から用途を推測
 */
function getFilePurpose(ext: string, fileName: string): string {
  const purposeMap: Record<string, string> = {
    ".md": "Markdownドキュメント",
    ".py": "Pythonスクリプト",
    ".ts": "TypeScriptソース",
    ".js": "JavaScriptソース",
    ".json": "JSON設定ファイル",
    ".yaml": "YAML設定ファイル",
    ".yml": "YAML設定ファイル",
    ".txt": "テキストファイル",
    ".sh": "シェルスクリプト",
    ".sql": "SQLスクリプト",
    ".html": "HTMLファイル",
    ".css": "CSSスタイルシート",
    ".tsx": "React TypeScriptコンポーネント",
    ".jsx": "React JavaScriptコンポーネント",
  };

  if (purposeMap[ext]) {
    return purposeMap[ext];
  }

  // ファイル名から推測
  if (fileName === "README.md" || fileName === "README.txt") {
    return "プロジェクト概要・セットアップ手順";
  }
  if (fileName === "package.json") {
    return "Node.js依存パッケージ";
  }
  if (fileName === "requirements.txt") {
    return "Python依存パッケージ";
  }
  if (fileName === "Dockerfile") {
    return "Docker設定ファイル";
  }

  return "ファイル";
}

/**
 * 2つの構造情報の差分を検出
 */
export function findDiff(
  actual: Record<string, string>,
  stored: Record<string, string>
): {
  added: Record<string, string>;
  removed: Record<string, string>;
  changed: Record<string, { old: string; new: string }>;
} {
  const added: Record<string, string> = {};
  const removed: Record<string, string> = {};
  const changed: Record<string, { old: string; new: string }> = {};

  // 追加・変更を検出
  for (const key of Object.keys(actual)) {
    if (!(key in stored)) {
      added[key] = actual[key];
    } else if (stored[key] !== actual[key]) {
      changed[key] = { old: stored[key], new: actual[key] };
    }
  }

  // 削除を検出
  for (const key of Object.keys(stored)) {
    if (!(key in actual)) {
      removed[key] = stored[key];
    }
  }

  return { added, removed, changed };
}

/**
 * 差分ログをファイルに出力
 */
export function logDiff(
  projectId: string,
  diff: {
    added: Record<string, string>;
    removed: Record<string, string>;
    changed: Record<string, { old: string; new: string }>;
  }
): void {
  const logDir = path.join(__dirname, "../../logs");
  const logFile = path.join(logDir, "structure_diff.log");

  // ログディレクトリを作成
  if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir, { recursive: true });
  }

  const timestamp = new Date().toISOString();
  const logEntry = {
    timestamp,
    projectId,
    added: Object.keys(diff.added).length,
    removed: Object.keys(diff.removed).length,
    changed: Object.keys(diff.changed).length,
    details: {
      added: diff.added,
      removed: diff.removed,
      changed: diff.changed,
    },
  };

  // ログファイルに追記
  const logLine = JSON.stringify(logEntry) + "\n";
  fs.appendFileSync(logFile, logLine, "utf-8");
}

/**
 * 全プロジェクトの構造情報を自動同期
 */
export async function structureAutoSync(rootDir: string): Promise<void> {
  const projects = loadProjectStates();

  for (const projectId of Object.keys(projects)) {
    const project = projects[projectId];

    try {
      // 実際のファイルシステムをスキャン
      const actualStructure = scanStructure(rootDir);

      // 保存されている構造情報を取得
      const storedStructure = project.structure || {};

      // 差分を検出
      const diff = findDiff(actualStructure, storedStructure);

      // 差分がある場合のみ更新
      const hasChanges =
        Object.keys(diff.added).length > 0 ||
        Object.keys(diff.removed).length > 0 ||
        Object.keys(diff.changed).length > 0;

      if (hasChanges) {
        console.log(`[SYNC] 構造差分検出: ${projectId}`);
        console.log(`  追加: ${Object.keys(diff.added).length}件`);
        console.log(`  削除: ${Object.keys(diff.removed).length}件`);
        console.log(`  変更: ${Object.keys(diff.changed).length}件`);

        // 構造情報を更新
        project.structure = actualStructure;
        project.updatedAt = new Date().toISOString();

        // 保存
        saveProjectState(project);

        // 差分ログを出力
        logDiff(projectId, diff);
      }
    } catch (error) {
      console.error(`[SYNC] エラー: ${projectId} の同期に失敗しました:`, error);
    }
  }
}

