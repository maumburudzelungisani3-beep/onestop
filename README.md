# 🌐 DataBridge — Unified Access DB & Excel Network Search

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![SQLite](https://img.shields.io/badge/SQLite-530k_Rows-003B57.svg?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Simultaneously search, query, and inspect records across local network Microsoft Access databases (`.accdb`, `.mdb`), Excel workbooks (`.xlsx`, `.xls`), and a high-performance consolidated local SQLite replica.**

---

## 🚀 Key Features

* **⚡ Ultra-Fast Unified Search:** Search simultaneously across multiple remote network files and local replicas in under 5 milliseconds.
* **🛡️ Zero Network File-Locks:** Extracts and consolidates remote network databases into a local SQLite replica with Full-Text Search (FTS5) to prevent multi-user locking issues on network shares.
* **📱 Fully Responsive Mobile Interface:** 
  * Responsive layout tailored for desktop, tablets, and smartphones.
  * Search results dynamically adapt into **high-density mobile cards** on screens under 680px.
  * Full-screen mobile modals for database browsing and SQL exploration.
* **💻 Interactive SQL Console:** Run live `SELECT` queries with pagination, column sorting, and instant CSV export against the 530,000+ consolidated record database.
* **🔍 Automatic Network Scanner:** Discover all `.accdb`, `.mdb`, and `.xlsx` files across any network folder or share with a single click.
* **📊 Deep Record Inspection:** Slide-out detail drawer displaying all raw attributes, farm origin lineage ("↳ Taken from"), parent diagram numbers, and beneficiary profiles.
* **☁️ Cloud & Container Ready:** Native deployment configurations for **Render** (FastAPI backend), **Vercel** (modern frontend), and **Docker Compose**.

---

## 🏗️ Architecture

```
                       ┌───────────────────────────────┐
                       │  Client (Browser / Mobile)    │
                       └───────────────┬───────────────┘
                                       │ HTTP / JSON
                                       ▼
                       ┌───────────────────────────────┐
                       │   FastAPI Web Server (:8000)   │
                       └───────┬───────────────┬───────┘
                               │               │
            ┌──────────────────┴──┐         ┌──┴──────────────────┐
            ▼                     ▼         ▼                     ▼
┌───────────────────────┐ ┌───────────────┐ ┌───────────────────┐ ┌───────────────────┐
│ Consolidated SQLite   │ │ MS Access DB  │ │ Excel Workbooks   │ │ Network Share     │
│ (530k Rows, FTS5)     │ │ (.accdb/.mdb) │ │ (.xlsx/.xls)      │ │ Scanner (UNC)     │
└───────────────────────┘ └───────────────┘ └───────────────────┘ └───────────────────┘
```

---

## 🛠️ Tech Stack

* **Backend:** Python 3.10+, FastAPI, Uvicorn, Pandas, OpenPyXL, XLRD, PyODBC (Windows).
* **Frontend:** Modern Vanilla JavaScript (ES6+), Semantic HTML5, Custom CSS Design System (CSS variables, glassmorphism, responsive cards).
* **Storage:** SQLite 3 (WAL mode enabled, FTS5 full-text indexing).
* **Deployment:** Docker, Docker Compose, Render Blueprint (`render.yaml`), Vercel (`vercel.json`).

---

## ⚡ Quick Start

### 1. One-Click Windows Start
Simply double-click:
```cmd
start_databridge.bat
```
The script will detect your Python environment, determine your local network IPv4 address, and launch the server.

### 2. Manual Start
```bash
# Clone the repository
git clone https://github.com/<your-username>/databridge.git
cd databridge

# Install dependencies
pip install -r requirements.txt

# Start the application
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
Open your browser at:
* **Local:** [http://localhost:8000](http://localhost:8000)
* **Mobile / LAN:** `http://<YOUR-IP>:8000`

### 3. Docker Start
```bash
docker compose up -d --build
```

---

## 🌐 Deploy to Render & Vercel

* **Render (Backend API):** Deploy using [`render.yaml`](render.yaml) as a Web Service.
* **Vercel (Frontend UI):** Deploy the repository directly with [`vercel.json`](vercel.json) to proxy API requests to Render.
* Read the complete instructions in [**`DEPLOYMENT_GUIDE.md`**](DEPLOYMENT_GUIDE.md).

---

## 📁 Repository Structure

```
├── backend/
│   ├── connectors/          # Connectors for Access, Excel, and SQLite
│   │   ├── access_connector.py
│   │   ├── excel_connector.py
│   │   └── sqlite_connector.py
│   ├── config.py            # Source registry & configuration manager
│   ├── demo_data.py         # Sample data generator
│   ├── etl_pipeline.py      # Background ETL replication pipeline
│   ├── main.py              # FastAPI application & endpoints
│   └── search_engine.py     # Multi-threaded federated search engine
├── frontend/
│   ├── css/
│   │   └── style.css        # Responsive design system & mobile cards
│   ├── js/
│   │   └── app.js           # Frontend controller & search handler
│   ├── index.html           # Main user interface
│   └── vercel.json          # Frontend deployment config
├── data/                    # Local SQLite database & cache
├── sample_data/             # Demo databases & workbooks
├── Dockerfile               # Production container image
├── docker-compose.yml       # Container orchestration
├── render.yaml              # Render blueprint config
├── vercel.json              # Root Vercel deployment config
├── requirements.txt         # Python dependencies
├── start_databridge.bat     # Windows one-click launcher
├── DEPLOYMENT_GUIDE.md      # Deployment manual
└── README.md                # Project documentation
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
