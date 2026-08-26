from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import analyze
from .models import AnalyzeRequest, AnalyzeResponse
from .models import CheckoutRequest, CheckoutResponse, RepositoryInfo, RepositoryRequest
from .git_service import checkout_latest, list_branches

app = FastAPI(title="AI Code Dependency Mapper", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/repositories/branches", response_model=RepositoryInfo)
def repository_branches(request: RepositoryRequest):
    url, branches = list_branches(request.url)
    return RepositoryInfo(url=url, branches=branches)

@app.post("/api/repositories/checkout", response_model=CheckoutResponse)
def repository_checkout(request: CheckoutRequest):
    key, branch, commit = checkout_latest(request.url, request.branch)
    return CheckoutResponse(url=request.url.strip(), branch=branch, commit=commit, cache_key=key, status="Cached latest branch commit. No files have been analyzed.")


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_codebase(request: AnalyzeRequest):
    if sum(len(item.content) for item in request.files) > 5_000_000:
        raise HTTPException(status_code=413, detail="Source selection exceeds the 5 MB analysis limit.")
    nodes, edges, overview, insights, stats = analyze(request.files)
    return AnalyzeResponse(nodes=nodes, edges=edges, overview=overview, insights=insights, stats=stats)
