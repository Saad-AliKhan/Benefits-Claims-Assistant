# -*- coding: utf-8 -*-
"""Train the scam model and write honest numbers.  Run:  python -m scripts.train_scam"""
import json

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from app.rules import DEFAULT_RULES
from app.scam_classifier import METRICS_PATH, MODEL_DIR, MODEL_PATH, normalize_text
from scripts.scam_data import HANDWRITTEN_TEST, build, is_test_template


def new_model():
    return make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True),
        LogisticRegression(C=50, class_weight="balanced", max_iter=2000),
    )


def evaluate(model, texts, labels, block_min):
    probs = model.predict_proba([normalize_text(t) for t in texts])[:, 1]
    flagged = [p >= block_min for p in probs]
    unsure = [(1 - block_min) < p < block_min for p in probs]
    ok_idx = [i for i, y in enumerate(labels) if y == 0]
    sc_idx = [i for i, y in enumerate(labels) if y == 1]
    false_alarms = int(sum(bool(flagged[i]) for i in ok_idx))                      # genuine called scam
    missed = int(sum((not flagged[i]) and (not unsure[i]) for i in sc_idx))        # scam called safe
    to_human = int(sum(bool(u) for u in unsure))
    return {
        "n": len(labels), "n_genuine": len(ok_idx), "n_scam": len(sc_idx),
        "false_alarm_rate": round(false_alarms / max(1, len(ok_idx)), 4),
        "false_alarms": false_alarms,
        "scam_called_safe_rate": round(missed / max(1, len(sc_idx)), 4),
        "scam_called_safe": missed,
        "sent_to_human_rate": round(to_human / len(labels), 4),
        "accuracy_if_forced": round(int(sum((p >= 0.5) == bool(y) for p, y in zip(probs, labels))) / len(labels), 4),
    }


def main():
    block_min = DEFAULT_RULES["scam_block_min"]
    rows = build()
    train = [(normalize_text(t), y) for t, y, tid in rows if not is_test_template(tid)]
    held = [(t, y) for t, y, tid in rows if is_test_template(tid)]

    model = new_model().fit([t for t, _ in train], [y for _, y in train])
    held_metrics = evaluate(model, [t for t, _ in held], [y for _, y in held], block_min)
    hand_metrics = evaluate(model, [t for t, _ in HANDWRITTEN_TEST], [y for _, y in HANDWRITTEN_TEST], block_min)

    # Ship a model trained on ALL templates; the numbers above come from the held-out run.
    final = new_model().fit([normalize_text(t) for t, _, _ in rows], [y for _, y, _ in rows])
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump(final, MODEL_PATH)

    metrics = {
        "threshold_used": block_min,
        "held_out_templates": held_metrics,
        "fresh_handwritten_messages": hand_metrics,
        "notes": ("All data is mock/synthetic. 'held_out_templates' = wordings never seen in training. "
                  "'fresh_handwritten_messages' = a small separate set. Both sets are small, so treat the "
                  "numbers as rough, not as real-world accuracy."),
    }
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()