import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

from backend.config import AppConfig, DataSource
from backend.connectors.access_connector import AccessConnector
from backend.connectors.excel_connector import ExcelConnector
from backend.connectors.sqlite_connector import SQLiteConnector

class SearchEngine:
    @staticmethod
    def _search_single_source(source: DataSource, query: str, max_per_source: int = 150) -> Dict[str, Any]:
        """Worker function to search one source safely"""
        start = time.perf_counter()
        records = []
        status = "ok"
        err_msg = None

        try:
            if source.type.lower() == "access":
                records = AccessConnector.search_items(
                    file_path=source.path,
                    query=query,
                    tables_to_search=source.tables_or_sheets,
                    max_results=max_per_source,
                    password=source.password
                )
            elif source.type.lower() == "excel":
                records = ExcelConnector.search_items(
                    file_path=source.path,
                    query=query,
                    sheets_to_search=source.tables_or_sheets,
                    max_results=max_per_source
                )
            elif source.type.lower() == "sqlite":
                records = SQLiteConnector.search_items(
                    db_path=source.path,
                    query=query,
                    max_results=max_per_source
                )
            else:
                err_msg = f"Unsupported source type: {source.type}"
                status = "error"
        except Exception as e:
            status = "error"
            err_msg = str(e)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        
        # Tag each record with the source ID and source custom name
        for r in records:
            r["source_id"] = source.id
            r["source_name"] = source.name

        return {
            "source_id": source.id,
            "source_name": source.name,
            "source_type": source.type,
            "status": status,
            "error_message": err_msg,
            "duration_ms": duration_ms,
            "count": len(records),
            "records": records
        }

    @staticmethod
    def search(
        query: str,
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Executes concurrent search across all active data sources.
        """
        overall_start = time.perf_counter()
        all_sources = AppConfig.get_sources()

        # Filter active sources
        target_sources = [s for s in all_sources if s.enabled]

        if source_id and source_id != "all":
            target_sources = [s for s in target_sources if s.id == source_id]

        if source_type and source_type != "all":
            st_low = source_type.lower()
            if st_low in ["access", "excel"]:
                target_sources = [s for s in target_sources if s.type.lower() == st_low or s.type.lower() == "sqlite"]
            else:
                target_sources = [s for s in target_sources if s.type.lower() == st_low]

        all_records = []
        source_reports = []

        if target_sources:
            # Run concurrently across network sources with 6s timeout threshold
            with ThreadPoolExecutor(max_workers=min(10, len(target_sources))) as executor:
                futures = {
                    executor.submit(SearchEngine._search_single_source, src, query): src
                    for src in target_sources
                }
                try:
                    for f in as_completed(futures, timeout=6.0):
                        src = futures[f]
                        try:
                            res = f.result()
                            source_reports.append({
                                "source_id": res["source_id"],
                                "source_name": res["source_name"],
                                "source_type": res["source_type"],
                                "status": res["status"],
                                "error_message": res["error_message"],
                                "duration_ms": res["duration_ms"],
                                "count": res["count"]
                            })
                            all_records.extend(res["records"])
                        except Exception as e:
                            source_reports.append({
                                "source_id": src.id,
                                "source_name": src.name,
                                "source_type": src.type,
                                "status": "error",
                                "error_message": str(e),
                                "duration_ms": 6000,
                                "count": 0
                            })
                except TimeoutError:
                    # Collect unfinished sources as timed out
                    for f, src in futures.items():
                        if not f.done():
                            source_reports.append({
                                "source_id": src.id,
                                "source_name": src.name,
                                "source_type": src.type,
                                "status": "timeout",
                                "error_message": "Network share response delayed (>6s)",
                                "duration_ms": 6000,
                                "count": 0
                            })

        total_matches = len(all_records)
        
        # Slice for pagination
        paginated_records = all_records[offset: offset + limit]

        total_duration_ms = round((time.perf_counter() - overall_start) * 1000, 2)

        return {
            "query": query,
            "total_matches": total_matches,
            "returned_count": len(paginated_records),
            "limit": limit,
            "offset": offset,
            "duration_ms": total_duration_ms,
            "source_reports": source_reports,
            "results": paginated_records
        }
