#!/usr/bin/env python3
"""
Extended OCR Training (Epochs 41 -> 80) for Indian License Plates.
Resumes from weights/indian_plate_crnn_best.pt with enhanced augmentations:
- Tilt and small perspective shifts
- Road motion blur
- Low-light CCTV sensor noise
- Fine learning rate cosine annealing schedule
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
RUN_DIR = ROOT_DIR / "runs" / "ocr" / "crnn_plate_ocr_extended"
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

class EnhancedIndianPlateOCRDataset(Dataset):
    def __init__(self, items, img_h=32, img_w=128, is_train=False):
        self.items = items
        self.img_h = img_h
        self.img_w = img_w
        self.is_train = is_train

    def __len__(self):
        return len(self.items)

    def augment(self, img):
        h, w = img.shape[:2]
        # 1. Photometric jitter (brightness / contrast)
        if random.random() < 0.4:
            alpha = random.uniform(0.75, 1.25)
            beta = random.uniform(-25, 25)
            img = np.clip(alpha * img + beta, 0, 255).astype(np.uint8)

        # 2. Slight rotation / perspective tilt (-4 to +4 degrees)
        if random.random() < 0.35:
            angle = random.uniform(-4, 4)
            M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
            img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

        # 3. Motion blur (horizontal or slight angle)
        if random.random() < 0.25:
            ksize = random.choice([3, 5])
            kernel = np.zeros((ksize, ksize))
            kernel[int((ksize - 1) / 2), :] = np.ones(ksize)
            kernel /= ksize
            img = cv2.filter2D(img, -1, kernel)

        # 4. Low-light sensor Gaussian noise
        if random.random() < 0.2:
            noise = np.random.normal(0, random.uniform(3, 8), img.shape)
            img = np.clip(img + noise, 0, 255).astype(np.uint8)

        return img

    def __getitem__(self, idx):
        img_path, text = self.items[idx]
        img = cv2.imread(str(img_path))
        if img is None:
            img = np.zeros((self.img_h, self.img_w, 3), dtype=np.uint8)
        else:
            if self.is_train:
                img = self.augment(img)
            img = cv2.resize(img, (self.img_w, self.img_h), interpolation=cv2.INTER_LINEAR)

        img_t = torch.from_numpy(img).permute(2, 0, 1).float() / 127.5 - 1.0
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
            nn.Conv2d(3, 64, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d(2, 2),
            nn.Conv2d(64, 128, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d(2, 2),
            nn.Conv2d(128, 256, 3, 1, 1), nn.BatchNorm2d(256), nn.ReLU(True),
            nn.Conv2d(256, 256, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d((2, 2), (2, 1), (0, 1)),
            nn.Conv2d(256, 512, 3, 1, 1), nn.BatchNorm2d(512), nn.ReLU(True),
            nn.Conv2d(512, 512, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d((2, 2), (2, 1), (0, 1)),
            nn.Conv2d(512, 512, 2, 1, 0), nn.BatchNorm2d(512), nn.ReLU(True)
        )
        self.rnn = nn.LSTM(512, 256, bidirectional=True, num_layers=2, batch_first=True)
        self.fc = nn.Linear(512, num_classes)

    def forward(self, x):
        features = self.cnn(x)
        features = features.squeeze(2).permute(0, 2, 1)
        out, _ = self.rnn(features)
        logits = self.fc(out)
        return logits

def ctc_decode(logits):
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
    print(f"Dataset: {len(train_items)} Train crops, {len(val_items)} Validation crops.")
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

            logits = model(imgs)
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
    print("Extended OCR Training (Epochs 41 -> 80) for Indian Plates")
    print(f"Resuming weights from: {DEST_WEIGHTS}")
    print("=" * 70)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Using Compute Device: {device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

    train_items, val_items = load_all_data()
    train_dataset = EnhancedIndianPlateOCRDataset(train_items, is_train=True)
    val_dataset = EnhancedIndianPlateOCRDataset(val_items, is_train=False)

    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True, num_workers=4, collate_fn=collate_fn, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False, num_workers=4, collate_fn=collate_fn, pin_memory=True)

    model = CRNN(num_classes=NUM_CLASSES).to(device)

    # Load checkpoint
    best_exact_acc = 63.02
    start_epoch = 41
    total_epochs = 80
    if DEST_WEIGHTS.is_file():
        ckpt = torch.load(str(DEST_WEIGHTS), map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        best_exact_acc = float(ckpt.get("best_exact_acc", 63.02))
        print(f"Loaded existing weights! Starting from baseline accuracy: {best_exact_acc:.2f}%")

    criterion = nn.CTCLoss(blank=0, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=1e-4)

    remaining_epochs = total_epochs - start_epoch + 1
    scheduler = CosineAnnealingLR(optimizer, T_max=remaining_epochs, eta_min=1e-5)
    scaler = torch.amp.GradScaler('cuda')

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    metrics_log = []

    print(f"\nStarting Extended Training: Epochs {start_epoch} to {total_epochs} (40 additional epochs)...")
    start_time = time.time()

    for epoch in range(start_epoch, total_epochs + 1):
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
                logits = model(imgs)
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
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "best_exact_acc": best_exact_acc,
                "cer": cer,
                "alphabet": ALPHABET,
                "num_classes": NUM_CLASSES
            }, str(DEST_WEIGHTS))

        print(f"Epoch {epoch:02d}/{total_epochs:02d} [{ep_time:.1f}s] - Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | Exact Match: {exact_acc:.2f}% | CER: {cer:.2f}% {'🌟 (New Best!)' if is_best else ''}")

        metrics_log.append({
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "val_loss": round(val_loss, 4),
            "exact_acc": round(exact_acc, 2),
            "cer": round(cer, 2),
            "time_s": round(ep_time, 1)
        })

    total_time = (time.time() - start_time) / 60.0
    print(f"\nExtended training finished in {total_time:.1f} minutes. Final Best Exact Accuracy: {best_exact_acc:.2f}%")

    with open(RUN_DIR / "extended_metrics.json", "w") as f:
        json.dump(metrics_log, f, indent=2)

    # Re-export ONNX
    print("Re-exporting best checkpoint to ONNX...")
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
            dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=14,
            dynamo=False
        )
        print(f"Exported updated ONNX Model to: {DEST_ONNX} ({DEST_ONNX.stat().st_size / 1e6:.1f} MB)")
    except Exception as e:
        print(f"Warning during ONNX export: {e}")

    print("\nExtended OCR Training Completed Successfully!")

if __name__ == "__main__":
    main()
