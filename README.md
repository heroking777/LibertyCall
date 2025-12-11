# Project State Backend

案件ごとに長期記憶を持てる開発アシスタント用バックエンドAPI。

ChatGPT / カスタムGPT / MCPから叩いて、「チャットを変えても案件ごとのコンテキストを復元する」ための"外部記憶サーバー"として機能します。

## セットアップ

### 1. 依存関係のインストール

```bash
npm install
```

### 2. 開発サーバーの起動

```bash
npm run dev
```

サーバーは `http://localhost:3000` で起動します。

### 3. ビルド（本番用）

```bash
npm run build
npm start
```

## 提供されるエンドポイント

### 1. 案件一覧取得

```bash
GET /projects
```

**レスポンス例:**
```json
[
  {
    "projectId": "ai-phone-main",
    "name": "AI電話システム本体",
    "type": "ai_phone"
  }
]
```

### 2. 特定案件の状態取得

```bash
GET /projects/:projectId/state
```

**レスポンス例:**
```json
{
  "projectId": "ai-phone-main",
  "name": "AI電話システム本体",
  "type": "ai_phone",
  "summary": "...",
  "techStack": ["Python", "FastAPI"],
  "status": "in_progress",
  "currentFocus": "...",
  "tasks": [...],
  "decisions": [...],
  "issues": [...],
  "importantFiles": [...],
  "updatedAt": "2024-01-25T09:15:00.000Z"
}
```

**エラー時（404）:**
```json
{
  "error": "not_found",
  "message": "Project with id \"xxx\" not found"
}
```

### 3. 特定案件の状態保存（新規 or 更新）

```bash
POST /projects/:projectId/state
Content-Type: application/json
```

**リクエストボディ例:**
```json
{
  "name": "AI電話システム本体",
  "type": "ai_phone",
  "summary": "プロジェクトの概要...",
  "techStack": ["Python", "FastAPI"],
  "status": "in_progress",
  "currentFocus": "現在のフォーカス",
  "tasks": [
    {
      "id": "task-1",
      "title": "タスク名",
      "status": "doing",
      "note": "メモ"
    }
  ],
  "decisions": [],
  "issues": [],
  "importantFiles": []
}
```

**注意:**
- `projectId` は URL パラメータのものが優先されます
- `updatedAt` はサーバー側で自動的に現在時刻がセットされます
- 既存データがある場合はマージされます

**レスポンス:**
保存後のフル `ProjectState` オブジェクトが返されます。

### 4. 簡易ログ追記

```bash
POST /projects/:projectId/logs
Content-Type: application/json
```

**リクエストボディ例:**
```json
{
  "summary": "通話ログ要約バッチのベース実装完了。TODO: エラー処理追加。"
}
```

**レスポンス例:**
```json
{
  "success": true,
  "log": {
    "summary": "通話ログ要約バッチのベース実装完了。TODO: エラー処理追加。",
    "createdAt": "2024-01-25T10:30:00.000Z"
  }
}
```

### 5. ヘルスチェック

```bash
GET /health
```

**レスポンス:**
```json
{
  "status": "ok"
}
```

## 使い方の例

### curl を使った例

#### 案件一覧を取得
```bash
curl http://localhost:3000/projects
```

#### 特定案件の状態を取得
```bash
curl http://localhost:3000/projects/ai-phone-main/state
```

#### 案件の状態を更新
```bash
curl -X POST http://localhost:3000/projects/ai-phone-main/state \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI電話システム本体",
    "type": "ai_phone",
    "summary": "更新された概要",
    "techStack": ["Python", "FastAPI", "Asterisk"],
    "status": "in_progress",
    "currentFocus": "新しいフォーカス",
    "tasks": [],
    "decisions": [],
    "issues": [],
    "importantFiles": []
  }'
```

#### ログを追記
```bash
curl -X POST http://localhost:3000/projects/ai-phone-main/logs \
  -H "Content-Type: application/json" \
  -d '{
    "summary": "新しい進捗メモ"
  }'
```

### HTTPie を使った例

#### 案件一覧を取得
```bash
http GET http://localhost:3000/projects
```

#### 特定案件の状態を取得
```bash
http GET http://localhost:3000/projects/ai-phone-main/state
```

#### 案件の状態を更新
```bash
http POST http://localhost:3000/projects/ai-phone-main/state \
  name="AI電話システム本体" \
  type="ai_phone" \
  summary="更新された概要" \
  techStack:='["Python","FastAPI"]' \
  status="in_progress" \
  currentFocus="新しいフォーカス" \
  tasks:='[]' \
  decisions:='[]' \
  issues:='[]' \
  importantFiles:='[]'
```

## データ保存

- プロジェクト状態は `project_states.json` に保存されます
- ログは `project_logs.json` に保存されます
- どちらもルートディレクトリに作成されます

## エラーハンドリング

- **400 Bad Request**: バリデーションエラー（必須フィールドの欠如、型の不一致など）
- **404 Not Found**: 指定されたプロジェクトが見つからない
- **500 Internal Server Error**: サーバー内部エラー（ファイルI/Oエラーなど）

エラーレスポンスは以下の形式です:
```json
{
  "error": "error_code",
  "message": "エラーメッセージ"
}
```

## カスタムGPTとの連携

### 1. OpenAPI定義のインポート

1. ChatGPTのカスタムGPTビルダーを開く
2. **Actions** → **Add Action** → **"Import from URL / file"** を選択
3. `openapi.yaml` ファイルをアップロード、またはURLを指定
   - ローカル環境の場合: サーバーを起動した状態で、`openapi.yaml` の `servers.url` を確認
   - 本番環境の場合: `openapi.yaml` の `servers` セクションで本番URLを指定

### 2. 指示文の設定

1. カスタムGPTビルダーの **Instructions / 指示** 欄を開く
2. `custom_gpt_instructions.txt` の内容をコピー＆ペースト
3. 必要に応じて、あなたの案件やワークフローに合わせてカスタマイズ

### 3. 動作確認

カスタムGPTで以下のように話しかけてみてください：

```
「AI電話案件の続きやるわ」
```

GPTが自動的に：
1. `listProjects` で案件一覧を取得
2. `getProjectState("ai-phone-main")` で状態を取得
3. 前回の続きから会話を開始

するはずです。

## 今後の拡張予定

- SQLite や Supabase への移行
- 認証・認可機能の追加
- より詳細なログ機能
- プロジェクト間の依存関係管理

## ライセンス

ISC
