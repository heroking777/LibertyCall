#!/usr/bin/env node
/**
 * 会話フローテスター
 * 
 * docs/会話フロー_JSON構造版.json を読み込み、
 * 意図（intent）を指定して会話の進行をシミュレーションします。
 * 
 * 使い方:
 *   npx ts-node src/tools/flow_tester.ts --intent INQUIRY
 *   npx ts-node src/tools/flow_tester.ts --intent SALES_CALL --phase QA
 *   npx ts-node src/tools/flow_tester.ts --intent HANDOFF_REQUEST --verbose
 *   npx ts-node src/tools/flow_tester.ts --intent INQUIRY --export output.json
 */

import * as fs from "fs";
import * as path from "path";

interface Transition {
  condition: string;
  target: string;
  note?: string;
}

interface Phase {
  name: string;
  description: string;
  transitions: Transition[];
  templates: string[];
}

interface FlowData {
  version: string;
  updated_at: string;
  description: string;
  phases: Record<string, Phase>;
  keywords: Record<string, string[]>;
  templates: Record<string, any>;
}

interface FlowStep {
  phase: string;
  intent: string;
  nextPhase: string | null;
  matchedCondition: string | null;
  templates: string[];
}

interface TestResult {
  intent: string;
  startPhase: string;
  steps: FlowStep[];
  finalPhase: string;
  success: boolean;
  error?: string;
}

/**
 * 条件を評価（簡易版）
 */
function evaluateCondition(condition: string, intent: string, keywords?: Record<string, string[]>): boolean {
  // intent == 'XXX' の形式をチェック
  const intentMatch = condition.match(/intent\s*==\s*['"]([^'"]+)['"]/);
  if (intentMatch) {
    return intentMatch[1] === intent;
  }
  
  // intent == 'XXX' && 初回 のような複合条件
  if (condition.includes("intent ==") && condition.includes("初回")) {
    const intentInCondition = condition.match(/intent\s*==\s*['"]([^'"]+)['"]/);
    if (intentInCondition) {
      return intentInCondition[1] === intent;
    }
  }
  
  // intent == 'XXX' || intent == 'YYY' の形式をチェック
  const orMatch = condition.match(/intent\s*==\s*['"]([^'"]+)['"]\s*\|\|\s*intent\s*==\s*['"]([^'"]+)['"]/);
  if (orMatch) {
    return orMatch[1] === intent || orMatch[2] === intent;
  }
  
  // キーワードを含む条件（簡易チェック）
  if (condition.includes("KEYWORDS を含む")) {
    // 実際の実装では、キーワードマッチングを行う
    return true; // デフォルトで true（詳細な実装は後で追加可能）
  }
  
  // user_reply_received などの条件は false を返す（実際の実装では状態をチェック）
  if (condition.includes("user_reply_received") || condition.includes("user_voice_detected")) {
    return false;
  }
  
  // "その他" 条件
  if (condition.includes("その他")) {
    return true;
  }
  
  return false;
}

/**
 * 会話フローをシミュレーション
 */
function simulateFlow(
  flowData: FlowData,
  intent: string,
  startPhase: string = "ENTRY",
  verbose: boolean = false
): TestResult {
  const steps: FlowStep[] = [];
  let currentPhase = startPhase;
  let maxIterations = 20; // 無限ループ防止
  let iteration = 0;
  
  while (currentPhase && iteration < maxIterations) {
    iteration++;
    
    const phase = flowData.phases[currentPhase];
    if (!phase) {
      return {
        intent,
        startPhase,
        steps,
        finalPhase: currentPhase,
        success: false,
        error: `フェーズ '${currentPhase}' が見つかりません`,
      };
    }
    
    // 遷移条件を評価
    let matchedTransition: Transition | null = null;
    let matchedCondition: string | null = null;
    
    for (const transition of phase.transitions) {
      if (evaluateCondition(transition.condition, intent, flowData.keywords)) {
        matchedTransition = transition;
        matchedCondition = transition.condition;
        break;
      }
    }
    
    // デフォルト遷移（条件に一致しない場合）
    if (!matchedTransition) {
      // "その他" 条件を探す
      const defaultTransition = phase.transitions.find(t => t.condition.includes("その他"));
      if (defaultTransition) {
        matchedTransition = defaultTransition;
        matchedCondition = defaultTransition.condition;
      }
    }
    
    const nextPhase = matchedTransition?.target || null;
    
    steps.push({
      phase: currentPhase,
      intent,
      nextPhase,
      matchedCondition,
      templates: phase.templates,
    });
    
    if (verbose) {
      console.log(`  [${iteration}] ${currentPhase} -> ${nextPhase || "END"} (条件: ${matchedCondition || "なし"})`);
      if (phase.templates.length > 0) {
        console.log(`      テンプレート: ${phase.templates.join(", ")}`);
      }
    }
    
    // 終了条件
    if (!nextPhase || nextPhase === "END" || nextPhase === "[*]") {
      break;
    }
    
    // 同じフェーズに遷移する場合は1回だけ遷移して終了（無限ループ防止）
    if (nextPhase === currentPhase) {
      if (verbose) {
        console.log(`  ⚠️  同じフェーズ (${currentPhase}) への遷移を検出。ループ防止のため終了。`);
      }
      break;
    }
    
    currentPhase = nextPhase;
  }
  
  if (iteration >= maxIterations) {
    return {
      intent,
      startPhase,
      steps,
      finalPhase: currentPhase,
      success: false,
      error: "最大反復回数に達しました（無限ループの可能性）",
    };
  }
  
  return {
    intent,
    startPhase,
    steps,
    finalPhase: currentPhase || "END",
    success: true,
  };
}

/**
 * メイン処理
 */
function main() {
  // コマンドライン引数の解析
  const args = process.argv.slice(2);
  let intent = "INQUIRY";
  let startPhase = "ENTRY";
  let verbose = false;
  let exportPath: string | null = null;
  let userText: string | null = null;
  
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--intent" && args[i + 1]) {
      intent = args[i + 1];
      i++;
    } else if (arg === "--user_text" && args[i + 1]) {
      userText = args[i + 1];
      i++;
    } else if (arg === "--phase" && args[i + 1]) {
      startPhase = args[i + 1];
      i++;
    } else if (arg === "--verbose" || arg === "-v") {
      verbose = true;
    } else if (arg === "--export" && args[i + 1]) {
      exportPath = args[i + 1];
      i++;
    } else if (!arg.startsWith("--")) {
      // 位置引数として intent を解釈
      intent = arg;
    }
  }
  
  // user_textが指定されている場合、実際のintent分類を実行
  if (userText) {
    try {
      // Pythonのclassify_intentを呼び出す
      const { execSync } = require("child_process");
      const escapedText = userText.replace(/"/g, '\\"').replace(/\$/g, '\\$').replace(/'/g, "\\'");
      // 一時ファイルを使用してPythonスクリプトを実行
      const fs = require("fs");
      const os = require("os");
      const tmpFile = path.join(os.tmpdir(), `flow_test_${Date.now()}.py`);
      const pythonScript = `import sys
sys.path.insert(0, '/opt/libertycall')
from libertycall.gateway.intent_rules import classify_intent
text = ${JSON.stringify(userText)}
intent = classify_intent(text)
print(intent)
`;
      fs.writeFileSync(tmpFile, pythonScript, "utf-8");
      const result = execSync(`python3 "${tmpFile}"`, { encoding: "utf-8" });
      fs.unlinkSync(tmpFile);
      intent = result.trim();
      console.log(`📝 ユーザーテキスト: "${userText}"`);
      console.log(`🎯 分類されたIntent: ${intent}`);
    } catch (error: any) {
      console.warn(`⚠️  Intent分類に失敗しました。指定されたintent (${intent}) を使用します。`);
      if (verbose) {
        console.warn(`   エラー詳細: ${error.message}`);
      }
    }
  }
  
  // フローデータを読み込む
  const flowPath = path.resolve(__dirname, "../../docs/会話フロー_JSON構造版.json");
  
  if (!fs.existsSync(flowPath)) {
    console.error(`❌ エラー: フローファイルが見つかりません: ${flowPath}`);
    process.exit(1);
  }
  
  let flowData: FlowData;
  try {
    const flowContent = fs.readFileSync(flowPath, "utf-8");
    flowData = JSON.parse(flowContent);
  } catch (error) {
    console.error(`❌ エラー: フローファイルの読み込みに失敗しました: ${error}`);
    process.exit(1);
  }
  
  // シミュレーション実行
  console.log("=".repeat(60));
  console.log(`🧠 会話フローテスト: ${intent}`);
  console.log(`   開始フェーズ: ${startPhase}`);
  console.log("=".repeat(60));
  
  const result = simulateFlow(flowData, intent, startPhase, verbose);
  
  // 結果表示
  if (!verbose) {
    console.log("\n📊 遷移ログ:");
    result.steps.forEach((step, index) => {
      console.log(`  ${index + 1}. ${step.phase} -> ${step.nextPhase || "END"} (${step.matchedCondition || "デフォルト"})`);
    });
  }
  
  console.log(`\n✅ 最終フェーズ: ${result.finalPhase}`);
  
  if (result.error) {
    console.error(`\n❌ エラー: ${result.error}`);
  }
  
  // エクスポート
  if (exportPath) {
    try {
      fs.writeFileSync(exportPath, JSON.stringify(result, null, 2), "utf-8");
      console.log(`\n💾 結果をエクスポートしました: ${exportPath}`);
    } catch (error) {
      console.error(`\n❌ エクスポートに失敗しました: ${error}`);
    }
  }
  
  console.log("=".repeat(60));
  
  process.exit(result.success ? 0 : 1);
}

if (require.main === module) {
  main();
}

export { simulateFlow, TestResult, FlowData };

