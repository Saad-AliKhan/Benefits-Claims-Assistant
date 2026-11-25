"""Download Indic-Transcribe Core (one time) into models/.

The model is gated on Hugging Face. Once:
  1. Open https://huggingface.co/bodhan-ai/indic-transcribe-core, sign in and accept the Indic Open Model License.
     (For the lighter ONNX version, also accept https://huggingface.co/hari31416/indic-transcribe-onnx-int8.)
  2. Make a read token (huggingface.co/settings/tokens) and run:  hf auth login   (or set HF_TOKEN=...)
Then, from the project folder:
    python tools/voice/fetch_indic.py            # official model, PyTorch: 4.6 GB -> models/indic-transcribe-core
    python tools/voice/fetch_indic.py --onnx     # community ONNX int8: 1.5 GB -> models/indic-transcribe-onnx-int8
and set WHISPER_MODEL=indic (or indic-onnx) in .env. Check http://127.0.0.1:8080/health/ai after a restart.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from voice_core.indic import FOLDERS, HF_REPOS
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", action="store_true", help="the lighter community ONNX export instead of the official model")
    a = ap.parse_args()
    runtime = "onnx" if a.onnx else "pytorch"
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError
    except ImportError:
        sys.exit("Install the download tool first:  pip install -r requirements-indic.txt")
    repo, dest = HF_REPOS[runtime], FOLDERS[runtime]
    print(f"Downloading {repo} -> {dest} (resumes if interrupted) ...")
    try:
        snapshot_download(repo, local_dir=str(dest))
    except GatedRepoError:
        sys.exit(f"No access yet. Open https://huggingface.co/{repo}, accept the licence, then run 'hf auth login'.")
    except RepositoryNotFoundError:
        sys.exit(f"Not found or not signed in: run 'hf auth login' with a token, then try again ({repo}).")
    print(f"Done. Put WHISPER_MODEL={'indic-onnx' if a.onnx else 'indic'} in .env and restart the app.")


if __name__ == "__main__":
    main()
