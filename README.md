# Evidence-Based Research Paper Assistant

> **Every sentence in the output is traceable to a specific page and paragraph of an uploaded source.**
> If evidence is missing, the system flags it for your input — it never guesses.

---

## Quick Start

### 1. Set up API keys

```bash
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY and OPENAI_API_KEY
```

Both keys are required. The backend will exit immediately at startup if either is missing.

### 2. Run

```bash
docker compose up
```

Then open **http://localhost:3000**

---

## How it works

| Stage | What happens |
|---|---|
| **1 — Upload** | PDFs/TXT/DOCX parsed into blocks using PyMuPDF bounding-box detection (handles two-column layouts). Each block gets a stable `p{page}_b{block}` ID. |
| **2 — Extract** | Claude analyzes each paper → strict JSON with every claim anchored to a page + paragraph ID. Invalid claims are retried once, then dropped and logged. |
| **3 — Embed** | OpenAI `text-embedding-3-small` embeds all claims into a local ChromaDB index. |
| **4 — Analyze project** | Same extraction applied to your project file. Missing fields surface as form prompts, never silently inferred. |
| **5 — Compare** | For each project claim, top-5 similar literature claims are retrieved; Claude classifies each as matching / partial / not found. Batched 10 claims per call. |
| **6a — Generate** | Claude drafts the paper with inline `[CLAIM:id]` citations for every sentence. |
| **6b — Verify** | GPT-4o-mini (separate provider) independently checks each sentence. Fails → sentence dropped and logged, never reworded. |
| **7 — Output** | DOCX with sections, mandatory bibliography (only cited papers), transparency report appendix. |

### Why two different AI providers?

Claude writes the paper. GPT-4o-mini checks it. Using the same model for both risks it rationalizing its own hallucinated output as self-consistent. Two different systems catching each other's mistakes is stronger than self-verification.

---

## Limits (MVP scope)

- Max 15 literature files per session
- Max 1 project file per session
- Max 20MB per file
- Accepted formats: PDF, TXT, DOCX
- Single-session (no multi-user auth)
- Output: Markdown preview + DOCX download

---

## File structure

```
Re_Assist/
├── backend/          # FastAPI + Python pipeline
├── frontend/         # Next.js + Tailwind SPA
├── data/             # SQLite DB + ChromaDB (created on first run)
├── docker-compose.yml
└── .env.example
```

---

## Development (without Docker)

**Backend:**
```bash
cd backend
pip install -r requirements.txt
cp ../.env .env
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev  # http://localhost:3000
```

---

## Transparency report

After every run, the app generates:
- Count of papers analyzed, claims extracted, sentences generated/verified/rejected
- Full log of rejected sentences with reasons
- API usage breakdown by stage with estimated cost (USD)

This report is embedded in the DOCX and viewable in the UI alongside the paper.
