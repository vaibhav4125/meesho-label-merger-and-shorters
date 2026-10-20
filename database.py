import os
import json
import sqlite3
import tempfile
from datetime import datetime
from contextlib import contextmanager

_cur_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_cur_dir) if os.path.basename(_cur_dir) == "backend" else _cur_dir
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

DB_PATH = os.environ.get("MEESHO_DB_PATH", os.path.join(DATA_DIR, "meesho_orders.db"))
PERSISTENT_MAPPINGS_FILE = os.path.join(DATA_DIR, "sku_mappings_persistent.json")

def get_connection():
    db_path = os.environ.get("MEESHO_DB_PATH", DB_PATH)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            page_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending', -- pending, processing, completed, error
            error_message TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS product_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT DEFAULT 'General',
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sku_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES product_groups(id) ON DELETE CASCADE,
            sku TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            seller_account TEXT,
            order_no TEXT NOT NULL,
            awb TEXT,
            sku TEXT NOT NULL,
            product_name TEXT,
            size TEXT NOT NULL,
            qty INTEGER DEFAULT 1,
            color TEXT,
            pickup_date TEXT,
            confidence REAL DEFAULT 1.0,
            validation_status TEXT DEFAULT 'Valid', -- 'Valid', 'Needs Review', 'Duplicate'
            is_duplicate INTEGER DEFAULT 0,
            duplicate_of_id INTEGER,
            is_excluded INTEGER DEFAULT 0,
            manual_override INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_orders_file_id ON orders(file_id);
        CREATE INDEX IF NOT EXISTS idx_orders_sku ON orders(sku);
        CREATE INDEX IF NOT EXISTS idx_orders_size ON orders(size);
        CREATE INDEX IF NOT EXISTS idx_orders_order_no ON orders(order_no);
        CREATE INDEX IF NOT EXISTS idx_sku_mappings_group ON sku_mappings(group_id);

        CREATE TABLE IF NOT EXISTS generated_pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            group_name TEXT NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            order_count INTEGER NOT NULL,
            page_count INTEGER NOT NULL,
            verified INTEGER DEFAULT 1,
            size_summary_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS product_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            label TEXT,
            icon TEXT DEFAULT '🏷️',
            display_order INTEGER DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Column migrations for existing databases
        cols = [c[1] for c in conn.execute("PRAGMA table_info(product_groups)").fetchall()]
        if "category" not in cols:
            conn.execute("ALTER TABLE product_groups ADD COLUMN category TEXT DEFAULT 'General'")
        if "display_order" not in cols:
            conn.execute("ALTER TABLE product_groups ADD COLUMN display_order INTEGER DEFAULT 0")

        # Seed default categories if empty
        DEFAULT_CATEGORIES = [
            ("Plazo", "👖 Plazo (Top)", "👖", 1),
            ("Women T-Shirt", "👕 Women T-Shirt (Middle)", "👕", 2),
            ("Men T-Shirt", "👕 Men T-Shirt", "👕", 3),
            ("Black Patti", "🏷️ Black Patti", "🏷️", 4),
            ("General", "📦 General", "📦", 5),
            ("Other", "📦 Other (Bottom)", "📦", 6),
        ]
        cat_count = conn.execute("SELECT COUNT(*) FROM product_categories").fetchone()[0]
        if cat_count == 0:
            for cname, clabel, cicon, corder in DEFAULT_CATEGORIES:
                conn.execute(
                    "INSERT OR IGNORE INTO product_categories (name, label, icon, display_order) VALUES (?, ?, ?, ?)",
                    (cname, clabel, cicon, corder)
                )

        # Also register any existing categories from product_groups if not already in product_categories
        try:
            existing_group_cats = conn.execute("SELECT DISTINCT category FROM product_groups WHERE category IS NOT NULL AND category != ''").fetchall()
            for r in existing_group_cats:
                cname = r[0].strip()
                if cname and cname not in ("undefined", "None"):
                    conn.execute(
                        "INSERT OR IGNORE INTO product_categories (name, label, icon, display_order) VALUES (?, ?, '🏷️', 10)",
                        (cname, f"🏷️ {cname}")
                    )
        except Exception:
            pass

    # Persistent SKU Mappings Auto-Sync on startup
    # (Skip during pytest test runs where a temporary test database is used)
    is_test_env = "test" in os.environ.get("MEESHO_DB_PATH", "").lower()
    if not is_test_env:
        if os.path.exists(PERSISTENT_MAPPINGS_FILE):
            # Restore any groups or mappings from the permanent JSON file
            restore_sku_mappings_from_json(force=False)
            # Re-sync any new DB groups back into JSON
            save_sku_mappings_to_json()
        else:
            # If persistent file doesn't exist yet, create it from current DB
            with get_db() as c:
                group_count = c.execute("SELECT COUNT(*) FROM product_groups").fetchone()[0]
                if group_count > 0:
                    save_sku_mappings_to_json()

        checkpoint_db()

def checkpoint_db():
    """Checkpoint SQLite WAL journal to ensure data is completely written to disk."""
    try:
        with get_db() as conn:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
    except Exception:
        pass

def get_all_categories_db():
    """Get all product categories ordered by display_order."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, name, label, icon, display_order, created_at
            FROM product_categories
            ORDER BY display_order ASC, id ASC
        """).fetchall()
        return [dict(r) for r in rows]

def add_category_db(name: str, label: str = None, icon: str = "🏷️", display_order: float = None):
    """Add a new custom product category and persist it."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Category name cannot be empty")
    icon = (icon or "🏷️").strip()
    if not label:
        label = f"{icon} {name}"
    else:
        label = label.strip()

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, name, label, icon, display_order FROM product_categories WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))",
            (name,)
        ).fetchone()
        if existing:
            return dict(existing)

        if display_order is None:
            max_order_row = conn.execute("SELECT MAX(display_order) FROM product_categories").fetchone()
            max_order = (max_order_row[0] or 6) if max_order_row else 6
            display_order = max_order + 1

        cur = conn.execute(
            "INSERT INTO product_categories (name, label, icon, display_order) VALUES (?, ?, ?, ?)",
            (name, label, icon, display_order)
        )
        new_id = cur.lastrowid
        res = {
            "id": new_id,
            "name": name,
            "label": label,
            "icon": icon,
            "display_order": display_order
        }

    save_sku_mappings_to_json()
    return res

def delete_category_db(name: str):
    """Delete a custom category. Groups assigned to it fall back to 'General'."""
    name = (name or "").strip()
    BUILTIN_PROTECTED = {"Plazo", "Women T-Shirt", "Men T-Shirt", "Black Patti", "General", "Other"}
    if name in BUILTIN_PROTECTED:
        raise ValueError(f"Built-in category '{name}' cannot be deleted")

    with get_db() as conn:
        conn.execute("UPDATE product_groups SET category = 'General' WHERE LOWER(TRIM(category)) = LOWER(TRIM(?))", (name,))
        conn.execute("DELETE FROM product_categories WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (name,))

    save_sku_mappings_to_json()
    return True

def save_sku_mappings_to_json(backup: bool = False):
    """
    Export current product groups, their mapped SKUs, and categories from SQLite to a permanent JSON file.
    This guarantees that mappings survive any DB corruption, program restarts, or daily order resets.
    """
    is_test_env = "test" in os.environ.get("MEESHO_DB_PATH", "").lower()
    target_file = os.path.join(tempfile.gettempdir(), "test_sku_mappings_persistent.json") if is_test_env else PERSISTENT_MAPPINGS_FILE
    target_backup_dir = os.path.join(tempfile.gettempdir(), "test_backups") if is_test_env else BACKUP_DIR
    os.makedirs(target_backup_dir, exist_ok=True)

    try:
        with get_db() as conn:
            groups = conn.execute("""
                SELECT id, name, category, display_order, created_at, updated_at
                FROM product_groups
                ORDER BY display_order ASC, name ASC
            """).fetchall()

            cats = conn.execute("""
                SELECT name, label, icon, display_order
                FROM product_categories
                ORDER BY display_order ASC, id ASC
            """).fetchall()

            data = {
                "version": 1,
                "saved_at": datetime.now().isoformat(),
                "total_groups": len(groups),
                "total_mappings": 0,
                "categories": [
                    {
                        "name": c["name"],
                        "label": c["label"] or f"{c['icon'] or '🏷️'} {c['name']}",
                        "icon": c["icon"] or "🏷️",
                        "display_order": c["display_order"] if c["display_order"] is not None else 10
                    }
                    for c in cats
                ],
                "groups": []
            }
            total_skus = 0
            for g in groups:
                gid = g["id"]
                sku_rows = conn.execute("SELECT sku FROM sku_mappings WHERE group_id = ? ORDER BY sku", (gid,)).fetchall()
                skus = [r["sku"] for r in sku_rows]
                total_skus += len(skus)
                data["groups"].append({
                    "id": gid,
                    "name": g["name"],
                    "category": g["category"] or "General",
                    "display_order": g["display_order"] or 0,
                    "created_at": str(g["created_at"]),
                    "updated_at": str(g["updated_at"]),
                    "skus": skus
                })
            data["total_mappings"] = total_skus

        # Write atomically to persistent file
        temp_file = target_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, target_file)

        # Also write backup copy if requested
        if backup:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(target_backup_dir, f"sku_mappings_backup_{ts}.json")
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        checkpoint_db()
        return data
    except Exception as e:
        print(f"[!] Warning saving SKU mappings to JSON: {e}")
        return None

def restore_sku_mappings_from_json(json_path: str = None, force: bool = False):
    """
    Restore product groups and SKU mappings from the permanent JSON file into SQLite.
    - If force=False: only restores groups/SKUs that are missing from the DB.
    - If force=True: overwrites existing mappings with those from the JSON file.
    """
    is_test_env = "test" in os.environ.get("MEESHO_DB_PATH", "").lower()
    if json_path is None and is_test_env:
        return {"restored_groups": 0, "restored_skus": 0, "message": "Test environment, skipping default restore"}

    target_path = json_path or PERSISTENT_MAPPINGS_FILE
    if not os.path.exists(target_path):
        return {"restored_groups": 0, "restored_skus": 0, "message": "No backup file found"}

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] Error loading {target_path}: {e}")
        return {"restored_groups": 0, "restored_skus": 0, "error": str(e)}

    groups = data.get("groups", [])
    categories = data.get("categories", [])
    restored_groups = 0
    restored_skus = 0
    restored_categories = 0

    with get_db() as conn:
        for cat in categories:
            if isinstance(cat, dict):
                cname = (cat.get("name") or "").strip()
                clabel = cat.get("label")
                cicon = cat.get("icon") or "🏷️"
                corder = cat.get("display_order", 10)
            elif isinstance(cat, str):
                cname = cat.strip()
                clabel = f"🏷️ {cname}"
                cicon = "🏷️"
                corder = 10
            else:
                continue

            if not cname:
                continue

            if not clabel:
                clabel = f"{cicon} {cname}"

            existing_cat = conn.execute("SELECT id FROM product_categories WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (cname,)).fetchone()
            if not existing_cat:
                conn.execute(
                    "INSERT INTO product_categories (name, label, icon, display_order) VALUES (?, ?, ?, ?)",
                    (cname, clabel, cicon, corder)
                )
                restored_categories += 1

        for g in groups:
            name = (g.get("name") or "").strip()
            if not name:
                continue
            cat = g.get("category", "General")
            order = g.get("display_order", 0)

            existing = conn.execute("SELECT id, name FROM product_groups WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (name,)).fetchone()
            if existing:
                gid = existing["id"]
                if cat:
                    conn.execute("UPDATE product_groups SET category = ?, display_order = ? WHERE id = ?", (cat, order, gid))
            else:
                cur = conn.execute("INSERT INTO product_groups (name, category, display_order) VALUES (?, ?, ?)", (name, cat, order))
                gid = cur.lastrowid
                restored_groups += 1

            for sku in g.get("skus", []):
                s = sku.strip()
                if not s:
                    continue
                mapped = conn.execute("SELECT id, group_id FROM sku_mappings WHERE sku = ?", (s,)).fetchone()
                if not mapped:
                    conn.execute("INSERT INTO sku_mappings (group_id, sku) VALUES (?, ?)", (gid, s))
                    restored_skus += 1
                elif force and mapped["group_id"] != gid:
                    conn.execute("UPDATE sku_mappings SET group_id = ? WHERE sku = ?", (gid, s))
                    restored_skus += 1

        checkpoint_db()

    return {
        "success": True,
        "restored_groups": restored_groups,
        "restored_skus": restored_skus,
        "total_groups": len(groups)
    }

def get_sku_mappings_status():
    """Get status of persistent SKU mappings file and DB counts."""
    file_exists = os.path.exists(PERSISTENT_MAPPINGS_FILE)
    file_info = {}
    if file_exists:
        try:
            with open(PERSISTENT_MAPPINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            file_info = {
                "saved_at": data.get("saved_at"),
                "file_groups": data.get("total_groups", len(data.get("groups", []))),
                "file_mappings": data.get("total_mappings", sum(len(g.get("skus", [])) for g in data.get("groups", [])))
            }
        except Exception:
            pass

    with get_db() as conn:
        db_groups = conn.execute("SELECT COUNT(*) FROM product_groups").fetchone()[0]
        db_mappings = conn.execute("SELECT COUNT(*) FROM sku_mappings").fetchone()[0]

    return {
        "persistent_file_exists": file_exists,
        "persistent_file_path": PERSISTENT_MAPPINGS_FILE,
        "db_groups": db_groups,
        "db_mappings": db_mappings,
        **file_info,
        "is_safe": True
    }
