#!/usr/bin/env python3
"""Compute the addons whose Odoo tests must run for a set of changed files.

Reads changed file paths (one per line) on stdin and prints the affected addon
names, space-separated, on stdout.

An addon is "affected" when it, or any addon that (transitively) depends on it,
is touched by the change. This is the reverse-dependency closure prescribed by
``docs/development-governance.md`` §4: changing a core addon such as ``llm``
must re-run the tests of every addon built on it, not just ``llm`` itself.

The closure is computed over repo-internal ``depends`` edges only. Modules
declared in ``depends`` that live outside this repo (``base``, ``mail``,
``web``, …) are ignored here — they are Odoo core/enterprise and never change
with this repository.

Two output modes:

- ``affected`` (default) — the addons whose *tests* must run: the directly
  changed addons plus their reverse dependents.
- ``install`` — the affected set plus everything they transitively depend on.
  Odoo auto-installs the ``depends`` closure, so those modules' external
  dependencies must be pip-installed too.

Example::

    git diff --name-only origin/19.0...HEAD | python3 scripts/ci_affected.py
    git diff --name-only origin/19.0...HEAD | python3 scripts/ci_affected.py --install
"""

import ast
import io
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Top-level paths that never map to an addon.
NON_ADDON_DIRS = {".git", ".github", ".claude", "docs", "scripts", "legacy"}


def iter_repo_addons():
    for name in sorted(os.listdir(REPO_ROOT)):
        if name.startswith("."):
            continue
        if os.path.isfile(os.path.join(REPO_ROOT, name, "__manifest__.py")):
            yield name


def addon_for(path):
    """The top-level addon a changed file belongs to, or ``None``."""
    parts = path.split(os.sep)
    top = parts[0] if parts else ""
    if top in NON_ADDON_DIRS or top.startswith(".") or top == "":
        return None
    if os.path.isfile(os.path.join(REPO_ROOT, top, "__manifest__.py")):
        return top
    return None


def parse_depends(addon):
    path = os.path.join(REPO_ROOT, addon, "__manifest__.py")
    try:
        manifest = ast.literal_eval(io.open(path, encoding="utf-8").read())
    except (SyntaxError, ValueError, OSError):
        return []
    return list(manifest.get("depends") or [])


def build_dependency_graph():
    repo_addons = set(iter_repo_addons())
    return {
        name: [dep for dep in parse_depends(name) if dep in repo_addons]
        for name in repo_addons
    }


def affected_addons(changed_files):
    graph = build_dependency_graph()

    changed = set()
    for path in changed_files:
        name = addon_for(path)
        if name:
            changed.add(name)

    # Reverse edges: addon -> the addons that depend on it.
    dependents = {name: set() for name in graph}
    for name, deps in graph.items():
        for dep in deps:
            dependents[dep].add(name)

    affected = set(changed)
    stack = list(changed)
    while stack:
        node = stack.pop()
        for downstream in dependents.get(node, ()):
            if downstream not in affected:
                affected.add(downstream)
                stack.append(downstream)

    return affected


def install_closure(affected):
    """The affected set plus everything they transitively depend on.

    Odoo auto-installs the ``depends`` closure when the affected addons are
    installed, so those modules' external dependencies must be pip-installed
    too — not just the affected addons' own requirements.
    """
    graph = build_dependency_graph()
    closure = set(affected)
    stack = list(affected)
    while stack:
        node = stack.pop()
        for dep in graph.get(node, ()):
            if dep not in closure:
                closure.add(dep)
                stack.append(dep)
    return closure


def main():
    mode = sys.argv[1].lstrip("-") if len(sys.argv) > 1 else "affected"
    changed_files = [line.strip() for line in sys.stdin if line.strip()]
    affected = affected_addons(changed_files)
    result = install_closure(affected) if mode == "install" else affected
    if result:
        print(" ".join(sorted(result)))


if __name__ == "__main__":
    main()
