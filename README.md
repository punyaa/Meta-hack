# SignalForge

SignalForge turns messy technical slide photos, screenshots, and optional speaker notes into a source-backed visual field report and a buildable prototype blueprint.

The MVP combines:

- **Muse Spark 1.3** for per-image understanding and collection-level planning.
- **SAM 3.1** for pixel-accurate projection-screen or whiteboard masks.
- **OpenCV** for perspective correction and readability enhancement.
- Local perceptual hashing to remove duplicate shots before model calls.

The result uses a magazine-like structure rather than a dashboard:

1. **Photo essay** — original and repaired captures with editorial captions.
2. **What Muse learned** — cross-image themes plus lessons from notes or a transcript.
3. **Prototype blueprint** — problem, intended user, MVP scope, architecture, backlog, and first task.
4. **Evidence appendix** — source ids, support labels, missing context, and conflicts.

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

## Deploy

The repo ships a `Dockerfile` (works on Render, Railway, Fly.io, Cloud Run, Hugging Face Spaces) plus a `render.yaml` Blueprint. On Render's free tier:

1. Push this repo to GitHub.
2. Create a new **Blueprint** from the repo; Render reads `render.yaml`.
3. Paste your key when prompted for `MODEL_API_KEY`.
4. Open the service URL; `/api/health` should report `"demo_mode": false`.

Uploads live on the container's ephemeral disk: old run images disappear on restart or redeploy, so treat share links as short-lived unless you add object storage.

## Deploy to Vercel

SignalForge ships a serverless flow (v2 API) for Vercel's Hobby tier:

1. Push this repo to GitHub.
2. In Vercel, import the repo. The Python framework preset auto-detects FastAPI via `tool.vercel.entrypoint` in `pyproject.toml`; no `vercel.json` needed.
3. Create a Blob store (Storage tab) and connect it to the project. Vercel adds `BLOB_READ_WRITE_TOKEN` automatically; use a **public** store so result images render.
4. Set environment variables: `MODEL_API_KEY`, `STORAGE_BACKEND=blob`, `JOB_BACKEND=blob`.
5. For accounts and history: create a Vercel Postgres database, connect it, and set `POSTGRES_URL` (pooled) plus a generated `SESSION_SECRET`. For Drive import, set `GOOGLE_API_KEY`.
6. Deploy and open `/api/health`: `"flow"` should be `"v2"`, `"demo_mode"` false with a key set.

How v2 differs: the browser compresses each photo (max 1600px JPEG, under the 4.5MB request cap), uploads images one per request, then each status poll advances exactly one pipeline step (dedupe → one image read → one correction → final plan), with job state in Blob. No background tasks, no local disk. Uploads accept JPG, PNG, and WebP in this flow (no HEIC: browsers can't reliably decode it for compression).

Test the v2 flow locally without Vercel: set `WEB_FLOW=v2` in `.env` and restart. Uploads stay on local disk and jobs stay in memory.

After pulling, run `uv sync` once (needs network): it installs the new `vercel-blob` and `psycopg` dependencies and refreshes `uv.lock`.

## Accounts, Library, and Drive import

When `POSTGRES_URL` is set, the app requires an account: `/signup` and `/login` (email + password, scrypt-hashed, 30-day signed cookie sessions). Without it, the app stays open and unrecorded, exactly as before.

- **Library** (`/library`): every v2 project is recorded — goal, status, photos, and notes. Each card has **Photos** and **Notes** tabs, and finished projects reopen the full report.
- **Drive import**: paste a public Google Drive folder link in the v2 form. Photos import as evidence (20 MB cap each, remaining slots only); Google Docs, Slides, and Sheets export into the notes (10 docs max, truncated). Needs a `GOOGLE_API_KEY` with the Drive API enabled; folders must be shared as "Anyone with the link".

## How Muse Spark works in this repository

`signalforge/services/muse.py` is the only Model API boundary. It uses the OpenAI-compatible Meta endpoint:

```python
client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.environ["MODEL_API_KEY"],
)
```

SignalForge makes two schema-constrained Muse calls:

1. `analyze_image()` sends one retained image and parses the response directly into `ImageAnalysis`.
2. `build_plan()` sends the validated image analyses and optional notes/transcript, then parses the response into `CollectionPlan`.

Pydantic schemas in `signalforge/models.py` make the response contract explicit. `pipeline.py` removes duplicate captures before model calls, sends corrected images back to Muse when available, and rejects evidence ids that do not belong to the current project.

The browser submits notes through the optional `context_notes` form field. Muse must keep insights found only in those notes inside `notes_takeaways`; they cannot be presented as visually supported claims.

## Test

```bash
uv run pytest
```

The suite covers:

- perspective geometry and minimum surface size;
- binary mask resizing;
- duplicate selection and sharpness preference;
- live/demo configuration;
- upload rejection before filesystem mutation;
- demo pipeline behavior and progress reporting;
- Muse image request construction without a network call;
- transcript propagation into the synthesis prompt;
- evidence-id sanitization across themes, actions, and the build blueprint.

## MVP flow

1. Upload 1–15 JPG, PNG, WebP, HEIC, or HEIF images.
2. State one goal.
3. Near-duplicates are grouped and the sharpest image is retained.
4. Muse classifies and reads each retained image.
5. SAM segments a photographed screen or board.
6. OpenCV estimates its quadrilateral and flattens the image.
7. Muse re-reads corrected images and reasons across the retained collection.
8. Optional notes or a transcript are summarized separately from visual evidence.
9. Muse compiles the photo essay, themes, blueprint, and build sequence.
10. Every supported theme or action refers to a real image id.

## Important limitation

SAM identifies visible pixels. It does not reconstruct text or corners fully hidden by a person. SignalForge falls back to local boundary detection when a SAM mask is unavailable; a manual four-corner correction control is the next reliability feature.

## Data handling

Development runs are written under `data/runs/`, which is ignored by Git. In live mode, retained images are sent to Meta Model API for Muse and SAM processing. Before public deployment, add an automated retention job and private object storage; do not serve uploaded media from an unrestricted public bucket.
