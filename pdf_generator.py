import os
import re
import zipfile
from collections import defaultdict
import fitz # PyMuPDF
try:
    from .database import get_db
except (ImportError, ValueError):
    from database import get_db

_cur_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_cur_dir) if os.path.basename(_cur_dir) == "backend" else _cur_dir
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Preset size orders
ADULT_SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL", "5XL", "Free Size"]
CHILDREN_SIZE_ORDER = [
    "0-1 Years", "0-3 Months", "3-6 Months", "6-9 Months", "9-12 Months",
    "1-2 Years", "2-3 Years", "3-4 Years", "4-5 Years", "5-6 Years",
    "6-7 Years", "7-8 Years", "8-9 Years", "9-10 Years", "10-11 Years",
    "11-12 Years", "12-13 Years", "13-14 Years", "14-15 Years"
]

def sanitize_filename(name: str) -> str:
    """Turn a group or SKU name into a clean, safe filename."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r"\s+", "_", clean.strip())
    clean = re.sub(r"[()\[\].]", "", clean)
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean or "Product"

def get_size_sort_key(size: str, custom_order: list = None) -> tuple:
    """Calculate sorting rank for a size value."""
    size_clean = size.strip()

    if custom_order:
        # User defined order
        for idx, s in enumerate(custom_order):
            if s.lower() == size_clean.lower():
                return (0, idx)

    # Check Children size list first if it contains Years or Months
    if "year" in size_clean.lower() or "month" in size_clean.lower():
        for idx, s in enumerate(CHILDREN_SIZE_ORDER):
            if s.lower() == size_clean.lower():
                return (1, idx)
        # Try extracting numbers
        nums = re.findall(r"\d+", size_clean)
        if nums:
            return (1, int(nums[0]))
        return (1, 999)

    # Check Adult sizes
    size_upper = size_clean.upper()
    for idx, s in enumerate(ADULT_SIZE_ORDER):
        if s == size_upper:
            return (2, idx)

    # Check numeric apparel sizes (e.g. 28, 30, 32, 34, 36, 38, 40, 42...)
    if size_clean.isdigit():
        return (2.5, int(size_clean))

    return (3, size_clean.lower())

def generate_sorted_pdf(
    group_id: int = None,
    sku: str = None,
    included_sizes: list = None,
    sort_preset: str = "auto", # 'adult', 'children', 'custom', 'auto'
    custom_size_order: list = None,
    secondary_sort: str = "sku", # 'sku', 'seller', 'pickup', 'filename', 'page'
    output_filename: str = None
) -> dict:
    """
    Generate a sorted PDF containing original, unmodified shipping label pages.
    Preserves exact vector labels, barcodes, addresses, and invoices.
    """
    with get_db() as conn:
        # 1. Determine target group name and SKUs
        target_skus = []
        group_name = ""

        if group_id:
            group = conn.execute("SELECT id, name, category FROM product_groups WHERE id = ?", (group_id,)).fetchone()
            if not group:
                raise ValueError(f"Product Group with ID {group_id} not found")
            group_name = group["name"]
            grp_category = group["category"]
            mappings = conn.execute("SELECT sku FROM sku_mappings WHERE group_id = ?", (group_id,)).fetchall()
            target_skus = [m["sku"] for m in mappings]
            if not target_skus:
                raise ValueError(f"Product Group '{group_name}' has no mapped SKUs")
        elif sku:
            group_name = sku
            grp = conn.execute("SELECT g.category FROM product_groups g JOIN sku_mappings m ON g.id = m.group_id WHERE m.sku = ?", (sku,)).fetchone()
            grp_category = grp["category"] if grp else None
            target_skus = [sku]
        else:
            raise ValueError("Either group_id or sku must be provided")

        from .services import parse_sku_and_color, normalize_color_name, detect_product_category
        cat = detect_product_category(group_name, grp_category)
        is_women_tshirt = (cat == "Women T-Shirt")

        # 2. Query eligible orders
        placeholders = ",".join("?" for _ in target_skus)
        query = f"""
            SELECT o.*, f.filepath, f.filename as src_filename
            FROM orders o
            JOIN uploaded_files f ON o.file_id = f.id
            WHERE o.sku IN ({placeholders})
              AND o.is_excluded = 0
        """
        params = list(target_skus)

        if included_sizes:
            effective_filter_sizes = list(included_sizes)
            if is_women_tshirt and "M" in [s.upper() for s in included_sizes] and "S" not in [s.upper() for s in included_sizes]:
                effective_filter_sizes.append("S")
            size_placeholders = ",".join("?" for _ in effective_filter_sizes)
            query += f" AND o.size IN ({size_placeholders})"
            params.extend(effective_filter_sizes)

        rows = conn.execute(query, params).fetchall()
        orders = [dict(r) for r in rows]

        if not orders:
            raise ValueError(f"No eligible orders found for '{group_name}' with the selected sizes")

        # 3. Detect size sorting strategy if 'auto'
        active_custom_order = custom_size_order or []
        if sort_preset == "auto":
            # Count if majority are kids sizes vs adult sizes
            kids_count = sum(1 for o in orders if "year" in o["size"].lower() or "month" in o["size"].lower())
            if kids_count > len(orders) / 2:
                active_custom_order = CHILDREN_SIZE_ORDER
            else:
                active_custom_order = ADULT_SIZE_ORDER
        elif sort_preset == "children":
            active_custom_order = CHILDREN_SIZE_ORDER
        elif sort_preset == "adult":
            active_custom_order = ADULT_SIZE_ORDER

        # 3b. Group colors and sizes for this product
        color_counts = defaultdict(int)
        color_size_counts = defaultdict(lambda: defaultdict(int))
        for o in orders:
            raw_sku = o.get("sku") or ""
            _, color_raw = parse_sku_and_color(raw_sku, o.get("color"))
            norm_color = normalize_color_name(color_raw)
            o["norm_color"] = norm_color
            raw_sz = (o.get("size") or "Unknown").strip()
            eff_sz = "M" if is_women_tshirt and raw_sz.upper() == "S" else raw_sz
            o["effective_size"] = eff_sz
            color_counts[norm_color] += 1
            color_size_counts[norm_color][eff_sz] += 1

        # 4. Sort orders: Color (by order volume) -> Effective Size -> Secondary
        def sort_key(o):
            clr = o["norm_color"]
            clr_rank = (-color_counts[clr], clr.lower())
            size_rank = get_size_sort_key(o["effective_size"], active_custom_order)
            raw_sz = (o.get("size") or "").strip().upper()
            orig_sz_rank = 0 if raw_sz == "S" else 1
            sec_val = ""
            if secondary_sort == "seller":
                sec_val = o.get("seller_account") or ""
            elif secondary_sort == "pickup":
                sec_val = o.get("pickup_date") or ""
            elif secondary_sort == "filename":
                sec_val = o.get("src_filename") or ""
            elif secondary_sort == "sku":
                sec_val = o.get("sku") or ""
            else: # page
                sec_val = f"{o.get('src_filename')}_{o.get('page_number', 0):05d}"
            return (clr_rank, size_rank, orig_sz_rank, sec_val, o.get("order_no", ""))

        sorted_orders = sorted(orders, key=sort_key)

        # 5. Determine output filename
        if not output_filename:
            safe_name = sanitize_filename(group_name)
            output_filename = f"{safe_name}_Sorted.pdf"

        out_path = os.path.join(OUTPUT_DIR, output_filename)

        # 6. Build the merged PDF by inserting original pages
        src_docs = {}
        out_doc = fitz.open()
        toc = []
        current_clr = None
        current_sz = None

        try:
            for idx, o in enumerate(sorted_orders):
                page_1_based = idx + 1
                clr = o["norm_color"]
                sz = o["effective_size"]

                # Bookmark Level 1: Color
                if clr != current_clr:
                    current_clr = clr
                    current_sz = None
                    toc.append([1, f"{clr} ({color_counts[clr]} bills)", page_1_based])

                # Bookmark Level 2: Size
                if sz != current_sz:
                    current_sz = sz
                    toc.append([2, f"{sz} ({color_size_counts[clr][sz]} bills)", page_1_based])

                fpath = o["filepath"]
                if fpath not in src_docs:
                    if not os.path.exists(fpath):
                        raise FileNotFoundError(f"Source PDF file not found: {fpath}")
                    src_docs[fpath] = fitz.open(fpath)

                src_doc = src_docs[fpath]
                page_idx = o["page_number"] - 1 # 0-indexed in PyMuPDF

                if page_idx < 0 or page_idx >= len(src_doc):
                    raise IndexError(f"Page {o['page_number']} out of range in {fpath} (total pages: {len(src_doc)})")

                # Insert original PDF page directly without rasterization or resizing
                out_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)

            if toc:
                out_doc.set_toc(toc)

            # Save generated PDF
            out_doc.save(out_path, deflate=True)
            generated_page_count = len(out_doc)
        finally:
            out_doc.close()
            for d in src_docs.values():
                d.close()
            import gc
            gc.collect()

        # 7. Verification checks
        expected_page_count = len(sorted_orders)
        if generated_page_count != expected_page_count:
            raise RuntimeError(
                f"PDF verification failed! Generated page count ({generated_page_count}) "
                f"does not match expected order count ({expected_page_count})"
            )

        # Build size breakdown summary
        size_summary = {}
        for o in sorted_orders:
            sz_key = o.get("effective_size") or o["size"]
            size_summary[sz_key] = size_summary.get(sz_key, 0) + o.get("qty", 1)

        # Record into generated_pdfs database table
        cursor = conn.execute("""
            INSERT INTO generated_pdfs (group_id, group_name, filename, filepath, order_count, page_count, verified, size_summary_json)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            group_id,
            group_name,
            output_filename,
            out_path,
            len(sorted_orders),
            generated_page_count,
            str(size_summary)
        ))
        record_id = cursor.lastrowid

        return {
            "id": record_id,
            "group_name": group_name,
            "filename": output_filename,
            "filepath": out_path,
            "order_count": len(sorted_orders),
            "page_count": generated_page_count,
            "verified": True,
            "size_summary": size_summary,
            "download_url": f"/api/download/{output_filename}"
        }

def batch_generate_sorted_pdfs(
    group_ids: list = None,
    skus: list = None,
    sort_preset: str = "auto",
    secondary_sort: str = "sku",
    create_zip: bool = True
) -> dict:
    """Generate separate sorted PDFs for multiple product groups and bundle into a ZIP."""
    results = []
    generated_files = []

    # Process groups
    if group_ids:
        for gid in group_ids:
            try:
                res = generate_sorted_pdf(
                    group_id=gid,
                    sort_preset=sort_preset,
                    secondary_sort=secondary_sort
                )
                results.append(res)
                generated_files.append((res["filename"], res["filepath"]))
            except Exception as e:
                results.append({
                    "group_id": gid,
                    "error": str(e),
                    "verified": False
                })

    # Process individual SKUs
    if skus:
        for sku_val in skus:
            try:
                res = generate_sorted_pdf(
                    sku=sku_val,
                    sort_preset=sort_preset,
                    secondary_sort=secondary_sort
                )
                results.append(res)
                generated_files.append((res["filename"], res["filepath"]))
            except Exception as e:
                results.append({
                    "sku": sku_val,
                    "error": str(e),
                    "verified": False
                })

    zip_filename = None
    zip_url = None
    if create_zip and generated_files:
        zip_filename = "Meesho_Sorted_Labels_Bundle.zip"
        zip_path = os.path.join(OUTPUT_DIR, zip_filename)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, fpath in generated_files:
                if os.path.exists(fpath):
                    zf.write(fpath, arcname=fname)
        zip_url = f"/api/download/{zip_filename}"

    return {
        "success": True,
        "results": results,
        "total_generated": len(generated_files),
        "zip_filename": zip_filename,
        "zip_url": zip_url
    }

def generate_all_merged_sorted_pdf(
    group_ids: list = None,
    sort_preset: str = "auto",
    secondary_sort: str = "sku",
    sort_mode: str = "color_first",
    output_filename: str = "Meesho_All_Orders_Merged_Sorted.pdf"
) -> dict:
    """
    Merge ALL orders across all products into ONE SINGLE continuous downloadable PDF.
    Does NOT create a ZIP archive.
    Preserves 100% of all pages with zero omissions, zero rasterization, and zero page drops.
    Sort hierarchy:
      - When sort_mode == 'size_first':
          1. Product Group / Design (by order volume descending)
          2. Size (kids 0-1Y to 14Y, adult XS to XXL)
          3. Color (consecutive per size)
          4. Secondary sorting (SKU, order number, page)
      - When sort_mode == 'color_first' (default):
          1. Product Group / Design (by order volume descending)
          2. Color (by order volume descending)
          3. Size (ordered logically)
          4. Secondary sorting (SKU, order number, page)
    Embeds PDF Bookmarks (TOC) for instant navigation across products, colors, and sizes.
    """
    with get_db() as conn:
        query = """
            SELECT o.*, f.filepath, f.filename as src_filename,
                   CASE WHEN g.name IS NULL OR g.name = '' OR g.name = 'undefined' THEN 'Unmapped' ELSE g.name END as group_name,
                   COALESCE(g.id, 0) as grp_id,
                   g.category as grp_category
            FROM orders o
            JOIN uploaded_files f ON o.file_id = f.id
            LEFT JOIN sku_mappings m ON o.sku = m.sku
            LEFT JOIN product_groups g ON m.group_id = g.id
            WHERE o.is_excluded = 0
        """
        params = []

        if group_ids and len(group_ids) > 0:
            placeholders = ",".join("?" for _ in group_ids)
            query += f" AND (g.id IN ({placeholders}) OR m.group_id IN ({placeholders}))"
            params.extend(group_ids)

        rows = conn.execute(query, params).fetchall()
        orders = [dict(r) for r in rows]

        if not orders:
            raise ValueError("No eligible orders found to merge into a single PDF")

        total_eligible_orders = len(orders)

        # 1. Parse SKU base, normalized color, and assign display product group
        from .services import parse_sku_and_color, normalize_color_name, detect_product_category, get_all_category_meta
        cat_meta = get_all_category_meta()
        group_counts = defaultdict(int)
        group_color_counts = defaultdict(lambda: defaultdict(int))
        group_color_size_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        group_size_counts = defaultdict(lambda: defaultdict(int))
        group_size_color_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        for o in orders:
            raw_sku = o.get("sku") or "Unknown SKU"
            base, color_raw = parse_sku_and_color(raw_sku, o.get("color"))
            norm_color = normalize_color_name(color_raw)
            gname = o.get("group_name")
            display_group = gname if (gname and gname not in ("Unmapped", "undefined")) else base

            grp_category = detect_product_category(display_group, o.get("grp_category"))
            cat_priority = cat_meta.get(grp_category, {}).get("priority", 99)

            o["display_group"] = display_group
            o["norm_color"] = norm_color
            o["cat_priority"] = cat_priority
            raw_sz = (o.get("size") or "Unknown").strip()
            is_women_tshirt = (grp_category == "Women T-Shirt")
            eff_sz = "M" if is_women_tshirt and raw_sz.upper() == "S" else raw_sz
            o["effective_size"] = eff_sz

            group_counts[display_group] += 1
            group_color_counts[display_group][norm_color] += 1
            group_color_size_counts[display_group][norm_color][eff_sz] += 1
            group_size_counts[display_group][eff_sz] += 1
            group_size_color_counts[display_group][eff_sz][norm_color] += 1

        # 2. Sort orders according to the selected hierarchy
        if sort_mode == "size_first":
            def order_sort_key(o):
                grp = o["display_group"]
                clr = o["norm_color"]
                eff_sz = o.get("effective_size") or "Unknown"
                orig_sz = (o.get("size") or "Unknown").strip().upper()
                grp_rank = (o.get("cat_priority", 99), -group_counts[grp], grp.lower())
                size_rank = get_size_sort_key(eff_sz)
                clr_rank = (-group_size_color_counts[grp][eff_sz][clr], clr.lower())
                sz_subrank = (0 if orig_sz == "S" else 1) if o.get("grp_category") == "Women T-Shirt" else 0
                sec_val = ""
                if secondary_sort == "seller":
                    sec_val = o.get("seller_account") or ""
                elif secondary_sort == "pickup":
                    sec_val = o.get("pickup_date") or ""
                elif secondary_sort == "filename":
                    sec_val = o.get("src_filename") or ""
                else:
                    sec_val = o.get("sku") or ""
                return (grp_rank, size_rank, clr_rank, sz_subrank, sec_val, o.get("order_no", ""), o.get("page_number", 0))
        else:
            def order_sort_key(o):
                grp = o["display_group"]
                clr = o["norm_color"]
                eff_sz = o.get("effective_size") or "Unknown"
                orig_sz = (o.get("size") or "Unknown").strip().upper()
                grp_rank = (o.get("cat_priority", 99), -group_counts[grp], grp.lower())
                clr_rank = (-group_color_counts[grp][clr], clr.lower())
                size_rank = get_size_sort_key(eff_sz)
                sz_subrank = (0 if orig_sz == "S" else 1) if o.get("grp_category") == "Women T-Shirt" else 0
                sec_val = ""
                if secondary_sort == "seller":
                    sec_val = o.get("seller_account") or ""
                elif secondary_sort == "pickup":
                    sec_val = o.get("pickup_date") or ""
                elif secondary_sort == "filename":
                    sec_val = o.get("src_filename") or ""
                else:
                    sec_val = o.get("sku") or ""
                return (grp_rank, clr_rank, size_rank, sz_subrank, sec_val, o.get("order_no", ""), o.get("page_number", 0))

        sorted_orders = sorted(orders, key=order_sort_key)

        out_path = os.path.join(OUTPUT_DIR, output_filename)
        src_docs = {}
        out_doc = fitz.open()

        toc = []
        current_grp = None
        current_clr = None
        current_sz = None

        try:
            for idx, o in enumerate(sorted_orders):
                page_1_based = idx + 1
                grp = o["display_group"]
                clr = o["norm_color"]
                sz = o.get("effective_size") or "Unknown"

                if sort_mode == "size_first":
                    # Bookmark Level 1: Product Group / Design
                    if grp != current_grp:
                        current_grp = grp
                        current_sz = None
                        current_clr = None
                        toc.append([1, f"{grp} ({group_counts[grp]} bills)", page_1_based])

                    # Bookmark Level 2: Size
                    if sz != current_sz:
                        current_sz = sz
                        current_clr = None
                        toc.append([2, f"Size: {sz} ({group_size_counts[grp][sz]} bills)", page_1_based])

                    # Bookmark Level 3: Color
                    if clr != current_clr:
                        current_clr = clr
                        toc.append([3, f"{clr} ({group_size_color_counts[grp][sz][clr]} bills)", page_1_based])
                else:
                    # Bookmark Level 1: Product Group
                    if grp != current_grp:
                        current_grp = grp
                        current_clr = None
                        current_sz = None
                        toc.append([1, f"{grp} ({group_counts[grp]} bills)", page_1_based])

                    # Bookmark Level 2: Color
                    if clr != current_clr:
                        current_clr = clr
                        current_sz = None
                        toc.append([2, f"{clr} ({group_color_counts[grp][clr]} bills)", page_1_based])

                    # Bookmark Level 3: Size
                    if sz != current_sz:
                        current_sz = sz
                        toc.append([3, f"{sz} ({group_color_size_counts[grp][clr][sz]} bills)", page_1_based])

                fpath = o["filepath"]
                if fpath not in src_docs:
                    if not os.path.exists(fpath):
                        raise FileNotFoundError(f"Source PDF file not found: {fpath}")
                    src_docs[fpath] = fitz.open(fpath)

                src_doc = src_docs[fpath]
                page_idx = o["page_number"] - 1

                if page_idx < 0 or page_idx >= len(src_doc):
                    raise IndexError(f"Page {o['page_number']} out of range in {fpath}")

                out_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)

            if toc:
                out_doc.set_toc(toc)

            out_doc.save(out_path, deflate=True)
            generated_page_count = len(out_doc)
        finally:
            out_doc.close()
            for d in src_docs.values():
                d.close()

        # Strict Verification Check: Not a single page must be removed or missing!
        expected_page_count = len(sorted_orders)
        if generated_page_count != expected_page_count:
            raise RuntimeError(
                f"Page count verification failed! Expected {expected_page_count} pages, "
                f"but generated PDF contains {generated_page_count} pages!"
            )
        if generated_page_count != total_eligible_orders:
            raise RuntimeError(
                f"Critical Error: Generated {generated_page_count} pages but eligible orders count was {total_eligible_orders}!"
            )

        # Record into generated_pdfs database table
        display_label = "ALL PRODUCTS MERGED (Size-Wise PDF)" if sort_mode == "size_first" else "ALL PRODUCTS MERGED (Single PDF)"
        cursor = conn.execute("""
            INSERT INTO generated_pdfs (group_id, group_name, filename, filepath, order_count, page_count, verified, size_summary_json)
            VALUES (NULL, ?, ?, ?, ?, ?, 1, ?)
        """, (
            display_label,
            output_filename,
            out_path,
            len(sorted_orders),
            generated_page_count,
            '{"total_merged": ' + str(generated_page_count) + '}'
        ))
        record_id = cursor.lastrowid

        return {
            "id": record_id,
            "group_name": "ALL PRODUCTS MERGED",
            "filename": output_filename,
            "filepath": out_path,
            "order_count": len(sorted_orders),
            "page_count": generated_page_count,
            "verified": True,
            "download_url": f"/api/download/{output_filename}"
        }
