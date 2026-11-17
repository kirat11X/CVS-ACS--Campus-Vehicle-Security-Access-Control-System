"""
Real-ESRGAN (4x) copies of a video's plate crops, written to training/<video>/super_res/<plate_id>.jpg.

    research_track/hitl_anpr/.venv/bin/python scripts/super_resolve_crops.py 1

FOR YOUR EYES ONLY. A super-resolution network invents plausible detail: a smeared 8 can come back as a crisp 0 or B.
These images help you read a plate when you type its text, but they are never evidence of what the plate says, so they
must not be used to write labels, to train a model, or to run OCR whose output is stored. Use crops/ for those.

Run after extract_plates.py (and again after extract_plates.py --refresh, which replaces crops/). A crop that already
has an up-to-date copy is skipped. Needs scripts/../ml-assets setup: the Real-ESRGAN weights and the `spandrel` loader
live in ~/ml-assets/campus/sr/ (outside the locked hitl_anpr environment); --weights points to other weights.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SR_HOME = Path("~/ml-assets/campus/sr").expanduser()
DEFAULT_WEIGHTS = SR_HOME / "weights" / "RealESRGAN_x4plus.pth"
DEFAULT_OUT = PROJECT_ROOT / "training"
README = (
    "For human viewing only. These are Real-ESRGAN 4x reconstructions of ../crops/. A super-resolution network invents\n"
    "plausible detail, so a character you see here may not exist in the real plate. Never use these images to write\n"
    "labels, to train a model, or to store OCR output. Use ../crops/ (the original pixels) for that.\n"
)

sys.path.append(str(SR_HOME / "pkgs"))  # spandrel, einops, safetensors (installed with --target, not into the hitl env)
try:
    import cv2
    import numpy as np
    import torch
    from spandrel import ImageModelDescriptor, ModelLoader
except ImportError as exc:
    sys.exit(f"{exc}\nRun this with research_track/hitl_anpr/.venv/bin/python; spandrel is expected in {SR_HOME / 'pkgs'}.")


def load_model(weights, device):
    model = ModelLoader(device).load_from_file(weights)
    if not isinstance(model, ImageModelDescriptor):
        sys.exit(f"{weights} is not an image super-resolution model.")
    return model.to(device).eval()


@torch.inference_mode()
def upscale(model, bgr, device):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    tensor = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255).unsqueeze(0).to(device)
    out = model(tensor).squeeze(0).clamp(0, 1).mul(255).round().byte().permute(1, 2, 0).cpu().numpy()
    return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="video number/name, as given to extract_plates.py")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="parent folder holding <video>/ (default: training/)")
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS), help="Real-ESRGAN weights (.pth / .safetensors)")
    parser.add_argument("--force", action="store_true", help="redo copies that are already up to date")
    args = parser.parse_args()

    folder = Path(args.out).expanduser().resolve() / args.video
    crops = sorted((folder / "crops").glob("*.jpg"))
    if not crops:
        sys.exit(f"No crops in {folder / 'crops'}; run extract_plates.py {args.video} first.")
    weights = Path(args.weights).expanduser()
    if not weights.is_file():
        sys.exit(f"Weights not found: {weights}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(weights, device)
    dest = folder / "super_res"
    dest.mkdir(exist_ok=True)
    (dest / "README.txt").write_text(README)

    # Copies of crops that no longer exist (e.g. after --refresh removed a box) are removed too.
    names = {c.name for c in crops}
    stale = [p for p in dest.glob("*.jpg") if p.name not in names]
    for p in stale:
        p.unlink()

    done = skipped = 0
    for crop_path in crops:
        target = dest / crop_path.name
        if not args.force and target.is_file() and target.stat().st_mtime >= crop_path.stat().st_mtime:
            skipped += 1
            continue
        crop = cv2.imread(str(crop_path))
        if crop is None or min(crop.shape[:2]) < 2:
            continue
        cv2.imwrite(str(target), upscale(model, crop, device), [cv2.IMWRITE_JPEG_QUALITY, 95])
        done += 1
    print(f"{done} crops super-resolved ({skipped} already up to date, {len(stale)} stale removed) -> {dest} [{device}]")


if __name__ == "__main__":
    main()
