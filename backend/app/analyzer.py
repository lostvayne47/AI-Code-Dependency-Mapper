"""Safe, lightweight multi-language source analysis.

Python is parsed with the standard AST. JavaScript/TypeScript extraction is
intentionally regex-based to avoid executing or evaluating uploaded source.
"""
from __future__ import annotations

import ast
import os
import re
from collections import Counter
from pathlib import PurePosixPath

from .models import Edge, Node, SourceFile, Symbol

LANGUAGES = {".py": "Python", ".js": "JavaScript", ".jsx": "React", ".ts": "TypeScript", ".tsx": "React/TypeScript", ".json": "JSON"}
IGNORE_DIRS = {
    "node_modules", ".venv", "venv", "env", ".env", ".git", "dist", "build",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".next", "out", "coverage", ".idea", ".vscode"
}
IMPORT_RE = re.compile(r"(?:import\s+(?:.+?\s+from\s+)?|export\s+.+?\s+from\s+|require\s*\()\s*['\"]([^'\"]+)['\"]")
JS_SYMBOL_RE = re.compile(r"(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)|(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")


def _path(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/"))).lstrip("/")


def _is_ignored(path: str) -> bool:
    parts = set(PurePosixPath(path).parts)
    return bool(parts.intersection(IGNORE_DIRS))


def _language(path: str) -> str:
    return LANGUAGES.get(PurePosixPath(path).suffix.lower(), "Text")


def _python_symbols(content: str) -> tuple[list[Symbol], list[str]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [], []
    symbols: list[Symbol] = []
    imports: list[str] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [arg.arg for arg in item.args.args]
            prefix = "async function" if isinstance(item, ast.AsyncFunctionDef) else "function"
            symbols.append(Symbol(name=item.name, kind=prefix, line=item.lineno, summary=f"{prefix.capitalize()} `{item.name}` takes {', '.join(args) or 'no arguments'}.") )
        elif isinstance(item, ast.ClassDef):
            methods = sum(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) for child in item.body)
            symbols.append(Symbol(name=item.name, kind="class", line=item.lineno, summary=f"Class `{item.name}` defines {methods} method{'s' if methods != 1 else ''}."))
        elif isinstance(item, ast.Import):
            imports.extend(alias.name for alias in item.names)
        elif isinstance(item, ast.ImportFrom):
            if item.module:
                imports.append(("." * item.level) + item.module)
    return symbols, imports


def _js_symbols(content: str) -> list[Symbol]:
    output = []
    for line_no, line in enumerate(content.splitlines(), 1):
        match = JS_SYMBOL_RE.search(line)
        if match:
            name = match.group(1) or match.group(2)
            kind = "class" if "class" in line else "function"
            output.append(Symbol(name=name, kind=kind, line=line_no, summary=f"{kind.capitalize()} `{name}` is declared here."))
    return output


def _resolve_import(source: str, imported: str, known: set[str]) -> str | None:
    imported = imported.replace("\\", "/")
    if not imported.startswith("."):
        candidate = imported.replace(".", "/")
        for suffix in (".py", ".ts", ".tsx", ".js", ".jsx", "/__init__.py", "/index.ts", "/index.tsx", "/index.js"):
            if candidate + suffix in known:
                return candidate + suffix
        # Python absolute imports are commonly rooted at a source directory
        # such as `src/`, which is not part of the import statement.
        matches = [path for path in known if path.endswith("/" + candidate + ".py")]
        if len(matches) == 1:
            return matches[0]
        return None
    base = PurePosixPath(source).parent
    raw = (base / imported).as_posix()
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    candidate = "/".join(parts)
    for suffix in ("", ".py", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js"):
        if candidate + suffix in known:
            return candidate + suffix
    return None


def analyze(files: list[SourceFile]) -> tuple[list[Node], list[Edge], str, list[str]]:
    normalized = [SourceFile(path=_path(f.path), content=f.content) for f in files if f.path and not _is_ignored(_path(f.path))]
    known = {f.path for f in normalized}
    
    file_nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen_edges: set[tuple[str, str]] = set()
    type_counts: Counter[str] = Counter()
    total_symbols = 0
    
    # Map folder paths to list of contained file paths and subfolder paths
    module_children: dict[str, set[str]] = {}
    module_files: dict[str, set[str]] = {}
    module_symbol_count: Counter[str] = Counter()

    for file in normalized:
        language = _language(file.path)
        suffix = PurePosixPath(file.path).suffix.lower()
        if suffix == ".py":
            symbols, imports = _python_symbols(file.content)
        elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
            symbols = _js_symbols(file.content)
            imports = IMPORT_RE.findall(file.content)
        else:
            symbols, imports = [], []

        total_symbols += len(symbols)
        type_counts[language] += 1
        
        parent_dir = PurePosixPath(file.path).parent.as_posix()
        parent_id = None if parent_dir == "." else parent_dir

        purpose = f"Contains {len(symbols)} top-level symbol{'s' if len(symbols) != 1 else ''}."
        file_nodes[file.path] = Node(
            id=file.path,
            label=PurePosixPath(file.path).name,
            kind="file",
            parent=parent_id,
            language=language,
            summary=purpose,
            symbols=symbols,
            file_count=1,
            children_ids=[]
        )

        # Update module hierarchy tracking
        curr = parent_dir
        while curr and curr != ".":
            if curr not in module_children:
                module_children[curr] = set()
                module_files[curr] = set()
            module_files[curr].add(file.path)
            module_symbol_count[curr] += len(symbols)
            
            p = PurePosixPath(curr).parent.as_posix()
            parent_mod = None if p == "." else p
            if parent_mod:
                if parent_mod not in module_children:
                    module_children[parent_mod] = set()
                    module_files[parent_mod] = set()
                module_children[parent_mod].add(curr)
            curr = parent_mod

        if parent_id:
            module_children[parent_id].add(file.path)

        for imported in imports:
            target = _resolve_import(file.path, imported, known)
            if target and target != file.path and (file.path, target) not in seen_edges:
                seen_edges.add((file.path, target))
                edges.append(Edge(source=file.path, target=target))

    # Construct Module Nodes
    module_nodes: list[Node] = []
    for mod_path, child_ids in module_children.items():
        parent_p = PurePosixPath(mod_path).parent.as_posix()
        mod_parent = None if parent_p == "." else parent_p
        f_count = len(module_files.get(mod_path, set()))
        s_count = module_symbol_count.get(mod_path, 0)
        summary = f"Module directory containing {f_count} file{'s' if f_count != 1 else ''} and {s_count} symbol{'s' if s_count != 1 else ''}."
        module_nodes.append(Node(
            id=mod_path,
            label=PurePosixPath(mod_path).name + "/",
            kind="module",
            parent=mod_parent,
            language="Module",
            summary=summary,
            symbols=[],
            file_count=f_count,
            children_ids=sorted(list(child_ids))
        ))

    all_nodes = module_nodes + list(file_nodes.values())
    root_count = len({edge.source for edge in edges})
    overview = f"This codebase has {len(file_nodes)} files, {len(module_nodes)} modules, {total_symbols} discovered symbols, and {len(edges)} internal dependency links."
    languages = ", ".join(f"{count} {name}" for name, count in type_counts.most_common()) or "no recognized source files"
    insights = [f"Detected: {languages}.", f"{root_count} files import another file in this selection."]
    if not edges:
        insights.append("No resolvable internal imports were found; external packages are intentionally omitted from the graph.")
    return all_nodes, edges, overview, insights
