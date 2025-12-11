export type ProjectType = "ai_phone" | "upwork" | "system" | "other";

export type TaskStatus = "todo" | "doing" | "done" | "blocked";

export interface ProjectTask {
  id: string;
  title: string;
  status: TaskStatus;
  note?: string;
}

export interface ProjectDecision {
  id: string;
  title: string;
  detail?: string;
  decidedAt?: string; // ISO文字列
}

export interface ProjectIssue {
  id: string;
  title: string;
  detail?: string;
  status: "open" | "investigating" | "fixed" | "wontfix";
}

export interface ProjectImportantFile {
  path: string;    // 例: "backend/src/ivr/router.ts"
  purpose: string; // 例: "着信分配ロジック"
}

export interface ProjectState {
  projectId: string;        // "ai-phone-main" など一意なID
  name: string;             // 表示名
  type: ProjectType;

  summary: string;          // プロジェクト全体の要約(3〜10行程度)
  techStack: string[];      // 例: ["Node.js","React","PostgreSQL"]
  status: "planning" | "in_progress" | "paused" | "done";

  currentFocus: string;     // 「今この案件で何やってるか」を1行で

  tasks: ProjectTask[];
  decisions: ProjectDecision[];
  issues: ProjectIssue[];
  importantFiles: ProjectImportantFile[];

  structure?: Record<string, string>; // プロジェクト構造（パス: 用途のマッピング）

  updatedAt: string;        // 最後に状態更新した時刻（ISO文字列）
}

// APIレスポンス用の簡易プロジェクト情報
export interface ProjectListItem {
  projectId: string;
  name: string;
  type: ProjectType;
}

