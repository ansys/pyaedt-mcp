# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline search over the PyAEDT API.

The index is built by statically parsing (``ast``) the installed
``ansys.aedt.core`` package, so nothing is imported or executed. Each public
class, method, property, and function becomes one entry holding its signature,
docstring, and the native AEDT API calls it relies on. Native calls are
collected from two sources:

* The ``References`` docstring section (for example ``>>> oModule.AssignRadiation``).
* Calls in the function body on AEDT COM objects (for example
  ``self.oeditor.CreateBox(...)``).

This makes it possible to search in both directions: from a PyAEDT concept to
the method that implements it, and from a native AEDT scripting call to the
PyAEDT method that wraps it.

Ranking uses BM25 over weighted name, native, summary, and docstring tokens,
plus boosts for exact name or native method matches.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
import importlib.metadata as importlib_metadata
import importlib.util
import math
from pathlib import Path
import re
import threading
from typing import Iterable, Literal

DOCS_BASE_URL = "https://aedt.docs.pyansys.com/version/stable"
PYAEDT_PACKAGE = "ansys.aedt.core"

#: Subpackages that contain UI helpers, CLIs, or RPC plumbing rather than API.
_SKIPPED_SUBPACKAGES = {"extensions", "cli", "examples", "rpc", "__pycache__"}

#: Receivers that look like AEDT objects but are plain Python/third-party modules.
_NON_NATIVE_RECEIVERS = {
    "os",
    "obj",
    "object",
    "other",
    "out",
    "output",
    "opt",
    "options",
    "op",
    "ordered",
}

_NATIVE_RECEIVER_HINTS = ("object", "desktop", "design", "project", "module", "editor")

_TOKEN_RE = re.compile(r"[A-Za-z][a-z]*|[A-Z]+(?![a-z])|\d+")
_REFERENCE_RE = re.compile(r"^\s*>>>\s*([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)+)")
_SECTION_UNDERLINE_RE = re.compile(r"^\s*-{3,}\s*$")

_DOC_TOKEN_LIMIT = 400

SearchScope = Literal["all", "pyaedt", "native"]
EntryKind = Literal["class", "method", "property", "function"]


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, breaking camelCase and snake_case words.

    Full identifiers are also kept as single tokens (for example ``CreateBox``
    yields ``create``, ``box`` and ``createbox``) so exact native names match.
    """
    tokens: list[str] = []
    for word in re.findall(r"[A-Za-z0-9_]+", text):
        parts = [p.lower() for p in _TOKEN_RE.findall(word)]
        tokens.extend(_normalize(p) for p in parts if p)
        joined = word.replace("_", "").lower()
        if len(parts) > 1 and joined:
            tokens.append(joined)
    return [t for t in tokens if t]


def _normalize(token: str) -> str:
    # Minimal plural folding so "boundaries"/"boundary" and "ports"/"port" match.
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


@dataclass
class ApiEntry:
    """One searchable PyAEDT API object."""

    name: str
    qualname: str
    kind: EntryKind
    module: str
    class_name: str | None
    signature: str
    summary: str
    doc: str
    file: str
    line: int
    native_references: list[str] = field(default_factory=list)
    native_calls: list[str] = field(default_factory=list)
    tokens: Counter = field(default_factory=Counter)
    length: int = 0

    @property
    def native_methods(self) -> set[str]:
        """Lowercase native method names (without receiver) used by this entry."""
        return {ref.rsplit(".", 1)[-1].lower() for ref in self.native_api}

    @property
    def native_api(self) -> list[str]:
        """Native AEDT calls from the docstring references and the function body."""
        seen: dict[str, str] = {}
        for ref in [*self.native_references, *self.native_calls]:
            seen.setdefault(ref.lower(), ref)
        return list(seen.values())

    def native_match_strength(self, method: str) -> int:
        """Return how many sources (docstring references, body calls) use ``method``."""
        method = method.lower()
        in_refs = any(r.rsplit(".", 1)[-1].lower() == method for r in self.native_references)
        in_body = any(c.rsplit(".", 1)[-1].lower() == method for c in self.native_calls)
        return int(in_refs) + int(in_body)


@dataclass
class _ClassInfo:
    name: str
    qualname: str
    bases: list[str]


class PyAEDTApiIndex:
    """Lazily built, thread-safe BM25 index over the installed PyAEDT sources."""

    k1 = 1.4
    b = 0.6

    def __init__(self, package_root: Path | None = None) -> None:
        self._package_root = package_root
        self._lock = threading.Lock()
        self._loaded = False
        self.entries: list[ApiEntry] = []
        self._df: Counter = Counter()
        self._avg_len = 1.0
        self._subclasses: dict[str, set[str]] = {}
        self.version: str | None = None
        self.parse_errors: list[str] = []

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        """Build the index on first use."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._build()
            self._loaded = True

    def _resolve_root(self) -> Path:
        if self._package_root is not None:
            return Path(self._package_root)
        spec = importlib.util.find_spec(PYAEDT_PACKAGE)
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError("PyAEDT (ansys.aedt.core) is not installed in this environment.")
        return Path(next(iter(spec.submodule_search_locations)))

    def _build(self) -> None:
        root = self._resolve_root()
        try:
            self.version = importlib_metadata.version("pyaedt")
        except importlib_metadata.PackageNotFoundError:
            self.version = None

        classes: list[_ClassInfo] = []
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root)
            if any(part in _SKIPPED_SUBPACKAGES for part in rel.parts[:-1]):
                continue
            if any(part.startswith("_") and part != "__init__.py" for part in rel.parts):
                continue
            module = ".".join([PYAEDT_PACKAGE, *rel.with_suffix("").parts])
            module = module.removesuffix(".__init__")
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError, OSError) as exc:
                self.parse_errors.append(f"{rel}: {exc}")
                continue
            self._index_module(tree, module, str(path), classes)

        for cls in classes:
            for base in cls.bases:
                self._subclasses.setdefault(base, set()).add(cls.name)

        for entry in self.entries:
            self._df.update(set(entry.tokens))
        total = sum(e.length for e in self.entries)
        self._avg_len = total / len(self.entries) if self.entries else 1.0

    def _index_module(
        self, tree: ast.Module, module: str, file: str, classes: list[_ClassInfo]
    ) -> None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    self._add_function(node, module, None, file)
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                bases = [_base_name(b) for b in node.bases]
                classes.append(_ClassInfo(node.name, f"{module}.{node.name}", bases))
                self._add_class(node, module, file)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("_") or item.name == "__init__":
                            if item.name != "__init__":
                                self._add_function(item, module, node.name, file)

    def _add_class(self, node: ast.ClassDef, module: str, file: str) -> None:
        doc = ast.get_docstring(node) or ""
        init = next(
            (
                n
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "__init__"
            ),
            None,
        )
        signature = _render_signature(init) if init is not None else "()"
        if init is not None and not doc:
            doc = ast.get_docstring(init) or ""
        bases = ", ".join(_base_name(b) for b in node.bases)
        entry = ApiEntry(
            name=node.name,
            qualname=f"{module}.{node.name}",
            kind="class",
            module=module,
            class_name=node.name,
            signature=signature,
            summary=_summary(doc),
            doc=doc,
            file=file,
            line=node.lineno,
            native_references=_doc_references(doc),
        )
        self._finalize(entry, extra_text=bases)

    def _add_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        module: str,
        class_name: str | None,
        file: str,
    ) -> None:
        decorators = {_base_name(d) for d in node.decorator_list}
        if any(d.endswith(".setter") or d.endswith(".deleter") for d in decorators):
            return
        if class_name is None:
            kind: EntryKind = "function"
        elif "property" in decorators or "cached_property" in decorators:
            kind = "property"
        else:
            kind = "method"
        doc = ast.get_docstring(node) or ""
        owner = f"{module}.{class_name}" if class_name else module
        entry = ApiEntry(
            name=node.name,
            qualname=f"{owner}.{node.name}",
            kind=kind,
            module=module,
            class_name=class_name,
            signature="" if kind == "property" else _render_signature(node),
            summary=_summary(doc),
            doc=doc,
            file=file,
            line=node.lineno,
            native_references=_doc_references(doc),
            native_calls=_native_calls(node),
        )
        self._finalize(entry)

    def _finalize(self, entry: ApiEntry, extra_text: str = "") -> None:
        name_tokens = tokenize(entry.name) + [entry.name.lower()]
        native_tokens: list[str] = []
        for ref in entry.native_api:
            native_tokens.extend(tokenize(ref.rsplit(".", 1)[-1]))
        owner_tokens = tokenize(entry.class_name or "") + tokenize(entry.module.split(".")[-1])
        doc_tokens = tokenize(_strip_examples(entry.doc))[:_DOC_TOKEN_LIMIT]

        tokens: Counter = Counter()
        for token in name_tokens:
            tokens[token] += 4
        for token in native_tokens:
            tokens[token] += 3
        for token in tokenize(entry.summary):
            tokens[token] += 2
        for token in owner_tokens + tokenize(extra_text):
            tokens[token] += 1
        tokens.update(doc_tokens)
        entry.tokens = tokens
        entry.length = sum(tokens.values())
        self.entries.append(entry)

    # ------------------------------------------------------------------
    # Searching
    # ------------------------------------------------------------------

    def subclasses_of(self, class_name: str, limit: int = 8) -> list[str]:
        """Return public descendants of a class, concrete (leaf) classes first."""
        found: list[str] = []
        queue = [class_name]
        seen = {class_name}
        while queue:
            current = queue.pop(0)
            for child in sorted(self._subclasses.get(current, ())):
                if child not in seen:
                    seen.add(child)
                    found.append(child)
                    queue.append(child)
        leaves = [c for c in found if not self._subclasses.get(c)]
        intermediates = [c for c in found if self._subclasses.get(c)]
        return (leaves + intermediates)[:limit]

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        scope: SearchScope = "all",
        kinds: Iterable[str] | None = None,
        module: str | None = None,
    ) -> list[tuple[ApiEntry, float]]:
        """Rank entries for a free-text, PyAEDT-name, or native-API query."""
        self.ensure_loaded()
        query = query.strip()
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        kind_filter = {k.lower() for k in kinds} if kinds else None
        module_filter = module.strip().lower() if module else None

        # "oEditor.CreateBox" or "CreateBox" -> "createbox"; "create_box" -> "create_box".
        last_identifier = re.split(r"[.\s(]+", query.rstrip("() "))[-1].lower()
        compact_query = last_identifier.replace("_", "")
        unique_tokens = list(dict.fromkeys(q_tokens))
        n_docs = len(self.entries)

        scored: list[tuple[ApiEntry, float]] = []
        for entry in self.entries:
            if kind_filter and entry.kind not in kind_filter:
                continue
            if module_filter and not (
                entry.qualname.lower().startswith(module_filter)
                or module_filter in entry.qualname.lower()
            ):
                continue
            native_methods = entry.native_methods
            if scope == "native" and not native_methods:
                continue

            score = 0.0
            for token in unique_tokens:
                tf = entry.tokens.get(token, 0)
                if not tf:
                    continue
                df = self._df.get(token, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                norm = self.k1 * (1 - self.b + self.b * entry.length / self._avg_len)
                score += idf * tf * (self.k1 + 1) / (tf + norm)
            if score <= 0:
                continue

            name_lower = entry.name.lower()
            name_hit = last_identifier == name_lower or compact_query == name_lower.replace("_", "")
            if scope != "pyaedt" and compact_query in native_methods:
                score += 8.0 * (1 + entry.native_match_strength(compact_query))
            if scope != "native" and name_hit:
                score += 12.0
            if scope == "native":
                native_tokens = {t for m in native_methods for t in tokenize(m)}
                score += 2.0 * sum(1 for t in unique_tokens if t in native_tokens)
            if entry.kind == "class":
                score *= 0.9
            scored.append((entry, score))

        scored.sort(key=lambda item: (-item[1], item[0].qualname))
        return scored[:top_k]

    def describe(self, entry: ApiEntry, score: float, include_doc: bool = False) -> dict:
        """Serialize an entry for the tool response."""
        out: dict = {
            "name": entry.name,
            "kind": entry.kind,
            "qualname": entry.qualname,
            "signature": (
                f"{entry.name}{entry.signature}" if entry.kind != "property" else entry.name
            ),
            "summary": entry.summary,
            "score": round(score, 3),
        }
        if entry.class_name and entry.kind != "class":
            out["defined_in_class"] = entry.class_name
        if entry.class_name:
            subclasses = self.subclasses_of(entry.class_name)
            if subclasses:
                out["available_on_subclasses"] = subclasses
        if entry.native_api:
            out["native_api"] = entry.native_api[:12]
        out["source"] = f"{entry.file}:{entry.line}"
        out["docs_search_url"] = f"{DOCS_BASE_URL}/search.html?q={entry.name}"
        if include_doc and entry.doc:
            doc = entry.doc
            out["docstring"] = doc if len(doc) <= 3000 else doc[:3000] + "\n[...]"
        return out


# ----------------------------------------------------------------------
# AST helpers
# ----------------------------------------------------------------------


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _base_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    if positional and positional[0].arg in {"self", "cls"}:
        trimmed = ast.arguments(
            posonlyargs=list(args.posonlyargs[1:]) if args.posonlyargs else [],
            args=list(args.args[1:]) if not args.posonlyargs else list(args.args),
            vararg=args.vararg,
            kwonlyargs=args.kwonlyargs,
            kw_defaults=args.kw_defaults,
            kwarg=args.kwarg,
            defaults=args.defaults,
        )
    else:
        trimmed = args
    rendered = f"({ast.unparse(trimmed)})"
    if node.returns is not None:
        rendered += f" -> {ast.unparse(node.returns)}"
    return rendered if len(rendered) <= 400 else rendered[:397] + "..."


def _summary(doc: str) -> str:
    for line in doc.strip().splitlines():
        if line.strip():
            return line.strip()[:240]
    return ""


def _doc_sections(doc: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"": []}
    current = ""
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and _SECTION_UNDERLINE_RE.match(lines[i + 1]) and line.strip():
            current = line.strip().lower()
            sections.setdefault(current, [])
            continue
        if _SECTION_UNDERLINE_RE.match(line):
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _doc_references(doc: str) -> list[str]:
    refs: list[str] = []
    for line in _doc_sections(doc).get("references", []):
        match = _REFERENCE_RE.match(line)
        if match and match.group(1) not in refs:
            refs.append(match.group(1))
    return refs


def _strip_examples(doc: str) -> str:
    sections = _doc_sections(doc)
    return "\n".join(
        "\n".join(body) for name, body in sections.items() if name not in {"examples", "references"}
    )


def _is_native_receiver(name: str) -> bool:
    stripped = name.lstrip("_")
    lower = stripped.lower()
    if not stripped or lower in _NON_NATIVE_RECEIVERS:
        return False
    if lower.startswith("o") and len(lower) > 2:
        return True
    return any(hint in lower for hint in _NATIVE_RECEIVER_HINTS)


def _native_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    calls: dict[str, None] = {}
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)):
            continue
        method = sub.func.attr
        if not method[:1].isupper() or method.isupper():
            continue
        receiver = sub.func.value
        if isinstance(receiver, ast.Attribute):
            receiver_name = receiver.attr
        elif isinstance(receiver, ast.Name):
            receiver_name = receiver.id
        elif isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute):
            # Chained native calls such as ``oDesign.GetChildObject(...).GetPropValue``.
            if receiver.func.attr[:1].isupper():
                calls.setdefault(f"{receiver.func.attr}().{method}", None)
            continue
        else:
            continue
        if _is_native_receiver(receiver_name):
            calls.setdefault(f"{receiver_name.lstrip('_')}.{method}", None)
    return list(calls)


_default_index: PyAEDTApiIndex | None = None
_default_lock = threading.Lock()


def get_api_index() -> PyAEDTApiIndex:
    """Return the process-wide PyAEDT API index (built lazily on first search)."""
    global _default_index
    with _default_lock:
        if _default_index is None:
            _default_index = PyAEDTApiIndex()
        return _default_index
