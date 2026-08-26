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

from .models import AnalyzeStats, Edge, Node, SourceFile, Symbol

LANGUAGES = {".py": "Python", ".js": "JavaScript", ".jsx": "React", ".ts": "TypeScript", ".tsx": "React/TypeScript", ".json": "JSON"}
IGNORE_DIRS = {
    "node_modules", ".venv", "venv", "env", ".env", ".git", "dist", "build",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".next", "out", "coverage", ".idea", ".vscode"
}
IMPORT_RE = re.compile(r"(?:import\s+(?:.+?\s+from\s+)?|export\s+.+?\s+from\s+|require\s*\()\s*['\"]([^'\"]+)['\"]")
JS_SYMBOL_RE = re.compile(r"(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)|(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")


def _path(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/"))).lstrip("/")


def _compile_gitignore_rule(rule: str) -> re.Pattern | None:
    rule = rule.strip()
    if not rule or rule.startswith("#"):
        return None
    if rule.endswith("/"):
        rule = rule[:-1]
    
    parts = []
    i = 0
    while i < len(rule):
        c = rule[i]
        if c == "*":
            if i + 1 < len(rule) and rule[i + 1] == "*":
                parts.append(".*")
                i += 2
                continue
            else:
                parts.append("[^/]*")
        elif c == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(c))
        i += 1
    
    pattern_str = "".join(parts)
    if "/" in rule:
        pattern = f"^{pattern_str}(/.*)?$"
    else:
        pattern = f"(^|/){pattern_str}(/.*)?$"
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _parse_gitignore_rules(files: list[SourceFile]) -> list[re.Pattern]:
    patterns: list[re.Pattern] = []
    for file in files:
        if PurePosixPath(_path(file.path)).name == ".gitignore":
            for line in file.content.splitlines():
                compiled = _compile_gitignore_rule(line)
                if compiled:
                    patterns.append(compiled)
    return patterns


def _is_ignored(path: str, gitignore_patterns: list[re.Pattern] | None = None) -> bool:
    clean = _path(path)
    name = PurePosixPath(clean).name
    if name.startswith("."):
        return True
    parts = set(PurePosixPath(clean).parts)
    if bool(parts.intersection(IGNORE_DIRS)):
        return True
    if gitignore_patterns:
        for pattern in gitignore_patterns:
            if pattern.search(clean):
                return True
    return False


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


def _extract_package_name(imported: str) -> str | None:
    imported = imported.strip().replace("\\", "/")
    if not imported or imported.startswith("."):
        return None
    if imported.startswith("@"):
        parts = imported.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return imported
    first_part = imported.split("/")[0].split(".")[0]
    return first_part if first_part else None


def analyze(files: list[SourceFile]) -> tuple[list[Node], list[Edge], str, list[str], AnalyzeStats]:
    gitignore_rules = _parse_gitignore_rules(files)
    normalized = [SourceFile(path=_path(f.path), content=f.content) for f in files if f.path and not _is_ignored(f.path, gitignore_rules)]
    known = {f.path for f in normalized}
    
    file_nodes: dict[str, Node] = {}
    external_nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen_edges: set[tuple[str, str]] = set()
    type_counts: Counter[str] = Counter()
    total_symbols = 0
    
    # Map folder paths to list of contained file paths and subfolder paths
    module_children: dict[str, set[str]] = {}
    module_files: dict[str, set[str]] = {}
    module_symbol_count: Counter[str] = Counter()
    module_size_bytes: Counter[str] = Counter()

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
        file_bytes = len(file.content.encode("utf-8"))
        
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
            size_bytes=file_bytes,
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
            module_size_bytes[curr] += file_bytes
            
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
                edges.append(Edge(source=file.path, target=target, kind="imports"))
            elif not target and not imported.startswith("."):
                pkg = _extract_package_name(imported)
                if pkg:
                    pkg_id = f"pkg:{pkg}"
                    if pkg_id not in external_nodes:
                        external_nodes[pkg_id] = Node(
                            id=pkg_id,
                            label=pkg,
                            kind="external",
                            parent=None,
                            language="External Package",
                            summary=f"External package dependency `{pkg}`.",
                            symbols=[],
                            file_count=0,
                            size_bytes=0,
                            children_ids=[]
                        )
                    if (file.path, pkg_id) not in seen_edges:
                        seen_edges.add((file.path, pkg_id))
                        edges.append(Edge(source=file.path, target=pkg_id, kind="external_import"))

    # Construct Module Nodes
    module_nodes: list[Node] = []
    for mod_path, child_ids in module_children.items():
        parent_p = PurePosixPath(mod_path).parent.as_posix()
        mod_parent = None if parent_p == "." else parent_p
        f_count = len(module_files.get(mod_path, set()))
        s_count = module_symbol_count.get(mod_path, 0)
        m_bytes = module_size_bytes.get(mod_path, 0)
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
            size_bytes=m_bytes,
            children_ids=sorted(list(child_ids))
        ))


    all_nodes = module_nodes + list(file_nodes.values()) + list(external_nodes.values())
    
    total_files = len(file_nodes)
    total_modules = len(module_nodes)
    total_externals = len(external_nodes)
    total_edges = len(edges)

    stats = AnalyzeStats(
        file_count=total_files,
        module_count=total_modules,
        external_count=total_externals,
        symbol_count=total_symbols,
        edge_count=total_edges
    )

    # Rich Overview Narrative
    if total_files == 0:
        overview = "No valid source files found in the selected folder."
    else:
        overview = f"Codebase Architecture: {total_files} source file{'s' if total_files != 1 else ''} across {total_modules} module directory{'ies' if total_modules != 1 else ''} with {total_externals} external package dependenc{'ies' if total_externals != 1 else 'y'}."

    # Detailed Architectural Insights
    insights: list[str] = []

    # 1. Languages breakdown
    if total_files > 0:
        lang_parts = [f"{count} {lang} file{'s' if count != 1 else ''} ({round(count/total_files*100)}%)" for lang, count in type_counts.most_common()]
        insights.append(f"Language Breakdown: {', '.join(lang_parts)}.")

    # 2. External Packages
    if external_nodes:
        pkg_names = [node.label for node in external_nodes.values()]
        insights.append(f"External Packages Detected: {', '.join(sorted(pkg_names))}.")
    else:
        insights.append("External Packages: No third-party package imports detected.")

    # 3. File connectivity & entrypoints
    outgoing_counts: Counter[str] = Counter(edge.source for edge in edges)
    incoming_counts: Counter[str] = Counter(edge.target for edge in edges if not edge.target.startswith("pkg:"))

    if outgoing_counts:
        top_caller, top_outgoing = outgoing_counts.most_common(1)[0]
        caller_name = PurePosixPath(top_caller).name
        insights.append(f"Primary Dependency Hub: `{caller_name}` ({top_outgoing} outgoing link{'s' if top_outgoing != 1 else ''}).")
    elif total_files > 0:
        insights.append("Dependency Coupling: No cross-file or external import links were found.")

    # 4. Module directory structure
    if module_nodes:
        top_modules = sorted([m.id for m in module_nodes if not m.parent])
        insights.append(f"Root Modules: {', '.join(f'`{m}/`' for m in top_modules)}.")

    # 5. Symbol extraction summary
    insights.append(f"Symbol Index: Discovered {total_symbols} top-level function & class declaration{'s' if total_symbols != 1 else ''}.")

    return all_nodes, edges, overview, insights, stats


