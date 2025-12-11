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
Object.defineProperty(exports, "__esModule", { value: true });
exports.loadProjectStates = loadProjectStates;
exports.saveProjectStates = saveProjectStates;
exports.getProjectState = getProjectState;
exports.saveProjectState = saveProjectState;
exports.getAllProjects = getAllProjects;
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const STORAGE_FILE = path.join(__dirname, "../../project_states.json");
/**
 * プロジェクト状態を保存するJSONファイルのパスを取得
 */
function getStoragePath() {
    return STORAGE_FILE;
}
/**
 * ストレージファイルが存在しない場合は空オブジェクトを返す
 * 存在する場合は読み込んで返す
 */
function loadProjectStates() {
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
        return data;
    }
    catch (error) {
        // JSON parse エラーの場合は空オブジェクトを返す
        console.error("Failed to load project states:", error);
        return {};
    }
}
/**
 * プロジェクト状態を保存する
 * pretty-print（インデント付き）で保存する
 */
function saveProjectStates(states) {
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
    }
    catch (error) {
        console.error("Failed to save project states:", error);
        throw new Error(`Failed to save project states: ${error}`);
    }
}
/**
 * 特定のプロジェクト状態を取得する
 */
function getProjectState(projectId) {
    const states = loadProjectStates();
    return states[projectId] || null;
}
/**
 * プロジェクト状態を保存または更新する
 */
function saveProjectState(state) {
    const states = loadProjectStates();
    states[state.projectId] = state;
    saveProjectStates(states);
}
/**
 * 全プロジェクトのリストを取得
 */
function getAllProjects() {
    const states = loadProjectStates();
    return Object.values(states);
}
