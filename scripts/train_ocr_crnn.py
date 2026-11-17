#!/usr/bin/env python3
"""
Production PyTorch CRNN (CNN + BiLSTM + CTC) Training Pipeline for Indian License Plates.

Trained on:
1. prepared/ocr_in_v1 (9,570 train / 2,053 val verified Indian plate crops)
2. training_1/ocr_dataset (1,081 verified statutory Indian plate crops)
Total: 10,451 train images, 2,253 validation images.

Architecture:
- Input: (B, 3, 32, 128)
- 7-layer CNN Feature Extractor
- 2-layer Bidirectional LSTM Sequence Encoder
- CTC Loss (Blank token = 0)
- Vocabulary: 36 Alphanumeric Characters (0-9, A-Z)

Saves:
- PyTorch Best Weights: weights/indian_plate_crnn_best.pt
- ONNX Optimized Export: weights/indian_plate_crnn_best.onnx
- Training Curves & Logs: runs/ocr/crnn_plate_ocr/
"""

import os
import sys
import time
import json
import csv
import random
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torch.optim.lr_scheduler import CosineAnnealingLR

ROOT_DIR = Path("/home/kirat/coding/honours")
OCR_IN_V1_DIR = Path("/home/kirat/ml-assets/campus/datasets/prepared/ocr_in_v1")
OCR_T1_DIR = ROOT_DIR / "training_1" / "ocr_dataset"
RUN_DIR = ROOT_DIR / "runs" / "ocr" / "crnn_plate_ocr"
DEST_WEIGHTS = ROOT_DIR / "weights" / "indian_plate_crnn_best.pt"
DEST_ONNX = ROOT_DIR / "weights" / "indian_plate_crnn_best.onnx"

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHAR2IDX = {ch: i + 1 for i, ch in enumerate(ALPHABET)}  # 0 is CTC Blank
IDX2CHAR = {i + 1: ch for i, ch in enumerate(ALPHABET)}
NUM_CLASSES = len(ALPHABET) + 1  # 37

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

class IndianPlateOCRDataset(Dataset):
    def __init__(self, items, img_h=32, img_w=128, is_train=False):
        self.items = items
        self.img_h = img_h
        self.img_w = img_w
        self.is_train = is_train

    def __len__(self):
        return len(self.items)

    def augment(self, img):
        # Slight brightness & contrast
        if random.random() < 0.4:
            alpha = random.uniform(0.7, 1.3)
            beta = random.uniform(-20, 20)
            img = np.clip(alpha * img + beta, 0, 255).astype(np.uint8)
        # Slight Gaussian blur
        if random.random() < 0.2:
            img = cv2.GaussianBlur(img, (3, 3), 0)
        return img

    def __getitem__(self, idx):
        img_path, text = self.items[idx]
        img = cv2.imread(str(img_path))
        if img is None:
            # Fallback zero image
            img = np.zeros((self.img_h, self.img_w, 3), dtype=np.uint8)
        else:
            if self.is_train:
                img = self.augment(img)
            img = cv2.resize(img, (self.img_w, self.img_h), interpolation=cv2.INTER_LINEAR)

        # Normalize to [-1, 1]
        img_t = torch.from_numpy(img).permute(2, 0, 1).float() / 127.5 - 1.0

        # Encode text to indices
        target = [CHAR2IDX[c] for c in text if c in CHAR2IDX]
        return img_t, torch.tensor(target, dtype=torch.long), text

def collate_fn(batch):
    imgs, targets, texts = zip(*batch)
    imgs = torch.stack(imgs, 0)
    target_lengths = torch.tensor([len(t) for t in targets], dtype=torch.long)
    flat_targets = torch.cat(targets) if targets else torch.empty(0, dtype=torch.long)
    return imgs, flat_targets, target_lengths, texts

class CRNN(nn.Module):
    def __init__(self, num_classes=NUM_CLASSES):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(3, 64, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d(2, 2),                   # 64, 16, 64
            nn.Conv2d(64, 128, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d(2, 2),                  # 128, 8, 32
            nn.Conv2d(128, 256, 3, 1, 1), nn.BatchNorm2d(256), nn.ReLU(True),               # 256, 8, 32
            nn.Conv2d(256, 256, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d((2, 2), (2, 1), (0, 1)), # 256, 4, 33
            nn.Conv2d(256, 512, 3, 1, 1), nn.BatchNorm2d(512), nn.ReLU(True),               # 512, 4, 33
            nn.Conv2d(512, 512, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d((2, 2), (2, 1), (0, 1)), # 512, 2, 34
            nn.Conv2d(512, 512, 2, 1, 0), nn.BatchNorm2d(512), nn.ReLU(True)                # 512, 1, 33
        )
        self.rnn = nn.LSTM(512, 256, bidirectional=True, num_layers=2, batch_first=True)
        self.fc = nn.Linear(512, num_classes)

    def forward(self, x):
        features = self.cnn(x)                         # (B, 512, 1, W_seq)
        features = features.squeeze(2).permute(0, 2, 1) # (B, W_seq, 512)
        out, _ = self.rnn(features)                    # (B, W_seq, 512)
        logits = self.fc(out)                          # (B, W_seq, num_classes)
        return logits

def ctc_decode(logits):
    """Greedy CTC decoder."""
    preds = logits.argmax(dim=-1).cpu().numpy()
    decoded = []
    for row in preds:
        chars = []
        prev = 0
        for p in row:
            if p != 0 and p != prev:
                chars.append(IDX2CHAR[p])
            prev = p
        decoded.append("".join(chars))
    return decoded

def levenshtein_dist(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_dist(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insert = prev[j + 1] + 1
            delete = curr[j] + 1
            subst = prev[j] + (c1 != c2)
            curr.append(min(insert, delete, subst))
        prev = curr
    return prev[-1]

def load_all_data():
    train_items = []
    val_items = []

    # 1. Prepared OCR in v1
    if OCR_IN_V1_DIR.is_dir():
        t_csv = OCR_IN_V1_DIR / "train.csv"
        v_csv = OCR_IN_V1_DIR / "val.csv"
        if t_csv.is_file():
            with open(t_csv) as f:
                for r in csv.DictReader(f):
                    p = (OCR_IN_V1_DIR / r["image_path"]).resolve()
                    if p.is_file() and r["plate_text"]:
                        clean_text = "".join(c for c in r["plate_text"].upper() if c in CHAR2IDX)
                        if len(clean_text) >= 4:
                            train_items.append((p, clean_text))
        if v_csv.is_file():
            with open(v_csv) as f:
                for r in csv.DictReader(f):
                    p = (OCR_IN_V1_DIR / r["image_path"]).resolve()
                    if p.is_file() and r["plate_text"]:
                        clean_text = "".join(c for c in r["plate_text"].upper() if c in CHAR2IDX)
                        if len(clean_text) >= 4:
                            val_items.append((p, clean_text))

    # 2. Training_1 OCR Dataset
    if OCR_T1_DIR.is_dir():
        lbl_csv = OCR_T1_DIR / "labels.csv"
        if lbl_csv.is_file():
            t1_items = []
            with open(lbl_csv) as f:
                for r in csv.DictReader(f):
                    p = OCR_T1_DIR / "images" / r["image_filename"]
                    if p.is_file() and r["plate_text"]:
                        clean_text = "".join(c for c in r["plate_text"].upper() if c in CHAR2IDX)
                        if len(clean_text) >= 4:
                            t1_items.append((p, clean_text))
            random.shuffle(t1_items)
            val_split_n = int(len(t1_items) * 0.15)
            val_items.extend(t1_items[:val_split_n])
            train_items.extend(t1_items[val_split_n:])

    random.shuffle(train_items)
    print(f"Loaded Dataset: {len(train_items)} Train crops, {len(val_items)} Validation crops.")
    return train_items, val_items

def evaluate(model, val_loader, criterion, device):
    model.eval()
    total_loss = 0.0
    exact_matches = 0
    total_chars = 0
    total_edits = 0
    total_samples = 0

    with torch.no_grad():
        for imgs, targets, target_lengths, texts in val_loader:
            imgs = imgs.to(device)
            targets = targets.to(device)
            target_lengths = target_lengths.to(device)
            b_size = imgs.size(0)

            logits = model(imgs) # (B, W_seq, num_classes)
            w_seq = logits.size(1)
            input_lengths = torch.full((b_size,), w_seq, dtype=torch.long, device=device)
            log_probs = logits.log_softmax(2).permute(1, 0, 2)

            loss = criterion(log_probs, targets, input_lengths, target_lengths)
            total_loss += loss.item() * b_size

            preds = ctc_decode(logits)
            for pred, true in zip(preds, texts):
                exact_matches += int(pred == true)
                total_edits += levenshtein_dist(pred, true)
                total_chars += len(true)
                total_samples += 1

    val_loss = total_loss / max(total_samples, 1)
    exact_acc = (exact_matches / max(total_samples, 1)) * 100.0
    cer = (total_edits / max(total_chars, 1)) * 100.0
    return val_loss, exact_acc, cer

def main():
    print("=" * 70)
    print("PyTorch Indian License Plate CRNN OCR Training Pipeline")
    print("=" * 70)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Using Compute Device: {device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

    train_items, val_items = load_all_data()
    train_dataset = IndianPlateOCRDataset(train_items, is_train=True)
    val_dataset = IndianPlateOCRDataset(val_items, is_train=False)

    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True, num_workers=4, collate_fn=collate_fn, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False, num_workers=4, collate_fn=collate_fn, pin_memory=True)

    model = CRNN(num_classes=NUM_CLASSES).to(device)
    criterion = nn.CTCLoss(blank=0, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)

    epochs = 40
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)
    scaler = torch.amp.GradScaler('cuda')

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    metrics_log = []
    best_exact_acc = 0.0

    print(f"\nStarting training for {epochs} epochs (Batch size: 64, AMP: True)...")
    start_time = time.time()

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        train_samples = 0
        ep_start = time.time()

        for imgs, targets, target_lengths, _ in train_loader:
            imgs = imgs.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)
            target_lengths = target_lengths.to(device, non_blocking=True)
            b_size = imgs.size(0)

            optimizer.zero_grad()
            with torch.amp.autocast('cuda'):
                logits = model(imgs) # (B, W_seq, num_classes)
                w_seq = logits.size(1)
                input_lengths = torch.full((b_size,), w_seq, dtype=torch.long, device=device)
                log_probs = logits.log_softmax(2).permute(1, 0, 2)
                loss = criterion(log_probs, targets, input_lengths, target_lengths)

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()

            train_loss += loss.item() * b_size
            train_samples += b_size

        scheduler.step()
        ep_time = time.time() - ep_start
        train_loss /= max(train_samples, 1)

        # Validation
        val_loss, exact_acc, cer = evaluate(model, val_loader, criterion, device)

        is_best = exact_acc > best_exact_acc
        if is_best:
            best_exact_acc = exact_acc
            DEST_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "best_exact_acc": best_exact_acc,
                "cer": cer,
                "alphabet": ALPHABET,
                "num_classes": NUM_CLASSES
            }, str(DEST_WEIGHTS))

        print(f"Epoch {epoch:02d}/{epochs:02d} [{ep_time:.1f}s] - Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | Exact Match: {exact_acc:.2f}% | CER: {cer:.2f}% {'🌟 (Best)' if is_best else ''}")

        metrics_log.append({
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "val_loss": round(val_loss, 4),
            "exact_acc": round(exact_acc, 2),
            "cer": round(cer, 2),
            "time_s": round(ep_time, 1)
        })

    total_time = (time.time() - start_time) / 60.0
    print(f"\nTraining completed in {total_time:.1f} minutes. Best Exact Accuracy: {best_exact_acc:.2f}%")

    # Save log
    with open(RUN_DIR / "metrics.json", "w") as f:
        json.dump(metrics_log, f, indent=2)

    # Export to ONNX
    print("Exporting best PyTorch model to ONNX...")
    try:
        best_ckpt = torch.load(str(DEST_WEIGHTS), map_location="cpu")
        export_model = CRNN(num_classes=NUM_CLASSES)
        export_model.load_state_dict(best_ckpt["model_state_dict"])
        export_model.eval()

        dummy_input = torch.randn(1, 3, 32, 128)
        torch.onnx.export(
            export_model,
            dummy_input,
            str(DEST_ONNX),
            input_names=["input"],
            output_names=["logits"],
            dynamic_axes={"input": {0: "batch_size"}, "logits": {0: "batch_size"}},
            opset_version=14
        )
        print(f"Exported ONNX Model to: {DEST_ONNX} ({DEST_ONNX.stat().st_size / 1e6:.1f} MB)")
    except Exception as e:
        print(f"Warning during ONNX export: {e}")

    print("\nOCR Training & Export Completed Successfully!")

if __name__ == "__main__":
    main()
