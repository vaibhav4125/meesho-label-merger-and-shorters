import os
import re
import fitz # PyMuPDF

import shutil

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = bool(shutil.which("tesseract")) or os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
except ImportError:
    HAS_OCR = False

# Regex patterns
MEESHO_ORDER_RE = re.compile(r"\b(\d{14,24}(?:[_\-]\d+)?)\b")
SIZE_PATTERN = re.compile(
    r"(?:[;,]\s*)?(\b\d{1,2}[-–]\d{1,2}\s*(?:Years?|Months?|M|Y)\b|\b(?:XS|S|M|L|XL|XXL|XXXL|2XL|3XL|4XL|5XL|6XL|Free\s*Size|FS|Semi\s*Stitched|Unstitched)\b|\b(?:2[4-9]|3[0-9]|4[0-9]|5[0-2])\b)\s*$",
    re.IGNORECASE
)
AWB_RE = re.compile(r"^(?:[A-Z]{2}\d{9,}[A-Z0-9]*|SF[A-Z0-9]{8,}|\d{12,18})$", re.IGNORECASE)
PICKUP_RE = re.compile(r"Pickup\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.IGNORECASE)

def normalize_size(size_str: str) -> str:
    """Standardize size text cleanly while preserving original category."""
    if not size_str:
        return "Unknown"
    s = size_str.strip().replace("–", "-")
    # Clean trailing punctuation
    s = re.sub(r"[;,.]+$", "", s).strip()
    upper = s.upper()
    if upper in ["FS", "FREE", "FREE SIZE", "FREESIZE"]:
        return "Free Size"
    if upper in ["SEMI STITCHED", "SEMI-STITCHED", "SEMISTITCHED"]:
        return "Semi Stitched"
    if upper in ["UNSTITCHED", "UN-STITCHED"]:
        return "Unstitched"
    # Normalize cases like '5-6 years' -> '5-6 Years'
    s = re.sub(r"\b(\d+-\d+)\s*years?\b", r"\1 Years", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+-\d+)\s*months?\b", r"\1 Months", s, flags=re.IGNORECASE)
    # Standardize adult sizes
    if upper in ["XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL", "5XL", "6XL"]:
        return upper
    return s

def extract_from_text(text: str, page_idx: int, filename: str) -> dict:
    """Parse Meesho shipping label from extracted text."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return None

    # 1. Seller Account / Name
    seller = "Unknown Seller"
    for i, l in enumerate(lines):
        if any(h in l for h in ["If undelivered, return to:", "Return to:", "Return Address:", "Return To:"]) and i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if candidate and not candidate.startswith("SHED") and not candidate.startswith("PLOT"):
                seller = candidate
            elif i + 2 < len(lines):
                seller = lines[i + 2].strip()
            break
        elif l.lower().startswith("sold by :") or l.lower().startswith("sold by:"):
            seller = re.sub(r"^sold by\s*:\s*", "", l, flags=re.IGNORECASE).strip()
            break
        elif l.lower().startswith("seller name:") or l.lower().startswith("seller:"):
            seller = re.sub(r"^seller(?:\s*name)?\s*:\s*", "", l, flags=re.IGNORECASE).strip()
            break

    # 2. Tracking / AWB
    awb = ""
    for l in lines:
        if AWB_RE.match(l):
            awb = l
            break

    # 3. Pickup Date
    pickup = ""
    for l in lines:
        m = PICKUP_RE.search(l)
        if m:
            pickup = m.group(1)
            break

    # 4. Product Details Header detection (Meesho header ends at 'Order No.')
    header_idx = -1
    for i, l in enumerate(lines):
        if l == "Order No." or l.endswith("Order No.") or l == "Order No" or l.endswith("Order No"):
            header_idx = i
            break

    if header_idx == -1:
        # Fallback search for 'Product Details' or 'Order Details'
        for i, l in enumerate(lines):
            if "Product Details" in l or "Order Details" in l:
                # Check if Order No is in the next few lines
                for j in range(i, min(len(lines), i + 8)):
                    if "Order No" in lines[j]:
                        header_idx = j
                        break
                if header_idx == -1:
                    header_idx = i
                break

    if header_idx == -1:
        return {
            "seller": seller,
            "awb": awb,
            "pickup": pickup,
            "order_no": f"UNKNOWN_P{page_idx+1}",
            "sku": "Unknown SKU",
            "size": "Unknown",
            "qty": 1,
            "color": "NA",
            "page_num": page_idx + 1,
            "filename": filename,
            "confidence": 0.2,
            "validation_status": "Needs Review",
            "error_note": "Product Details / Order No header not found (verify if this is a Meesho shipping label)"
        }

    # Locate Meesho order number
    order_idx = -1
    order_no = ""
    for i in range(header_idx + 1, min(len(lines), header_idx + 18)):
        m = MEESHO_ORDER_RE.search(lines[i])
        if m:
            order_idx = i
            order_no = m.group(1)
            break

    if order_idx == -1:
        # Check if an order number appears anywhere in page text
        for i, l in enumerate(lines):
            m = MEESHO_ORDER_RE.search(l)
            if m:
                order_idx = i
                order_no = m.group(1)
                break

    if order_idx == -1 or not order_no:
        return {
            "seller": seller,
            "awb": awb,
            "pickup": pickup,
            "order_no": f"UNKNOWN_P{page_idx+1}",
            "sku": "Unknown SKU",
            "size": "Unknown",
            "qty": 1,
            "color": "NA",
            "page_num": page_idx + 1,
            "filename": filename,
            "confidence": 0.4,
            "validation_status": "Needs Review",
            "error_note": "Meesho Order number could not be identified"
        }

    color = lines[order_idx - 1] if order_idx - 1 > header_idx else "NA"
    qty_str = lines[order_idx - 2] if order_idx - 2 > header_idx else "1"
    qty = int(qty_str) if qty_str.isdigit() else 1
    qty = int(qty_str) if qty_str.isdigit() else 1

    item_lines = lines[header_idx + 1 : max(header_idx + 1, order_idx - 2)]

    sku = ""
    size = ""
    if len(item_lines) == 1:
        line = item_lines[0]
        m = SIZE_PATTERN.search(line)
        if m:
            size = m.group(1).strip()
            sku = line[:m.start()].rstrip(" ;,").strip()
        else:
            sku = line
            size = "Unknown"
    elif len(item_lines) >= 2:
        last_line = item_lines[-1]
        m = SIZE_PATTERN.search(last_line)
        if m and m.start() == 0:
            size = last_line
            sku = " ".join(item_lines[:-1]).strip()
        elif m:
            size = m.group(1).strip()
            item_lines[-1] = last_line[:m.start()].rstrip(" ;,").strip()
            sku = " ".join(item_lines).strip()
        else:
            size = last_line
            sku = " ".join(item_lines[:-1]).strip()
    else:
        # Check if color line or order line has size
        sku = "Unknown SKU"
        size = "Unknown"

    size = normalize_size(size)

    # Determine confidence and status
    confidence = 1.0
    status = "Valid"
    error_note = ""

    if not sku or sku == "Unknown SKU":
        confidence -= 0.4
        status = "Needs Review"
        error_note = "SKU could not be confidently identified"
    if not size or size == "Unknown":
        confidence -= 0.4
        status = "Needs Review"
        error_note = "Size could not be confidently identified"

    return {
        "seller": seller,
        "awb": awb,
        "pickup": pickup,
        "order_no": order_no,
        "sku": sku,
        "product_name": sku,
        "size": size,
        "qty": qty,
        "color": color,
        "page_num": page_idx + 1,
        "filename": filename,
        "confidence": round(confidence, 2),
        "validation_status": status,
        "error_note": error_note
    }

def ocr_page(page, page_idx: int, filename: str) -> dict:
    """Fallback OCR extraction if direct text extraction yields empty result."""
    if not HAS_OCR:
        return {
            "seller": "Unknown",
            "awb": "",
            "pickup": "",
            "order_no": f"OCR_UNAVAILABLE_P{page_idx+1}",
            "sku": "Needs Review",
            "product_name": "Needs Review",
            "size": "Unknown",
            "qty": 1,
            "color": "NA",
            "page_num": page_idx + 1,
            "filename": filename,
            "confidence": 0.1,
            "validation_status": "Needs Review",
            "error_note": "OCR engine not available for scanned page"
        }

    pix = None
    img = None
    try:
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        ocr_text = pytesseract.image_to_string(img)
        res = extract_from_text(ocr_text, page_idx, filename)
        if res:
            res["confidence"] = min(res["confidence"], 0.8) # OCR slight discount
            return res
    except Exception as e:
        pass
    finally:
        try:
            del pix
            del img
        except Exception:
            pass

    return {
        "seller": "Unknown",
        "awb": "",
        "pickup": "",
        "order_no": f"OCR_FAILED_P{page_idx+1}",
        "sku": "Unknown SKU",
        "product_name": "Unknown",
        "size": "Unknown",
        "qty": 1,
        "color": "NA",
        "page_num": page_idx + 1,
        "filename": filename,
        "confidence": 0.1,
        "validation_status": "Needs Review",
        "error_note": "OCR fallback failed to extract order"
    }

def parse_pdf_file(filepath: str, filename: str = None, progress_callback = None) -> list:
    """Parse all pages in a given PDF file with bounded memory usage."""
    import gc
    if filename is None:
        filename = os.path.basename(filepath)

    doc = fitz.open(filepath)
    total_pages = len(doc)
    results = []

    for page_idx in range(total_pages):
        page = doc[page_idx]
        text = page.get_text()
        if len(text.strip()) < 50:
            # Scanned or non-selectable page -> try OCR
            data = ocr_page(page, page_idx, filename)
        else:
            data = extract_from_text(text, page_idx, filename)
            if not data or data["validation_status"] == "Needs Review":
                # If text extraction was partial or failed, try OCR as fallback
                if HAS_OCR:
                    ocr_data = ocr_page(page, page_idx, filename)
                    if ocr_data and ocr_data["validation_status"] == "Valid":
                        data = ocr_data

        if not data:
            data = {
                "seller": "Unknown",
                "awb": "",
                "pickup": "",
                "order_no": f"PARSE_ERR_P{page_idx+1}",
                "sku": "Unknown SKU",
                "product_name": "Unknown",
                "size": "Unknown",
                "qty": 1,
                "color": "NA",
                "page_num": page_idx + 1,
                "filename": filename,
                "confidence": 0.0,
                "validation_status": "Needs Review",
                "error_note": "Page extraction failed completely"
            }
        results.append(data)
        del page

        # Periodic garbage collection and progress notification
        if (page_idx + 1) % 50 == 0:
            gc.collect()
            if progress_callback:
                try:
                    progress_callback(page_idx + 1, total_pages)
                except Exception:
                    pass

    doc.close()
    gc.collect()
    if progress_callback:
        try:
            progress_callback(total_pages, total_pages)
        except Exception:
            pass

    return results
