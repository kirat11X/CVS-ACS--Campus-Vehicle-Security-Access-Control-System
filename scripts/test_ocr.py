import os
import sys
from PIL import Image

def run_tesseract_ocr(image_path: str) -> str:
    import pytesseract
    print("[OCR] Running Pytesseract (Tesseract 5.5 native engine)...")
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img)
    return text

def run_rapidocr_ocr(image_path: str) -> str:
    from rapidocr_onnxruntime import RapidOCR
    print("[OCR] Running RapidOCR (PP-OCRv4 ONNX model engine)...")
    engine = RapidOCR()
    result, elapse = engine(image_path)
    if not result:
        return ""
    lines = [line[1] for line in result]
    return "\n".join(lines)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    image_path = os.path.join(project_root, "media", "test_invoice.png")

    if not os.path.exists(image_path):
        print(f"ERROR: Test image not found at {image_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading test image: {image_path}")
    detected_text = ""

    # Test Pytesseract engine
    try:
        tess_text = run_tesseract_ocr(image_path)
        print("\n--- Pytesseract Extracted Text ---")
        print(tess_text.strip())
        print("----------------------------------\n")
        detected_text += "\n" + tess_text
    except Exception as e:
        print(f"Warning: Pytesseract failed: {e}", file=sys.stderr)

    # Test RapidOCR engine
    try:
        rapid_text = run_rapidocr_ocr(image_path)
        print("\n--- RapidOCR Extracted Text ---")
        print(rapid_text.strip())
        print("--------------------------------\n")
        detected_text += "\n" + rapid_text
    except Exception as e:
        print(f"Warning: RapidOCR failed: {e}", file=sys.stderr)

    # Verification criteria: Ensure target keywords from synthetic invoice are found
    keywords = ["ORD-2026-9821", "INVOICE", "Zomato"]
    found_any = any(kw.lower() in detected_text.lower() for kw in keywords)

    if found_any:
        print("[SUCCESS] OCR successfully extracted text from the test invoice image.")
        for kw in keywords:
            status = "FOUND" if kw.lower() in detected_text.lower() else "NOT FOUND"
            print(f"  - Target keyword '{kw}': {status}")
        sys.exit(0)
    else:
        print("[FAILURE] OCR failed to detect expected keywords in the image.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
