import os
try:
    import pyodbc
except ImportError:
    pyodbc = None

from typing import List, Dict, Any, Tuple, Optional

ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"

class AccessConnector:
    @staticmethod
    def get_connection_string(file_path: str, read_only: bool = True, password: Optional[str] = None) -> str:
        # Standard connection string for 64-bit Access ODBC driver
        conn_str = f"Driver={{{ACCESS_DRIVER}}};Dbq={file_path};"
        if read_only:
            conn_str += "ExtendedAnsiSQL=1;READONLY=True;"
        if password:
            conn_str += f"Pwd={password};"
        return conn_str

    @staticmethod
    def _open_connection(file_path: str, password: Optional[str] = None, timeout: int = 8):
        """Attempts connection, trying provided password or known legacy passwords if password error occurs"""
        if pyodbc is None:
            raise RuntimeError(
                "pyodbc is not available on this platform (Linux/Cloud). "
                "Microsoft Access databases (.accdb/.mdb) require Windows ODBC drivers. "
                "Use the consolidated SQLite database or Excel workbooks on Linux/Render."
            )
        passwords_to_try = [password] if password is not None else [None, "ALLOCATIONS", "admin"]
        
        last_err = None
        for pwd in passwords_to_try:
            try:
                conn_str = AccessConnector.get_connection_string(file_path, read_only=True, password=pwd)
                conn = pyodbc.connect(conn_str, autocommit=True, timeout=timeout)
                try:
                    conn.setdecoding(pyodbc.SQL_CHAR, encoding="utf-8")
                    conn.setdecoding(pyodbc.SQL_WCHAR, encoding="utf-16le")
                except Exception:
                    pass
                return conn, pwd
            except Exception as e:
                err_str = str(e)
                last_err = e
                # Only retry if it's an invalid password error
                if "-1905" not in err_str and "password" not in err_str.lower():
                    raise e
        
        if last_err:
            raise last_err
        raise RuntimeError("Failed to connect to Access database.")

    @staticmethod
    def test_connection(file_path: str, password: Optional[str] = None) -> Tuple[bool, str, List[str]]:
        """Tests connection to the Access database and returns (success, message, table_list)"""
        if not os.path.exists(file_path):
            return False, f"File not found or unreachable across network: {file_path}", []

        try:
            conn, _ = AccessConnector._open_connection(file_path, password=password, timeout=6)
            with conn:
                cursor = conn.cursor()
                tables = []
                for row in cursor.tables(tableType='TABLE'):
                    tbl_name = row.table_name
                    # Filter out internal Access system tables
                    if not tbl_name.startswith("MSys") and not tbl_name.startswith("~"):
                        tables.append(tbl_name)
                return True, "Successfully connected to Access database.", tables
        except Exception as e:
            return False, f"ODBC Connection error: {str(e)}", []

    @staticmethod
    def get_schema(file_path: str, password: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Returns tables and their columns with types"""
        schema = {}
        if not os.path.exists(file_path):
            return schema

        try:
            conn, _ = AccessConnector._open_connection(file_path, password=password, timeout=8)
            with conn:
                cursor = conn.cursor()
                tables = []
                for row in cursor.tables(tableType='TABLE'):
                    tbl_name = row.table_name
                    if tbl_name.startswith("MSys") or tbl_name.startswith("~"):
                        continue
                    tables.append(tbl_name)

                for tbl_name in tables:
                    cols = []
                    try:
                        for col in cursor.columns(table=tbl_name):
                            cols.append({
                                "name": col.column_name,
                                "type": col.type_name,
                                "size": col.column_size
                            })
                    except Exception:
                        # Fallback for older MDBs where cursor.columns encounters encoding issues
                        try:
                            cursor.execute(f"SELECT TOP 1 * FROM [{tbl_name}]")
                            if cursor.description:
                                for d in cursor.description:
                                    cols.append({
                                        "name": d[0],
                                        "type": d[1].__name__ if hasattr(d[1], '__name__') else str(d[1]),
                                        "size": d[3] if len(d) > 3 else None
                                    })
                        except Exception as inner_err:
                            print(f"Could not read columns for table {tbl_name}: {inner_err}")
                    schema[tbl_name] = cols
        except Exception as e:
            print(f"Error fetching schema for {file_path}: {e}")
        return schema

    @staticmethod
    def search_items(file_path: str, query: str, tables_to_search: List[str] = None, max_results: int = 200, password: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Searches across tables in the Access database for rows matching the query string.
        Returns a list of match dictionaries.
        """
        results = []
        if not os.path.exists(file_path):
            return results

        try:
            conn, _ = AccessConnector._open_connection(file_path, password=password, timeout=12)
            with conn:
                cursor = conn.cursor()
                
                # Determine available tables
                available_tables = []
                for row in cursor.tables(tableType='TABLE'):
                    tbl_name = row.table_name
                    if not tbl_name.startswith("MSys") and not tbl_name.startswith("~"):
                        available_tables.append(tbl_name)
                
                target_tables = [t for t in available_tables if tables_to_search is None or t in tables_to_search]
                query_lower = query.strip().lower()

                for tbl in target_tables:
                    escaped_tbl = f"[{tbl}]"
                    
                    # Determine column names
                    col_info = []
                    try:
                        cursor.execute(f"SELECT TOP 1 * FROM {escaped_tbl}")
                        if cursor.description:
                            col_info = [d[0] for d in cursor.description]
                    except Exception as desc_err:
                        print(f"Error getting columns for {tbl}: {desc_err}")
                        continue

                    if not col_info:
                        continue

                    # If browsing (empty query), limit rows returned immediately
                    if not query_lower:
                        sql = f"SELECT TOP {max_results} * FROM {escaped_tbl}"
                    else:
                        sql = f"SELECT * FROM {escaped_tbl}"

                    try:
                        cursor.execute(sql)
                        
                        # Process in chunks to maintain low latency across network shares
                        chunk_size = 250
                        scanned_count = 0
                        max_scan = 2000 if query_lower else max_results

                        while scanned_count < max_scan:
                            rows = cursor.fetchmany(chunk_size)
                            if not rows:
                                break
                            
                            for row in rows:
                                scanned_count += 1
                                row_dict = {}
                                matched_fields = []
                                is_match = False
                                
                                for idx, col_name in enumerate(col_info):
                                    if idx >= len(row):
                                        continue
                                    val = row[idx]
                                    val_str = str(val) if val is not None else ""
                                    row_dict[col_name] = val
                                    
                                    if query_lower and query_lower in val_str.lower():
                                        is_match = True
                                        matched_fields.append(col_name)
                                    elif not query_lower:
                                        is_match = True

                                if is_match:
                                    results.append({
                                        "source_type": "Access Database",
                                        "container": tbl,
                                        "file_path": file_path,
                                        "file_name": os.path.basename(file_path),
                                        "data": row_dict,
                                        "matched_fields": matched_fields
                                    })
                                    if len(results) >= max_results:
                                        return results
                    except Exception as tbl_err:
                        print(f"Error querying table {tbl} in {file_path}: {tbl_err}")
                        continue
        except Exception as e:
            print(f"Error searching Access database {file_path}: {e}")

        return results
