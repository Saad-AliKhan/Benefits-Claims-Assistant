# Training the smart-CNIC field detector

`ocr_core/models/cnic_fields.onnx` is a small YOLO11n detector. It boxes the card and each value on
the front of a smart CNIC: `Identity Number`, `Name Eng`, `FatherName Eng`, `Gender Eng`,
`Country Eng`, `Date of Birth`, `Date of Issue` and `Date of Expiry`, plus the Urdu `Name` and
`Father Name`. The service then crops each box and reads it with the OCR engine. The detector only
says *where* a field is, never *what* it says.

## How the shipped model was trained

* Data: "CNIC Detection v1" (Roboflow Universe, public domain), 263 smart-CNIC photos already split
  180 train / 66 valid / 17 test, resized to 640×640 (stretched). Annotations are COCO boxes.
* Base model: `yolo11n.pt` (Ultralytics, pre-trained on COCO).
* Settings: 45 epochs, image size 640, batch 16, CPU; **horizontal flip off** (mirrored text is not a
  real card), rotation ±4°, light perspective, mosaic off for the last 8 epochs.
* Export: ONNX (opset 17, fixed 640×640 input). At run time the service needs only `onnxruntime`,
  which it already uses; Ultralytics and PyTorch are **not** needed.

## Retraining with more photos

Add photos to the dataset in Roboflow (or any COCO tool), using the **same class names**, and
export as COCO. Then, in a separate environment (the training packages are large and are not
part of the service):

```bash
python -m venv .venv_train && .venv_train\Scripts\activate
pip install ultralytics onnx
python tools/ocr/train_cnic_detector.py --coco "C:\path\to\CNIC Detection.v2.coco" --epochs 45
```

The script converts COCO to YOLO format, trains, prints the scores on the validation split and
writes `ocr_core/models/cnic_fields.onnx`. Then run `pytest` and `tools/evaluate_labelled.py` on
your own labelled photos to check that the new model is actually better before keeping it.

## Licence note

Ultralytics YOLO and its pre-trained weights are AGPL-3.0, and a model fine-tuned from them is
generally treated as covered too. That is fine for this prototype and a hackathon demo. Before any
real deployment, either buy an Ultralytics enterprise licence or retrain with a permissively
licensed detector; the service only needs an ONNX model with the same output format.

## Switching it off

Set `OCR_CNIC_DETECTOR=0`, and smart cards are read by their printed labels alone, the way the
service did before the detector existed.
