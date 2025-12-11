# 管理画面UI更新サマリー

## 概要
通話ログ管理画面のUIをLP（ランディングページ）と同じトーンに統一しました。

## 変更ファイル

### 新規作成
- `frontend/src/components/ConsoleHeader.jsx` - LPと同じヘッダーコンポーネント
- `frontend/src/components/ConsoleHeader.css` - ヘッダーのスタイル（LPから移植）
- `frontend/src/components/ConsoleLayout.jsx` - 共通レイアウトコンポーネント
- `frontend/src/components/ConsoleLayout.css` - レイアウトのスタイル

### 修正
- `frontend/src/App.jsx` - ConsoleLayoutでラップ、既存ヘッダーを削除
- `frontend/src/App.css` - 既存ヘッダー関連スタイルを削除
- `frontend/src/index.css` - フォントと背景色をLPに合わせて更新
- `frontend/src/pages/FileLogsList.css` - テキスト色と背景をダークネイビーに合わせて調整
- `frontend/src/pages/FileLogDetail.css` - テキスト色と背景をダークネイビーに合わせて調整

## デザイン仕様

### ヘッダー
- 背景: `rgba(4, 8, 24, 0.9)` + backdrop-filter blur
- ロゴ: 34x34pxの円形グラデーション（#1f55d6 → #5dd8ff）に「LC」
- ブランドテキスト: 「LibertyCall」（大きめ） + 「AI Telephone System」（小さめ）
- ナビゲーション: 「課題 / 特徴 / 料金 / 導入フロー」（「資料請求」は非表示）

### 背景
- 全体背景: `linear-gradient(135deg, #040818 0%, #0a1440 65%, #0b1f4f 100%)`
- コンテンツカード: `rgba(255, 255, 255, 0.95)` で浮き上がる見た目

### フォント
- フォントファミリ: `"Inter", "Noto Sans JP", system-ui, ...`

## 今後の調整ポイント
- ヘッダーのナビゲーションリンクは現在 `#` に設定。必要に応じてLPへのアンカーリンクに変更可能
- レスポンシブ対応は基本的にLPと同じ（768px以下でナビゲーション非表示）

