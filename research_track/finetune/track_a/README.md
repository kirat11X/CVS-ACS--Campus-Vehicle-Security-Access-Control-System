# Track A Preparation

Track A remains split into separate tasks:

- `prepare_lpr_crops.py`: four-point plate rectification manifest, grouped by plate text.
- `prepare_vehicle_manifest.py`: vehicle detection/classification manifest from explicit COCO labels.
- `prepare_yolo_plate_detector.py`: converts the authorized Kaggle YOLO boxes into a reproducible train/validation detector split.
- `train_plate_detector.py`: approved local RTX 4050 detector smoke/full launcher.
- Plate-to-vehicle association remains a separate evaluation task requiring linked full-scene detections.
- `train_fast_plate_ocr.py`: G3-gated training entrypoint; it refuses to train without the exact Track A approval token and an external run directory.

The current Kaggle payload contains plate boxes but no OCR text labels, so it supports plate detection only. OCR training remains blocked until text-labeled Indian crops are authorized. The scripts do not infer vehicle labels from plates or collapse detection and OCR into one task.
