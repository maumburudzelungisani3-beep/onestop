import os
import subprocess
try:
    import pyodbc
except ImportError:
    pyodbc = None
import pandas as pd

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_data")
SAMPLE_ACCDB = os.path.join(SAMPLE_DIR, "warehouse_inventory.accdb")
SAMPLE_XLSX = os.path.join(SAMPLE_DIR, "procurement_catalog.xlsx")

def create_sample_excel():
    """Generates a rich multi-sheet Excel file with items, parts, and active orders"""
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    
    # Sheet 1: Vendor Catalog
    catalog_data = [
        {"PartNumber": "P-1001", "ItemName": "Precision Ball Bearing 608-2RS", "Category": "Mechanical", "Supplier": "SKF Industrial", "UnitCost": 4.75, "LeadTimeDays": 3, "StockStatus": "In Stock", "WarehouseBay": "A-01-2"},
        {"PartNumber": "P-1002", "ItemName": "Hydraulic Pressure Gauge 0-400 Bar", "Category": "Hydraulics", "Supplier": "WIKA Instruments", "UnitCost": 58.20, "LeadTimeDays": 5, "StockStatus": "Low Stock", "WarehouseBay": "B-04-1"},
        {"PartNumber": "P-1003", "ItemName": "Digital Multimeter Fluke 115", "Category": "Electronics", "Supplier": "Fluke Corp", "UnitCost": 239.00, "LeadTimeDays": 2, "StockStatus": "In Stock", "WarehouseBay": "E-10-3"},
        {"PartNumber": "P-1004", "ItemName": "Stainless Steel Flange DN50 PN16", "Category": "Piping", "Supplier": "Tubing Systems Ltd", "UnitCost": 32.50, "LeadTimeDays": 7, "StockStatus": "In Stock", "WarehouseBay": "C-02-4"},
        {"PartNumber": "P-1005", "ItemName": "Optical Laser Sensor 24V NPN", "Category": "Automation", "Supplier": "Omron Global", "UnitCost": 115.00, "LeadTimeDays": 4, "StockStatus": "In Stock", "WarehouseBay": "A-09-1"},
        {"PartNumber": "P-1006", "ItemName": "Solenoid Valve 3/2-way 24VDC", "Category": "Pneumatics", "Supplier": "Festo AG", "UnitCost": 84.90, "LeadTimeDays": 6, "StockStatus": "Backordered", "WarehouseBay": "B-06-2"},
        {"PartNumber": "P-1007", "ItemName": "Variable Frequency Drive 5.5kW", "Category": "Electrical", "Supplier": "Siemens Industry", "UnitCost": 620.00, "LeadTimeDays": 12, "StockStatus": "In Stock", "WarehouseBay": "D-01-5"},
        {"PartNumber": "P-1008", "ItemName": "Heavy Duty Caster Wheel 150mm", "Category": "Hardware", "Supplier": "Blickle Wheels", "UnitCost": 26.30, "LeadTimeDays": 2, "StockStatus": "In Stock", "WarehouseBay": "C-08-3"},
        {"PartNumber": "P-1009", "ItemName": "PTFE Thread Sealant Tape (Pack of 10)", "Category": "Consumables", "Supplier": "3M Direct", "UnitCost": 12.00, "LeadTimeDays": 1, "StockStatus": "In Stock", "WarehouseBay": "A-00-1"},
        {"PartNumber": "P-1010", "ItemName": "Linear Motion Rail HGR20 1000mm", "Category": "Machinery", "Supplier": "HIWIN Corp", "UnitCost": 145.00, "LeadTimeDays": 8, "StockStatus": "Low Stock", "WarehouseBay": "D-03-2"},
        {"PartNumber": "P-1011", "ItemName": "Solid State Relay 40A 240VAC", "Category": "Electrical", "Supplier": "Crydom Controls", "UnitCost": 38.50, "LeadTimeDays": 3, "StockStatus": "In Stock", "WarehouseBay": "E-05-1"},
        {"PartNumber": "P-1012", "ItemName": "Nitrile O-Ring Assortment Kit (419 pcs)", "Category": "Seals", "Supplier": "Parker Hannifin", "UnitCost": 29.90, "LeadTimeDays": 2, "StockStatus": "In Stock", "WarehouseBay": "A-03-3"}
    ]

    # Sheet 2: Purchase Orders
    orders_data = [
        {"PO_Number": "PO-2026-081", "ItemCode": "P-1007", "ItemTitle": "Variable Frequency Drive 5.5kW", "Quantity": 3, "TotalAmount": 1860.00, "Department": "Assembly Line 2", "Status": "Shipped", "EtaDate": "2026-09-18"},
        {"PO_Number": "PO-2026-082", "ItemCode": "P-1003", "ItemTitle": "Digital Multimeter Fluke 115", "Quantity": 2, "TotalAmount": 478.00, "Department": "Quality Assurance", "Status": "Delivered", "EtaDate": "2026-09-10"},
        {"PO_Number": "PO-2026-083", "ItemCode": "P-1006", "ItemTitle": "Solenoid Valve 3/2-way 24VDC", "Quantity": 10, "TotalAmount": 849.00, "Department": "Pneumatics Lab", "Status": "Awaiting Approval", "EtaDate": "2026-09-25"},
        {"PO_Number": "PO-2026-084", "ItemCode": "P-1001", "ItemTitle": "Precision Ball Bearing 608-2RS", "Quantity": 150, "TotalAmount": 712.50, "Department": "Maintenance", "Status": "Delivered", "EtaDate": "2026-09-08"},
        {"PO_Number": "PO-2026-085", "ItemCode": "P-1010", "ItemTitle": "Linear Motion Rail HGR20", "Quantity": 4, "TotalAmount": 580.00, "Department": "CNC Workshop", "Status": "Processing", "EtaDate": "2026-09-20"}
    ]

    with pd.ExcelWriter(SAMPLE_XLSX, engine='openpyxl') as writer:
        pd.DataFrame(catalog_data).to_excel(writer, sheet_name='VendorCatalog', index=False)
        pd.DataFrame(orders_data).to_excel(writer, sheet_name='ActiveOrders', index=False)

    return SAMPLE_XLSX

def create_sample_accdb():
    """Generates an Access database with warehouse inventory and machinery assets"""
    if pyodbc is None or os.name != 'nt':
        return None
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    if os.path.exists(SAMPLE_ACCDB):
        try:
            os.remove(SAMPLE_ACCDB)
        except Exception:
            return SAMPLE_ACCDB

    # Step 1: Create the empty accdb using our dedicated powershell helper
    abs_path = os.path.abspath(SAMPLE_ACCDB)
    helper_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "create_accdb.ps1")
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", helper_script, "-FilePath", abs_path], check=False)
    
    if not os.path.exists(abs_path):
        raise RuntimeError(f"Could not create sample Access database at {abs_path}")

    # Step 2: Populate tables via ODBC
    conn_str = f"Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={abs_path};"
    with pyodbc.connect(conn_str, autocommit=True) as conn:
        cursor = conn.cursor()
        
        # Table: WarehouseItems
        cursor.execute("""
            CREATE TABLE WarehouseItems (
                ItemID INT PRIMARY KEY,
                ItemCode VARCHAR(50),
                ItemDescription VARCHAR(150),
                Category VARCHAR(50),
                StockQuantity INT,
                ReorderLevel INT,
                LocationBin VARCHAR(50),
                UnitValue DOUBLE,
                Barcode VARCHAR(50)
            )
        """)
        
        items = [
            (2001, "WH-BEAR-01", "Deep Groove Ball Bearing 6205-2Z", "Bearings & Power Transmission", 340, 50, "Rack 3 - Shelf B", 18.50, "847291038201"),
            (2002, "WH-PUMP-44", "Submersible Water Pump 1.5HP Stainless", "Fluid Handling", 15, 5, "Rack 1 - Floor Section", 310.00, "847291038202"),
            (2003, "WH-ELEC-88", "Siemens Industrial Contactor 3P 24V 32A", "Electrical Controls", 62, 20, "Cabinet E - Row 2", 74.50, "847291038203"),
            (2004, "WH-FAST-12", "Galvanized Hex Head Bolt M12 x 80mm (Box 100)", "Fasteners & Fixings", 85, 30, "Aisle 4 - Bin 112", 42.00, "847291038204"),
            (2005, "WH-SEAL-09", "High Temp Viton Gasket Sheet 2mm", "Sealing Solutions", 28, 10, "Cabinet S - Drawer 4", 89.00, "847291038205"),
            (2006, "WH-SENS-31", "Inductive Proximity Sensor M18 PNP NO", "Sensors & Instrumentation", 110, 25, "Cabinet E - Row 5", 35.80, "847291038206"),
            (2007, "WH-VALV-77", "High Pressure Ball Valve 1 Inch SS316", "Piping & Valves", 44, 15, "Rack 2 - Shelf D", 95.00, "847291038207"),
            (2008, "WH-TOOL-05", "Carbide End Mill Cutter Set 4-Flute 6-12mm", "Cutting Tools", 32, 8, "Tool Crib - Locker 7", 165.00, "847291038208"),
            (2009, "WH-PNEU-18", "Compact Air Cylinder 40mm Bore 50mm Stroke", "Pneumatics", 53, 15, "Rack 5 - Shelf A", 68.00, "847291038209"),
            (2010, "WH-SAFE-02", "3M Half Facepiece Reusable Respirator L", "Safety & PPE", 120, 40, "PPE Supply Room", 24.50, "847291038210")
        ]
        
        for item in items:
            cursor.execute("INSERT INTO WarehouseItems VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", item)

        # Table: MachineAssets
        cursor.execute("""
            CREATE TABLE MachineAssets (
                AssetTag VARCHAR(50) PRIMARY KEY,
                MachineName VARCHAR(100),
                Department VARCHAR(50),
                Manufacturer VARCHAR(80),
                InstallYear INT,
                OperationalStatus VARCHAR(50),
                MaintenanceContact VARCHAR(80)
            )
        """)

        assets = [
            ("AST-CNC-001", "5-Axis CNC Milling Center Haas VF-4", "Precision Machining", "Haas Automation", 2021, "Operational", "John Miller (Ext 401)"),
            ("AST-LAT-002", "CNC Lathe Doosan Puma 2600", "Turning Dept", "DN Solutions", 2023, "Operational", "Sarah Chen (Ext 402)"),
            ("AST-WLD-003", "Robotic MIG Welding Station", "Fabrication", "KUKA Robotics", 2022, "Scheduled Maintenance", "Dave Roberts (Ext 415)"),
            ("AST-CMP-004", "Atlas Copco Rotary Screw Air Compressor GA37", "Facility Utilities", "Atlas Copco", 2020, "Operational", "Utilities Team (Ext 300)"),
            ("AST-LSR-005", "Trumpf Fiber Laser Cutting System 4kW", "Sheet Metal Works", "Trumpf GmbH", 2024, "Operational", "Alex Vance (Ext 420)")
        ]

        for asset in assets:
            cursor.execute("INSERT INTO MachineAssets VALUES (?, ?, ?, ?, ?, ?, ?)", asset)

    return SAMPLE_ACCDB

def seed_demo_data():
    """Generates both demo files and registers them as default sources if none exist"""
    excel_path = create_sample_excel()
    accdb_path = create_sample_accdb()

    from backend.config import AppConfig, DataSource
    existing = AppConfig.get_sources()

    # Add Access DB source if created
    if accdb_path and os.path.exists(accdb_path):
        AppConfig.add_source(DataSource(
            name="Warehouse Central Access DB",
            type="access",
            path=os.path.abspath(accdb_path),
            description="Local network warehouse inventory and machine assets (.accdb)",
            enabled=True,
            status="connected",
            cached_tables=["WarehouseItems", "MachineAssets"]
        ))

    # Add Excel Workbook source
    AppConfig.add_source(DataSource(
        name="Procurement & Orders Excel",
        type="excel",
        path=os.path.abspath(excel_path),
        description="Local network procurement vendor catalog and purchase orders (.xlsx)",
        enabled=True,
        status="connected",
        cached_tables=["VendorCatalog", "ActiveOrders"]
    ))

    return {
        "excel_path": os.path.abspath(excel_path),
        "accdb_path": os.path.abspath(accdb_path) if accdb_path else None
    }

if __name__ == "__main__":
    res = seed_demo_data()
    print("Demo data generated successfully:", res)
