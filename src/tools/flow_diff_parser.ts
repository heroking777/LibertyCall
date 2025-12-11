#!/usr/bin/env node
/**
 * フロー差分パーサー
 * 
 * git diffの結果から会話フローの変更を検出し、
 * 関連するintentとテスト音声ファイルを抽出します。
 * 
 * 使い方:
 *   npx ts-node src/tools/flow_diff_parser.ts <git_diff_output>
 *   git diff HEAD~1 docs/会話フロー_JSON構造版.json | npx ts-node src/tools/flow_diff_parser.ts
 */

import * as fs from "fs";
import * as path from "path";

interface FlowChange {
  phase: string;
  transition?: {
    condition: string;
    target: string;
  };
  template?: string;
  intent?: string;
}

interface ParsedDiff {
  changedPhases: string[];
  changedIntents: string[];
  changedTemplates: string[];
  relatedAudioFiles: string[];
}

/**
 * git diffの出力から変更されたフェーズを抽出
 */
function extractChangedPhases(diffContent: string): string[] {
  const phases: string[] = [];
  
  // "phases": { ... } セクション内の変更を検出
  const phasePattern = /"([A-Z_]+)":\s*\{/g;
  const addedPhases = new Set<string>();
  const removedPhases = new Set<string>();
  
  // 追加された行（+で始まる）
  const addedLines = diffContent.split('\n').filter(line => line.startsWith('+') && !line.startsWith('+++'));
  for (const line of addedLines) {
    const match = line.match(phasePattern);
    if (match) {
      addedPhases.add(match[1]);
    }
  }
  
  // 削除された行（-で始まる）
  const removedLines = diffContent.split('\n').filter(line => line.startsWith('-') && !line.startsWith('---'));
  for (const removedLine of removedLines) {
    const match = removedLine.match(phasePattern);
    if (match) {
      removedPhases.add(match[1]);
    }
  }
  
  // 変更されたフェーズ（追加または削除されたもの）
  const allPhases = new Set([...addedPhases, ...removedPhases]);
  
  // より詳細な検出: フェーズ名の前後で変更があった行を探す
  const contextPattern = /"([A-Z_]+)":\s*\{/g;
  let match;
  while ((match = contextPattern.exec(diffContent)) !== null) {
    const phaseName = match[1];
    // このフェーズの前後で変更があったかチェック
    const beforeIndex = Math.max(0, match.index - 100);
    const afterIndex = Math.min(diffContent.length, match.index + 100);
    const context = diffContent.substring(beforeIndex, afterIndex);
    
    if (context.includes('+') || context.includes('-')) {
      allPhases.add(phaseName);
    }
  }
  
  return Array.from(allPhases);
}

/**
 * 変更されたintentを抽出
 */
function extractChangedIntents(diffContent: string): string[] {
  const intents: string[] = [];
  
  // intent == 'XXX' パターンを検出
  const intentPattern = /intent\s*==\s*['"]([A-Z_]+)['"]/g;
  const addedIntents = new Set<string>();
  const removedIntents = new Set<string>();
  
  // 追加された行
  const addedLines = diffContent.split('\n').filter(line => line.startsWith('+') && !line.startsWith('+++'));
  for (const line of addedLines) {
    let match;
    while ((match = intentPattern.exec(line)) !== null) {
      addedIntents.add(match[1]);
    }
  }
  
  // 削除された行
  const removedLines = diffContent.split('\n').filter(line => line.startsWith('-') && !line.startsWith('---'));
  for (const removedLine of removedLines) {
    let match;
    while ((match = intentPattern.exec(removedLine)) !== null) {
      removedIntents.add(match[1]);
    }
  }
  
  // 変更されたintent（追加または削除されたもの）
  const allIntents = new Set([...addedIntents, ...removedIntents]);
  
  return Array.from(allIntents);
}

/**
 * 変更されたテンプレートIDを抽出
 */
function extractChangedTemplates(diffContent: string): string[] {
  const templates: string[] = [];
  
  // templates配列内のテンプレートIDを検出
  const templatePattern = /"(\d{3}(?:_SYS)?)"/g;
  const addedTemplates = new Set<string>();
  const removedTemplates = new Set<string>();
  
  // 追加された行
  const addedLines = diffContent.split('\n').filter(line => line.startsWith('+') && !line.startsWith('+++'));
  for (const line of addedLines) {
    let match;
    while ((match = templatePattern.exec(line)) !== null) {
      addedTemplates.add(match[1]);
    }
  }
  
  // 削除された行
  const removedLines = diffContent.split('\n').filter(line => line.startsWith('-') && !line.startsWith('---'));
  for (const removedLine of removedLines) {
    let match;
    while ((match = templatePattern.exec(removedLine)) !== null) {
      removedTemplates.add(match[1]);
    }
  }
  
  // 変更されたテンプレート（追加または削除されたもの）
  const allTemplates = new Set([...addedTemplates, ...removedTemplates]);
  
  return Array.from(allTemplates);
}

/**
 * intentとフェーズから関連する音声ファイルを推測
 */
function findRelatedAudioFiles(
  intents: string[],
  phases: string[],
  templates: string[],
  audioTestDir: string
): string[] {
  const relatedFiles: string[] = [];
  
  if (!fs.existsSync(audioTestDir)) {
    return relatedFiles;
  }
  
  const audioFiles = fs.readdirSync(audioTestDir)
    .filter(f => f.endsWith(".wav"))
    .map(f => path.join(audioTestDir, f));
  
  // intent名からファイル名を推測
  const intentToFileMap: Record<string, string[]> = {
    "INQUIRY": ["inquiry", "question", "005"],
    "SALES_CALL": ["sales", "introduction", "006"],
    "HANDOFF_REQUEST": ["handoff", "transfer", "担当者"],
    "END_CALL": ["end", "goodbye", "086", "087"],
    "NOT_HEARD": ["not_heard", "noise", "110"],
    "GREETING": ["greeting", "moshimoshi", "004"],
    "HANDOFF_YES": ["yes", "ok", "承知"],
    "HANDOFF_NO": ["no", "いいえ", "不要"],
  };
  
  // フェーズ名からファイル名を推測
  const phaseToFileMap: Record<string, string[]> = {
    "ENTRY": ["entry", "004", "005"],
    "QA": ["qa", "inquiry", "question"],
    "HANDOFF_CONFIRM_WAIT": ["handoff", "confirm", "0604"],
    "AFTER_085": ["after", "085", "followup"],
  };
  
  // テンプレートIDから直接ファイル名を推測
  for (const template of templates) {
    const templateNum = template.replace("_SYS", "");
    relatedFiles.push(...audioFiles.filter(f => f.includes(templateNum)));
  }
  
  // intentからファイル名を推測
  for (const intent of intents) {
    const keywords = intentToFileMap[intent] || [intent.toLowerCase()];
    for (const keyword of keywords) {
      relatedFiles.push(...audioFiles.filter(f => 
        f.toLowerCase().includes(keyword.toLowerCase())
      ));
    }
  }
  
  // フェーズからファイル名を推測
  for (const phase of phases) {
    const keywords = phaseToFileMap[phase] || [phase.toLowerCase()];
    for (const keyword of keywords) {
      relatedFiles.push(...audioFiles.filter(f => 
        f.toLowerCase().includes(keyword.toLowerCase())
      ));
    }
  }
  
  // 重複を除去
  return Array.from(new Set(relatedFiles));
}

/**
 * git diffの内容をパース
 */
function parseFlowDiff(diffContent: string, audioTestDir: string): ParsedDiff {
  const changedPhases = extractChangedPhases(diffContent);
  const changedIntents = extractChangedIntents(diffContent);
  const changedTemplates = extractChangedTemplates(diffContent);
  const relatedAudioFiles = findRelatedAudioFiles(
    changedIntents,
    changedPhases,
    changedTemplates,
    audioTestDir
  );
  
  return {
    changedPhases,
    changedIntents,
    changedTemplates,
    relatedAudioFiles,
  };
}

/**
 * 簡易版: intentのみを抽出（実装計画に合わせて簡潔化）
 */
function extractChangedIntentsSimple(diffContent: string): string[] {
  const intents: string[] = [];
  
  // intent == 'XXX' パターンを検出
  const intentPattern = /intent\s*==\s*['"]([A-Z_]+)['"]/g;
  const addedIntents = new Set<string>();
  const removedIntents = new Set<string>();
  
  // 追加された行
  const addedLines = diffContent.split('\n').filter(line => line.startsWith('+') && !line.startsWith('+++'));
  for (const line of addedLines) {
    let match;
    while ((match = intentPattern.exec(line)) !== null) {
      addedIntents.add(match[1]);
    }
  }
  
  // 削除された行
  const removedLines = diffContent.split('\n').filter(line => line.startsWith('-') && !line.startsWith('---'));
  for (const removedLine of removedLines) {
    let match;
    while ((match = intentPattern.exec(removedLine)) !== null) {
      removedIntents.add(match[1]);
    }
  }
  
  // 変更されたintent（追加または削除されたもの）
  const allIntents = new Set([...addedIntents, ...removedIntents]);
  
  return Array.from(allIntents);
}

/**
 * メイン処理
 */
function main() {
  const args = process.argv.slice(2);
  
  let diffContent = "";
  
  if (args.length > 0 && args[0] !== "-") {
    // ファイルパスが指定された場合
    const filePath = path.resolve(args[0]);
    if (fs.existsSync(filePath)) {
      diffContent = fs.readFileSync(filePath, "utf-8");
    } else {
      console.error(`❌ エラー: ファイルが見つかりません: ${filePath}`);
      process.exit(1);
    }
  } else {
    // 標準入力から読み込む
    const chunks: Buffer[] = [];
    let chunk: Buffer;
    while ((chunk = process.stdin.read()) !== null) {
      chunks.push(chunk);
    }
    diffContent = Buffer.concat(chunks).toString("utf-8");
  }
  
  if (!diffContent) {
    // 空の場合は空配列を返す
    console.log(JSON.stringify({ changedIntents: [] }));
    process.exit(0);
  }
  
  // 簡易版: intentのみを抽出
  const changedIntents = extractChangedIntentsSimple(diffContent);
  
  // 結果をJSON形式で出力（changedIntentsのみ）
  console.log(JSON.stringify({ changedIntents }));
}

if (require.main === module) {
  main();
}

export { parseFlowDiff, ParsedDiff, FlowChange };

