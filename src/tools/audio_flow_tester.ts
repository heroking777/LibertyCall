#!/usr/bin/env node
/**
 * 音声フローテスター
 * 
 * 音声ファイルをASRでテキスト化し、AICoreで処理して会話フローを検証します。
 * 
 * 使い方:
 *   npx ts-node src/tools/audio_flow_tester.ts [audio_file.wav]
 *   npx ts-node src/tools/audio_flow_tester.ts tts_test/004_moshimoshi.wav
 */

import * as fs from "fs";
import * as path from "path";
import { spawnSync } from "child_process";

const PROJECT_ROOT = path.resolve(__dirname, "../..");
const TEST_AUDIO_DIR = path.resolve(PROJECT_ROOT, "tts_test");
const LOG_FILE = path.resolve(PROJECT_ROOT, "logs/conversation_trace.log");
const TEST_ASR_SCRIPT = path.resolve(PROJECT_ROOT, "scripts/test_audio_asr.py");
const TEST_AI_SCRIPT = path.resolve(PROJECT_ROOT, "scripts/test_ai_response.py");

interface TestResult {
  audioFile: string;
  recognizedText: string;
  phase: string;
  templateIds: string;
  responseText: string;
  success: boolean;
  error?: string;
}

/**
 * 音声ファイルをASRでテキスト化
 */
function transcribeAudio(audioFile: string): string | null {
  console.log(`🎧 ASR認識中: ${path.basename(audioFile)}`);
  
  const result = spawnSync("python3", [TEST_ASR_SCRIPT, audioFile], {
    encoding: "utf-8",
    cwd: PROJECT_ROOT,
  });
  
  if (result.error) {
    console.error(`❌ ASR実行エラー: ${result.error.message}`);
    return null;
  }
  
  if (result.status !== 0) {
    console.error(`❌ ASR失敗 (exit code: ${result.status})`);
    if (result.stderr) {
      console.error(result.stderr);
    }
    return null;
  }
  
  const text = result.stdout.trim();
  if (!text) {
    console.warn("⚠️  認識結果が空です。");
    return null;
  }
  
  console.log(`🗣️  認識結果: ${text}`);
  return text;
}

/**
 * テキストをAICoreで処理
 */
function processWithAI(text: string, callId: string = "TEST_CALL"): {
  phase: string;
  templateIds: string;
  responseText: string;
} | null {
  console.log(`🤖 AI処理中: ${text}`);
  
  const result = spawnSync("python3", [TEST_AI_SCRIPT, text, callId], {
    encoding: "utf-8",
    cwd: PROJECT_ROOT,
  });
  
  if (result.error) {
    console.error(`❌ AI処理エラー: ${result.error.message}`);
    return null;
  }
  
  if (result.status !== 0) {
    console.error(`❌ AI処理失敗 (exit code: ${result.status})`);
    if (result.stderr) {
      console.error(result.stderr);
    }
    return null;
  }
  
  // 出力をパース: PHASE=... TEMPLATE=... TEXT=...
  const output = result.stdout.trim();
  const phaseMatch = output.match(/PHASE=([^\s]+)/);
  const templateMatch = output.match(/TEMPLATE=([^\s]+)/);
  const textMatch = output.match(/TEXT=(.+)$/);
  
  const phase = phaseMatch ? phaseMatch[1] : "UNKNOWN";
  const templateIds = templateMatch ? templateMatch[1] : "NONE";
  const responseText = textMatch ? textMatch[1] : "";
  
  return { phase, templateIds, responseText };
}

/**
 * 単一の音声ファイルをテスト
 */
function testAudioFile(audioFile: string): TestResult {
  console.log("=".repeat(60));
  console.log(`📁 テスト: ${path.basename(audioFile)}`);
  console.log("=".repeat(60));
  
  // ASR認識
  const recognizedText = transcribeAudio(audioFile);
  if (!recognizedText) {
    return {
      audioFile,
      recognizedText: "",
      phase: "",
      templateIds: "",
      responseText: "",
      success: false,
      error: "ASR認識失敗",
    };
  }
  
  // AI処理
  const aiResult = processWithAI(recognizedText);
  if (!aiResult) {
    return {
      audioFile,
      recognizedText,
      phase: "",
      templateIds: "",
      responseText: "",
      success: false,
      error: "AI処理失敗",
    };
  }
  
  console.log(`✅ 結果: PHASE=${aiResult.phase} TEMPLATE=${aiResult.templateIds}`);
  console.log(`   TEXT=${aiResult.responseText}`);
  console.log("");
  
  return {
    audioFile,
    recognizedText,
    phase: aiResult.phase,
    templateIds: aiResult.templateIds,
    responseText: aiResult.responseText,
    success: true,
  };
}

/**
 * メイン処理
 */
function main() {
  const args = process.argv.slice(2);
  
  let audioFiles: string[] = [];
  
  if (args.length > 0) {
    // 引数で指定されたファイル
    audioFiles = args.map(f => path.resolve(f));
  } else {
    // tts_test/ ディレクトリ内のすべてのWAVファイル
    if (!fs.existsSync(TEST_AUDIO_DIR)) {
      console.error(`❌ エラー: テスト音声ディレクトリが見つかりません: ${TEST_AUDIO_DIR}`);
      process.exit(1);
    }
    
    const files = fs.readdirSync(TEST_AUDIO_DIR)
      .filter(f => f.endsWith(".wav"))
      .map(f => path.join(TEST_AUDIO_DIR, f));
    
    if (files.length === 0) {
      console.error(`❌ エラー: テスト音声ファイルが見つかりません: ${TEST_AUDIO_DIR}`);
      process.exit(1);
    }
    
    audioFiles = files;
  }
  
  console.log("=".repeat(60));
  console.log("🎧 音声フローテスト開始");
  console.log("=".repeat(60));
  console.log(`📁 テスト対象: ${audioFiles.length} ファイル`);
  console.log("");
  
  const results: TestResult[] = [];
  
  // 各音声ファイルをテスト
  for (const audioFile of audioFiles) {
    if (!fs.existsSync(audioFile)) {
      console.error(`⚠️  ファイルが見つかりません: ${audioFile}`);
      results.push({
        audioFile,
        recognizedText: "",
        phase: "",
        templateIds: "",
        responseText: "",
        success: false,
        error: "ファイルが見つかりません",
      });
      continue;
    }
    
    const result = testAudioFile(audioFile);
    results.push(result);
  }
  
  // 結果サマリー
  console.log("=".repeat(60));
  console.log("📊 テスト結果サマリー");
  console.log("=".repeat(60));
  
  const successCount = results.filter(r => r.success).length;
  const failCount = results.filter(r => !r.success).length;
  
  for (const result of results) {
    const status = result.success ? "✅" : "❌";
    console.log(`${status} ${path.basename(result.audioFile)}`);
    if (result.recognizedText) {
      console.log(`   認識: ${result.recognizedText}`);
    }
    if (result.phase) {
      console.log(`   PHASE=${result.phase} TEMPLATE=${result.templateIds}`);
    }
    if (result.error) {
      console.log(`   エラー: ${result.error}`);
    }
  }
  
  console.log("");
  console.log(`合計: ${results.length} テスト`);
  console.log(`✅ 成功: ${successCount}`);
  console.log(`❌ 失敗: ${failCount}`);
  
  if (LOG_FILE && fs.existsSync(LOG_FILE)) {
    console.log("");
    console.log(`📜 会話ログ: ${LOG_FILE}`);
  }
  
  console.log("=".repeat(60));
  
  process.exit(failCount > 0 ? 1 : 0);
}

if (require.main === module) {
  main();
}

export { testAudioFile, TestResult };

