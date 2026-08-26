from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class SourceFile(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=500_000)


class AnalyzeRequest(BaseModel):
    files: list[SourceFile] = Field(min_length=1, max_length=1000)


class Symbol(BaseModel):
    name: str
    kind: str
    line: int
    summary: str


class Node(BaseModel):
    id: str
    label: str
    kind: str = "file"  # "file", "module", or "external"
    parent: Optional[str] = None
    language: str
    summary: str
    symbols: list[Symbol] = Field(default_factory=list)
    file_count: int = 1
    size_bytes: int = 0
    children_ids: list[str] = Field(default_factory=list)


class Edge(BaseModel):
    source: str
    target: str
    kind: str = "imports"


class AnalyzeStats(BaseModel):
    file_count: int
    module_count: int
    external_count: int
    symbol_count: int
    edge_count: int


class AnalyzeResponse(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    overview: str
    insights: list[str]
    stats: AnalyzeStats


class RepositoryRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2_000)

class CheckoutRequest(RepositoryRequest):
    branch: str = Field(min_length=1, max_length=500)

class RepositoryInfo(BaseModel):
    url: str
    branches: list[str]

class CheckoutResponse(BaseModel):
    url: str
    branch: str
    commit: str
    cache_key: str
    status: str
