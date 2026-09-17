import os
import sqlite3
import time
from typing import List, Dict, Any, Tuple, Optional

class SQLiteConnector:
    """Connector for the local consolidated SQLite database"""

    @staticmethod
    def test_connection(db_path: str) -> Tuple[bool, str, List[str]]:
        if not os.path.exists(db_path):
            return False, f"Database file not found: {db_path}", []
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                tables = [row[0] for row in cursor.fetchall()]
            return True, "Successfully connected to SQLite database.", tables
        except Exception as e:
            return False, f"SQLite connection error: {str(e)}", []

    @staticmethod
    def get_database_stats(db_path: str) -> Dict[str, Any]:
        """Returns row count and column information for every table in the database"""
        if not os.path.exists(db_path):
            return {"exists": False, "tables": {}, "total_rows": 0, "size_mb": 0}

        stats = {
            "exists": True,
            "size_mb": round(os.path.getsize(db_path) / (1024 * 1024), 2),
            "tables": {},
            "total_rows": 0,
            "last_modified": time.ctime(os.path.getmtime(db_path))
        }

        try:
            conn = sqlite3.connect(db_path, timeout=5)
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'unified_search_fts%';")
                all_items = [r[0] for r in cursor.fetchall()]
                priority = [
                    "vw_consolidated_farms_origin",
                    "ol2026_farm_register",
                    "ol2026_beneficiary_details",
                    "lands02_farm_details",
                    "lands02_personal_details",
                    "lands02_farm_withdrawn",
                    "a2_alloc_sheet1"
                ]
                tables = sorted(all_items, key=lambda x: (0 if x in priority else 1, priority.index(x) if x in priority else x))

                total_rows = 0
                for tbl in tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM [{tbl}];")
                        count = cursor.fetchone()[0]
                    except Exception:
                        count = 0

                    cursor.execute(f"PRAGMA table_info([{tbl}]);")
                    cols = [c[1] for c in cursor.fetchall()]

                    stats["tables"][tbl] = {
                        "row_count": count,
                        "column_count": len(cols),
                        "columns": cols
                    }
                    if not tbl.startswith("vw_"):
                        total_rows += count

                stats["total_rows"] = total_rows

                # Check FTS5
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unified_search_fts';")
                stats["has_fts"] = cursor.fetchone() is not None

                # Check ETL metadata
                try:
                    cursor.execute("SELECT key, value FROM _etl_metadata;")
                    stats["metadata"] = dict(cursor.fetchall())
                except Exception:
                    stats["metadata"] = {}

        except Exception as e:
            stats["error"] = str(e)

        return stats

    @staticmethod
    def execute_query(db_path: str, sql: str, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
        """Safely executes read-only SQL queries with pagination and column metadata"""
        if not os.path.exists(db_path):
            raise FileNotFoundError("Consolidated database has not yet been generated. Run ETL sync first.")

        clean_sql = sql.strip().rstrip(";")
        # Enforce read-only safety
        lowered = clean_sql.lower()
        forbidden_keywords = ["drop", "delete", "insert", "update", "alter", "vacuum", "truncate", "create", "attach"]
        first_word = lowered.split()[0] if lowered.split() else ""
        if first_word not in ["select", "pragma", "explain", "with"]:
            raise ValueError("Only read-only SELECT and PRAGMA queries are permitted.")

        for kw in forbidden_keywords:
            if f" {kw} " in f" {lowered} " and first_word not in ["select", "pragma", "with"]:
                raise ValueError(f"Modification keyword '{kw}' is not allowed in read-only mode.")

        t0 = time.time()
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
        try:
            cursor = conn.cursor()
            # If user didn't specify LIMIT, apply default limit
            paginated_sql = clean_sql
            if "limit" not in lowered:
                paginated_sql = f"{clean_sql} LIMIT {limit} OFFSET {offset}"

            cursor.execute(paginated_sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            elapsed_ms = round((time.time() - t0) * 1000, 2)

            return {
                "success": True,
                "columns": columns,
                "rows": [list(r) for r in rows],
                "row_count": len(rows),
                "execution_ms": elapsed_ms,
                "sql": paginated_sql
            }
        finally:
            conn.close()

    @staticmethod
    def search_fts(db_path: str, query: str, limit: int = 150) -> List[Dict[str, Any]]:
        """Performs ultra-fast full-text search across unified_search_fts"""
        if not os.path.exists(db_path) or not query.strip():
            return []

        # Prepare FTS query string with proper token prefix matching
        sanitized_query = query
        for ch in ['"', "'", '-', '/', '\\', ':', '.', '_', '(', ')', '[', ']', '{', '}']:
            sanitized_query = sanitized_query.replace(ch, ' ')
        clean_words = [w.strip() for w in sanitized_query.split() if w.strip()]
        if not clean_words:
            return []
        safe_query = " ".join([f"{w}*" for w in clean_words])

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT source_name, table_name, title, subtitle, content, rank
                FROM unified_search_fts
                WHERE unified_search_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (safe_query, limit))
            
            results = []
            for r in cursor.fetchall():
                results.append({
                    "source_name": r[0],
                    "table_name": r[1],
                    "title": r[2],
                    "subtitle": r[3],
                    "content": r[4],
                    "score": round(r[5], 2)
                })
            return results
        except Exception:
            return []
        finally:
            conn.close()

    @staticmethod
    def search_items(db_path: str, query: str = "", tables_to_search: Optional[List[str]] = None, max_results: int = 150) -> List[Dict[str, Any]]:
        """
        Searches across the consolidated SQLite database and returns fully-populated records
        compatible with the DataBridge frontend and inspector drawer.
        """
        results = []
        if not os.path.exists(db_path):
            return results

        clean_query = query.strip()
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            cursor = conn.cursor()
            file_name = os.path.basename(db_path)

            if not clean_query:
                # Default browsing: get sample rows from primary tables
                priority_tables = [
                    "ol2026_beneficiary_details",
                    "ol2026_farm_register",
                    "reg2025_mashwest_a1_allocation",
                    "reg2025_mashcentral_a1_allocation",
                    "reg2025_manicaland_a1_allocation",
                    "reg2025_masvingo_a1_allocation",
                    "lands02_farm_details",
                    "lands02_personal_details",
                    "a2_alloc_sheet1"
                ]
                per_table_limit = max(10, max_results // len(priority_tables))
                for tbl in priority_tables:
                    try:
                        cursor.execute(f"PRAGMA table_info([{tbl}]);")
                        cols = [c[1] for c in cursor.fetchall()]
                        if not cols:
                            continue
                        cursor.execute(f"SELECT * FROM [{tbl}] LIMIT {per_table_limit};")
                        for row in cursor.fetchall():
                            row_dict = dict(zip(cols, row))
                            row_dict = SQLiteConnector._enrich_land_record(cursor, tbl, row_dict)
                            clean_data = {k: (v if v is not None and str(v).lower() != 'none' else None) for k, v in row_dict.items()}
                            results.append({
                                "source_type": "SQLite Database",
                                "container": tbl,
                                "file_path": db_path,
                                "file_name": file_name,
                                "data": clean_data,
                                "matched_fields": []
                            })
                    except Exception:
                        continue
                return results[:max_results]

            # Text query: use FTS5 index for instant search
            sanitized_query = clean_query
            for ch in ['"', "'", '-', '/', '\\', ':', '.', '_', '(', ')', '[', ']', '{', '}']:
                sanitized_query = sanitized_query.replace(ch, ' ')
            clean_words = [w.strip() for w in sanitized_query.split() if w.strip()]
            if not clean_words:
                return []
            fts_query = " ".join([f"{w}*" for w in clean_words])

            # Detect FTS schema to handle both old (no row_id) and new (with row_id) layouts
            fts_has_row_id = False
            try:
                cursor.execute("PRAGMA table_info(unified_search_fts);")
                fts_columns = [c[1] for c in cursor.fetchall()]
                fts_has_row_id = "row_id" in fts_columns
            except Exception:
                pass

            if fts_has_row_id:
                cursor.execute("""
                    SELECT table_name, row_id, title, subtitle, content
                    FROM unified_search_fts
                    WHERE unified_search_fts MATCH ?
                    LIMIT ?
                """, (fts_query, max_results))
                matches = [(r[0], r[1], r[2], r[3], r[4]) for r in cursor.fetchall()]
            else:
                cursor.execute("""
                    SELECT table_name, title, subtitle, content
                    FROM unified_search_fts
                    WHERE unified_search_fts MATCH ?
                    LIMIT ?
                """, (fts_query, max_results))
                matches = [(r[0], None, r[1], r[2], r[3]) for r in cursor.fetchall()]

            # Cache table columns for fast dict mapping
            table_col_cache = {}

            for tbl, row_id, title, sub, content in matches:
                if tbl not in table_col_cache:
                    cursor.execute(f"PRAGMA table_info([{tbl}]);")
                    cols = [c[1] for c in cursor.fetchall()]
                    table_col_cache[tbl] = cols
                cols = table_col_cache[tbl]
                if not cols:
                    continue

                row = None
                if row_id and str(row_id).isdigit():
                    row = cursor.execute(f"SELECT * FROM [{tbl}] WHERE rowid = ?;", (int(row_id),)).fetchone()

                if not row:
                    first_col = cols[0]
                    row = cursor.execute(f"SELECT * FROM [{tbl}] WHERE [{first_col}] = ? LIMIT 1;", (title,)).fetchone()
                    if not row and sub:
                        for c in cols[1:4]:
                            row = cursor.execute(f"SELECT * FROM [{tbl}] WHERE [{c}] = ? LIMIT 1;", (sub,)).fetchone()
                            if row:
                                break

                if row:
                    row_dict = dict(zip(cols, row))
                else:
                    first_col = cols[0] if cols else "item"
                    row_dict = {first_col: title, "Details": content[:250]}

                # Cross-reference essential land records across tables
                row_dict = SQLiteConnector._enrich_land_record(cursor, tbl, row_dict)

                clean_data = {k: (v if v is not None and str(v).lower() != 'none' else None) for k, v in row_dict.items()}

                # Determine matched fields
                matched = []
                q_low = clean_query.lower()
                for k, v in clean_data.items():
                    if v and q_low in str(v).lower():
                        matched.append(k)

                results.append({
                    "source_type": "SQLite Database",
                    "container": tbl,
                    "file_path": db_path,
                    "file_name": file_name,
                    "data": clean_data,
                    "matched_fields": matched
                })

            return results
        finally:
            conn.close()

    @staticmethod
    def _enrich_land_record(cursor: sqlite3.Cursor, tbl: str, row_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cross-references complementary land administration fields across tables
        so that Name, ID Number, Farm Name, Subdivision Number, Surname, District, Province
        are populated whenever available.
        """
        try:
            # 1. LANDS 02 Personal Details -> enrich Farm Details & Origin
            if tbl == "lands02_personal_details":
                id_num = row_dict.get("id_number")
                if id_num and not row_dict.get("national_id"):
                    row_dict["national_id"] = id_num
                if row_dict.get("initials") and not row_dict.get("first_name"):
                    row_dict["first_name"] = row_dict.get("initials")
                if id_num and str(id_num).strip() not in ("-", "", "None"):
                    f_row = cursor.execute(
                        "SELECT farm_name, subdivision_number, district, province, subdiv_size, where_farm_taken_from FROM lands02_farm_details WHERE id_number = ? LIMIT 1;",
                        (id_num,)
                    ).fetchone()
                    if f_row:
                        if f_row[0] and not row_dict.get("farm_name"): row_dict["farm_name"] = f_row[0]
                        if f_row[1] and not row_dict.get("subdivision_number"): row_dict["subdivision_number"] = f_row[1]
                        if f_row[2] and not row_dict.get("district"): row_dict["district"] = f_row[2]
                        if f_row[3] and not row_dict.get("province"): row_dict["province"] = f_row[3]
                        if f_row[4] and not row_dict.get("subdiv_size"): row_dict["subdiv_size"] = f_row[4]
                        if f_row[5] and not row_dict.get("where_farm_taken_from"): row_dict["where_farm_taken_from"] = f_row[5]
                    
                    # Also check if reallocated from a withdrawn farm
                    fw_row = cursor.execute(
                        "SELECT farm_withdrawn, subdivision_number, district FROM lands02_farm_withdrawn WHERE id_number = ? LIMIT 1;",
                        (id_num,)
                    ).fetchone()
                    if fw_row and fw_row[0]:
                        row_dict["where_farm_taken_from"] = f"Reallocated from Withdrawn Farm: {fw_row[0]} (District: {fw_row[2] or 'Unspecified'})"

            # 2. LANDS 02 Farm Details -> enrich Personal Details & Origin
            elif tbl == "lands02_farm_details":
                id_num = row_dict.get("id_number")
                if id_num and not row_dict.get("national_id"):
                    row_dict["national_id"] = id_num
                if id_num and str(id_num).strip() not in ("-", "", "None"):
                    p_row = cursor.execute(
                        "SELECT title, surname, initials, address FROM lands02_personal_details WHERE id_number = ? LIMIT 1;",
                        (id_num,)
                    ).fetchone()
                    if p_row:
                        if p_row[0] and not row_dict.get("title"): row_dict["title"] = p_row[0]
                        if p_row[1] and not row_dict.get("surname"): row_dict["surname"] = p_row[1]
                        if p_row[2] and not row_dict.get("initials"): row_dict["initials"] = p_row[2]
                        if p_row[2] and not row_dict.get("first_name"): row_dict["first_name"] = p_row[2]
                        if p_row[3] and not row_dict.get("address"): row_dict["address"] = p_row[3]
                    
                    # Check withdrawn
                    fw_row = cursor.execute(
                        "SELECT farm_withdrawn, district FROM lands02_farm_withdrawn WHERE id_number = ? LIMIT 1;",
                        (id_num,)
                    ).fetchone()
                    if fw_row and fw_row[0]:
                        row_dict["where_farm_taken_from"] = f"Reallocated from Withdrawn Farm: {fw_row[0]} (District: {fw_row[1] or 'Unspecified'})"

            # 3. Offer Letters 2026 Beneficiary Details -> enrich Farm, Subdivision, & Origin from Permits / Farm Register
            elif tbl == "ol2026_beneficiary_details":
                nat_id = row_dict.get("national_id")
                if nat_id and str(nat_id).strip() not in ("-", "", "None"):
                    perm_row = cursor.execute(
                        "SELECT farm_name, subdivision_id, where_farm_taken_from FROM ol2026_permitsprinted WHERE national_id = ? LIMIT 1;",
                        (nat_id,)
                    ).fetchone()
                    if perm_row:
                        if perm_row[0] and not row_dict.get("farm_name"): row_dict["farm_name"] = perm_row[0]
                        if perm_row[1] and not row_dict.get("subdivision_number"): row_dict["subdivision_number"] = perm_row[1]
                        if perm_row[2] and not row_dict.get("where_farm_taken_from"): row_dict["where_farm_taken_from"] = perm_row[2]
                    else:
                        alloc_row = cursor.execute(
                            "SELECT subdivision_id, land_use FROM ol2026_allocation_register WHERE beneficiary_id = ? LIMIT 1;",
                            (nat_id,)
                        ).fetchone()
                        if alloc_row:
                            if alloc_row[0] and not row_dict.get("subdivision_number"): row_dict["subdivision_number"] = alloc_row[0]
                            if alloc_row[1] and not row_dict.get("land_use"): row_dict["land_use"] = alloc_row[1]

                    # If farm_name is known, lookup where it was taken from in ol2026_farm_register
                    fn = row_dict.get("farm_name")
                    if fn and not row_dict.get("where_farm_taken_from"):
                        fr_row = cursor.execute(
                            "SELECT where_farm_taken_from, previous_district, current_district, diagram_no FROM ol2026_farm_register WHERE farm_name = ? LIMIT 1;",
                            (fn,)
                        ).fetchone()
                        if fr_row and fr_row[0]:
                            row_dict["where_farm_taken_from"] = fr_row[0]

            # 4. A2 Allocations Sheet 1 & 2 standardizing
            elif tbl.startswith("a2_alloc_"):
                if row_dict.get("disrict") and not row_dict.get("district"):
                    row_dict["district"] = row_dict["disrict"]
                if row_dict.get("s_d_no") and not row_dict.get("subdivision_number"):
                    row_dict["subdivision_number"] = row_dict["s_d_no"]
                if row_dict.get("area_ha") and not row_dict.get("subdiv_size"):
                    row_dict["subdiv_size"] = row_dict["area_ha"]
                if row_dict.get("unnamed_1") and not row_dict.get("province"):
                    row_dict["province"] = row_dict["unnamed_1"]

            # 5. Current Farm Registers 2025 standardizing
            elif tbl.startswith("reg2025_"):
                if row_dict.get("sd_no") and not row_dict.get("subdivision_number"):
                    row_dict["subdivision_number"] = row_dict["sd_no"]
                if row_dict.get("s_d") and not row_dict.get("subdivision_number"):
                    row_dict["subdivision_number"] = row_dict["s_d"]
                if row_dict.get("id_no") and not row_dict.get("national_id"):
                    row_dict["national_id"] = row_dict["id_no"]
                if row_dict.get("idnumber") and not row_dict.get("national_id"):
                    row_dict["national_id"] = row_dict["idnumber"]
                if row_dict.get("extent_ha") and not row_dict.get("area_ha"):
                    row_dict["area_ha"] = row_dict["extent_ha"]
                if row_dict.get("current_district") and not row_dict.get("district"):
                    row_dict["district"] = row_dict["current_district"]
                if row_dict.get("first_nme") and not row_dict.get("first_name"):
                    row_dict["first_name"] = row_dict["first_nme"]
                if row_dict.get("other_name") and not row_dict.get("other_names"):
                    row_dict["other_names"] = row_dict["other_name"]
                if row_dict.get("from_farm_register") and not row_dict.get("farm_name"):
                    row_dict["farm_name"] = row_dict["from_farm_register"]

            # Ensure where_farm_taken_from is fallback constructed if still missing
            if not row_dict.get("where_farm_taken_from"):
                fn = row_dict.get("farm_name") or row_dict.get("from_farm_register")
                p_diag = row_dict.get("parent_farm_diagm_no")
                prev_d = row_dict.get("previous_district")
                sd = row_dict.get("subdivision_number") or row_dict.get("sd_no")
                parts = []
                if p_diag: parts.append(f"Parent Diagram: {p_diag}")
                if sd and fn: parts.append(f"Subdivision {sd} of Farm {fn}")
                elif fn: parts.append(f"Farm: {fn}")
                if prev_d: parts.append(f"Original District: {prev_d}")
                if parts: row_dict["where_farm_taken_from"] = " | ".join(parts)

        except Exception:
            pass
        return row_dict
