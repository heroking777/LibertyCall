import * as fs from "fs";
import * as path from "path";
import { ProjectState } from "../types/ProjectState";

const STORAGE_FILE = path.join(__dirname, "../../project_states.json");

/**
 * プロジェクト状態を保存するJSONファイルのパスを取得
 */
function getStoragePath(): string {
  return STORAGE_FILE;
}

/**
 * ストレージファイルが存在しない場合は空オブジェクトを返す
 * 存在する場合は読み込んで返す
 */
export function loadProjectStates(): Record<string, ProjectState> {
  const filePath = getStoragePath();
  
  try {
    // ファイルが存在しない場合は空オブジェクトを返す
    if (!fs.existsSync(filePath)) {
      return {};
    }

    const fileContent = fs.readFileSync(filePath, "utf-8");
    
    // 空ファイルの場合は空オブジェクトを返す
    if (fileContent.trim() === "") {
      return {};
    }

    const data = JSON.parse(fileContent);
    return data as Record<string, ProjectState>;
  } catch (error) {
    // JSON parse エラーの場合は空オブジェクトを返す
    console.error("Failed to load project states:", error);
    return {};
  }
}

/**
 * プロジェクト状態を保存する
 * pretty-print（インデント付き）で保存する
 */
export function saveProjectStates(states: Record<string, ProjectState>): void {
  const filePath = getStoragePath();
  
  try {
    // ディレクトリが存在しない場合は作成
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // pretty-print（インデント2スペース）で保存
    const jsonContent = JSON.stringify(states, null, 2);
    fs.writeFileSync(filePath, jsonContent, "utf-8");
  } catch (error) {
    console.error("Failed to save project states:", error);
    throw new Error(`Failed to save project states: ${error}`);
  }
}

/**
 * 特定のプロジェクト状態を取得する
 */
export function getProjectState(projectId: string): ProjectState | null {
  const states = loadProjectStates();
  return states[projectId] || null;
}

/**
 * プロジェクト状態を保存または更新する
 */
export function saveProjectState(state: ProjectState): void {
  const states = loadProjectStates();
  states[state.projectId] = state;
  saveProjectStates(states);
}

/**
 * 全プロジェクトのリストを取得
 */
export function getAllProjects(): ProjectState[] {
  const states = loadProjectStates();
  return Object.values(states);
}

