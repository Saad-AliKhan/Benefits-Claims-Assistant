"""Train the smart-CNIC field detector from a COCO export and write ocr_core/models/cnic_fields.onnx.
See tools/train_cnic_detector.md. Needs `pip install ultralytics onnx` (not part of the service)."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root
OUT = ROOT / "ocr_core" / "models" / "cnic_fields.onnx"


def coco_to_yolo(src: Path, dst: Path) -> Path:
    names = None
    for split in ("train", "valid", "test"):
        ann = src / split / "_annotations.coco.json"
        if not ann.exists():
            continue
        d = json.loads(ann.read_text(encoding="utf-8"))
        cats = sorted((c["id"], c["name"]) for c in d["categories"] if c["name"] != "words")  # Roboflow's parent class
        idmap = {cid: i for i, (cid, _) in enumerate(cats)}
        names = [n for _, n in cats]
        (dst / "images" / split).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / split).mkdir(parents=True, exist_ok=True)
        by_image: dict[int, list] = {}
        for a in d["annotations"]:
            if a["category_id"] in idmap:
                by_image.setdefault(a["image_id"], []).append(a)
        for im in d["images"]:
            shutil.copy(src / split / im["file_name"], dst / "images" / split / im["file_name"])
            w, h = im["width"], im["height"]
            lines = []
            for a in by_image.get(im["id"], []):
                x, y, bw, bh = a["bbox"]
                lines.append(f"{idmap[a['category_id']]} {(x + bw / 2) / w:.6f} {(y + bh / 2) / h:.6f} "
                             f"{bw / w:.6f} {bh / h:.6f}")
            (dst / "labels" / split / (Path(im["file_name"]).stem + ".txt")).write_text("\n".join(lines))
    yaml = dst / "data.yaml"
    yaml.write_text(f"path: {dst.as_posix()}\ntrain: images/train\nval: images/valid\ntest: images/test\nnames:\n"
                    + "".join(f"  {i}: {n}\n" for i, n in enumerate(names or [])))
    return yaml


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coco", type=Path, required=True, help="folder with train/valid/test COCO exports")
    ap.add_argument("--work", type=Path, default=ROOT / "train_work")
    ap.add_argument("--epochs", type=int, default=45)
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    from ultralytics import YOLO

    data = coco_to_yolo(a.coco, a.work / "yolo")
    model = YOLO("yolo11n.pt")
    model.train(data=str(data), epochs=a.epochs, imgsz=640, batch=16, device=a.device, fliplr=0.0, degrees=4,
                perspective=0.0005, close_mosaic=8, project=str(a.work / "runs"), name="cnic_fields",
                exist_ok=True, plots=False, seed=0)
    metrics = model.val(data=str(data), split="val", imgsz=640, device=a.device)
    print(f"validation mAP50={metrics.box.map50:.3f} mAP50-95={metrics.box.map:.3f}")
    onnx = Path(model.export(format="onnx", imgsz=640, opset=17, dynamic=False, simplify=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(onnx, OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
