# Google ASR / TTS システム仕様（LibertyCall）

## 1. 使用ライブラリ

- google-cloud-speech==2.34.0
- google-cloud-texttospeech==2.33.0
- いずれも /opt/libertycall/requirements.txt にバージョン固定で記載済み。

## 2. 認証とプロジェクト

- 標準サービスアカウント JSON:
  - /opt/libertycall/key/google_tts.json
  - project_id: libertycall-main

- 認証ファイル解決の優先順位（GoogleASR.__init__）:
  1. 環境変数 GOOGLE_APPLICATION_CREDENTIALS
  2. 環境変数 LC_GOOGLE_CREDENTIALS_PATH
  3. AICore / GoogleASR 初期化引数 credentials_path
  4. デフォルト: /opt/libertycall/key/google_tts.json
     （将来用に /opt/libertycall/key/libertycall-main-7e4af202cdff.json も候補として残している）

- 実際に採用されたパスはログに INFO レベルで出力:
  - "GoogleASR: using credentials file: /opt/libertycall/key/google_tts.json"

## 3. 必須環境変数（本番）

- LC_ASR_PROVIDER=google
- LC_ASR_STREAMING_ENABLED=1 or 0
- LC_GOOGLE_PROJECT_ID=libertycall-main
- LC_GOOGLE_CREDENTIALS_PATH=/opt/libertycall/key/google_tts.json
- GOOGLE_APPLICATION_CREDENTIALS=/opt/libertycall/key/google_tts.json

## 4. 障害時の挙動

- GoogleASR ストリームエラー（ネットワーク障害 / 認証切れなど）の場合:
  - ai_core.GoogleASR が error を検知し、AICore._on_asr_error をコール
  - _on_asr_error の処理:
    - ログ: "ASR_ERROR_HANDLER: call_id=... error=..."
    - フォールバック発話:
      - 「恐れ入ります。うまくお話をお伺いできませんでしたので、担当者におつなぎいたします。」
    - セッション状態:
      - handoff_state = "done"
      - transfer_requested = True
    - 転送:
      - transfer_callback(call_id) を1回だけ実行
    - gateway 側には tts_callback でフォールバック音声と template_ids=["081","082"] を渡す

- ポリシー:
  - AI 内で粘らず、「ASR 落ちたら担当者に転送して逃げる」設計を採用。
  - 転送ラッシュ制御は別レイヤ（運用 or 将来の制御）で扱う。

