import os
import re
import csv
import io
from collections import defaultdict
import pandas as pd
from .database import get_db
from .pdf_parser import parse_pdf_file
from .pdf_generator import ADULT_SIZE_ORDER, CHILDREN_SIZE_ORDER, get_size_sort_key

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

def process_file_records(file_id: int):
    """Parse PDF file and insert extracted orders with duplicate detection."""
    with get_db() as conn:
        f = conn.execute("SELECT filepath, filename FROM uploaded_files WHERE id = ?", (file_id,)).fetchone()
        if not f:
            raise ValueError("File not found")
        filepath = f["filepath"]
        filename = f["filename"]

        conn.execute("UPDATE uploaded_files SET status = 'processing' WHERE id = ?", (file_id,))

    try:
        results = parse_pdf_file(filepath, filename)

        with get_db() as conn:
            # Delete existing parsed orders for this file if re-processing
            conn.execute("DELETE FROM orders WHERE file_id = ?", (file_id,))

            for r in results:
                conn.execute("""
                    INSERT INTO orders (
                        file_id, page_number, seller_account, order_no, awb,
                        sku, product_name, size, qty, color, pickup_date,
                        confidence, validation_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    file_id,
                    r["page_num"],
                    r["seller"],
                    r["order_no"],
                    r["awb"],
                    r["sku"],
                    r.get("product_name", r["sku"]),
                    r["size"],
                    r["qty"],
                    r["color"],
                    r["pickup"],
                    r["confidence"],
                    r["validation_status"]
                ))

            # Mark completed with page count
            conn.execute(
                "UPDATE uploaded_files SET status = 'completed', page_count = ? WHERE id = ?",
                (len(results), file_id)
            )

            # Run duplicate detection across all orders
            check_and_flag_duplicates(conn)

        return len(results)
    except Exception as e:
        with get_db() as conn:
            conn.execute(
                "UPDATE uploaded_files SET status = 'error', error_message = ? WHERE id = ?",
                (str(e), file_id)
            )
        raise

def check_and_flag_duplicates(conn):
    """
    Find duplicate orders by order_no.
    Preserves original orders and flags subsequent occurrences as duplicates.
    Does not delete anything automatically.
    """
    # Reset duplicates first
    conn.execute("UPDATE orders SET is_duplicate = 0, duplicate_of_id = NULL WHERE validation_status != 'Needs Review'")

    duplicates = conn.execute("""
        SELECT order_no, COUNT(*) as cnt, MIN(id) as first_id
        FROM orders
        WHERE order_no NOT LIKE 'UNKNOWN_%' AND order_no NOT LIKE 'PARSE_%'
        GROUP BY order_no
        HAVING cnt > 1
    """).fetchall()

    for dup in duplicates:
        ord_no = dup["order_no"]
        first_id = dup["first_id"]
        conn.execute("""
            UPDATE orders
            SET is_duplicate = 1, duplicate_of_id = ?, validation_status = 'Duplicate'
            WHERE order_no = ? AND id != ?
        """, (first_id, ord_no, first_id))

def get_dashboard_summary():
    """Retrieve comprehensive statistics for the dashboard."""
    with get_db() as conn:
        total_files = conn.execute("SELECT COUNT(*) FROM uploaded_files").fetchone()[0]
        total_pages = conn.execute("SELECT COALESCE(SUM(page_count), 0) FROM uploaded_files").fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE is_excluded = 0").fetchone()[0]
        total_pieces = conn.execute("SELECT COALESCE(SUM(qty), 0) FROM orders WHERE is_excluded = 0").fetchone()[0]
        needs_review = conn.execute("SELECT COUNT(*) FROM orders WHERE validation_status = 'Needs Review'").fetchone()[0]
        duplicates_count = conn.execute("SELECT COUNT(*) FROM orders WHERE is_duplicate = 1").fetchone()[0]

        # Sellers breakdown
        sellers_rows = conn.execute("""
            SELECT seller_account, COUNT(*) as orders_count, SUM(qty) as pieces_count
            FROM orders
            WHERE is_excluded = 0
            GROUP BY seller_account
            ORDER BY orders_count DESC
        """).fetchall()
        sellers = [dict(r) for r in sellers_rows]

        # Top SKUs breakdown
        sku_rows = conn.execute("""
            SELECT o.sku,
                   CASE WHEN g.name IS NULL OR g.name = '' OR g.name = 'undefined' THEN 'Unmapped' ELSE g.name END as group_name,
                   COUNT(*) as orders_count, SUM(o.qty) as pieces_count
            FROM orders o
            LEFT JOIN sku_mappings m ON o.sku = m.sku
            LEFT JOIN product_groups g ON m.group_id = g.id
            WHERE o.is_excluded = 0
            GROUP BY o.sku
            ORDER BY orders_count DESC
            LIMIT 10
        """).fetchall()
        top_skus = []
        for r in sku_rows:
            sku_dict = dict(r)
            size_counts_rows = conn.execute("""
                SELECT size, COUNT(*) as orders_count, COALESCE(SUM(qty), 0) as pieces_count
                FROM orders
                WHERE sku = ? AND is_excluded = 0
                GROUP BY size
            """, (sku_dict["sku"],)).fetchall()
            
            sizes_list = [dict(sr) for sr in size_counts_rows]
            sizes_list.sort(key=lambda s: get_size_sort_key(s["size"]))
            sku_total_orders = sku_dict["orders_count"] or 1
            for s in sizes_list:
                s["percentage"] = round((s["orders_count"] / sku_total_orders) * 100, 1)
            sku_dict["sizes"] = sizes_list
            top_skus.append(sku_dict)

        # Top Sizes
        size_rows = conn.execute("""
            SELECT size, COUNT(*) as orders_count, COALESCE(SUM(qty), 0) as pieces_count
            FROM orders
            WHERE is_excluded = 0
            GROUP BY size
            ORDER BY orders_count DESC
        """).fetchall()
        sizes = [dict(r) for r in size_rows]
        sizes.sort(key=lambda s: get_size_sort_key(s["size"]))
        for s in sizes:
            s["percentage"] = round((s["orders_count"] / total_orders) * 100, 1) if total_orders > 0 else 0

        # Product Groups summary
        groups_count = conn.execute("SELECT COUNT(*) FROM product_groups").fetchone()[0]

        return {
            "total_files": total_files,
            "total_pages": total_pages,
            "total_orders": total_orders,
            "total_pieces": total_pieces,
            "needs_review": needs_review,
            "duplicates_count": duplicates_count,
            "groups_count": groups_count,
            "sellers": sellers,
            "top_skus": top_skus,
            "sizes": sizes
        }

def parse_sku_and_color(raw_sku: str, order_color: str = "NA"):
    """
    Extract base product/design name and color variation from a Meesho clothing SKU.
    Examples:
    - '( BEST MOOD  ) PLAZO PAR 1004- Sky Blue' -> ('( BEST MOOD  ) PLAZO PAR 1004', 'Sky Blue')
    - 'W.H.T. Hug Me Taddy ( Chiku).' -> ('W.H.T. Hug Me Taddy', 'Chiku')
    - 'IFM(LAVENDER)' -> ('IFM', 'LAVENDER')
    """
    if not raw_sku:
        return "Unknown SKU", "Default"
    s = raw_sku.strip().rstrip('.;, ')

    # Check parenthetical color at end: 'W.H.T. Hug Me Taddy ( Chiku).' or 'IFM(LAVENDER)'
    m_paren = re.search(r'\(([^)]+)\)\.?$', s)
    if m_paren:
        candidate = m_paren.group(1).strip()
        base = s[:m_paren.start()].strip()
        if base:
            return base, candidate

    # Check '=' separator: 'L.A = BLACK'
    if '=' in s:
        parts = s.rsplit('=', 1)
        base = parts[0].strip()
        color_part = parts[1].strip().rstrip('.; ')
        if base and color_part:
            return base, color_part

    # Check hyphenated color: '( BEST MOOD ) PLAZO PAR 1004- Sky Blue'
    if '-' in s:
        parts = s.rsplit('-', 1)
        base = parts[0].strip()
        color_part = parts[1].strip().rstrip('.; ')
        if base and color_part:
            return base, color_part

    # Fallback to order_color if valid
    if order_color and order_color not in ('NA', 'Unknown'):
        return s, order_color

    return s, 'Default'

def normalize_color_name(c: str) -> str:
    """Standardize color names so case variations and common synonyms merge seamlessly."""
    if not c or c in ("NA", "Unknown", "Default"):
        return "Standard"
    c_clean = c.strip().rstrip(".;, ")
    c_upper = c_clean.upper()
    if c_upper in ("GRAY", "GREY"):
        return "Grey"
    if c_upper in ("SKY BLUE", "SKYBLUE"):
        return "Sky Blue"
    if c_upper in ("C.GREEN", "C GREEN", "CGREEN", "C.CREEN"):
        return "C.Green"
    if c_upper in ("LAVENDER", "LAVENDAR", "LAVENDWR"):
        return "Lavender"
    if c_upper in ("CHIKU", "CHIKOO", "BEIGE"):
        return "Chiku"
    if c_upper in ("CREAM", "CREEM"):
        return "Cream"
    if c_upper in ("WHITE",):
        return "White"
    if c_upper in ("BLACK",):
        return "Black"
    if c_upper in ("PINK",):
        return "Pink"
    if c_upper in ("PISTA",):
        return "Pista"
    return c_clean.title()

CATEGORY_META = {
    "Plazo": {"label": "👖 Plazo / Bottoms", "priority": 1, "icon": "👖"},
    "Women T-Shirt": {"label": "👕 Women T-Shirts & Tops", "priority": 2, "icon": "👕"},
    "Men T-Shirt": {"label": "👕 Men T-Shirts", "priority": 3, "icon": "👕"},
    "Black Patti": {"label": "🏷️ Black Patti", "priority": 4, "icon": "🏷️"},
    "Black Pati": {"label": "🏷️ Black Patti", "priority": 4, "icon": "🏷️"},
    "General": {"label": "📦 General", "priority": 5, "icon": "📦"},
    "Other": {"label": "📦 Other Products", "priority": 6, "icon": "📦"}
}

def get_all_category_meta():
    """Retrieve combined CATEGORY_META dynamically including all user-defined categories."""
    meta = dict(CATEGORY_META)
    try:
        from .database import get_db
        with get_db() as conn:
            rows = conn.execute("SELECT name, label, icon, display_order FROM product_categories ORDER BY display_order ASC, id ASC").fetchall()
            for r in rows:
                cname = r["name"]
                cicon = r["icon"] or "🏷️"
                clabel = r["label"] or f"{cicon} {cname}"
                corder = r["display_order"] if r["display_order"] is not None else 10
                meta[cname] = {
                    "label": clabel,
                    "priority": corder,
                    "icon": cicon
                }
    except Exception:
        pass
    return meta

def get_all_product_categories():
    """Retrieve list of all categories from DB."""
    from .database import get_all_categories_db
    return get_all_categories_db()

def add_product_category(name: str, label: str = None, icon: str = "🏷️", display_order: float = None):
    """Add a new product category."""
    from .database import add_category_db
    return add_category_db(name, label, icon, display_order)

def delete_product_category(name: str):
    """Delete a custom product category."""
    from .database import delete_category_db
    return delete_category_db(name)

def detect_product_category(name: str, existing_cat: str = None) -> str:
    if existing_cat and existing_cat not in ("General", "undefined", "", "None"):
        if existing_cat in ("Black Pati", "BLACK PATI"):
            return "Black Patti"
        return existing_cat
    n = (name or "").upper()
    if any(k in n for k in ["PLAZO", "PLAZZA", "PLAAZO", "PANTS", "PALAZZO", "TROUSER"]):
        return "Plazo"
    if any(k in n for k in ["BLACK PATTI", "BLACK PATI"]):
        return "Black Patti"
    if any(k in n for k in ["MEN T-SHIRT", "MEN TSHIRT", "MEN T SHIRT", "MEN T", "MENS T-SHIRT", "MAN T-SHIRT"]):
        return "Men T-Shirt"
    if any(k in n for k in ["T-SHIRT", "TSHIRT", "T SHIRT", "HUG ME", "TADDY", "TEDDY", "V NACK", "V-NECK", "V NECK", "M.O.T", "W.O.T", "IFM", "BURGER", "TEAM MINATO", "CHAOS", "WILD", "TOP", "MOT=", "EGAL"]) or n == "V":
        return "Women T-Shirt"
    return "Other"

def get_all_skus_color_breakdown(
    search: str = None,
    seller_filter: str = None,
    group_filter: str = None,
    group_by: str = "group",
    category_filter: str = None,
    sort_by: str = "category"
):
    """
    Comprehensive breakdown of ALL SKUs organized by Product Group / Base SKU -> Color -> Sizes.
    When group_by='group' (default), merges all catalog numbers (e.g. 1001, 1002, 1003...) belonging
    to the same physical product into a unified row with merged colors and sizes.
    Supports Category-wise priority sorting (Plazos on top, Women T-Shirts below it).
    """
    with get_db() as conn:
        query = """
            SELECT o.sku, o.size, o.qty, o.color, o.seller_account,
                   CASE WHEN g.name IS NULL OR g.name = '' OR g.name = 'undefined' THEN 'Unmapped' ELSE g.name END as group_name,
                   g.category as group_category,
                   g.display_order as group_display_order
            FROM orders o
            LEFT JOIN sku_mappings m ON o.sku = m.sku
            LEFT JOIN product_groups g ON m.group_id = g.id
            WHERE o.is_excluded = 0
        """
        params = []
        if seller_filter:
            query += " AND o.seller_account = ?"
            params.append(seller_filter)
        if group_filter:
            if group_filter == "__unmapped__":
                query += " AND (g.name IS NULL OR g.name = '' OR g.name = 'undefined')"
            else:
                query += " AND g.name = ?"
                params.append(group_filter)

        rows = conn.execute(query, params).fetchall()

    if not rows:
        return {
            "total_products": 0,
            "total_colors": 0,
            "total_orders": 0,
            "total_pieces": 0,
            "all_sizes": [],
            "products": []
        }

    all_sizes_set = set()
    products_map = defaultdict(lambda: {
        "display_name": "",
        "group_name": "Unmapped",
        "sellers": set(),
        "total_orders": 0,
        "total_pieces": 0,
        "included_skus": set(),
        "base_sizes": defaultdict(lambda: {"orders": 0, "pieces": 0}),
        "colors": defaultdict(lambda: {
            "color": "",
            "full_skus": set(),
            "orders_count": 0,
            "pieces_count": 0,
            "sizes": defaultdict(lambda: {"orders": 0, "pieces": 0})
        })
    })

    grand_orders = 0
    grand_pieces = 0

    for r in rows:
        raw_sku = r["sku"] or "Unknown SKU"
        base, color_raw = parse_sku_and_color(raw_sku, r["color"])
        color = normalize_color_name(color_raw)
        qty = r["qty"] or 1
        raw_size = (r["size"] or "Unknown").strip()
        gname = r["group_name"]
        if group_by == "group":
            display_key = gname if gname != "Unmapped" else base
            p_group_label = gname
        else:
            display_key = base
            p_group_label = gname

        p = products_map[display_key]
        p["display_name"] = display_key
        p["group_name"] = p_group_label
        grp_cat = r["group_category"]
        cat = detect_product_category(p_group_label if p_group_label != "Unmapped" else display_key, grp_cat)
        p["category"] = cat

        # For Women T-Shirt, S and M size are physically identical and referred strictly as one size M
        is_women_tshirt = (cat == "Women T-Shirt")
        if is_women_tshirt and raw_size.upper() == "S":
            eff_size = "M"
        else:
            eff_size = raw_size

        all_sizes_set.add(eff_size)
        p["display_order"] = r["group_display_order"] or 99
        p["included_skus"].add(raw_sku)
        if r["seller_account"]:
            p["sellers"].add(r["seller_account"])
        p["total_orders"] += 1
        p["total_pieces"] += qty
        p["base_sizes"][eff_size]["orders"] += 1
        p["base_sizes"][eff_size]["pieces"] += qty
        if is_women_tshirt and eff_size == "M":
            if raw_size.upper() == "S":
                p["base_sizes"]["M"]["s_orders"] = p["base_sizes"]["M"].get("s_orders", 0) + 1
            elif raw_size.upper() == "M":
                p["base_sizes"]["M"]["m_orders"] = p["base_sizes"]["M"].get("m_orders", 0) + 1

        c = p["colors"][color]
        c["color"] = color
        c["full_skus"].add(raw_sku)
        c["orders_count"] += 1
        c["pieces_count"] += qty
        c["sizes"][eff_size]["orders"] += 1
        c["sizes"][eff_size]["pieces"] += qty
        if is_women_tshirt and eff_size == "M":
            if raw_size.upper() == "S":
                c["sizes"]["M"]["s_orders"] = c["sizes"]["M"].get("s_orders", 0) + 1
            elif raw_size.upper() == "M":
                c["sizes"]["M"]["m_orders"] = c["sizes"]["M"].get("m_orders", 0) + 1

        grand_orders += 1
        grand_pieces += qty

    sorted_all_sizes = sorted(all_sizes_set, key=get_size_sort_key)
    products_list = []
    total_color_variations = 0

    for display_key, pdata in products_map.items():
        base_orders = pdata["total_orders"]
        cat = pdata.get("category") or detect_product_category(display_key)
        is_women_tshirt = (cat == "Women T-Shirt")
        color_list = []

        # Color-wise list sorted by orders descending
        for color_name, cdata in sorted(pdata["colors"].items(), key=lambda x: x[1]["orders_count"], reverse=True):
            total_color_variations += 1
            c_orders = cdata["orders_count"]

            sizes_list = []
            for sname in sorted(cdata["sizes"].keys(), key=get_size_sort_key):
                sinfo = cdata["sizes"][sname]
                s_pct = round((sinfo["orders"] / c_orders) * 100, 1) if c_orders > 0 else 0
                s_dict = {
                    "size": sname,
                    "orders_count": sinfo["orders"],
                    "pieces_count": sinfo["pieces"],
                    "percentage": s_pct
                }
                if is_women_tshirt and sname == "M" and sinfo.get("s_orders", 0) > 0:
                    s_dict["tooltip"] = f"M: {sinfo['orders']} orders (includes S: {sinfo.get('s_orders', 0)}, M: {sinfo.get('m_orders', 0)})"
                    s_dict["s_count"] = sinfo.get("s_orders", 0)
                    s_dict["m_count"] = sinfo.get("m_orders", 0)
                sizes_list.append(s_dict)

            color_list.append({
                "color": color_name,
                "full_skus": sorted(list(cdata["full_skus"])),
                "orders_count": c_orders,
                "pieces_count": cdata["pieces_count"],
                "color_share_pct": round((c_orders / base_orders) * 100, 1) if base_orders > 0 else 0,
                "sizes": sizes_list
            })

        # Overall sizes summary for the base product
        base_sizes_list = []
        for sname in sorted(pdata["base_sizes"].keys(), key=get_size_sort_key):
            sinfo = pdata["base_sizes"][sname]
            bs_dict = {
                "size": sname,
                "orders_count": sinfo["orders"],
                "pieces_count": sinfo["pieces"],
                "percentage": round((sinfo["orders"] / base_orders) * 100, 1) if base_orders > 0 else 0
            }
            if is_women_tshirt and sname == "M" and sinfo.get("s_orders", 0) > 0:
                bs_dict["tooltip"] = f"M: {sinfo['orders']} orders (includes S: {sinfo.get('s_orders', 0)}, M: {sinfo.get('m_orders', 0)})"
                bs_dict["s_count"] = sinfo.get("s_orders", 0)
                bs_dict["m_count"] = sinfo.get("m_orders", 0)
            base_sizes_list.append(bs_dict)
        cat_meta = get_all_category_meta()
        cat_priority = cat_meta.get(cat, {}).get("priority", 99)

        products_list.append({
            "base_sku": display_key,
            "display_name": display_key,
            "group_name": pdata["group_name"],
            "category": cat,
            "category_label": cat_meta.get(cat, {}).get("label", cat),
            "category_priority": cat_priority,
            "sellers": sorted(list(pdata["sellers"])),
            "total_orders": base_orders,
            "total_pieces": pdata["total_pieces"],
            "included_skus_count": len(pdata["included_skus"]),
            "included_skus": sorted(list(pdata["included_skus"])),
            "colors_count": len(color_list),
            "colors": color_list,
            "overall_sizes": base_sizes_list
        })

    # Build category breakdown summary
    cat_counts = defaultdict(lambda: {"products": 0, "orders": 0, "pieces": 0})
    for p in products_list:
        c = p["category"]
        cat_counts[c]["products"] += 1
        cat_counts[c]["orders"] += p["total_orders"]
        cat_counts[c]["pieces"] += p["total_pieces"]

    categories_summary = []
    cat_meta = get_all_category_meta()
    sorted_cat_names = sorted(cat_counts.keys(), key=lambda c: (cat_meta.get(c, {}).get("priority", 99), c.lower()))
    for cname in sorted_cat_names:
        if cname in ("Black Pati",):
            continue
        cinfo = cat_counts[cname]
        categories_summary.append({
            "category": cname,
            "label": cat_meta.get(cname, {}).get("label", cname),
            "icon": cat_meta.get(cname, {}).get("icon", "🏷️"),
            "products_count": cinfo["products"],
            "orders_count": cinfo["orders"],
            "pieces_count": cinfo["pieces"]
        })

    # Category filter
    if category_filter:
        cf_clean = category_filter.lower().strip()
        if cf_clean in ("black patti", "black pati"):
            products_list = [p for p in products_list if p["category"].lower() in ("black patti", "black pati")]
        else:
            products_list = [p for p in products_list if p["category"].lower() == cf_clean]

    # Sort products: 'category' (Plazo on top, Women T-Shirt below), 'orders_desc', or 'name_asc'
    if sort_by == "orders_desc":
        products_list.sort(key=lambda x: x["total_orders"], reverse=True)
    elif sort_by == "name_asc":
        products_list.sort(key=lambda x: x["display_name"].lower())
    else: # default 'category': Plazo first, Women T-Shirts below it, sorted by orders inside each category
        products_list.sort(key=lambda x: (x["category_priority"], -x["total_orders"], x["display_name"].lower()))

    # Search filter
    if search:
        search_lower = search.lower().strip()
        filtered = []
        for p in products_list:
            match_base = search_lower in p["base_sku"].lower() or search_lower in p["group_name"].lower()
            match_color = any(
                search_lower in c["color"].lower() or
                any(search_lower in sku.lower() for sku in c["full_skus"])
                for c in p["colors"]
            )
            if match_base or match_color:
                filtered.append(p)
        products_list = filtered

    return {
        "total_products": len(products_list),
        "total_colors": total_color_variations,
        "total_orders": grand_orders,
        "total_pieces": grand_pieces,
        "all_sizes": sorted_all_sizes,
        "categories_summary": categories_summary,
        "products": products_list
    }

def export_color_breakdown_to_file(data: dict, export_format: str = "xlsx") -> str:
    """Export the SKU and Color-wise breakdown to Excel or CSV."""
    all_sizes = data.get("all_sizes", [])
    products = data.get("products", [])

    flat_rows = []
    for p in products:
        base_sku = p["base_sku"]
        group_name = p["group_name"]
        for c in p["colors"]:
            row_dict = {
                "Product / Base SKU": base_sku,
                "Color": c["color"],
                "Product Group": group_name,
                "Full Meesho SKU": "; ".join(c["full_skus"]),
                "Orders": c["orders_count"],
                "Pieces": c["pieces_count"]
            }
            # Fill sizes
            size_map = {s["size"]: s["orders_count"] for s in c["sizes"]}
            for sz in all_sizes:
                row_dict[f"Size {sz}"] = size_map.get(sz, 0)
            flat_rows.append(row_dict)

    df = pd.DataFrame(flat_rows)
    # Arrange columns
    size_cols = [f"Size {sz}" for sz in all_sizes]
    ordered_cols = ["Product / Base SKU", "Color", "Product Group"] + size_cols + ["Orders", "Pieces", "Full Meesho SKU"]
    existing_cols = [col for col in ordered_cols if col in df.columns]
    df = df[existing_cols]

    if export_format == "csv":
        out_fname = "Meesho_SKU_Color_Size_Breakdown.csv"
        out_path = os.path.join(OUTPUT_DIR, out_fname)
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
    else:
        out_fname = "Meesho_SKU_Color_Size_Breakdown.xlsx"
        out_path = os.path.join(OUTPUT_DIR, out_fname)
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="SKU Color Breakdown")

    return out_fname

def get_size_matrix(seller_filter: str = None, group_filter: str = None, search: str = None):
    """
    Generate dynamic matrix of Total Orders / Pieces by Product Group / SKU and Size.
    Returns:
    - columns: list of detected sizes in logical order (Kids 0-1Y -> 13-14Y, Adult XS -> XXL)
    - rows: list of group/sku rows with size counts, total orders, pieces, and mapped relationships
    - column_totals: totals per size
    - grand_total: total orders and pieces
    """
    with get_db() as conn:
        query = """
            SELECT o.id, o.sku, o.size, o.qty, o.seller_account,
                   COALESCE(g.id, 0) as group_id,
                   COALESCE(g.name, '') as group_name,
                   g.category as group_category
            FROM orders o
            LEFT JOIN sku_mappings m ON o.sku = m.sku
            LEFT JOIN product_groups g ON m.group_id = g.id
            WHERE o.is_excluded = 0
        """
        params = []

        if seller_filter:
            query += " AND o.seller_account = ?"
            params.append(seller_filter)
        if group_filter:
            if group_filter == "__unmapped__":
                query += " AND g.id IS NULL"
            else:
                query += " AND g.name = ?"
                params.append(group_filter)
        if search:
            query += " AND (o.sku LIKE ? OR g.name LIKE ?)"
            s_param = f"%{search}%"
            params.extend([s_param, s_param])

        rows = conn.execute(query, params).fetchall()

        if not rows:
            return {"columns": [], "rows": [], "column_totals": {}, "grand_total": {"orders": 0, "pieces": 0}}

        # Structure by Product Groups and SKUs
        # groups_data: { group_id: { "name": ..., "skus": { sku: { size: qty } } } }
        groups_data = {}
        unmapped_data = {}
        raw_sizes = set()

        for r in rows:
            gid = r["group_id"]
            gname = r["group_name"]
            sku = r["sku"]
            raw_sz = (r["size"] or "Unknown").strip()
            qty = r["qty"] or 1
            grp_cat = r["group_category"]
            cat = detect_product_category(gname if gname != "Unmapped" else sku, grp_cat)
            is_women = (cat == "Women T-Shirt" and gname != "T-Shirt Group")
            eff_sz = "M" if is_women and raw_sz.upper() == "S" else raw_sz
            raw_sizes.add(eff_sz)

            if gid > 0:
                if gid not in groups_data:
                    groups_data[gid] = {
                        "group_id": gid,
                        "name": gname,
                        "skus": defaultdict(lambda: defaultdict(int)),
                        "sku_orders": defaultdict(int)
                    }
                groups_data[gid]["skus"][sku][eff_sz] += qty
                groups_data[gid]["sku_orders"][sku] += 1
            else:
                if sku not in unmapped_data:
                    unmapped_data[sku] = {
                        "sizes": defaultdict(int),
                        "orders": 0
                    }
                unmapped_data[sku]["sizes"][eff_sz] += qty
                unmapped_data[sku]["orders"] += 1

        sorted_sizes = sorted(raw_sizes, key=lambda s: get_size_sort_key(s))

        output_rows = []
        column_totals = {s: 0 for s in sorted_sizes}
        grand_orders = 0
        grand_pieces = 0

        # Build group rows
        for gid, ginfo in sorted(groups_data.items(), key=lambda x: x[1]["name"].lower()):
            group_size_counts = {s: 0 for s in sorted_sizes}
            group_total_pieces = 0
            group_total_orders = 0

            # Sub-rows for each original SKU in the group
            sku_subrows = []
            for sku, size_map in sorted(ginfo["skus"].items()):
                sku_pieces = sum(size_map.values())
                sku_orders = ginfo["sku_orders"][sku]
                group_total_pieces += sku_pieces
                group_total_orders += sku_orders

                sku_counts = {s: size_map.get(s, 0) for s in sorted_sizes}
                for s, count in sku_counts.items():
                    group_size_counts[s] += count

                sku_subrows.append({
                    "type": "sku_in_group",
                    "group_id": gid,
                    "group_name": ginfo["name"],
                    "sku": sku,
                    "sizes": sku_counts,
                    "total_pieces": sku_pieces,
                    "total_orders": sku_orders
                })

            # Combined Total row for the Group
            output_rows.append({
                "type": "group_header",
                "group_id": gid,
                "group_name": ginfo["name"],
                "sku": f"Combined ({len(ginfo['skus'])} SKUs)",
                "sizes": group_size_counts,
                "total_pieces": group_total_pieces,
                "total_orders": group_total_orders,
                "subrows": sku_subrows
            })

            for s, c in group_size_counts.items():
                column_totals[s] += c
            grand_pieces += group_total_pieces
            grand_orders += group_total_orders

        # Build unmapped SKU rows
        for sku, sdata in sorted(unmapped_data.items()):
            sku_pieces = sum(sdata["sizes"].values())
            sku_orders = sdata["orders"]
            sku_counts = {s: sdata["sizes"].get(s, 0) for s in sorted_sizes}

            output_rows.append({
                "type": "unmapped_sku",
                "group_id": 0,
                "group_name": "Unmapped",
                "sku": sku,
                "sizes": sku_counts,
                "total_pieces": sku_pieces,
                "total_orders": sku_orders,
                "subrows": []
            })

            for s, c in sku_counts.items():
                column_totals[s] += c
            grand_pieces += sku_pieces
            grand_orders += sku_orders

        return {
            "columns": sorted_sizes,
            "rows": output_rows,
            "column_totals": column_totals,
            "grand_total": {
                "orders": grand_orders,
                "pieces": grand_pieces
            }
        }

def export_summary_to_file(matrix_data: dict, export_format: str = "xlsx") -> str:
    """Generate Excel or CSV export of the size summary table."""
    columns = matrix_data["columns"]
    rows = matrix_data["rows"]

    flat_data = []
    for r in rows:
        row_dict = {
            "Product Group": r["group_name"],
            "SKU": r["sku"],
            "Type": "Group Total" if r["type"] == "group_header" else "Unmapped SKU",
            "Total Pieces": r["total_pieces"],
            "Total Orders": r["total_orders"]
        }
        for c in columns:
            row_dict[c] = r["sizes"].get(c, 0)
        flat_data.append(row_dict)

        # Include individual SKUs inside groups
        for sub in r.get("subrows", []):
            sub_dict = {
                "Product Group": sub["group_name"],
                "SKU": sub["sku"],
                "Type": "Mapped SKU",
                "Total Pieces": sub["total_pieces"],
                "Total Orders": sub["total_orders"]
            }
            for c in columns:
                sub_dict[c] = sub["sizes"].get(c, 0)
            flat_data.append(sub_dict)

    # Add grand total row
    total_row = {
        "Product Group": "GRAND TOTAL",
        "SKU": "All Products",
        "Type": "Summary",
        "Total Pieces": matrix_data["grand_total"]["pieces"],
        "Total Orders": matrix_data["grand_total"]["orders"]
    }
    for c in columns:
        total_row[c] = matrix_data["column_totals"].get(c, 0)
    flat_data.append(total_row)

    df = pd.DataFrame(flat_data)
    # Reorder columns logically
    ordered_cols = ["Product Group", "SKU", "Type"] + columns + ["Total Pieces", "Total Orders"]
    df = df[ordered_cols]

    if export_format == "csv":
        out_fname = "Meesho_Order_Summary.csv"
        out_path = os.path.join(OUTPUT_DIR, out_fname)
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
    else:
        out_fname = "Meesho_Order_Summary.xlsx"
        out_path = os.path.join(OUTPUT_DIR, out_fname)
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Orders Summary")

    return out_fname

def get_sku_groups_info():
    """Retrieve all product groups with mapped SKUs, plus all unmapped SKUs."""
    with get_db() as conn:
        # Product Groups
        groups_rows = conn.execute("SELECT id, name, category, display_order, created_at FROM product_groups ORDER BY display_order ASC, name ASC").fetchall()
        groups = []
        mapped_skus_set = set()

        for gr in groups_rows:
            gid = gr["id"]
            mappings = conn.execute("""
                SELECT m.sku, COUNT(o.id) as orders_count, COALESCE(SUM(o.qty), 0) as pieces_count,
                       GROUP_CONCAT(DISTINCT o.seller_account) as sellers
                FROM sku_mappings m
                LEFT JOIN orders o ON m.sku = o.sku AND o.is_excluded = 0
                WHERE m.group_id = ?
                GROUP BY m.sku
                ORDER BY m.sku
            """, (gid,)).fetchall()

            sku_list = []
            group_orders = 0
            group_pieces = 0
            for m in mappings:
                sku_val = m["sku"]
                mapped_skus_set.add(sku_val)
                o_cnt = m["orders_count"] or 0
                p_cnt = m["pieces_count"] or 0
                group_orders += o_cnt
                group_pieces += p_cnt
                sku_list.append({
                    "sku": sku_val,
                    "orders_count": o_cnt,
                    "pieces_count": p_cnt,
                    "sellers": m["sellers"] or ""
                })

            cat = gr["category"] or detect_product_category(gr["name"])
            cat_meta = get_all_category_meta()
            groups.append({
                "id": gid,
                "name": gr["name"],
                "category": cat,
                "category_label": cat_meta.get(cat, {}).get("label", cat),
                "display_order": gr["display_order"] or 0,
                "created_at": gr["created_at"],
                "skus": sku_list,
                "total_orders": group_orders,
                "total_pieces": group_pieces
            })

        # Unmapped SKUs
        unmapped_rows = conn.execute("""
            SELECT o.sku, COUNT(o.id) as orders_count, COALESCE(SUM(o.qty), 0) as pieces_count,
                   GROUP_CONCAT(DISTINCT o.seller_account) as sellers
            FROM orders o
            WHERE o.sku NOT IN (SELECT sku FROM sku_mappings)
              AND o.is_excluded = 0
            GROUP BY o.sku
            ORDER BY orders_count DESC
        """).fetchall()

        unmapped = [dict(r) for r in unmapped_rows]

        return {
            "groups": groups,
            "unmapped_skus": unmapped
        }

def get_sku_clusters():
    """Cluster unmapped SKUs by clean base product name across all seller accounts."""
    with get_db() as conn:
        unmapped = conn.execute("""
            SELECT sku, COUNT(id) as orders_count, GROUP_CONCAT(DISTINCT seller_account) as sellers
            FROM orders
            WHERE sku NOT IN (SELECT sku FROM sku_mappings)
            GROUP BY sku
        """).fetchall()
        existing_groups = {r["name"].upper().strip() for r in conn.execute("SELECT name FROM product_groups").fetchall()}

    def extract_cluster_name(sku):
        s = sku.strip()
        s_upper = s.upper()
        if 'V NACK' in s_upper or 'V-NECK' in s_upper or 'V NECK' in s_upper or s_upper.startswith('V-'):
            return 'V'
        if 'BEST MOOD' in s_upper or 'BEST MOODE' in s_upper:
            return 'BEST MOOD PLAZO'
        if 'HUG ME TADDY' in s_upper or 'HUG ME TEDDY' in s_upper:
            return 'Hug Me Taddy'
        if 'IFM' in s_upper and ('NEW YORK' in s_upper or 'NEWYORK' in s_upper):
            return 'IFM New York'
        if 'IFM' in s_upper:
            return 'IFM'
        if 'PLAAZO PER BE KIND' in s_upper or 'BI KIDE' in s_upper or 'BE KIND' in s_upper:
            return 'Be Kind Plazo'
        if 'NICE' in s_upper:
            return 'Nice Plazo'

        # Check if matches any existing product group
        for eg in existing_groups:
            if eg and len(eg) >= 4 and eg in s_upper:
                return eg

        # Use robust base sku parser
        base, _ = parse_sku_and_color(s)
        base_clean = re.sub(r'[\(\)\[\]]', '', base).strip().rstrip('.-;, ')
        if base_clean:
            return base_clean
        return s

    clusters = defaultdict(list)
    for r in unmapped:
        sku = r['sku']
        if not sku:
            continue
        cname = extract_cluster_name(sku)
        clusters[cname].append({
            'sku': sku,
            'orders_count': r['orders_count'],
            'sellers': r['sellers'] or ''
        })

    result = []
    for cname, items in sorted(clusters.items(), key=lambda x: -sum(i['orders_count'] for i in x[1])):
        total_orders = sum(i['orders_count'] for i in items)
        if len(items) >= 2 or total_orders >= 10 or cname.upper().strip() in existing_groups:
            result.append({
                'name': cname,
                'skus': [i['sku'] for i in items],
                'sku_count': len(items),
                'total_orders': total_orders,
                'items': items
            })

    return result

def auto_group_all_clusters():
    """Auto-create groups for all detected clusters."""
    clusters = get_sku_clusters()
    created = []
    with get_db() as conn:
        for c in clusters:
            name = c['name']
            # Check if group already exists with this name (case-insensitive)
            existing = conn.execute(
                "SELECT id, name FROM product_groups WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))",
                (name,)
            ).fetchone()

            # If creating a new group from scratch, require at least 2 variants;
            # but if the group already exists, immediately map even single new variants into it!
            if not existing and c['sku_count'] < 2:
                continue

            if existing:
                gid = existing["id"]
                name = existing["name"]
            else:
                base_name = name
                cnt = 1
                while True:
                    exists = conn.execute("SELECT id FROM product_groups WHERE name = ?", (name,)).fetchone()
                    if not exists:
                        break
                    cnt += 1
                    name = f"{base_name} ({cnt})"

                cat = detect_product_category(name)
                cursor = conn.execute("INSERT INTO product_groups (name, category) VALUES (?, ?)", (name, cat))
                gid = cursor.lastrowid

            for sku in c['skus']:
                conn.execute("DELETE FROM sku_mappings WHERE sku = ?", (sku,))
                conn.execute("INSERT INTO sku_mappings (group_id, sku) VALUES (?, ?)", (gid, sku))

            created.append({'id': gid, 'name': name, 'sku_count': len(c['skus'])})

    if created:
        from backend.database import save_sku_mappings_to_json
        save_sku_mappings_to_json()

    return created
