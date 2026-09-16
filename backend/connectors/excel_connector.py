import os
import time
import pandas as pd
import openpyxl
from typing import List, Dict, Any, Tuple

# In-memory cache for fast search: {file_path: {"mtime": float, "sheets": {sheet_name: [row_dicts]}}}
_EXCEL_CACHE: Dict[str, Dict[str, Any]] = {}

class ExcelConnector:
    @staticmethod
    def test_connection(file_path: str) -> Tuple[bool, str, List[str]]:
        """Tests reading the Excel file and returns (success, message, sheet_names)"""
        if not os.path.exists(file_path):
            return False, f"File not found or unreachable across network: {file_path}", []

        try:
            if file_path.lower().endswith(('.xlsx', '.xlsm')):
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                sheets = wb.sheetnames
                wb.close()
                return True, "Successfully connected to Excel workbook.", sheets
            else:
                xl = pd.ExcelFile(file_path)
                return True, "Successfully connected to Excel workbook.", xl.sheet_names
        except Exception as e:
            return False, f"Excel read error: {str(e)}", []

    @staticmethod
    def _load_and_cache_file(file_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """Loads and caches sheet data, refreshing if file modification time changed"""
        current_mtime = os.path.getmtime(file_path)
        cached = _EXCEL_CACHE.get(file_path)

        if cached and cached["mtime"] == current_mtime:
            return cached["sheets"]

        sheets_data = {}
        xl = pd.ExcelFile(file_path)
        for sheet in xl.sheet_names:
            df = pd.read_excel(xl, sheet_name=sheet)
            df.columns = [str(col).strip() for col in df.columns]
            rows = []
            for _, row in df.iterrows():
                row_dict = {}
                for col in df.columns:
                    val = row[col]
                    if pd.isna(val):
                        row_dict[col] = ""
                    elif isinstance(val, (int, float)) and int(val) == val:
                        row_dict[col] = int(val)
                    else:
                        row_dict[col] = val
                rows.append(row_dict)
            sheets_data[sheet] = rows

        _EXCEL_CACHE[file_path] = {
            "mtime": current_mtime,
            "sheets": sheets_data
        }
        return sheets_data

    @staticmethod
    def get_schema(file_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """Returns sheets and their detected columns"""
        schema = {}
        if not os.path.exists(file_path):
            return schema

        try:
            sheets_data = ExcelConnector._load_and_cache_file(file_path)
            for sheet, rows in sheets_data.items():
                if rows:
                    schema[sheet] = [{"name": k, "type": type(v).__name__} for k, v in rows[0].items()]
                else:
                    schema[sheet] = []
        except Exception as e:
            print(f"Error getting schema for {file_path}: {e}")
        return schema

    @staticmethod
    def search_items(file_path: str, query: str, sheets_to_search: List[str] = None, max_results: int = 200) -> List[Dict[str, Any]]:
        """
        Searches across sheets in the Excel workbook for rows matching the query string.
        """
        results = []
        if not os.path.exists(file_path):
            return results

        try:
            sheets_data = ExcelConnector._load_and_cache_file(file_path)
            target_sheets = [s for s in sheets_data.keys() if sheets_to_search is None or s in sheets_to_search]
            query_lower = query.strip().lower()

            for sheet in target_sheets:
                rows = sheets_data[sheet]
                for row_dict in rows:
                    matched_fields = []
                    is_match = False

                    for col, val in row_dict.items():
                        val_str = str(val) if val is not None else ""
                        if query_lower and query_lower in val_str.lower():
                            is_match = True
                            matched_fields.append(col)
                        elif not query_lower:
                            is_match = True

                    if is_match:
                        results.append({
                            "source_type": "Excel Spreadsheet",
                            "container": sheet,
                            "file_path": file_path,
                            "file_name": os.path.basename(file_path),
                            "data": row_dict,
                            "matched_fields": matched_fields
                        })
                        if len(results) >= max_results:
                            return results
        except Exception as e:
            print(f"Error searching Excel workbook {file_path}: {e}")

        return results
