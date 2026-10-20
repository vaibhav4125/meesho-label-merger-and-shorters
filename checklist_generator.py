import os
import re
from datetime import datetime
import fitz

def clean_pdf_text(text: str) -> str:
    """Strip emojis and non-ASCII chars for clean rendering in standard Helvetica."""
    if not text:
        return ""
    # Replace common formatting characters, preserve letters, digits, spaces and punctuation
    cleaned = re.sub(r'[^\x20-\x7E]', ' ', str(text))
    return " ".join(cleaned.split())

def generate_picking_checklist_pdf(
    data: dict,
    category_title: str = "All Categories",
    output_filename: str = None
) -> str:
    """
    Generate a clean, high-contrast, professional A4 printable picking & packing checklist PDF.
    Every size item has a tick-box [ ] so warehouse workers can tick off pieces while picking.
    """
    _cur = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(_cur) if os.path.basename(_cur) == "backend" else _cur
    output_dir = os.path.join(base_dir, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    clean_cat_title = clean_pdf_text(category_title) or "All Categories"

    if not output_filename:
        safe_cat = "".join(c if c.isalnum() else "_" for c in clean_cat_title).strip("_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"Picking_Checklist_{safe_cat}_{ts}.pdf"

    output_path = os.path.join(output_dir, output_filename)

    doc = fitz.open()

    # A4 Dimensions in points (72 points/inch)
    PAGE_WIDTH = 595.32
    PAGE_HEIGHT = 841.92
    MARGIN_LEFT = 36.0
    MARGIN_RIGHT = PAGE_WIDTH - 36.0
    USABLE_WIDTH = MARGIN_RIGHT - MARGIN_LEFT
    MARGIN_BOTTOM = PAGE_HEIGHT - 36.0

    total_products = data.get("total_products", 0)
    total_colors = data.get("total_colors", 0)
    total_orders = data.get("total_orders", 0)
    total_pieces = data.get("total_pieces", 0)
    products = data.get("products", [])

    def start_new_page():
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

        # Header Background
        header_rect = fitz.Rect(MARGIN_LEFT, 30, MARGIN_RIGHT, 65)
        page.draw_rect(header_rect, color=(0.06, 0.09, 0.16), fill=(0.06, 0.09, 0.16))

        # Title
        page.insert_text(
            (MARGIN_LEFT + 10, 48),
            "ORDER PICKING & PACKING CHECKLIST",
            fontsize=12,
            fontname="helv",
            color=(1, 1, 1)
        )
        page.insert_text(
            (MARGIN_LEFT + 10, 59),
            f"Category: {clean_cat_title}  |  Batch Date: {datetime.now().strftime('%d-%b-%Y %I:%M %p')}",
            fontsize=8.5,
            fontname="helv",
            color=(0.8, 0.85, 0.9)
        )

        # Summary Sub-header Bar
        summary_rect = fitz.Rect(MARGIN_LEFT, 65, MARGIN_RIGHT, 83)
        page.draw_rect(summary_rect, color=(0.85, 0.88, 0.92), fill=(0.95, 0.96, 0.98))
        summary_txt = f"TOTALS:  {total_products} Products  |  {total_colors} Colors  |  {total_pieces} Total Pieces  |  {total_orders} Orders"
        page.insert_text(
            (MARGIN_LEFT + 10, 77),
            summary_txt,
            fontsize=8.5,
            fontname="helv",
            color=(0.1, 0.15, 0.25)
        )

        return page, 96.0  # initial Y position for content

    current_page, cur_y = start_new_page()

    BOX_W = (USABLE_WIDTH - 24) / 5.0  # 5 boxes per row with 6pt spacing
    BOX_H = 22.0
    BOX_GAP = 6.0

    for p in products:
        p_name = clean_pdf_text(p.get("display_name", "Unknown Product"))
        p_cat = clean_pdf_text(p.get("category", ""))
        p_orders = p.get("total_orders", 0)
        p_pieces = p.get("total_pieces", 0)
        colors = p.get("colors", [])

        # Estimate required space for this product: banner (24pt) + first color header (18pt) + 1 row (25pt)
        needed_initial = 70.0
        if cur_y + needed_initial > MARGIN_BOTTOM - 20:
            current_page, cur_y = start_new_page()

        # Product Header Banner
        grp_banner_rect = fitz.Rect(MARGIN_LEFT, cur_y, MARGIN_RIGHT, cur_y + 22)
        current_page.draw_rect(grp_banner_rect, color=(0.7, 0.75, 0.85), fill=(0.92, 0.94, 0.98))
        
        # Product Title
        cat_badge = f"  [{p_cat}]" if p_cat else ""
        current_page.insert_text(
            (MARGIN_LEFT + 8, cur_y + 15),
            f"PRODUCT: {p_name.upper()}{cat_badge}",
            fontsize=9.5,
            fontname="helv",
            color=(0.05, 0.1, 0.2)
        )

        # Right-aligned pieces count
        right_info = f"Total: {p_pieces} Pcs ({p_orders} Orders)"
        r_len = fitz.get_text_length(right_info, fontname="helv", fontsize=9.5)
        current_page.insert_text(
            (MARGIN_RIGHT - r_len - 8, cur_y + 15),
            right_info,
            fontsize=9.5,
            fontname="helv",
            color=(0.1, 0.5, 0.2)
        )

        cur_y += 28.0

        for c in colors:
            c_name = clean_pdf_text(c.get("color", "Unknown"))
            c_orders = c.get("orders_count", 0)
            c_pieces = c.get("pieces_count", 0)
            sizes = c.get("sizes", [])

            # Calculate height needed for this color block
            rows_count = (len(sizes) + 4) // 5 if sizes else 1
            color_needed = 20.0 + (rows_count * (BOX_H + 4.0)) + 20.0

            if cur_y + color_needed > MARGIN_BOTTOM - 20:
                current_page, cur_y = start_new_page()
                # Repeat product name indicator
                current_page.insert_text(
                    (MARGIN_LEFT + 6, cur_y + 10),
                    f"(Cont.) PRODUCT: {p_name.upper()}",
                    fontsize=8.5,
                    fontname="helv",
                    color=(0.4, 0.45, 0.5)
                )
                cur_y += 18.0

            # Color Title
            c_rect = fitz.Rect(MARGIN_LEFT + 2, cur_y + 1, MARGIN_LEFT + 9, cur_y + 8)
            current_page.draw_rect(c_rect, color=(0.2, 0.3, 0.6), fill=(0.2, 0.3, 0.6))

            current_page.insert_text(
                (MARGIN_LEFT + 14, cur_y + 8),
                f"COLOR: {c_name.upper()}",
                fontsize=9.0,
                fontname="helv",
                color=(0.1, 0.1, 0.15)
            )

            c_info_txt = f"{c_pieces} pcs ({c_orders} orders)"
            c_info_len = fitz.get_text_length(c_info_txt, fontname="helv", fontsize=8.5)
            current_page.insert_text(
                (MARGIN_RIGHT - c_info_len - 6, cur_y + 8),
                c_info_txt,
                fontsize=8.5,
                fontname="helv",
                color=(0.3, 0.35, 0.45)
            )

            cur_y += 14.0

            # Draw size boxes grid (5 per row)
            for s_idx, s in enumerate(sizes):
                col_idx = s_idx % 5
                row_idx = s_idx // 5

                bx = MARGIN_LEFT + col_idx * (BOX_W + BOX_GAP)
                by = cur_y + row_idx * (BOX_H + 4.0)

                box_rect = fitz.Rect(bx, by, bx + BOX_W, by + BOX_H)
                current_page.draw_rect(box_rect, color=(0.8, 0.83, 0.88), fill=(0.98, 0.99, 1.0), width=0.7)

                # Checkbox square [ ]
                cb_rect = fitz.Rect(bx + 4, by + 5, bx + 15, by + 16)
                current_page.draw_rect(cb_rect, color=(0.3, 0.35, 0.45), fill=(1, 1, 1), width=0.8)

                # Size Name
                sz_name = clean_pdf_text(s.get("size", "-"))
                current_page.insert_text(
                    (bx + 18, by + 14),
                    sz_name,
                    fontsize=8.0,
                    fontname="helv",
                    color=(0.1, 0.15, 0.2)
                )

                # Bold Quantity
                qty_txt = f"{s.get('orders_count', 0)} pcs"
                qty_len = fitz.get_text_length(qty_txt, fontname="helv", fontsize=8.0)
                current_page.insert_text(
                    (bx + BOX_W - qty_len - 4, by + 14),
                    qty_txt,
                    fontsize=8.0,
                    fontname="helv",
                    color=(0.05, 0.1, 0.15)
                )

            # Advance Y past size rows
            cur_y += rows_count * (BOX_H + 4.0) + 4.0

            # Color subtotal checklist row
            sub_rect = fitz.Rect(MARGIN_LEFT + 6, cur_y, MARGIN_LEFT + 17, cur_y + 11)
            current_page.draw_rect(sub_rect, color=(0.2, 0.5, 0.2), fill=(1, 1, 1), width=0.8)
            current_page.insert_text(
                (MARGIN_LEFT + 22, cur_y + 9),
                f"CHECK & PACK COMPLETE: {c_name.upper()} ({c_pieces} Pieces Total)",
                fontsize=7.8,
                fontname="helv",
                color=(0.25, 0.3, 0.35)
            )

            # Divider line
            current_page.draw_line(
                (MARGIN_LEFT, cur_y + 14),
                (MARGIN_RIGHT, cur_y + 14),
                color=(0.9, 0.92, 0.95),
                width=0.6
            )

            cur_y += 20.0

        cur_y += 10.0  # space after product group

    # Add Footers to all pages with Page X of Y
    total_pages = len(doc)
    for p_num, page in enumerate(doc, start=1):
        # Footer line
        page.draw_line(
            (MARGIN_LEFT, PAGE_HEIGHT - 26),
            (MARGIN_RIGHT, PAGE_HEIGHT - 26),
            color=(0.85, 0.88, 0.92),
            width=0.6
        )
        footer_txt = f"Page {p_num} of {total_pages}   |   Meesho Order Sorting System   |   A4 Inventory Picking Checklist"
        f_len = fitz.get_text_length(footer_txt, fontname="helv", fontsize=7.5)
        page.insert_text(
            ((PAGE_WIDTH - f_len) / 2.0, PAGE_HEIGHT - 16),
            footer_txt,
            fontsize=7.5,
            fontname="helv",
            color=(0.5, 0.55, 0.6)
        )

    doc.save(output_path)
    doc.close()
    return output_filename
