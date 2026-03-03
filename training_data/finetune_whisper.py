#!/usr/bin/env python3
"""
Whisper large-v3-turbo ファインチューニング (CPU対応)
- /opt/libertycall/training_data/segments/ から音声+テキストペアを読み込み
- LoRA で効率的にファインチューニング
- 夜間cron実行を想定
"""
import os
import sys
import glob
import logging
import torch
import soundfile as sf
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/opt/libertycall/training_data/finetune.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Config ---
MODEL_NAME = "openai/whisper-large-v3-turbo"
OUTPUT_DIR = "/opt/libertycall/training_data/model_finetuned"
SEGMENTS_DIR = "/opt/libertycall/training_data/segments"
PROCESSED_DIR = "/opt/libertycall/training_data/segments_processed"
LORA_R = 8
LORA_ALPHA = 16
BATCH_SIZE = 1  # CPU: 1が安全
GRADIENT_ACCUMULATION = 8  # 実効バッチサイズ=8
NUM_EPOCHS = 3
LEARNING_RATE = 1e-4
MAX_DURATION_SEC = 30.0
MIN_SAMPLES = 5  # 最低5サンプルないとスキップ

def load_segments():
    """音声+テキストペアを読み込み"""
    pairs = []
    wav_files = sorted(glob.glob(f"{SEGMENTS_DIR}/*.wav"))
    for wav_path in wav_files:
        txt_path = wav_path.replace('.wav', '.txt')
        if not os.path.exists(txt_path):
            logger.warning("No transcript for %s, skipping", wav_path)
            continue
        with open(txt_path) as f:
            text = f.read().strip()
        if not text:
            continue
        # Check duration
        info = sf.info(wav_path)
        if info.duration > MAX_DURATION_SEC:
            logger.warning("Too long (%.1fs): %s", info.duration, wav_path)
            continue
        if info.duration < 0.5:
            logger.warning("Too short (%.1fs): %s", info.duration, wav_path)
            continue
        pairs.append({"audio_path": wav_path, "text": text, "duration": info.duration})
    return pairs

def main():
    logger.info("=== Whisper Fine-tuning Start ===")
    logger.info("Time: %s", datetime.now().isoformat())

    # Load data
    pairs = load_segments()
    logger.info("Found %d valid training pairs", len(pairs))

    if len(pairs) < MIN_SAMPLES:
        logger.info("Not enough samples (%d < %d). Skipping.", len(pairs), MIN_SAMPLES)
        return

    total_duration = sum(p["duration"] for p in pairs)
    logger.info("Total audio: %.1f seconds (%.1f minutes)", total_duration, total_duration / 60)

    # Load processor and model
    from transformers import WhisperProcessor, WhisperForConditionalGeneration
    logger.info("Loading model: %s", MODEL_NAME)

    processor = WhisperProcessor.from_pretrained(MODEL_NAME)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL_NAME, torch_dtype=torch.float32)

    # Check for existing LoRA weights
    if os.path.exists(f"{OUTPUT_DIR}/adapter_config.json"):
        logger.info("Loading existing LoRA weights from %s", OUTPUT_DIR)
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, OUTPUT_DIR)
        model = model.merge_and_unload()

    # Apply LoRA
    from peft import LoraConfig, get_peft_model, TaskType
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.SEQ_2_SEQ_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Prepare dataset
    from datasets import Dataset, Audio
    import numpy as np

    def prepare_dataset(batch):
        audio, sr = sf.read(batch["audio_path"])
        if sr != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
        input_features = processor(
            audio, sampling_rate=16000, return_tensors="np"
        ).input_features[0]
        labels = processor.tokenizer(batch["text"]).input_ids
        return {"input_features": input_features, "labels": labels}

    dataset = Dataset.from_list(pairs)
    dataset = dataset.map(prepare_dataset, remove_columns=["audio_path", "duration"])

    # Data collator
    from dataclasses import dataclass
    from typing import Any, Dict, List, Union

    @dataclass
    class DataCollatorSpeechSeq2SeqWithPadding:
        processor: Any
        def __call__(self, features: List[Dict[str, Union[List[int], torch.Tensor]]]) -> Dict[str, torch.Tensor]:
            input_features = [{"input_features": f["input_features"]} for f in features]
            batch = self.processor.feature_extractor.pad(input_features, return_tensors="pt")
            label_features = [{"input_ids": f["labels"]} for f in features]
            labels_batch = self.processor.tokenizer.pad(label_features, return_tensors="pt")
            labels = labels_batch["input_ids"].masked_fill(
                labels_batch.attention_mask.ne(1), -100
            )
            # Remove bos token if present
            if (labels[:, 0] == model.config.decoder_start_token_id).all().cpu().item():
                labels = labels[:, 1:]
            batch["labels"] = labels
            return batch

    data_collator = DataCollatorSpeechSeq2SeqWithPadding(processor=processor)

    # Training arguments
    from transformers import Seq2SeqTrainingArguments, Seq2SeqTrainer

    training_args = Seq2SeqTrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION,
        learning_rate=LEARNING_RATE,
        num_train_epochs=NUM_EPOCHS,
        fp16=False,  # CPU
        logging_steps=1,
        save_strategy="epoch",
        remove_unused_columns=False,
        label_names=["labels"],
        dataloader_num_workers=0,
        use_cpu=True,
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=data_collator,
        processing_class=processor,
    )

    logger.info("Starting training...")
    train_result = trainer.train()
    logger.info("Training complete. Loss: %.4f", train_result.training_loss)

    # Save LoRA weights
    model.save_pretrained(OUTPUT_DIR)
    processor.save_pretrained(OUTPUT_DIR)
    logger.info("Model saved to %s", OUTPUT_DIR)

    # Move processed segments
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    for pair in pairs:
        wav = pair["audio_path"]
        txt = wav.replace('.wav', '.txt')
        for f in [wav, txt]:
            if os.path.exists(f):
                dest = os.path.join(PROCESSED_DIR, os.path.basename(f))
                os.rename(f, dest)
    logger.info("Moved %d pairs to %s", len(pairs), PROCESSED_DIR)

    logger.info("=== Fine-tuning Complete ===")

if __name__ == "__main__":
    main()
