"""EmbeddingClassifier - Whisper embedding + MFCC features for audio classification."""

import numpy as np
import pickle
import logging
import librosa
from faster_whisper.feature_extractor import FeatureExtractor
import ctranslate2

logger = logging.getLogger(__name__)

MODEL_DIR = "/opt/libertycall/training_data/embeddings"

class EmbeddingClassifier:
    def __init__(self):
        self._scaler = pickle.load(open(f"{MODEL_DIR}/scaler_v2.pkl", "rb"))
        self._pca = pickle.load(open(f"{MODEL_DIR}/pca_v2.pkl", "rb"))
        self._classifier = pickle.load(open(f"{MODEL_DIR}/classifier_lr_v2.pkl", "rb"))
        self._ext = FeatureExtractor()
        self._ct = None
        
        # MFCC設定を読み込み
        try:
            self._config = pickle.load(open(f"{MODEL_DIR}/config_v2.pkl", "rb"))
            self._use_mfcc = self._config.get("use_mfcc", False)
        except:
            self._use_mfcc = False
        
        n_classes = len(self._classifier.classes_)
        logger.info("[EMB_CLF] loaded classifier: %d classes, PCA=%d dims, mfcc=%s",
                     n_classes, self._pca.n_components_, self._use_mfcc)

        # Warmup: preload librosa and run dummy inference
        try:
            dummy = np.zeros(16000, dtype=np.float32)  # 1s silence
            self._get_mfcc_features(dummy)
            logger.info("[EMB_CLF] warmup complete - librosa preloaded")
        except Exception as e:
            logger.warning("[EMB_CLF] warmup failed: %s", e)
    
    def set_ct_model(self, ct_model):
        self._ct = ct_model
    
    def _get_embedding(self, audio_16k):
        features = self._ext(audio_16k)
        sv = ctranslate2.StorageView.from_array(np.expand_dims(features, 0))
        out = np.array(self._ct.encode(sv))
        return out[0].mean(axis=0)
    
    def _get_mfcc_features(self, audio_16k):
        mfcc = librosa.feature.mfcc(y=audio_16k, sr=16000, n_mfcc=20)
        delta = librosa.feature.delta(mfcc)
        delta2 = librosa.feature.delta(mfcc, order=2)
        feats = []
        for f in [mfcc, delta, delta2]:
            feats.extend([f.mean(axis=1), f.std(axis=1)])
        return np.concatenate(feats)
    
    def classify(self, audio_16k):
        emb = self._get_embedding(audio_16k)
        
        if self._use_mfcc:
            mfcc_feat = self._get_mfcc_features(audio_16k)
            feature_vec = np.concatenate([emb, mfcc_feat])
        else:
            feature_vec = emb
        
        feature_vec = feature_vec.reshape(1, -1)
        scaled = self._scaler.transform(feature_vec)
        reduced = self._pca.transform(scaled)
        
        proba = self._classifier.predict_proba(reduced)[0]
        best_idx = np.argmax(proba)
        label = self._classifier.classes_[best_idx]
        confidence = proba[best_idx]
        
        return label, float(confidence)
