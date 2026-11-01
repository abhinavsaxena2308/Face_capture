# Face Finder

Face Finder is a local, single-user face-based photo search tool. The Angular app uploads a reference photo and a selected folder to a FastAPI service on the same computer. A CPU worker detects faces, compares face embeddings, retains matched copies, and records the match-to-source mapping in PostgreSQL.

## Projects

- [`frontend`](./frontend) — Angular 21 interface. It runs at `http://127.0.0.1:4300`.
- [`backend`](./backend) — FastAPI API, PostgreSQL persistence, local ingest/match storage, and CPU worker. It runs at `http://127.0.0.1:8000`.

## Requirements

- Node.js 24+ and npm
- Python 3.12+
- A running PostgreSQL database

Docker is not used.

## First-time setup

1. Create a PostgreSQL database named `facefinder`:

   ```sql
   CREATE DATABASE facefinder;
   ```

2. Copy [`backend/.env.example`](./backend/.env.example) to `backend/.env` and set `DATABASE_URL` with your PostgreSQL username and password.

3. Create and install the backend virtual environment:

   ```powershell
   cd backend
   py -3.12 -m venv .venv
   .\.venv\Scripts\python -m pip install -e .
   .\.venv\Scripts\python -m alembic upgrade head
   cd ..
   ```

4. Download and verify the pinned local models:

   ```powershell
   .\backend\.venv\Scripts\python .\scripts\fetch_models.py
   ```

5. Start each service in its own PowerShell window:

   ```powershell
   .\scripts\start-api.ps1
   .\scripts\start-worker.ps1
   cd frontend
   npm install
   npm start -- --host 127.0.0.1 --port 4300
   ```

Open `http://127.0.0.1:4300` in Chrome or Edge. Folder picking relies on Chromium’s folder-selection support.

## Data lifecycle

Collection images are copied temporarily under `APP_DATA_DIR/ingest` while a job is running. After the worker completes, each match is copied to `APP_DATA_DIR/matches/<search-id>` and the corresponding `matches` row maps the match ID to its `asset_id`, original relative path, result score, thumbnail, face box, and stored copy path. Temporary uploads and target face embeddings are then deleted.

The app does not upload images to a cloud service. Deleting a search removes its database records, reference crop, matched copies, and thumbnails.

Face embeddings are stored as PostgreSQL JSONB during a scan and compared with exact cosine similarity in NumPy. The temporary target embeddings are deleted when matching completes; PostgreSQL extensions are not required.

## Model choice

The backend uses OpenCV’s CPU-compatible YuNet detector and SFace recognizer. Model files, source URLs, SHA-256 checksums, and license metadata are pinned in [`backend/models.manifest.json`](./backend/models.manifest.json). Review the relevant model licenses before changing deployment context.
