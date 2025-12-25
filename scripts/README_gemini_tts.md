# Gemini 2.0 API 日本語TTS音声生成スクリプト

## 概要

Gemini 2.0 Flash APIを使用して、日本語テキストから音声ファイル（WAV形式）を生成するスクリプトです。

## 機能

- voice_list_000.tsvから000-003の音声テキストを読み込み
- Gemini 2.0 Flash with multimodal live APIで音声生成
- WAV形式（24kHz、16bit、モノラル）で出力
- エラーハンドリングと進捗表示

## 必要な環境

- Python 3.8以上
- google-generativeai パッケージ（既にrequirements.txtに含まれています）

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 2. 認証情報の設定

以下のいずれかの方法で認証情報を設定してください：

#### 方法1: APIキーを使用

```bash
export GOOGLE_API_KEY="your-api-key"
```

#### 方法2: サービスアカウントキーを使用

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
```

## 使用方法

```bash
python scripts/generate_gemini_tts.py
```

## 出力

生成された音声ファイルは `output/` ディレクトリに保存されます：

- `output/000.wav` - この通話は品質向上のため録音させて戴きます
- `output/001.wav` - お電話ありがとうございます
- `output/002.wav` - リバティーコールです。
- `output/003.wav` - はい。

## 音声仕様

- サンプリングレート: 24kHz
- ビット深度: 16bit
- チャンネル: モノラル
- 形式: WAV (LINEAR16)

## 注意事項

1. **Gemini 2.0 APIの音声生成機能について**
   - 実際のGemini 2.0 APIが音声合成（TTS）機能をサポートしているかどうかは、最新のAPIドキュメントを確認してください
   - もし音声生成機能がサポートされていない場合は、エラーメッセージが表示されます

2. **APIキーの取得方法**
   - Google AI Studio (https://makersuite.google.com/app/apikey) からAPIキーを取得できます
   - または、Google Cloud Consoleでサービスアカウントキーを作成してください

3. **モデル名**
   - デフォルトで `gemini-2.0-flash-exp` を使用します
   - 最新のモデル名に変更する場合は、スクリプト内の `GEMINI_MODEL` 変数を編集してください

## トラブルシューティング

### エラー: 認証情報が設定されていません

→ `GOOGLE_API_KEY` または `GOOGLE_APPLICATION_CREDENTIALS` 環境変数を設定してください

### エラー: google-generativeai がインストールされていません

→ `pip install google-generativeai` を実行してください

### エラー: 音声合成に失敗しました

→ Gemini 2.0 APIの音声生成機能がサポートされていない可能性があります。最新のAPIドキュメントを確認してください

## 関連ファイル

- `scripts/generate_gemini_tts.py` - メインスクリプト
- `clients/000/voice_list_000.tsv` - 音声テキストリスト
- `output/` - 音声ファイル出力先

