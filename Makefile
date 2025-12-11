# LibertyCall プロジェクト Makefile

SHELL := /bin/bash

.PHONY: audio audio-clean audio-all

# Python実行コマンド（仮想環境があれば使用、なければシステムのpython3）
PYTHON := $(shell if [ -f venv/bin/python3 ]; then echo "venv/bin/python3"; else echo "python3"; fi)

# 音声テンプレート生成（110, 111, 112）
audio:
	@echo "🎙️  Generating audio templates (110, 111, 112)..."
	@export GOOGLE_APPLICATION_CREDENTIALS=/opt/libertycall/key/google_tts.json && \
	$(PYTHON) scripts/generate_no_input_audio.py
	@if [ -f clients/000/audio/template_110.wav ] && [ -f clients/000/audio/template_111.wav ] && [ -f clients/000/audio/template_112.wav ]; then \
		echo ""; \
		echo "✅ Audio templates generated successfully!"; \
		echo "  - clients/000/audio/template_110.wav"; \
		echo "  - clients/000/audio/template_111.wav"; \
		echo "  - clients/000/audio/template_112.wav"; \
	else \
		echo "⚠️  Some audio files may be missing. Please check the output above."; \
		exit 1; \
	fi

# 古い音声テンプレートを削除
audio-clean:
	@echo "🧹 Cleaning old audio templates..."
	@rm -f clients/000/audio/template_1*.wav
	@echo "🧹 Cleaned old audio templates."

# すべての不足している音声ファイルを生成（intent_rules.pyの全テンプレート）
audio-all:
	@echo "🎙️  Generating all missing audio templates..."
	@export GOOGLE_APPLICATION_CREDENTIALS=/opt/libertycall/key/google_tts.json && \
	$(PYTHON) scripts/check_and_generate_audio.py
