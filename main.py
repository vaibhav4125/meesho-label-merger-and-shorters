import os
import shutil
import glob
import json
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

try:
    from .database import (
        init_db,
        get_db,
        save_sku_mappings_to_json,
        restore_sku_mappings_from_json,
        get_sku_mappings_status,
        checkpoint_db,
        DATA_DIR,
        PERSISTENT_MAPPINGS_FILE
    )
    from .services import (
        process_file_records,
        get_dashboard_summary,
        get_size_matrix,
        export_summary_to_file,
        get_sku_groups_info,
        get_sku_clusters,
        auto_group_all_clusters,
        get_all_skus_color_breakdown,
        export_color_breakdown_to_file,
        get_all_product_categories,
        add_product_category,
        delete_product_category
    )
    from .pdf_generator import generate_sorted_pdf, batch_generate_sorted_pdfs, generate_all_merged_sorted_pdf
except (ImportError, ValueError):
    from database import (
        init_db,
        get_db,
        save_sku_mappings_to_json,
        restore_sku_mappings_from_json,
        get_sku_mappings_status,
        checkpoint_db,
        DATA_DIR,
        PERSISTENT_MAPPINGS_FILE
    )
    from services import (
        process_file_records,
        get_dashboard_summary,
        get_size_matrix,
        export_summary_to_file,
        get_sku_groups_info,
        get_sku_clusters,
        auto_group_all_clusters,
        get_all_skus_color_breakdown,
        export_color_breakdown_to_file,
        get_all_product_categories,
        add_product_category,
        delete_product_category
    )
    from pdf_generator import generate_sorted_pdf, batch_generate_sorted_pdfs, generate_all_merged_sorted_pdf

_cur_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_cur_dir) if os.path.basename(_cur_dir) == "backend" else _cur_dir
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
SAMPLE_DIR = os.path.join(BASE_DIR, "sample_pdfs")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend") if os.path.exists(os.path.join(BASE_DIR, "frontend")) else BASE_DIR

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SAMPLE_DIR, exist_ok=True)

# Initialize Database Schema & Auto-Sync Persistent SKU Mappings
init_db()

app = FastAPI(title="Meesho Order Sorting & Merging System", version="1.0.0")

@app.on_event("shutdown")
def on_shutdown():
    """Ensure SKU mappings and product groups are safely persisted to disk when the program exits."""
    try:
        save_sku_mappings_to_json()
        checkpoint_db()
        print("[✓] Meesho Label Sorting: All SKU Mappings and Product Groups safely persisted to disk.")
    except Exception as e:
        print(f"[!] Warning on shutdown: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Request Models
class CreateGroupRequest(BaseModel):
    name: str
    skus: List[str]

class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    skus: Optional[List[str]] = None

class ModifySkusRequest(BaseModel):
    skus: List[str]

class UpdateGroupCategoryRequest(BaseModel):
    category: Optional[str] = None
    display_order: Optional[float] = None

class CreateCategoryRequest(BaseModel):
    name: str
    label: Optional[str] = None
    icon: Optional[str] = "🏷️"
    display_order: Optional[float] = None

class UpdateOrderRequest(BaseModel):
    sku: Optional[str] = None
    size: Optional[str] = None
    qty: Optional[int] = None
    color: Optional[str] = None
    seller_account: Optional[str] = None
    validation_status: Optional[str] = None

class GeneratePdfRequest(BaseModel):
    group_id: Optional[int] = None
    sku: Optional[str] = None
    included_sizes: Optional[List[str]] = None
    sort_preset: Optional[str] = "auto"
    custom_size_order: Optional[List[str]] = None
    secondary_sort: Optional[str] = "sku"
    output_filename: Optional[str] = None

class BatchGeneratePdfRequest(BaseModel):
    group_ids: Optional[List[int]] = None
    skus: Optional[List[str]] = None
    sort_preset: Optional[str] = "auto"
    secondary_sort: Optional[str] = "sku"
    create_zip: Optional[bool] = True

class MergeAllRequest(BaseModel):
    group_ids: Optional[List[int]] = None
    sort_preset: Optional[str] = "auto"
    secondary_sort: Optional[str] = "sku"
    sort_mode: Optional[str] = "color_first"
    output_filename: Optional[str] = None

# --- Health & Keep-Alive Endpoints ---

@app.get("/api/health")
def health_check():
    """Health check for keep-alive, wake-up detection, and cloud monitors."""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "app": "Meesho Multi-Account Label Sorting Hub"
    }

# --- Upload & File Endpoints ---

@app.post("/api/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...)
):
    """Upload one or multiple Meesho PDF files with immediate response & background processing."""
    saved_files = []
    errors = []

    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            errors.append(f"Skipped {file.filename}: not a PDF file")
            continue

        try:
            # Save uploaded file
            save_path = os.path.join(UPLOAD_DIR, file.filename)
            counter = 1
            base_name, ext = os.path.splitext(file.filename)
            while os.path.exists(save_path):
                save_path = os.path.join(UPLOAD_DIR, f"{base_name}_{counter}{ext}")
                counter += 1

            # Stream file to disk in 1MB chunks to prevent memory spikes
            with open(save_path, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    buffer.write(chunk)

            file_size = os.path.getsize(save_path)

            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO uploaded_files (filename, filepath, file_size, status)
                    VALUES (?, ?, ?, 'processing')
                """, (os.path.basename(save_path), save_path, file_size))
                file_id = cursor.lastrowid

            # Process in background task so HTTP response returns in < 1s (prevents Render 100s proxy timeout)
            background_tasks.add_task(process_file_records, file_id)

            saved_files.append({
                "file_id": file_id,
                "filename": os.path.basename(save_path),
                "file_size": file_size,
                "page_count": 0,
                "status": "processing"
            })
        except Exception as e:
            errors.append(f"Error processing {file.filename}: {str(e)}")

    return {
        "success": True,
        "uploaded": saved_files,
        "errors": errors
    }

@app.get("/api/files/{file_id}/status")
def get_file_status(file_id: int):
    """Get status of an uploaded PDF file being parsed in the background."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT id, filename, file_size, page_count, status, error_message, uploaded_at
            FROM uploaded_files
            WHERE id = ?
        """, (file_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        return dict(row)

@app.post("/api/load-sample")
def load_sample_files(background_tasks: BackgroundTasks):
    """Quick 1-click loading of the sample test PDFs."""
    sample_files = glob.glob(os.path.join(SAMPLE_DIR, "*.pdf"))
    if not sample_files:
        # Check Downloads folder as fallback
        download_samples = glob.glob(r"C:\Users\Mahadev\Downloads\sellerbox_sorted_labels_20261012*.pdf")
        sample_files = download_samples

    if not sample_files:
        raise HTTPException(
            status_code=404,
            detail="No sample PDF files found on server. Please upload your own Meesho shipping label PDFs using the Upload button."
        )

    loaded = []
    for sf in sample_files:
        dest = os.path.join(UPLOAD_DIR, os.path.basename(sf))
        shutil.copyfile(sf, dest)
        file_size = os.path.getsize(dest)

        with get_db() as conn:
            existing = conn.execute("SELECT id FROM uploaded_files WHERE filepath = ?", (dest,)).fetchone()
            if existing:
                file_id = existing["id"]
                conn.execute("UPDATE uploaded_files SET status = 'processing' WHERE id = ?", (file_id,))
            else:
                cursor = conn.execute("""
                    INSERT INTO uploaded_files (filename, filepath, file_size, status)
                    VALUES (?, ?, ?, 'processing')
                """, (os.path.basename(dest), dest, file_size))
                file_id = cursor.lastrowid

        background_tasks.add_task(process_file_records, file_id)
        loaded.append({
            "file_id": file_id,
            "filename": os.path.basename(dest),
            "page_count": 0,
            "status": "processing"
        })

    return {"success": True, "loaded": loaded}

@app.get("/api/files")
def list_files():
    """List all uploaded PDF files with status and metadata."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, filename, file_size, page_count, status, error_message, uploaded_at
            FROM uploaded_files
            ORDER BY id DESC
        """).fetchall()
        return [dict(r) for r in rows]

@app.delete("/api/files/{file_id}")
def delete_file(file_id: int):
    """Remove an uploaded file and all its parsed orders."""
    with get_db() as conn:
        f = conn.execute("SELECT filepath FROM uploaded_files WHERE id = ?", (file_id,)).fetchone()
        if not f:
            raise HTTPException(status_code=404, detail="File not found")
        filepath = f["filepath"]

        conn.execute("DELETE FROM uploaded_files WHERE id = ?", (file_id,))
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

    return {"success": True, "message": f"File {file_id} deleted successfully"}

# --- Dashboard & Order Summary Endpoints ---

@app.get("/api/dashboard")
def dashboard():
    """Get high-level statistics for dashboard."""
    return get_dashboard_summary()

@app.get("/api/summary")
def summary(
    seller: Optional[str] = None,
    group: Optional[str] = None,
    search: Optional[str] = None
):
    """Get size matrix pivot data."""
    return get_size_matrix(seller_filter=seller, group_filter=group, search=search)

@app.get("/api/summary/export")
def export_summary(
    format: str = Query("xlsx", regex="^(xlsx|csv)$"),
    seller: Optional[str] = None,
    group: Optional[str] = None,
    search: Optional[str] = None
):
    """Export size summary table to Excel or CSV."""
    matrix_data = get_size_matrix(seller_filter=seller, group_filter=group, search=search)
    out_fname = export_summary_to_file(matrix_data, export_format=format)
    file_path = os.path.join(OUTPUT_DIR, out_fname)
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/csv"
    return FileResponse(file_path, filename=out_fname, media_type=media_type)

# --- All SKUs by Product & Color Breakdown ---

@app.get("/api/skus-color-breakdown")
def skus_color_breakdown(
    search: Optional[str] = None,
    seller: Optional[str] = None,
    group: Optional[str] = None,
    category: Optional[str] = None,
    sort_by: str = Query("category", pattern="^(category|orders_desc|name_asc)$"),
    group_by: str = Query("group", pattern="^(group|sku)$")
):
    """Return 100% of SKUs grouped by Product Group (merged) or Catalog Title -> Color -> Sizes with category-wise sorting."""
    return get_all_skus_color_breakdown(
        search=search,
        seller_filter=seller,
        group_filter=group,
        group_by=group_by,
        category_filter=category,
        sort_by=sort_by
    )

@app.get("/api/skus-color-breakdown/export")
def export_color_breakdown(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    seller: Optional[str] = None,
    group: Optional[str] = None,
    category: Optional[str] = None,
    sort_by: str = Query("category", pattern="^(category|orders_desc|name_asc)$"),
    search: Optional[str] = None,
    group_by: str = Query("group", pattern="^(group|sku)$")
):
    """Export complete SKU + Color + Size breakdown matrix to Excel/CSV."""
    data = get_all_skus_color_breakdown(
        search=search,
        seller_filter=seller,
        group_filter=group,
        group_by=group_by,
        category_filter=category,
        sort_by=sort_by
    )
    out_fname = export_color_breakdown_to_file(data, export_format=format)
    file_path = os.path.join(OUTPUT_DIR, out_fname)
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/csv"
    return FileResponse(file_path, filename=out_fname, media_type=media_type)

# --- Picking Checklist A4 PDF Generator ---

@app.get("/api/checklist/pdf")
def get_picking_checklist_pdf(
    category: Optional[str] = None,
    group: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "category"
):
    """Generate and download A4 printable Order Picking & Packing Checklist PDF."""
    from .checklist_generator import generate_picking_checklist_pdf
    data = get_all_skus_color_breakdown(
        search=search,
        group_filter=group,
        category_filter=category,
        sort_by=sort_by or "category"
    )
    if group:
        data["products"] = [p for p in data["products"] if p.get("group_name") == group or p.get("display_name") == group]
        data["total_products"] = len(data["products"])
        data["total_colors"] = sum(len(p.get("colors", [])) for p in data["products"])
        data["total_orders"] = sum(p.get("total_orders", 0) for p in data["products"])
        data["total_pieces"] = sum(p.get("total_pieces", 0) for p in data["products"])

    cat_label = category or ("All Categories" if not group else group)
    out_fname = generate_picking_checklist_pdf(data, category_title=cat_label)
    file_path = os.path.join(OUTPUT_DIR, out_fname)
    return FileResponse(file_path, filename=out_fname, media_type="application/pdf")

# --- SKU Groups & Mapping Endpoints ---

@app.get("/api/sku-groups")
def list_sku_groups():
    """List all product groups with mapped SKUs, plus unmapped SKUs."""
    return get_sku_groups_info()

@app.post("/api/sku-groups")
def create_sku_group(req: CreateGroupRequest):
    """Create a new product group and map SKUs to it."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    if not req.skus:
        raise HTTPException(status_code=400, detail="At least one SKU must be mapped")

    with get_db() as conn:
        try:
            cursor = conn.execute("INSERT INTO product_groups (name) VALUES (?)", (name,))
            group_id = cursor.lastrowid
        except Exception:
            raise HTTPException(status_code=400, detail=f"Group with name '{name}' already exists")

        for sku in req.skus:
            # Remove any prior mapping for this SKU
            conn.execute("DELETE FROM sku_mappings WHERE sku = ?", (sku,))
            conn.execute("INSERT INTO sku_mappings (group_id, sku) VALUES (?, ?)", (group_id, sku))

    # Auto-save persistent backup
    save_sku_mappings_to_json()

    return {"success": True, "group_id": group_id, "name": name, "skus": req.skus}

@app.put("/api/sku-groups/{group_id}")
def update_sku_group(group_id: int, req: UpdateGroupRequest):
    """Update group name or mapped SKUs."""
    with get_db() as conn:
        group = conn.execute("SELECT id, name FROM product_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Product Group not found")

        if req.name and req.name.strip():
            conn.execute(
                "UPDATE product_groups SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (req.name.strip(), group_id)
            )

        if req.skus is not None:
            conn.execute("DELETE FROM sku_mappings WHERE group_id = ?", (group_id,))
            for sku in req.skus:
                conn.execute("DELETE FROM sku_mappings WHERE sku = ?", (sku,))
                conn.execute("INSERT INTO sku_mappings (group_id, sku) VALUES (?, ?)", (group_id, sku))

    save_sku_mappings_to_json()
    return {"success": True, "message": "Product Group updated successfully"}

@app.put("/api/sku-groups/{group_id}/category")
def update_group_category(group_id: int, req: UpdateGroupCategoryRequest):
    """Update a product group's category and/or display order."""
    with get_db() as conn:
        group = conn.execute("SELECT id, name FROM product_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Product Group not found")

        if req.category is not None:
            cat_val = req.category.strip()
            conn.execute("UPDATE product_groups SET category = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (cat_val, group_id))
            # Auto-register category into product_categories if new
            if cat_val and cat_val not in ("General", "undefined", "None"):
                conn.execute(
                    "INSERT OR IGNORE INTO product_categories (name, label, icon, display_order) VALUES (?, ?, '🏷️', 10)",
                    (cat_val, f"🏷️ {cat_val}")
                )
        if req.display_order is not None:
            conn.execute("UPDATE product_groups SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (req.display_order, group_id))

    save_sku_mappings_to_json()
    return {"success": True, "message": f"Updated category for group '{group['name']}'"}

# --- Categories Management Endpoints ---

@app.get("/api/categories")
def list_categories():
    """List all available product categories."""
    cats = get_all_product_categories()
    return {"success": True, "categories": cats}

@app.post("/api/categories")
def create_category(req: CreateCategoryRequest):
    """Create a new custom product category."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    try:
        cat = add_product_category(
            name=name,
            label=req.label,
            icon=req.icon or "🏷️",
            display_order=req.display_order
        )
        return {"success": True, "category": cat, "message": f"Category '{name}' created successfully"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/categories/{category_name}")
def delete_category(category_name: str):
    """Delete a custom category. Default categories are protected."""
    try:
        delete_product_category(category_name)
        return {"success": True, "message": f"Category '{category_name}' deleted successfully"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sku-groups/{group_id}")
def get_single_sku_group(group_id: int):
    """Get single product group details along with current mapped and unmapped SKUs."""
    data = get_sku_groups_info()
    target_group = next((g for g in data["groups"] if g["id"] == group_id), None)
    if not target_group:
        raise HTTPException(status_code=404, detail="Product Group not found")
    return {
        "success": True,
        "group": target_group,
        "unmapped_skus": data["unmapped_skus"]
    }

@app.post("/api/sku-groups/{group_id}/add-skus")
@app.post("/api/sku-groups/{group_id}/skus/add")
def add_skus_to_group(group_id: int, req: ModifySkusRequest):
    """Add one or more SKUs to this product group (moving them from outside into this group)."""
    if not req.skus:
        raise HTTPException(status_code=400, detail="No SKUs provided")

    with get_db() as conn:
        group = conn.execute("SELECT id, name FROM product_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Product Group not found")

        added_count = 0
        for sku in req.skus:
            s = sku.strip()
            if not s:
                continue
            conn.execute("DELETE FROM sku_mappings WHERE sku = ?", (s,))
            conn.execute("INSERT INTO sku_mappings (group_id, sku) VALUES (?, ?)", (group_id, s))
            added_count += 1

        conn.execute("UPDATE product_groups SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (group_id,))

    save_sku_mappings_to_json()
    return {"success": True, "message": f"Added {added_count} SKU(s) to group '{group['name']}'", "group_id": group_id}

@app.post("/api/sku-groups/{group_id}/remove-skus")
@app.post("/api/sku-groups/{group_id}/skus/remove")
def remove_skus_from_group(group_id: int, req: ModifySkusRequest):
    """Remove one or more SKUs from this product group (moving them outside to unmapped). All orders remain 100% intact."""
    if not req.skus:
        raise HTTPException(status_code=400, detail="No SKUs provided")

    with get_db() as conn:
        group = conn.execute("SELECT id, name FROM product_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Product Group not found")

        removed_count = 0
        for sku in req.skus:
            s = sku.strip()
            if not s:
                continue
            conn.execute("DELETE FROM sku_mappings WHERE group_id = ? AND sku = ?", (group_id, s))
            removed_count += 1

        conn.execute("UPDATE product_groups SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (group_id,))

    save_sku_mappings_to_json()
    return {"success": True, "message": f"Removed {removed_count} SKU(s) from group '{group['name']}'. They are now outside in the unmapped list.", "group_id": group_id}

@app.delete("/api/sku-groups/{group_id}")
def delete_sku_group(group_id: int):
    """Delete a product group and return its SKUs to unmapped."""
    with get_db() as conn:
        conn.execute("DELETE FROM product_groups WHERE id = ?", (group_id,))

    save_sku_mappings_to_json()
    return {"success": True, "message": f"Group {group_id} deleted"}

@app.get("/api/sku-clusters")
def list_sku_clusters():
    """Get smart clusters of unmapped SKUs grouped by base product name."""
    return get_sku_clusters()

@app.get("/api/sku-suggestions")
def sku_suggestions():
    return get_sku_clusters()

@app.post("/api/sku-clusters/auto-group-all")
def auto_group_all():
    """Automatically create product groups for all detected clusters."""
    created = auto_group_all_clusters()
    save_sku_mappings_to_json()
    return {"success": True, "created": created}

# --- SKU Mappings Persistence & Backup Endpoints ---

@app.get("/api/sku-mappings/status")
def sku_mappings_status():
    """Get current persistence and backup status of SKU mappings."""
    return get_sku_mappings_status()

@app.get("/api/sku-mappings/export")
def export_sku_mappings():
    """Download SKU mappings as a standalone JSON backup file."""
    save_sku_mappings_to_json(backup=True)
    if not os.path.exists(PERSISTENT_MAPPINGS_FILE):
        raise HTTPException(status_code=404, detail="No persistent mappings file found")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"meesho_sku_mappings_backup_{ts}.json"
    return FileResponse(PERSISTENT_MAPPINGS_FILE, filename=filename, media_type="application/json")

@app.post("/api/sku-mappings/import")
async def import_sku_mappings(file: UploadFile = File(...)):
    """Import and restore SKU mappings from an uploaded JSON backup file."""
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json backup files are supported")
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        if "groups" not in data or not isinstance(data["groups"], list):
            raise HTTPException(status_code=400, detail="Invalid backup file format: missing 'groups' list")

        temp_import_path = os.path.join(DATA_DIR, "temp_import_mappings.json")
        with open(temp_import_path, "w", encoding="utf-8") as f:
            f.write(content.decode("utf-8"))

        res = restore_sku_mappings_from_json(temp_import_path, force=True)
        try:
            os.remove(temp_import_path)
        except OSError:
            pass

        save_sku_mappings_to_json(backup=True)
        return {
            "success": True,
            "message": f"Successfully restored {res.get('restored_groups', 0)} groups and {res.get('restored_skus', 0)} mappings",
            "details": res
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

@app.post("/api/sku-mappings/sync")
def sync_sku_mappings():
    """Force flush database mappings to persistent disk storage."""
    data = save_sku_mappings_to_json(backup=True)
    checkpoint_db()
    return {
        "success": True,
        "message": "SKU mappings successfully saved and secured to disk!",
        "total_groups": data.get("total_groups") if data else 0,
        "total_mappings": data.get("total_mappings") if data else 0
    }

# --- Orders Explorer & Editing Endpoints ---

@app.get("/api/orders")
def list_orders(
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    seller: Optional[str] = None,
    size: Optional[str] = None,
    status: Optional[str] = None,
    is_duplicate: Optional[int] = None,
    group_id: Optional[int] = None
):
    """List orders with pagination and filtering."""
    with get_db() as conn:
        offset = (page - 1) * page_size
        where_clauses = []
        params = []

        if search:
            where_clauses.append("(o.order_no LIKE ? OR o.sku LIKE ? OR o.awb LIKE ?)")
            s_param = f"%{search}%"
            params.extend([s_param, s_param, s_param])
        if seller:
            where_clauses.append("o.seller_account = ?")
            params.append(seller)
        if size:
            where_clauses.append("o.size = ?")
            params.append(size)
        if status:
            where_clauses.append("o.validation_status = ?")
            params.append(status)
        if is_duplicate is not None:
            where_clauses.append("o.is_duplicate = ?")
            params.append(is_duplicate)
        if group_id:
            where_clauses.append("o.sku IN (SELECT sku FROM sku_mappings WHERE group_id = ?)")
            params.append(group_id)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        count_query = f"SELECT COUNT(*) FROM orders o {where_sql}"
        total_count = conn.execute(count_query, params).fetchone()[0]

        data_query = f"""
            SELECT o.*, f.filename as src_filename, COALESCE(g.name, 'Unmapped') as group_name
            FROM orders o
            JOIN uploaded_files f ON o.file_id = f.id
            LEFT JOIN sku_mappings m ON o.sku = m.sku
            LEFT JOIN product_groups g ON m.group_id = g.id
            {where_sql}
            ORDER BY o.id ASC
            LIMIT ? OFFSET ?
        """
        data_params = params + [page_size, offset]
        rows = conn.execute(data_query, data_params).fetchall()

        return {
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "orders": [dict(r) for r in rows]
        }

@app.put("/api/orders/{order_id}")
def update_order(order_id: int, req: UpdateOrderRequest):
    """Manually edit order information."""
    with get_db() as conn:
        order = conn.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        updates = []
        params = []
        if req.sku is not None:
            updates.append("sku = ?")
            params.append(req.sku)
        if req.size is not None:
            updates.append("size = ?")
            params.append(req.size)
        if req.qty is not None:
            updates.append("qty = ?")
            params.append(req.qty)
        if req.color is not None:
            updates.append("color = ?")
            params.append(req.color)
        if req.seller_account is not None:
            updates.append("seller_account = ?")
            params.append(req.seller_account)
        if req.validation_status is not None:
            updates.append("validation_status = ?")
            params.append(req.validation_status)

        updates.append("manual_override = 1")

        if updates:
            sql = f"UPDATE orders SET {', '.join(updates)} WHERE id = ?"
            params.append(order_id)
            conn.execute(sql, params)

    return {"success": True, "message": "Order updated successfully"}

@app.post("/api/orders/{order_id}/toggle-exclude")
def toggle_exclude_order(order_id: int):
    """Toggle exclusion status of an order from merged PDFs."""
    with get_db() as conn:
        row = conn.execute("SELECT is_excluded FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        new_val = 0 if row["is_excluded"] == 1 else 1
        conn.execute("UPDATE orders SET is_excluded = ? WHERE id = ?", (new_val, order_id))
    return {"success": True, "is_excluded": new_val}

# --- PDF Generation & History Endpoints ---

@app.post("/api/generate-pdf")
def create_sorted_pdf(req: GeneratePdfRequest):
    """Generate a single sorted PDF for a group or SKU."""
    try:
        res = generate_sorted_pdf(
            group_id=req.group_id,
            sku=req.sku,
            included_sizes=req.included_sizes,
            sort_preset=req.sort_preset or "auto",
            custom_size_order=req.custom_size_order,
            secondary_sort=req.secondary_sort or "sku",
            output_filename=req.output_filename
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/generate-batch-pdf")
def create_batch_sorted_pdfs(req: BatchGeneratePdfRequest):
    """Batch generate sorted PDFs for multiple product groups."""
    try:
        res = batch_generate_sorted_pdfs(
            group_ids=req.group_ids,
            skus=req.skus,
            sort_preset=req.sort_preset or "auto",
            secondary_sort=req.secondary_sort or "sku",
            create_zip=req.create_zip if req.create_zip is not None else True
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/generate-all-merged-pdf")
def create_all_merged_pdf(req: MergeAllRequest):
    """Merge ALL selected groups or ALL uploaded orders into ONE single PDF without ZIP."""
    try:
        sort_mode = req.sort_mode or "color_first"
        def_fname = "Meesho_All_Orders_Size_Wise_Merged.pdf" if sort_mode == "size_first" else "Meesho_All_Orders_Merged_Sorted.pdf"
        output_filename = req.output_filename or def_fname

        res = generate_all_merged_sorted_pdf(
            group_ids=req.group_ids,
            sort_preset=req.sort_preset or "auto",
            secondary_sort=req.secondary_sort or "sku",
            sort_mode=sort_mode,
            output_filename=output_filename
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/generated-pdfs")
def list_generated_pdfs():
    """List generated PDFs history."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, group_name, filename, order_count, page_count, verified, created_at
            FROM generated_pdfs
            ORDER BY id DESC
        """).fetchall()
        return [dict(r) for r in rows]

@app.delete("/api/generated-pdfs/{pdf_id}")
def delete_generated_pdf(pdf_id: int):
    """Delete a generated PDF record and its file."""
    with get_db() as conn:
        row = conn.execute("SELECT filepath FROM generated_pdfs WHERE id = ?", (pdf_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")
        conn.execute("DELETE FROM generated_pdfs WHERE id = ?", (pdf_id,))
        if os.path.exists(row["filepath"]):
            try:
                os.remove(row["filepath"])
            except OSError:
                pass
    return {"success": True}

@app.get("/api/download/{filename}")
def download_file(filename: str):
    """Download a generated PDF or ZIP file."""
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Requested file not found")
    media_type = "application/pdf" if filename.endswith(".pdf") else "application/zip"
    return FileResponse(filepath, filename=filename, media_type=media_type)

@app.post("/api/reset")
def reset_workspace(reset_mappings: bool = Query(False, description="Whether to also reset SKU mappings")):
    """
    Clear uploaded files, orders, and generated files.
    By default (reset_mappings=False), all SKU mappings and Product Groups remain 100% PRESERVED.
    """
    with get_db() as conn:
        if reset_mappings:
            # Create a permanent safety backup before any full factory reset
            save_sku_mappings_to_json(backup=True)
            conn.executescript("""
                DELETE FROM orders;
                DELETE FROM uploaded_files;
                DELETE FROM sku_mappings;
                DELETE FROM product_groups;
                DELETE FROM generated_pdfs;
            """)
        else:
            # Safe reset for daily order processing: keeps all product groups and SKU mappings intact!
            conn.executescript("""
                DELETE FROM orders;
                DELETE FROM uploaded_files;
                DELETE FROM generated_pdfs;
            """)

    # Clean uploads and outputs
    for f in glob.glob(os.path.join(UPLOAD_DIR, "*")):
        try:
            os.remove(f)
        except OSError:
            pass
    for f in glob.glob(os.path.join(OUTPUT_DIR, "*")):
        try:
            os.remove(f)
        except OSError:
            pass

    checkpoint_db()

    msg = "Workspace reset completely (including SKU mappings)" if reset_mappings else "Orders & uploaded files cleared. All SKU mappings & Product Groups are 100% preserved!"
    return {
        "success": True,
        "message": msg,
        "mappings_preserved": not reset_mappings
    }

@app.post("/api/clear-orders")
def clear_orders_only():
    """Daily reset: Clear uploaded PDF files and orders to start fresh. SKU mappings remain completely saved."""
    return reset_workspace(reset_mappings=False)

try:
    from .tunnel import start_tunnel, stop_tunnel, get_tunnel_status
except (ImportError, ValueError):
    from tunnel import start_tunnel, stop_tunnel, get_tunnel_status

def is_cloud_env():
    return bool(os.environ.get("RENDER") or os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("PORT"))

@app.on_event("startup")
def on_app_startup():
    if not is_cloud_env():
        start_tunnel(port=8000)

@app.on_event("shutdown")
def on_app_shutdown():
    if not is_cloud_env():
        stop_tunnel()

def get_local_network_ip():
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@app.get("/api/mobile-info")
def get_mobile_info():
    """Return local WiFi IP address and dynamic cloud/tunnel live URL."""
    port_env = os.environ.get("PORT")
    port = int(port_env) if port_env else 8000
    local_ip = get_local_network_ip()
    local_url = f"http://{local_ip}:{port}"

    # If running on cloud server (Render, Railway, etc.), use the public cloud URL
    cloud_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("PUBLIC_APP_URL")
    if cloud_url:
        if not cloud_url.startswith("http"):
            cloud_url = f"https://{cloud_url}"
        return {
            "local_ip": local_ip,
            "port": port,
            "local_url": cloud_url,
            "tunnel_url": cloud_url,
            "tunnel_status": "online",
            "tunnel_error": None,
            "is_live": True,
            "is_cloud": True
        }

    tunnel_info = get_tunnel_status()
    if tunnel_info["status"] == "offline" and not is_cloud_env():
        start_tunnel(port=port)
        tunnel_info = get_tunnel_status()

    return {
        "local_ip": local_ip,
        "port": port,
        "local_url": local_url,
        "tunnel_url": tunnel_info.get("url"),
        "tunnel_status": tunnel_info.get("status", "offline"),
        "tunnel_error": tunnel_info.get("error"),
        "is_live": tunnel_info.get("status") == "online",
        "is_cloud": False
    }

@app.post("/api/mobile-tunnel/restart")
def restart_mobile_tunnel():
    """Restart Cloudflare tunnel and generate a fresh live URL."""
    stop_tunnel()
    new_url = start_tunnel(port=8000, wait_for_url=8.0)
    tunnel_info = get_tunnel_status()
    return {
        "success": True,
        "url": new_url,
        "status": tunnel_info.get("status")
    }

@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join(FRONTEND_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="Manifest not found")

@app.get("/sw.js")
def get_service_worker():
    sw_path = os.path.join(FRONTEND_DIR, "sw.js")
    if os.path.exists(sw_path):
        response = FileResponse(sw_path, media_type="application/javascript")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
    raise HTTPException(status_code=404, detail="Service worker not found")

@app.get("/css/style.css")
@app.get("/style.css")
def get_style_css():
    for p in [
        os.path.join(FRONTEND_DIR, "css", "style.css"),
        os.path.join(FRONTEND_DIR, "style.css"),
        os.path.join(BASE_DIR, "style.css")
    ]:
        if os.path.exists(p):
            return FileResponse(p, media_type="text/css")
    raise HTTPException(status_code=404, detail="style.css not found")

@app.get("/js/app.js")
@app.get("/app.js")
def get_app_js():
    for p in [
        os.path.join(FRONTEND_DIR, "js", "app.js"),
        os.path.join(FRONTEND_DIR, "app.js"),
        os.path.join(BASE_DIR, "app.js")
    ]:
        if os.path.exists(p):
            return FileResponse(p, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")

# Mount Frontend static files
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

