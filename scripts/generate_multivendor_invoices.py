#!/usr/bin/env python3
"""
Generate ~1,000 realistic multi-vendor delivery invoices with embedded functional QR codes.
Supports:
- Zomato (Restaurant food orders, UPI pay QR)
- Swiggy (Food & Instamart, Swiggy BharatQR)
- Amazon (Amazon.in Tax Invoices, package digital verify QR)
- Uber (Uber Trips / Eats receipt, ride verification QR)
- Reliance (Reliance Smart / Fresh retail receipt, BharatQR)
- Blinkit (10-minute grocery receipt, UPI QR)
- Zepto (Quick commerce receipt, QR code)

Renders high-quality PNG images with QR codes directly into `media/invoices/`,
and creates schema-verified records in PostgreSQL:
- delivery_orders
- invoices
- invoice_items
"""
import os
import sys
import uuid
import random
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.config import MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.models import (
    DeliveryOrder, Invoice, InvoiceItem, DeliverySource, OrderStatus, AccessState,
    PlatformType, ScreeningVerdict, VehicleOwner, Gate, User, PersonType
)

# Seed for deterministic generation
random.seed(20261117)

INVOICES_DIR = MEDIA_ROOT / "invoices"
INVOICES_DIR.mkdir(parents=True, exist_ok=True)

# Try locating standard system fonts
FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

def get_font(size=14, bold=False):
    candidates = FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

# -------------------------------------------------------------
# Vendor Catalogs & Platforms
# -------------------------------------------------------------
VENDORS = {
    PlatformType.ZOMATO: {
        "name": "Zomato",
        "color": (226, 55, 68),
        "header_bg": (255, 245, 245),
        "merchants": [
            "Biryani By Kilo (Sector 35)", "McDonald's (Elante Mall)", "Haldiram's (Sector 26)",
            "Burger King (Sector 35)", "Domino's Pizza (Sector 11)", "Subway (PEC Market)",
            "Chai Point (IT Park)", "Wow! Momo (Sector 17)", "Sagar Ratna (Sector 35)",
            "La Pino'z Pizza (Sector 15)", "KFC (Sector 35)", "Barbeque Nation (Sector 26)"
        ],
        "items": [
            ("Dum Gosht Biryani", 380, "FOOD", "FOOD_OK"),
            ("Chicken Hyderabadi Biryani", 340, "FOOD", "FOOD_OK"),
            ("Paneer Tikka Roll", 190, "FOOD", "FOOD_OK"),
            ("Veg Whopper Meal", 280, "FOOD", "FOOD_OK"),
            ("Farmhouse Pizza Regular", 260, "FOOD", "FOOD_OK"),
            ("Cold Coffee with Ice Cream", 140, "BEVERAGE", "BEVERAGE_OK"),
            ("Masala Chai Flask 500ml", 130, "BEVERAGE", "BEVERAGE_OK"),
            ("Butter Naan (2 pcs)", 90, "FOOD", "FOOD_OK"),
            ("Dal Makhani Bowl", 220, "FOOD", "FOOD_OK"),
            ("Gulab Jamun (2 pcs)", 80, "FOOD", "FOOD_OK")
        ],
        "qr_prefix": "upi://pay?pa=zomato@icici&pn=Zomato&am="
    },
    PlatformType.SWIGGY: {
        "name": "Swiggy",
        "color": (252, 128, 25),
        "header_bg": (255, 248, 240),
        "merchants": [
            "Behrouz Biryani (Sector 34)", "Faasos (Sector 15)", "Baskin Robbins (Sector 8)",
            "Sweet Truth (Sector 34)", "Starbucks Coffee (Sector 35)", "Chaayos (Sector 17)",
            "The Belgian Waffle Co. (Sector 11)", "Keventers (Sector 35)", "Oven Story Pizza (Sector 22)"
        ],
        "items": [
            ("Shahi Paneer Biryani", 330, "FOOD", "FOOD_OK"),
            ("Cheesy Chicken Roll", 185, "FOOD", "FOOD_OK"),
            ("Belgian Chocolate Scoop", 150, "FOOD", "FOOD_OK"),
            ("Caramel Macchiato Grande", 320, "BEVERAGE", "BEVERAGE_OK"),
            ("Waffle Chocolate Overload", 175, "FOOD", "FOOD_OK"),
            ("Thick Chocolate Shake", 210, "BEVERAGE", "BEVERAGE_OK"),
            ("Paneer Tikka Wrap", 160, "FOOD", "FOOD_OK"),
            ("Hazelnut Cold Brew", 270, "BEVERAGE", "BEVERAGE_OK")
        ],
        "qr_prefix": "upi://pay?pa=swiggy@hdfcbank&pn=Swiggy&am="
    },
    PlatformType.AMAZON: {
        "name": "Amazon India",
        "color": (35, 47, 62),
        "header_bg": (245, 248, 252),
        "merchants": [
            "Appario Retail Private Ltd", "Cloudtail India Pvt Ltd", "Clicktech Retail Private Ltd",
            "Cocoblu Retail Limited", "Electronic Bazaar India", "Oxford Book Store Hub"
        ],
        "items": [
            ("USB-C Fast Charging Cable 2m", 299, "ELECTRONICS", "ELECTRONICS_OK"),
            ("Logitech Wireless Mouse M221", 799, "ELECTRONICS", "ELECTRONICS_OK"),
            ("Classmate Pulse Notebook 6-Pack", 420, "STATIONERY", "STATIONERY_OK"),
            ("Engineering Mathematics Book", 650, "STATIONERY", "STATIONERY_OK"),
            ("Parker Frontier Ballpoint Pen", 350, "STATIONERY", "STATIONERY_OK"),
            ("Boat Bassheads 100 Earphones", 399, "ELECTRONICS", "ELECTRONICS_OK"),
            ("Scientific Calculator FX-991EX", 1250, "ELECTRONICS", "ELECTRONICS_OK"),
            ("Laptop Cooling Pad Aluminium", 890, "ELECTRONICS", "ELECTRONICS_OK")
        ],
        "qr_prefix": "https://www.amazon.in/gp/digital/invoice/verify?order="
    },
    PlatformType.UBER: {
        "name": "Uber Trips & Eats",
        "color": (0, 0, 0),
        "header_bg": (245, 245, 245),
        "merchants": [
            "Uber Premier (Chandigarh Airport to PEC)", "Uber Go (Sector 17 Plaza to PEC Gate 1)",
            "Uber Auto (Tribune Chowk to Campus)", "Uber XL (Mohali Phase 7 to PEC Enclave)",
            "Uber Intercity (Delhi T3 to PEC Gate 2)"
        ],
        "items": [
            ("Trip Base Fare & Distance (14.2 km)", 280, "SERVICE", "SERVICE_OK"),
            ("Waiting & Access Fee", 35, "SERVICE", "SERVICE_OK"),
            ("Toll Charges (Airport Expressway)", 55, "SERVICE", "SERVICE_OK"),
            ("Late Night Surcharge", 60, "SERVICE", "SERVICE_OK")
        ],
        "qr_prefix": "https://m.uber.com/receipt/v/"
    },
    PlatformType.RELIANCE: {
        "name": "Reliance Smart / Fresh",
        "color": (0, 114, 188),
        "header_bg": (240, 248, 255),
        "merchants": [
            "Reliance Smart Superstore (Sector 20)", "Reliance Fresh (Sector 11 Chandigarh)",
            "Reliance Digital (Elante Mall)", "Reliance Smart Point (Sector 15)"
        ],
        "items": [
            ("Aashirvaad Shudh Chakki Atta 5kg", 245, "FOOD", "FOOD_OK"),
            ("Fortune Sunlite Sunflower Oil 1L", 155, "FOOD", "FOOD_OK"),
            ("Tata Salt Vacuum Evaporated 1kg", 28, "FOOD", "FOOD_OK"),
            ("Amul Taaza Homogenised Milk 1L", 72, "FOOD", "FOOD_OK"),
            ("Surf Excel Matic Liquid Detergent 1L", 230, "PERSONAL_CARE", "PERSONAL_CARE_OK"),
            ("Dettol Original Germ Protection Soap (4pk)", 180, "PERSONAL_CARE", "PERSONAL_CARE_OK"),
            ("Colgate MaxFresh Spicy Fresh 150g", 120, "PERSONAL_CARE", "PERSONAL_CARE_OK"),
            ("Britannia Good Day Cashew 600g", 140, "FOOD", "FOOD_OK")
        ],
        "qr_prefix": "https://reliancesmart.in/e-bill?inv="
    },
    PlatformType.BLINKIT: {
        "name": "Blinkit",
        "color": (244, 180, 0),
        "header_bg": (255, 253, 235),
        "merchants": [
            "Blinkit Dark Store #CHD-04 (Sector 11)", "Blinkit Hub #CHD-09 (Sector 15)",
            "Blinkit Micro-Fulfillment (Sector 24)"
        ],
        "items": [
            ("Lipton Green Tea Honey Lemon 25 Bags", 185, "BEVERAGE", "BEVERAGE_OK"),
            ("Maggi 2-Minute Noodles 12-Pack", 168, "FOOD", "FOOD_OK"),
            ("Amul Butter Pasteurised 500g", 275, "FOOD", "FOOD_OK"),
            ("Harvest Gold White Bread 400g", 45, "FOOD", "FOOD_OK"),
            ("Epigamia Greek Yogurt Strawberry 90g", 60, "FOOD", "FOOD_OK"),
            ("Haldiram's Bhujia Sev 400g", 125, "FOOD", "FOOD_OK"),
            ("Bisleri Packaged Drinking Water 5L", 70, "BEVERAGE", "BEVERAGE_OK")
        ],
        "qr_prefix": "upi://pay?pa=blinkit@icici&pn=Blinkit&am="
    },
    PlatformType.ZEPTO: {
        "name": "Zepto",
        "color": (148, 0, 211),
        "header_bg": (250, 245, 255),
        "merchants": [
            "Zepto Express Store (Sector 14)", "Zepto Hub (Sector 16 Chandigarh)",
            "Zepto Dark Store (Sector 22)"
        ],
        "items": [
            ("Coca-Cola Can 300ml (2 pk)", 80, "BEVERAGE", "BEVERAGE_OK"),
            ("Doritos Nacho Cheese 90g", 50, "FOOD", "FOOD_OK"),
            ("Nutella Hazelnut Spread 350g", 370, "FOOD", "FOOD_OK"),
            ("Quaker Oats Pouch 1kg", 195, "FOOD", "FOOD_OK"),
            ("Paper Boat Aamras Juice 250ml", 40, "BEVERAGE", "BEVERAGE_OK"),
            ("Real Mixed Fruit Juice 1L", 125, "BEVERAGE", "BEVERAGE_OK")
        ],
        "qr_prefix": "upi://pay?pa=zepto@axisbank&pn=Zepto&am="
    }
}

RIDER_NAMES = [
    "Suresh Kumar", "Ramesh Chand", "Baljit Singh", "Gurpreet Singh", "Rajesh Sharma",
    "Mukesh Yadav", "Deepak Verma", "Mohit Chauhan", "Sunil Pal", "Vikas Tiwari",
    "Manpreet Singh", "Pawan Kumar", "Ravi Shankar", "Dharmendra Singh", "Satish Kumar"
]

DELIVERY_PLATES = [
    "CH01CB1284", "PB65AD9021", "PB08BZ4412", "HR03F8821", "CH01BZ7719",
    "PB65AK3392", "HR70D1094", "CH01AT6022", "PB10CR5519", "CH01CD3190"
]

def render_invoice_with_qr(
    vendor_info,
    order_id: str,
    date_str: str,
    customer_name: str,
    customer_address: str,
    rider_name: str,
    rider_plate: str,
    merchant_name: str,
    items: list,
    subtotal: Decimal,
    delivery_fee: Decimal,
    tax: Decimal,
    total: Decimal,
    qr_payload: str,
    output_path: Path
):
    """
    Renders an authentic, high-fidelity receipt image with an embedded 2D QR Code.
    """
    width = 720
    # Calculate height dynamically based on items
    height = 540 + len(items) * 36

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    f_title = get_font(22, bold=True)
    f_sub = get_font(13, bold=False)
    f_head = get_font(14, bold=True)
    f_body = get_font(13, bold=False)
    f_bold = get_font(14, bold=True)
    f_small = get_font(11, bold=False)

    # 1. Header Banner
    header_h = 105
    draw.rectangle([0, 0, width, header_h], fill=vendor_info["header_bg"])
    draw.rectangle([0, header_h - 3, width, header_h], fill=vendor_info["color"])

    # Brand Title
    draw.text((28, 20), vendor_info["name"].upper(), font=f_title, fill=vendor_info["color"])
    draw.text((28, 54), merchant_name, font=f_head, fill=(40, 40, 40))
    draw.text((28, 76), f"Official Delivery Partner \u2022 Tax Invoice & Receipt", font=f_sub, fill=(100, 100, 100))

    # 2. Functional 2D QR Code (Upper Right)
    qr_img = qrcode.make(qr_payload).resize((96, 96))
    canvas.paste(qr_img, (width - 124, 6))
    draw.rectangle([width - 126, 4, width - 26, 104], outline=(200, 200, 200), width=1)
    draw.text((width - 120, 92), "SCAN TO VERIFY", font=f_small, fill=(70, 70, 70))

    # 3. Order Details Section
    y = header_h + 14
    draw.text((28, y), f"Order ID: {order_id}", font=f_bold, fill=(20, 20, 20))
    draw.text((width - 28, y), f"Date: {date_str}", font=f_body, fill=(60, 60, 60), anchor="ra")
    y += 24

    draw.text((28, y), f"Customer: {customer_name}", font=f_body, fill=(40, 40, 40))
    draw.text((width - 28, y), f"Delivery Rider: {rider_name} ({rider_plate})", font=f_body, fill=(40, 40, 40), anchor="ra")
    y += 20
    draw.text((28, y), f"Delivery Destination: {customer_address}", font=f_small, fill=(90, 90, 90))
    y += 28

    # Separator
    draw.line([(28, y), (width - 28, y)], fill=(210, 210, 210), width=1)
    y += 8

    # 4. Item Table Header
    draw.rectangle([28, y, width - 28, y + 28], fill=(240, 243, 246))
    draw.text((38, y + 6), "ITEM DESCRIPTION", font=f_head, fill=(50, 50, 50))
    draw.text((450, y + 6), "QTY", font=f_head, fill=(50, 50, 50))
    draw.text((540, y + 6), "PRICE", font=f_head, fill=(50, 50, 50))
    draw.text((width - 38, y + 6), "AMOUNT", font=f_head, fill=(50, 50, 50), anchor="ra")
    y += 34

    # 5. Items Rows
    for idx, (name, qty, unit_price, line_total, _, _) in enumerate(items):
        if idx % 2 == 1:
            draw.rectangle([28, y, width - 28, y + 30], fill=(250, 250, 252))
        draw.text((38, y + 6), name[:48], font=f_body, fill=(30, 30, 30))
        draw.text((460, y + 6), str(qty), font=f_body, fill=(50, 50, 50))
        draw.text((540, y + 6), f"\u20b9{unit_price:.2f}", font=f_body, fill=(50, 50, 50))
        draw.text((width - 38, y + 6), f"\u20b9{line_total:.2f}", font=f_body, fill=(20, 20, 20), anchor="ra")
        y += 32

    # Separator
    draw.line([(28, y + 4), (width - 28, y + 4)], fill=(210, 210, 210), width=1)
    y += 14

    # 6. Totals Breakdown
    draw.text((430, y), "Subtotal:", font=f_body, fill=(80, 80, 80))
    draw.text((width - 38, y), f"\u20b9{subtotal:.2f}", font=f_body, fill=(40, 40, 40), anchor="ra")
    y += 24

    draw.text((430, y), "Delivery / Packaging:", font=f_body, fill=(80, 80, 80))
    draw.text((width - 38, y), f"\u20b9{delivery_fee:.2f}", font=f_body, fill=(40, 40, 40), anchor="ra")
    y += 24

    draw.text((430, y), "Taxes (GST 5% / 18%):", font=f_body, fill=(80, 80, 80))
    draw.text((width - 38, y), f"\u20b9{tax:.2f}", font=f_body, fill=(40, 40, 40), anchor="ra")
    y += 28

    # Final Total Box
    draw.rectangle([410, y, width - 28, y + 42], fill=vendor_info["header_bg"], outline=vendor_info["color"], width=1)
    draw.text((424, y + 10), "GRAND TOTAL:", font=f_bold, fill=vendor_info["color"])
    draw.text((width - 38, y + 10), f"\u20b9{total:.2f}", font=f_title, fill=vendor_info["color"], anchor="ra")
    y += 56

    # 7. Statutory Footer & Security Clearance Notice
    draw.line([(28, y), (width - 28, y)], fill=(230, 230, 230), width=1)
    y += 10
    draw.text((width // 2, y), "Campus Security Gate Clearance Document \u2022 Verified Order", font=f_small, fill=(120, 120, 120), anchor="ma")
    draw.text((width // 2, y + 16), "Scan QR code above with any UPI app or browser to verify authenticity", font=f_small, fill=(150, 150, 150), anchor="ma")

    # Save to disk
    canvas.save(output_path, "PNG", optimize=True)

def generate_1000_invoices():
    db = SessionLocal()
    print("=" * 70)
    print("GENERATING 1,000 MULTI-VENDOR INVOICES WITH QR CODES")
    print("=" * 70)

    # Fetch registered owners (students & faculty) to link orders to real college members
    owners = db.query(VehicleOwner).filter(VehicleOwner.person_type.in_([PersonType.STUDENT, PersonType.FACULTY])).all()
    if not owners:
        print("ERROR: No registered students or faculty found. Run seed_college_members.py first!")
        return

    admin_user = db.query(User).filter(User.role == "ADMIN").first()
    gates = [g.id for g in db.query(Gate).all()] or ["GATE_1", "GATE_2", "GATE_3"]

    platforms = list(VENDORS.keys())
    now = datetime.now(timezone.utc)

    # Check how many orders already exist
    existing_order_ids = {o.order_id for o in db.query(DeliveryOrder.order_id).all()}
    print(f"Existing orders in database: {len(existing_order_ids)}")

    TARGET_COUNT = 1000
    needed = max(0, TARGET_COUNT - len(existing_order_ids))
    print(f"Target count: {TARGET_COUNT} | Generating {needed} new orders with QR code receipts...")

    created_orders = 0
    created_invoices = 0
    created_items = 0

    batch_orders = []
    batch_invoices = []
    batch_items = []

    for i in range(1, needed + 1):
        platform = random.choice(platforms)
        v_info = VENDORS[platform]

        # Order ID prefix
        prefix_map = {
            PlatformType.ZOMATO: "ZOM",
            PlatformType.SWIGGY: "SWG",
            PlatformType.AMAZON: "AMZ",
            PlatformType.UBER: "UBR",
            PlatformType.RELIANCE: "REL",
            PlatformType.BLINKIT: "BLK",
            PlatformType.ZEPTO: "ZPT"
        }
        p_prefix = prefix_map.get(platform, "ORD")
        if platform == PlatformType.AMAZON:
            order_id = f"AMZ-402-{random.randint(1000000, 9999999):07d}-{random.randint(1000000, 9999999):07d}"
        else:
            order_id = f"{p_prefix}-2026-{random.randint(10000, 99999):05d}"

        if order_id in existing_order_ids:
            continue
        existing_order_ids.add(order_id)

        customer = random.choice(owners)
        merchant = random.choice(v_info["merchants"])
        rider_name = random.choice(RIDER_NAMES)
        rider_plate = random.choice(DELIVERY_PLATES)
        rider_phone = f"+91 98{random.randint(10000000, 99999999)}"

        # Timestamp distributed over last 14 days
        order_time = now - timedelta(
            days=random.randint(0, 14),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59)
        )
        date_str = order_time.strftime("%d %b %Y, %I:%M %p")

        # Select 1 to 4 items
        n_items = random.randint(1, 4)
        sample_items = random.sample(v_info["items"], min(n_items, len(v_info["items"])))

        invoice_lines = []
        subtotal = Decimal("0.00")
        for item_name, base_price, cat, reason in sample_items:
            qty = random.choice([1, 1, 1, 2, 3])
            price = Decimal(str(base_price))
            line_total = price * qty
            subtotal += line_total
            invoice_lines.append((item_name, qty, price, line_total, cat, reason))

        delivery_fee = Decimal(random.choice([0, 25, 30, 40]))
        tax = (subtotal * Decimal("0.05")).quantize(Decimal("0.01"))
        total = subtotal + delivery_fee + tax

        # QR payload string
        if platform in [PlatformType.ZOMATO, PlatformType.SWIGGY, PlatformType.BLINKIT, PlatformType.ZEPTO]:
            qr_payload = f"{v_info['qr_prefix']}{total:.2f}&tr={order_id}"
        elif platform == PlatformType.AMAZON:
            qr_payload = f"{v_info['qr_prefix']}{order_id}"
        elif platform == PlatformType.UBER:
            qr_payload = f"{v_info['qr_prefix']}{order_id[4:]}"
        else:
            qr_payload = f"{v_info['qr_prefix']}{order_id}"

        # Image file setup
        inv_file_uuid = uuid.uuid4().hex
        inv_rel_path = f"invoices/{inv_file_uuid}.png"
        inv_abs_path = MEDIA_ROOT / inv_rel_path

        # Render invoice with QR Code!
        render_invoice_with_qr(
            vendor_info=v_info,
            order_id=order_id,
            date_str=date_str,
            customer_name=customer.full_name,
            customer_address=customer.residence or "PEC Campus, Sector 12, Chandigarh",
            rider_name=rider_name,
            rider_plate=rider_plate,
            merchant_name=merchant,
            items=invoice_lines,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            tax=tax,
            total=total,
            qr_payload=qr_payload,
            output_path=inv_abs_path
        )

        # Create DeliveryOrder model
        order = DeliveryOrder(
            order_id=order_id,
            platform=platform,
            customer_id=customer.id,
            customer_name=customer.full_name,
            restaurant=merchant,
            delivery_vehicle_plate=rider_plate,
            delivery_agent_name=rider_name,
            delivery_agent_phone=rider_phone,
            order_timestamp=order_time,
            status=OrderStatus.VERIFIED,
            verification_status=AccessState.ALLOWED,
            gate_id=random.choice(gates)
        )
        db.add(order)
        db.flush()

        raw_ocr = f"{v_info['name'].upper()}\n{merchant}\nORDER #{order_id}\nDATE: {date_str}\n"
        for name, qty, price, line_tot, _, _ in invoice_lines:
            raw_ocr += f"{name} x{qty} = Rs {line_tot}\n"
        raw_ocr += f"SUBTOTAL: {subtotal}\nDELIVERY: {delivery_fee}\nTAX: {tax}\nTOTAL: {total}\nQR: {qr_payload}"

        # Create Invoice model
        invoice = Invoice(
            order_id=order.id,
            image_path=inv_rel_path,
            preview_path=None,
            raw_ocr_text=raw_ocr,
            confidence=0.98,
            vendor=v_info["name"],
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            tax=tax,
            total_amount=total,
            computed_total=total,
            totals_match=True,
            overall_verdict=ScreeningVerdict.ALLOW,
            source=DeliverySource.WHATSAPP if random.random() < 0.7 else DeliverySource.CONSOLE,
            sender=rider_phone,
            gate_id=order.gate_id,
            reply_text=f"Order {order_id}: all {len(invoice_lines)} lines look fine. Total matches: {total:.2f}."
        )
        db.add(invoice)
        db.flush()

        # Create InvoiceItem models
        for line_no, (name, qty, price, line_tot, cat, reason) in enumerate(invoice_lines, start=1):
            inv_item = InvoiceItem(
                invoice_id=invoice.id,
                item_name=name,
                quantity=qty,
                unit_price=price,
                total_price=line_tot,
                line_no=line_no,
                category=cat,
                reason_code=reason,
                verdict=ScreeningVerdict.ALLOW,
                confidence=0.98
            )
            db.add(inv_item)
            created_items += 1

        created_orders += 1
        created_invoices += 1

        if i % 100 == 0:
            db.commit()
            print(f"  -> Generated {i}/{needed} invoices with QR codes...")

    db.commit()
    print("\n" + "=" * 70)
    print(f"INVOICE GENERATION COMPLETED!")
    print(f"  Orders created: {created_orders}")
    print(f"  Invoices created: {created_invoices}")
    print(f"  Items created: {created_items}")
    print(f"  Total orders in DB: {db.query(DeliveryOrder).count()}")
    print(f"  Total invoices in DB: {db.query(Invoice).count()}")
    print("=" * 70)
    db.close()

if __name__ == "__main__":
    generate_1000_invoices()
