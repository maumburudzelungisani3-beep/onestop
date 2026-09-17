import os
import io
import csv
import time
import traceback
import pandas as pd
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Response, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import AppConfig, DataSource
from backend.connectors.access_connector import AccessConnector
from backend.connectors.excel_connector import ExcelConnector
from backend.connectors.sqlite_connector import SQLiteConnector
from backend.etl_pipeline import get_sync_status, start_sync_background, CONSOLIDATED_DB_PATH
from backend.search_engine import SearchEngine
from backend.demo_data import seed_demo_data
from backend.auth import router as auth_router, get_current_user, get_optional_user

# Global startup diagnostics for the /api/database/health endpoint
_STARTUP_DIAGNOSTICS: Dict[str, Any] = {
    "extraction_attempted": False,
    "extraction_success": False,
    "extraction_error": None,
    "extraction_duration_seconds": None,
    "db_existed_before_startup": False,
}

app = FastAPI(
    title="DataBridge - Unified Network DB & Excel Search",
    version="1.0.0",
    description="Simultaneously access, search, and inspect Access databases and Excel sheets across your network"
)

# Enable CORS for development flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Authentication and WebAuthn / Passkeys Router
app.include_router(auth_router)

class TestSourcePayload(BaseModel):
    type: str  # "access" or "excel"
    path: str
    password: Optional[str] = None

class ScanFolderPayload(BaseModel):
    folder_path: str
    recursive: bool = False

class CreateSourcePayload(BaseModel):
    name: str
    type: str
    path: str
    description: Optional[str] = ""
    enabled: bool = True
    tables_or_sheets: Optional[List[str]] = None
    password: Optional[str] = None

class UpdateSourcePayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    tables_or_sheets: Optional[List[str]] = None
    password: Optional[str] = None

@app.on_event("startup")
def startup_event():
    global _STARTUP_DIAGNOSTICS

    data_dir = os.path.dirname(CONSOLIDATED_DB_PATH)
    os.makedirs(data_dir, exist_ok=True)

    _STARTUP_DIAGNOSTICS["db_existed_before_startup"] = os.path.exists(CONSOLIDATED_DB_PATH)

    # If uncompressed database is missing (e.g. fresh cloud deployment), auto-extract from committed zip
    if not os.path.exists(CONSOLIDATED_DB_PATH):
        zip_path = os.path.join(data_dir, "consolidated_lands.db.zip")
        zip_exists = os.path.exists(zip_path)
        print(f"[STARTUP] Consolidated DB missing at {CONSOLIDATED_DB_PATH}")
        print(f"[STARTUP] Zip archive {'found' if zip_exists else 'NOT FOUND'} at {zip_path}")

        if zip_exists:
            _STARTUP_DIAGNOSTICS["extraction_attempted"] = True
            t0 = time.time()
            try:
                zip_size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
                print(f"[STARTUP] Extracting database from zip ({zip_size_mb} MB)...")

                import zipfile
                with zipfile.ZipFile(zip_path, "r") as zf:
                    # Stream-extract each member to reduce peak memory usage
                    for member in zf.infolist():
                        print(f"[STARTUP]   Extracting: {member.filename} ({round(member.file_size / (1024 * 1024), 1)} MB)")
                        zf.extract(member, data_dir)

                elapsed = round(time.time() - t0, 1)
                _STARTUP_DIAGNOSTICS["extraction_duration_seconds"] = elapsed

                if os.path.exists(CONSOLIDATED_DB_PATH):
                    db_size_mb = round(os.path.getsize(CONSOLIDATED_DB_PATH) / (1024 * 1024), 2)
                    _STARTUP_DIAGNOSTICS["extraction_success"] = True
                    print(f"[STARTUP] ✅ Database extracted successfully: {db_size_mb} MB in {elapsed}s")
                else:
                    _STARTUP_DIAGNOSTICS["extraction_error"] = "Zip extracted but .db file not found on disk afterwards"
                    print(f"[STARTUP] ⚠️ Zip extracted but database file not found at {CONSOLIDATED_DB_PATH}")

            except Exception as e:
                elapsed = round(time.time() - t0, 1)
                err_msg = f"{type(e).__name__}: {e}"
                _STARTUP_DIAGNOSTICS["extraction_error"] = err_msg
                _STARTUP_DIAGNOSTICS["extraction_duration_seconds"] = elapsed
                print(f"[STARTUP] ❌ Failed to extract consolidated database after {elapsed}s: {err_msg}")
                traceback.print_exc()
        else:
            _STARTUP_DIAGNOSTICS["extraction_error"] = "Zip archive not found in deployment"
            print(f"[STARTUP] ❌ No zip archive found — database will be unavailable")
    else:
        db_size_mb = round(os.path.getsize(CONSOLIDATED_DB_PATH) / (1024 * 1024), 2)
        print(f"[STARTUP] ✅ Consolidated database already exists: {db_size_mb} MB")
        _STARTUP_DIAGNOSTICS["extraction_success"] = True

    # Ensure initial demo sources exist if sources.json is empty
    sources = AppConfig.get_sources()
    if not sources:
        try:
            seed_demo_data()
        except Exception as e:
            print(f"Startup demo data seeding notice: {e}")

@app.get("/api/sources")
def get_sources(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns all configured data sources along with current reachability status"""
    sources = AppConfig.get_sources()
    enriched = []
    for s in sources:
        item = s.model_dump()
        is_reachable = os.path.exists(s.path)
        item["is_reachable"] = is_reachable
        item["file_size_bytes"] = os.path.getsize(s.path) if is_reachable else 0
        enriched.append(item)
    return enriched

@app.post("/api/sources/test")
def test_source(payload: TestSourcePayload, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Verifies file path reachability and inspects available tables/sheets"""
    path = payload.path.strip()
    stype = payload.type.lower().strip()

    if not os.path.exists(path):
        return {
            "success": False,
            "message": f"Path unreachable or file not found on local network: {path}",
            "tables": []
        }

    if stype == "access":
        success, message, tables = AccessConnector.test_connection(path, password=payload.password)
        return {"success": success, "message": message, "tables": tables}
    elif stype == "excel":
        success, message, sheets = ExcelConnector.test_connection(path)
        return {"success": success, "message": message, "tables": sheets}
    elif stype == "sqlite":
        success, message, tables = SQLiteConnector.test_connection(path)
        return {"success": success, "message": message, "tables": tables}
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported source type '{stype}'. Must be 'access', 'excel', or 'sqlite'.")

@app.post("/api/sources/scan-folder")
def scan_network_folder(payload: ScanFolderPayload, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Scans a network directory (UNC or mapped drive) for Access and Excel files"""
    folder = payload.folder_path.strip()
    if not os.path.exists(folder):
        return {
            "success": False,
            "message": f"Network folder not found or unreachable: {folder}",
            "files": []
        }
    
    if not os.path.isdir(folder):
        return {
            "success": False,
            "message": f"Path is not a directory: {folder}",
            "files": []
        }

    discovered = []
    walk_gen = os.walk(folder) if payload.recursive else [(folder, [], os.listdir(folder))]

    for root, _, filenames in walk_gen:
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            full_path = os.path.join(root, fname)
            
            if fname.startswith("~$") or fname.startswith("."):
                continue

            if ext in [".accdb", ".mdb"]:
                discovered.append({
                    "name": os.path.splitext(fname)[0].replace("_", " ").title(),
                    "type": "access",
                    "path": full_path,
                    "size_bytes": os.path.getsize(full_path),
                    "filename": fname
                })
            elif ext in [".xlsx", ".xls", ".xlsm"]:
                discovered.append({
                    "name": os.path.splitext(fname)[0].replace("_", " ").title(),
                    "type": "excel",
                    "path": full_path,
                    "size_bytes": os.path.getsize(full_path),
                    "filename": fname
                })

    return {
        "success": True,
        "message": f"Discovered {len(discovered)} database / spreadsheet file(s).",
        "files": discovered
    }

@app.post("/api/sources")
def add_source(payload: CreateSourcePayload, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Adds or updates a network data source"""
    path = payload.path.strip()
    stype = payload.type.lower().strip()

    # Discover tables if not specified
    cached_tables = payload.tables_or_sheets
    status = "connected" if os.path.exists(path) else "offline"

    if os.path.exists(path) and not cached_tables:
        if stype == "access":
            _, _, tables = AccessConnector.test_connection(path, password=payload.password)
            cached_tables = tables
        elif stype == "excel":
            _, _, sheets = ExcelConnector.test_connection(path)
            cached_tables = sheets

    source = DataSource(
        name=payload.name.strip(),
        type=stype,
        path=path,
        description=payload.description or "",
        enabled=payload.enabled,
        tables_or_sheets=payload.tables_or_sheets,
        password=payload.password,
        status=status,
        cached_tables=cached_tables
    )
    saved = AppConfig.add_source(source)
    return saved

@app.put("/api/sources/{source_id}")
def update_source(source_id: str, payload: UpdateSourcePayload, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Updates an existing data source"""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = AppConfig.update_source(source_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Data source not found")
    return updated

@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Removes a configured data source"""
    deleted = AppConfig.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Data source not found")
    return {"success": True, "message": "Source removed successfully."}

@app.get("/api/sources/{source_id}/schema")
def get_source_schema(source_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns the schema (tables/sheets and their columns) of a source"""
    sources = [s for s in AppConfig.get_sources() if s.id == source_id]
    if not sources:
        raise HTTPException(status_code=404, detail="Source not found")
    source = sources[0]
    
    if source.type == "access":
        schema = AccessConnector.get_schema(source.path, password=source.password)
    else:
        schema = ExcelConnector.get_schema(source.path)
    return {"source_id": source.id, "source_name": source.name, "schema": schema}

@app.get("/api/search")
def search(
    q: str = Query("", description="Search term across all fields"),
    source_id: Optional[str] = Query(None, description="Optional source ID filter"),
    source_type: Optional[str] = Query(None, description="'access', 'excel', or 'all'"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Executes multi-source search across Access databases and Excel workbooks"""
    return SearchEngine.search(
        query=q,
        source_id=source_id,
        source_type=source_type,
        limit=limit,
        offset=offset
    )

@app.get("/api/export")
def export_results(
    q: str = Query("", description="Search term to export"),
    format: str = Query("csv", pattern="^(csv|excel)$"),
    source_id: Optional[str] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Exports matching search results to CSV or Excel file"""
    res = SearchEngine.search(query=q, source_id=source_id, limit=500, offset=0)
    records = res.get("results", [])

    flat_data = []
    for r in records:
        row = {
            "Source Type": r.get("source_type"),
            "Source Name": r.get("source_name"),
            "Table/Sheet": r.get("container"),
            "File Name": r.get("file_name"),
            "File Path": r.get("file_path")
        }
        for k, v in r.get("data", {}).items():
            row[f"Data_{k}"] = v
        flat_data.append(row)

    df = pd.DataFrame(flat_data)

    if format == "csv":
        stream = io.StringIO()
        df.to_csv(stream, index=False)
        return Response(
            content=stream.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=search_export_{int(os.path.getmtime(__file__))}.csv"}
        )
    else:
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="SearchResults")
        return Response(
            content=stream.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=search_export.xlsx"}
        )

class SQLQueryPayload(BaseModel):
    sql: str
    limit: Optional[int] = 100
    offset: Optional[int] = 0

@app.post("/api/sync/start")
def trigger_sync(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Starts background ETL extraction of all network databases into local SQLite"""
    started = start_sync_background()
    if not started:
        return {"success": False, "message": "An ETL sync is already currently in progress."}
    return {"success": True, "message": "Extraction and consolidation started in background."}

@app.get("/api/sync/status")
def sync_status(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns current extraction and consolidation status"""
    return get_sync_status()

@app.get("/api/database/health")
def database_health():
    """Returns diagnostic information about the consolidated database status — useful for debugging deployments (Public)"""
    db_exists = os.path.exists(CONSOLIDATED_DB_PATH)
    zip_path = os.path.join(os.path.dirname(CONSOLIDATED_DB_PATH), "consolidated_lands.db.zip")
    zip_exists = os.path.exists(zip_path)

    health = {
        "database_path": CONSOLIDATED_DB_PATH,
        "database_exists": db_exists,
        "database_size_mb": round(os.path.getsize(CONSOLIDATED_DB_PATH) / (1024 * 1024), 2) if db_exists else 0,
        "zip_path": zip_path,
        "zip_exists": zip_exists,
        "zip_size_mb": round(os.path.getsize(zip_path) / (1024 * 1024), 2) if zip_exists else 0,
        "startup_diagnostics": _STARTUP_DIAGNOSTICS,
    }

    # Quick validation: try opening the database
    if db_exists:
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{CONSOLIDATED_DB_PATH}?mode=ro", uri=True, timeout=3)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table';")
            table_count = cursor.fetchone()[0]
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unified_search_fts';")
            has_fts = cursor.fetchone() is not None
            fts_schema = []
            if has_fts:
                cursor.execute("PRAGMA table_info(unified_search_fts);")
                fts_schema = [c[1] for c in cursor.fetchall()]
            conn.close()
            health["table_count"] = table_count
            health["has_fts_index"] = has_fts
            health["fts_columns"] = fts_schema
            health["status"] = "healthy"
        except Exception as e:
            health["status"] = "error"
            health["error"] = str(e)
    else:
        health["status"] = "missing"

    return health

@app.get("/api/database/stats")
def database_stats(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns consolidated SQLite database tables, row counts, and metadata"""
    return SQLiteConnector.get_database_stats(CONSOLIDATED_DB_PATH)

@app.post("/api/database/query")
def execute_sql(payload: SQLQueryPayload, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Executes safe, read-only SQL queries against the consolidated database"""
    try:
        res = SQLiteConnector.execute_query(
            db_path=CONSOLIDATED_DB_PATH,
            sql=payload.sql,
            limit=payload.limit or 100,
            offset=payload.offset or 0
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/database/download")
def download_database(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Provides direct download of the standalone consolidated SQLite database"""
    if not os.path.exists(CONSOLIDATED_DB_PATH):
        raise HTTPException(status_code=404, detail="Consolidated database not found. Run sync first.")
    return FileResponse(
        path=CONSOLIDATED_DB_PATH,
        filename="consolidated_lands.db",
        media_type="application/x-sqlite3"
    )

@app.post("/api/demo/seed")
def seed_demo(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Generates sample Access database and Excel sheets for instant testing"""
    result = seed_demo_data()
    return {"success": True, "message": "Sample databases and workbooks generated successfully!", "paths": result}

# Mount static frontend
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)
