"""Download PaddleOCR-VL-1.6 (one time, ~2 GB, Apache-2.0, not gated) into models/paddleocr-vl-1.6.

    pip install -r requirements-vl.txt --extra-index-url https://download.pytorch.org/whl/cpu
    python tools/ocr/fetch_vl.py

Then restart the app. It is used as the second reader by default (OCR_VL=when_unsure); /health/ai shows it under
"second_reader". OCR_VL=off in .env switches it off.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from ocr_core.vl import FOLDER, HF_REPO
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("Install the packages first:  pip install -r requirements-vl.txt")
    print(f"Downloading {HF_REPO} -> {FOLDER} (resumes if interrupted) ...")
    # the transformers files only: the PaddlePaddle-format copies in the repo are not needed
    snapshot_download(HF_REPO, local_dir=str(FOLDER),
                      allow_patterns=["*.json", "*.safetensors", "*.py", "*.txt", "*.model", "*.jinja", "*.md"])
    print("Done. Restart the app; http://127.0.0.1:8080/health/ai shows 'second_reader'.")


if __name__ == "__main__":
    main()
