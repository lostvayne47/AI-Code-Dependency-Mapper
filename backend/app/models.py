from pydantic import BaseModel, Field


class SourceFile(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=500_000)


class AnalyzeRequest(BaseModel):
    files: list[SourceFile] = Field(min_length=1, max_length=400)


class Symbol(BaseModel):
    name: str
    kind: str
    line: int
    summary: str


class Node(BaseModel):
    id: str
    label: str
    language: str
    summary: str
    symbols: list[Symbol]


class Edge(BaseModel):
    source: str
    target: str
    kind: str = "imports"


class AnalyzeResponse(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    overview: str
    insights: list[str]

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
