# AI Code Dependency Mapper

A local-first developer tool for rapidly understanding an unfamiliar codebase. It accepts a selected project folder, extracts top-level functions and classes, resolves internal imports, and renders an interactive dependency graph.

## MVP capabilities

- Python AST analysis for imports, functions, async functions, and classes
- JavaScript/TypeScript/React import and top-level declaration extraction
- Interactive dependency graph with file-level symbol inspection
- Automatic ignoring of system and vendor paths (`node_modules`, `.venv`, `dist`, build artifacts, `.gitignore` rules)
- No source is uploaded to a third party by the UI; it is sent only to the local FastAPI service

## Run it

Start the backend (Python 3.11+ recommended):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In another terminal, start the dashboard (Node 20+):

```powershell
cd frontend
npm install
npm run dev
```

Open the URL Vite reports, select a project directory, or use **Try demo**.

## Next steps

The current version intentionally uses local, deterministic summaries. Add OpenAI-powered summaries after the dependency graph is trusted, so generated explanations are grounded in extracted symbols and imports.
