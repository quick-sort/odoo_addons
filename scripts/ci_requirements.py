#!/usr/bin/env python3
"""Print the pip requirements to install for a set of addons.

Combines each addon's runtime dependencies (``requirements.txt``, generated
from the manifest) with its test-only dependencies — third-party modules
imported at module level under ``tests/``.

Odoo's test loader imports every installed module's test files during install
(``loader.make_suite`` runs for the whole dependency graph, not just the
``--test-tags`` targets), so those test imports must be present too even though
they are not runtime dependencies. ``generate_requirements.py`` deliberately
skips ``tests/``, which is why this separate pass exists.

Usage::

    python3 scripts/ci_requirements.py <addon1> <addon2> ... > /tmp/ci-reqs.txt
"""

import ast
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, SCRIPTS_DIR)

import generate_requirements as g  # noqa: E402

#: Provided by the odoo base image already; re-installing would attempt a
#: psycopg2 source build. ``mcp`` is installed by the CI workflow as the real
#: package with its compiled wheels (cryptography/cffi) stripped afterwards —
#: keeping it out of the merged requirements avoids resolving that dependency
#: chain twice.
SKIP = {"psycopg2", "mcp"}


def _dist_name(requirement):
    return g._distribution_name(requirement).lower()


def collect(addons):
    seen, out = set(), []

    def add(req):
        if not req:
            return
        key = _dist_name(req)
        if key in SKIP or key in seen:
            return
        seen.add(key)
        out.append(req)

    for addon in addons:
        addon_dir = os.path.join(REPO_ROOT, addon)

        req_path = os.path.join(addon_dir, "requirements.txt")
        if os.path.isfile(req_path):
            for line in open(req_path):
                add(line.split("#", 1)[0].strip())

        tests_dir = os.path.join(addon_dir, "tests")
        if os.path.isdir(tests_dir):
            for root, _dirs, files in os.walk(tests_dir):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(root, name)
                    try:
                        tree = ast.parse(open(path, encoding="utf-8").read())
                    except (SyntaxError, UnicodeDecodeError):
                        continue
                    for node in tree.body:
                        modules = set()
                        if isinstance(node, ast.Import):
                            modules.update(a.name.split(".")[0] for a in node.names)
                        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                            modules.add(node.module.split(".")[0])
                        for mod in modules:
                            if (
                                mod in g.IGNORED
                                or mod in g.ODOO_PROVIDED
                                or mod in sys.stdlib_module_names
                            ):
                                continue
                            add(g.PYPI_NAMES.get(mod, mod))

    return out


def main():
    out = collect(sys.argv[1:])
    if out:
        print("\n".join(out))


if __name__ == "__main__":
    main()
