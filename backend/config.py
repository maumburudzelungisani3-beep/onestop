import os
import json
import uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "sources.json")

def resolve_source_path(p: str) -> str:
    if not p:
        return p
    if os.path.exists(p):
        return p
    candidate = os.path.normpath(os.path.join(BASE_DIR, p))
    if os.path.exists(candidate):
        return candidate
    for marker in ["onestop\\", "onestop/"]:
        if marker in p.lower():
            idx = p.lower().find(marker)
            subpath = p[idx + len(marker):]
            candidate2 = os.path.normpath(os.path.join(BASE_DIR, subpath))
            if os.path.exists(candidate2):
                return candidate2
    return p

class DataSource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: str  # "access", "excel", or "sqlite"
    path: str  # Local or UNC path, e.g. \\server\share\file.accdb or C:\data\file.xlsx
    description: Optional[str] = ""
    enabled: bool = True
    tables_or_sheets: Optional[List[str]] = None  # None means all, or list of specific tables/sheets
    last_connected: Optional[str] = None
    status: Optional[str] = "unknown"  # "connected", "offline", "error", "unknown"
    error_message: Optional[str] = None
    cached_tables: Optional[List[str]] = None
    password: Optional[str] = None

class AppConfig:
    @staticmethod
    def get_sources() -> List[DataSource]:
        if not os.path.exists(CONFIG_FILE):
            return []
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                sources = [DataSource(**item) for item in data]
                for s in sources:
                    s.path = resolve_source_path(s.path)
                return sources
        except Exception as e:
            print(f"Error loading sources config: {e}")
            return []

    @staticmethod
    def save_sources(sources: List[DataSource]):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump([s.model_dump() for s in sources], f, indent=2)

    @staticmethod
    def add_source(source: DataSource) -> DataSource:
        sources = AppConfig.get_sources()
        # Check if already exists by path
        for s in sources:
            if os.path.normpath(s.path.strip().lower()) == os.path.normpath(source.path.strip().lower()):
                s.name = source.name
                s.description = source.description
                s.enabled = source.enabled
                s.tables_or_sheets = source.tables_or_sheets
                AppConfig.save_sources(sources)
                return s
        sources.append(source)
        AppConfig.save_sources(sources)
        return source

    @staticmethod
    def update_source(source_id: str, updates: Dict[str, Any]) -> Optional[DataSource]:
        sources = AppConfig.get_sources()
        for i, s in enumerate(sources):
            if s.id == source_id:
                updated_data = s.model_dump()
                updated_data.update(updates)
                sources[i] = DataSource(**updated_data)
                AppConfig.save_sources(sources)
                return sources[i]
        return None

    @staticmethod
    def delete_source(source_id: str) -> bool:
        sources = AppConfig.get_sources()
        filtered = [s for s in sources if s.id != source_id]
        if len(filtered) != len(sources):
            AppConfig.save_sources(filtered)
            return True
        return False
