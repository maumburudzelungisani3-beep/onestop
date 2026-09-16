# Deploying DataBridge to Render (Backend) & Vercel (Frontend)

This guide walks you through deploying the **DataBridge** architecture:
* **Backend API (FastAPI + Python)** deployed on **Render**
* **Frontend Web Application (HTML / CSS / JS)** deployed on **Vercel**

---

## Architecture Overview

```
 [User / Mobile / Web]
          │
          ▼
   ┌───────────────┐
   │    Vercel     │  --> Hosts frontend (HTML, CSS, JS)
   │  (Frontend)   │  --> Proxies /api/* requests to Render via vercel.json
   └───────┬───────┘
           │
           ▼ /api/* (rewritten or direct)
   ┌───────────────┐
   │    Render     │  --> Runs FastAPI & Uvicorn Web Service (render.yaml)
   │   (Backend)   │  --> Queries SQLite, Excel, & provides API endpoints
   └───────────────┘
```

---

## Step 1: Push Project to GitHub

1. Initialize git in your project directory (if not already done):
   ```bash
   git init
   git add .
   git commit -m "Configure DataBridge for Render and Vercel deployment"
   ```

2. Create a new repository on [GitHub](https://github.com/new).

3. Link and push your code:
   ```bash
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git
   git push -u origin main
   ```

> **Note on Large Databases:**
> GitHub blocks files over 100MB. Files like `data/consolidated_lands.db` (500MB) are automatically ignored by `.gitignore`. For production cloud hosting with the full consolidated database, you can either:
> - Upload the `.db` file to Render Disks / S3 / R2, or
> - Use Git LFS (`git lfs track "*.db"`).

---

## Step 2: Deploy Backend to Render

1. Log in to [Render](https://render.com).
2. Click **New +** → **Web Service** (or **Blueprint** to use [`render.yaml`](file:///c:/Users/usr/Desktop/onestop/render.yaml)).
3. Connect your GitHub repository.
4. If setting up manually:
   * **Name:** `databridge-api` (or your choice)
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   * **Instance Type:** Free (or Starter for higher memory)
5. Click **Create Web Service**.
6. Once deployed, Render will provide a live URL such as:
   `https://databridge-api.onrender.com`

---

## Step 3: Deploy Frontend to Vercel

1. Log in to [Vercel](https://vercel.com).
2. Click **Add New...** → **Project**.
3. Import your GitHub repository.
4. In the configuration screen:
   * **Framework Preset:** `Other`
   * **Root Directory:** `./` (or `frontend`)
5. Update your Render URL:
   * Open [`vercel.json`](file:///c:/Users/usr/Desktop/onestop/vercel.json) in your project.
   * Replace `https://databridge-api.onrender.com` with your actual Render URL from Step 2.
   * Commit and push the change to GitHub, or let Vercel deploy.
6. Click **Deploy**.
7. Vercel will give you a live URL such as:
   `https://databridge.vercel.app`

---

## Step 4: Verification

1. Open your Vercel URL in your browser or phone.
2. The frontend will automatically route all `/api/*` searches and data requests to your Render backend.
3. Test a search (e.g. `smith` or `bearing`) to confirm data retrieval.
