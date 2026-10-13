import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MEDIA_DIR = os.path.join(os.path.dirname(__file__), "..", "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

def generate_invoice_image():
    width, height = 800, 1000
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([(0, 0), (width, 80)], fill=(34, 49, 63))
    draw.text((30, 25), "CAMPUS FOOD DELIVERY INVOICE", fill=(255, 255, 255))

    # Invoice details
    y = 120
    lines = [
        "Vendor: Zomato Campus Delivery",
        "Order ID: #ORD-2026-9821",
        "Date: 2026-09-22",
        "Customer: Student Hostel Block-B",
        "Delivery Gate: North Gate #1",
        "--------------------------------------------------",
        "ITEMS ORDERED:",
        "1. Margherita Pizza (Medium)         x 1     Rs. 299.00",
        "2. Garlic Breadsticks                x 1     Rs. 139.00",
        "3. Beverage (Cold Drink 500ml)       x 1     Rs.  50.00",
        "--------------------------------------------------",
        "SUBTOTAL:                                   Rs. 488.00",
        "DELIVERY CHARGES:                           Rs.  30.00",
        "TAXES (GST 5%):                             Rs.  25.90",
        "TOTAL AMOUNT PAID:                          Rs. 543.90",
        "--------------------------------------------------",
        "Delivery Agent: Ramesh Kumar",
        "Vehicle Reg: DL 01 AB 1234",
        "Status: VERIFIED_DELIVERY"
    ]

    for line in lines:
        draw.text((40, y), line, fill=(20, 20, 20))
        y += 35

    # Verification stamp box
    draw.rectangle([(40, y + 20), (350, y + 90)], outline=(0, 128, 0), width=3)
    draw.text((50, y + 35), "ACCESS AUTHORIZATION", fill=(0, 128, 0))
    draw.text((50, y + 60), "VALIDATED FOR CAMPUS ENTRY", fill=(0, 128, 0))

    out_path = os.path.join(MEDIA_DIR, "test_invoice.png")
    img.save(out_path)
    print(f"Generated invoice image: {out_path}")
    return out_path

def generate_plate_image():
    # Standard Indian high security registration plate ratio (500x120)
    w, h = 520, 120
    img = Image.new("RGB", (w, h), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)

    # Plate border
    draw.rectangle([(2, 2), (w - 3, h - 3)], outline=(10, 10, 10), width=5)
    # Blue IND strip on the left
    draw.rectangle([(5, 5), (45, h - 5)], fill=(0, 51, 153))
    draw.text((10, 45), "IND", fill=(255, 255, 255))

    # Plate characters
    draw.text((70, 35), "DL 01 AB 1234", fill=(10, 10, 10))

    out_path = os.path.join(MEDIA_DIR, "test_plate.png")
    img.save(out_path)
    print(f"Generated plate image: {out_path}")
    return out_path

def generate_test_video():
    # 5-second video at 10 fps (50 frames total), 1280x720
    width, height = 1280, 720
    fps = 10
    total_frames = 50
    out_path = os.path.join(MEDIA_DIR, "test_car_video.mp4")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

    plate_w, plate_h = 320, 80

    for i in range(total_frames):
        frame = np.ones((height, width, 3), dtype=np.uint8) * 200

        # Draw road
        cv2.rectangle(frame, (0, 400), (width, height), (70, 70, 70), -1)
        # Yellow dashed lane marker
        for x in range(0, width, 100):
            cv2.rectangle(frame, (x, 550), (x + 50, 560), (0, 215, 255), -1)

        # Vehicle position moving towards center from left then stopping
        progress = min(1.0, i / 30.0)
        car_x = int(100 + progress * 350)
        car_y = 300

        # Draw car body (SUV shape)
        cv2.rectangle(frame, (car_x, car_y), (car_x + 480, car_y + 220), (40, 50, 60), -1)
        cv2.rectangle(frame, (car_x + 60, car_y - 80), (car_x + 420, car_y), (60, 70, 80), -1)
        # Windows
        cv2.rectangle(frame, (car_x + 80, car_y - 70), (car_x + 220, car_y - 10), (180, 210, 230), -1)
        cv2.rectangle(frame, (car_x + 240, car_y - 70), (car_x + 390, car_y - 10), (180, 210, 230), -1)
        # Headlights / Tail lights
        cv2.rectangle(frame, (car_x + 460, car_y + 40), (car_x + 480, car_y + 80), (0, 255, 255), -1)
        cv2.rectangle(frame, (car_x, car_y + 40), (car_x + 20, car_y + 80), (0, 0, 255), -1)
        # Wheels
        cv2.circle(frame, (car_x + 100, car_y + 220), 45, (20, 20, 20), -1)
        cv2.circle(frame, (car_x + 380, car_y + 220), 45, (20, 20, 20), -1)

        # Front / Rear License Plate
        # Place license plate on vehicle bumper
        p_x = car_x + 140
        p_y = car_y + 130
        cv2.rectangle(frame, (p_x, p_y), (p_x + plate_w, p_y + plate_h), (255, 255, 255), -1)
        cv2.rectangle(frame, (p_x, p_y), (p_x + plate_w, p_y + plate_h), (0, 0, 0), 2)
        cv2.putText(
            frame,
            "DL 01 AB 1234",
            (p_x + 15, p_y + 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 0, 0),
            3,
            cv2.LINE_AA
        )

        out.write(frame)

    out.release()
    print(f"Generated test video: {out_path}")
    return out_path

if __name__ == "__main__":
    generate_invoice_image()
    generate_plate_image()
    generate_test_video()
