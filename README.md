# SignalForge

SignalForge turns a folder of messy technical slide photos and one goal into an evidence-backed **now / next / later** action plan.

The MVP combines:

- **Muse Spark 1.3** for per-image understanding and collection-level planning.
- **SAM 3.1** for pixel-accurate projection-screen or whiteboard masks.
- **OpenCV** for perspective correction and readability enhancement.
- Local perceptual hashing to remove duplicate shots before model calls.

## Run locally

This repository is pinned to Python 3.12 and uses `uv`.

```bash
uv sync
cp .env.example .env
uv run uvicorn signalforge.main:app --reload
```

Open <http://127.0.0.1:8000>.

Without a key, SignalForge automatically runs in demo mode: uploads, deduplication, local perspective correction, and the interface work, while model analysis is clearly labelled as simulated.

## Enable Muse and SAM

Create `.env` and set:

```dotenv
MODEL_API_KEY=your_model_api_key
SIGNALFORGE_DEMO_MODE=false
```

The Muse Code CLI login is stored in macOS Keychain and is separate from the environment variable used by this web application. Never commit `.env`.

## Test

```bash
uv run pytest
```

## MVP flow

1. Upload 1–15 JPG, PNG, WebP, HEIC, or HEIF images.
2. State one goal.
3. Near-duplicates are grouped and the sharpest image is retained.
4. Muse classifies and reads each retained image.
5. SAM segments a photographed screen or board.
6. OpenCV estimates its quadrilateral and flattens the image.
7. Muse re-reads corrected images and compiles a grounded action plan.
8. Every supported action refers to a real image id.

## Important limitation

SAM identifies visible pixels. It does not reconstruct text or corners fully hidden by a person. SignalForge falls back to local boundary detection when a SAM mask is unavailable; a manual four-corner correction control is the next reliability feature.

## Data handling

Development runs are written under `data/runs/`, which is ignored by Git. In live mode, retained images are sent to Meta Model API for Muse and SAM processing. Before public deployment, add an automated retention job and private object storage; do not serve uploaded media from an unrestricted public bucket.
