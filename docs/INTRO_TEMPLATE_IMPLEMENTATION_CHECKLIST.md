# LibertyCall: クライアント001専用イントロテンプレート実装 - 変更箇所チェックリスト

## 📋 変更概要
クライアントID `001` の場合のみ、通話開始時に固定テンプレート `000-002`（録音告知＋挨拶）を自動再生する機能を実装。

## 🔧 変更されたファイル

### 1. `/opt/libertycall/libertycall/gateway/ai_core.py`
**変更内容:**
- `on_call_start()` メソッドを追加/修正
  - クライアント001専用のイントロテンプレート（000-002）再生ロジック
  - `_call_started_calls` セットによる重複呼び出し防止
  - `_intro_played_calls` セットによるイントロ再生済みフラグ管理
  - INTROフェーズの導入（001のみ）
  - `state.meta["client_id"]` のセット（ログ用の一貫性確保）
- `on_call_end()` メソッドを追加
  - 通話終了時のフラグクリア（明示的なクリーンアップ）
  - ログ強化（source, client_id, phase, フラグ状態）
- `_reset_session_state()` メソッドを修正
  - セッション状態のみクリア（フラグは `on_call_end()` でクリア）
- `on_transcript()` メソッドを修正
  - INTROフェーズ中はTTS送信を抑制（ログ・state更新は通常通り）
- `_run_conversation_flow()` メソッドを修正
  - INTROフェーズの処理を追加
- `_synthesize_template_audio()` メソッドを修正
  - クライアント固有テンプレートの優先読み込み（client→global フォールバック）

**ロールバック方法:**
```bash
git checkout HEAD -- libertycall/gateway/ai_core.py
# または
git revert <commit_hash>
```

### 2. `/opt/libertycall/gateway/realtime_gateway.py`
**変更内容:**
- `_queue_initial_audio_sequence()` メソッドを修正
  - `ai_core.on_call_start()` の呼び出しを追加
- `_complete_console_call()` メソッドを修正
  - `ai_core.on_call_end()` の呼び出しを追加（source="_complete_console_call"）
- `_handle_hangup()` メソッドを修正
  - `ai_core.on_call_end()` の呼び出しを追加（source="_handle_hangup"）

**ロールバック方法:**
```bash
git checkout HEAD -- gateway/realtime_gateway.py
# または
git revert <commit_hash>
```

### 3. `/opt/libertycall/config/clients/001/templates.json` (新規作成)
**変更内容:**
- クライアント001専用のテンプレート定義ファイル
- テンプレートID: `000-002`（録音告知＋LibertyCall挨拶）

**ロールバック方法:**
```bash
rm /opt/libertycall/config/clients/001/templates.json
```

## 🧪 影響を受ける機能

### 影響あり
1. **クライアント001の通話開始処理**
   - イントロテンプレート（000-002）が自動再生される
   - INTROフェーズが導入される

2. **通話終了処理**
   - `on_call_end()` が呼ばれるようになる
   - フラグクリアが明示的に行われる

3. **INTROフェーズ中のユーザー発話処理**
   - TTS送信が抑制される（ログ・state更新は通常通り）

### 影響なし（既存動作維持）
1. **クライアント000, 002 などの他のクライアント**
   - 既存の動作が維持される
   - イントロテンプレートは再生されない

2. **ENTRYフェーズ以降の処理**
   - 既存の動作が維持される
   - ユーザー発話トリガーでENTRYテンプレートが送信される

## 🔍 動作確認項目

### 必須確認
- [ ] 001で通話開始 → イントロテンプレート（000-002）が再生される
- [ ] 001で通話開始 → イントロ後にENTRYテンプレートが被らない
- [ ] 001で通話開始 → ユーザーが即しゃべってもENTRYテンプレートが被らない（**耳で確認推奨**）
- [ ] 001で通話切断→復帰 → イントロが再発しない（**同一call_idの可能性含む**）
- [ ] 002で通話開始 → イントロテンプレートが再生されない（既存動作維持）

### ログ確認
- [ ] `[AICORE] on_call_start()` が出力される
- [ ] `[AICORE] intro=queued template_id=000-002` が出力される（001のみ）
- [ ] `[AICORE] intro=sent template_id=000-002` が出力される（001のみ）
- [ ] `[AICORE] Phase=INTRO, skipping TTS` が出力される（INTRO中にユーザー発話があった場合）
- [ ] `[AICORE] on_call_end()` が出力される（通話終了時）

## 🚨 ロールバック手順

1. **設定ファイルの削除**
   ```bash
   rm /opt/libertycall/config/clients/001/templates.json
   ```

2. **コードのロールバック**
   ```bash
   cd /opt/libertycall
   git checkout HEAD -- libertycall/gateway/ai_core.py gateway/realtime_gateway.py
   ```

3. **サービス再起動**
   ```bash
   systemctl restart libertycall.service
   ```

4. **動作確認**
   - 001で通話開始 → イントロテンプレートが再生されないことを確認
   - 既存の動作が維持されていることを確認

## 📝 注意事項

- 本変更はクライアント001専用の機能追加であり、他のクライアントには影響しない
- イントロテンプレート（000-002）は `/opt/libertycall/config/clients/001/templates.json` に定義されている
- テンプレートファイルが存在しない場合、イントロテンプレートは再生されない（エラーログが出力される）
- 再接続時は `call_id` が変わる可能性があるため、イントロが再発しない仕組みが実装されている
- `on_call_end()` は通常の終了経路（`_complete_console_call` / `_handle_hangup`）から呼ばれる
- 例外終了やプロセス落ちなどのレアケースでは `on_call_end()` が呼ばれない可能性がある（仕方ない）

## ✅ 最終チェック完了項目

- [x] `state.meta["client_id"]` を `on_call_start()` でセット（ログ用の一貫性確保）
- [x] INTRO→ENTRYの切り替えは送信成功時・例外時ともにENTRYへ遷移（INTROで止まり続ける事故がない）
- [x] `on_call_end()` が通常の終了経路から呼ばれることを確認

