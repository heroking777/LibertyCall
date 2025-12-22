# FreeSWITCH Dialplan - LibertyCall

段階的アナウンス（sleep + transfer）構成  
loopback経由でも安定動作する構成です。

## 📁 構成

```
freeswitch/
├── README.md
├── dialplan/
│   ├── default.xml      # 段階アナウンス（sleep+transfer）設定
│   └── public.xml       # 外線経由の入口（FORCE_PUBLICエントリ）
└── audio/
    ├── 000_8k.wav
    ├── 001_8k.wav
    ├── 002_8k.wav
    ├── 000-004_8k.wav
    ├── 000-005_8k.wav
    ├── 000-006_8k.wav
    └── combined_intro_8k.wav  # 000+001+002統合ファイル
```

## 🎯 動作フロー

1. `combined_intro_8k.wav` 再生（000+001+002統合）
2. `sleep(5000)` → `transfer(next_announce)`
3. `000-004_8k.wav` 再生
4. `sleep(10000)` → `transfer(warn_announce)`
5. `000-005_8k.wav` 再生
6. `sleep(10000)` → `transfer(final_announce)`
7. `000-006_8k.wav` 再生
8. `sleep(10000)` → `transfer(hangup_call)`
9. 正常終了（NORMAL_CLEARING）

## 🔧 デプロイ方法

```bash
# dialplanファイルをFreeSWITCHに配置
sudo cp freeswitch/dialplan/default.xml /usr/local/freeswitch/conf/dialplan/
sudo cp freeswitch/dialplan/public.xml /usr/local/freeswitch/conf/dialplan/

# 音声ファイルを配置
sudo cp freeswitch/audio/*.wav /opt/libertycall/clients/000/audio/

# FreeSWITCH設定リロード
sudo /usr/local/freeswitch/bin/fs_cli -x "reloadxml"
sudo /usr/local/freeswitch/bin/fs_cli -x "reload mod_dialplan_xml"
```

## 📝 技術詳細

- **方式**: `sleep` + `transfer`（タイマー制御）
- **理由**: `detect_silence`はloopback経由では入力ストリームが存在しないため機能しない
- **利点**: loopback経由でも確実に動作、無音検出失敗のリスクなし、安定したタイミングで段階遷移

## ✅ 動作確認済み

- 2025-12-22 20:59発信: 全ステップ正常動作、正常終了（NORMAL_CLEARING）

