"""DEC-5.25.1-4: the Decision Engine's determinism, proven structurally.

A test that merely calls the evaluator twice and compares the results shows
that it *happened* to be deterministic for one input. These tests show that
it cannot be otherwise: the engine has no clock to read, no identifier to
generate, no randomness to draw on, and no transitive import that could
reach a database, an HTTP client, or an object store.

This is the same discipline as the repositories having no generic
`update()`. The guarantee is worth more when the code is incapable of
violating it than when a reviewer has to keep confirming it doesn't.
"""

import ast
from pathlib import Path

import pytest

DECISION_PACKAGE = Path(__file__).resolve().parents[2] / "core" / "decision"

# Reading any of these inside the engine would make an evaluation depend on
# something other than its context (DEC-5.25.1, DEC-5.25.4).
FORBIDDEN_CALLS = frozenset(
    {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "uuid1", "uuid4", "uuid7"}
)

# Reaching any of these would mean the evaluator could perform I/O
# (DEC-5.25.3), and would break the dependency direction core/ maintains.
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "infrastructure",
        "apps",
        "sqlalchemy",
        "asyncpg",
        "psycopg",
        "psycopg2",
        "httpx",
        "requests",
        "fastapi",
        "starlette",
        "minio",
        "boto3",
        "redis",
        "random",
        "secrets",
    }
)

DECISION_MODULES = sorted(p for p in DECISION_PACKAGE.glob("*.py") if p.name != "__init__.py")


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _module_path(module: str) -> Path | None:
    root = DECISION_PACKAGE.parents[1]
    candidate = root / Path(*module.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    return None


def _transitive_project_imports() -> set[str]:
    """Every module reachable from core.decision, following first-party
    imports. A forbidden dependency hidden two hops away is still a
    forbidden dependency."""
    seen: set[str] = set()
    external: set[str] = set()
    queue = list(DECISION_MODULES)
    while queue:
        path = queue.pop()
        if str(path) in seen:
            continue
        seen.add(str(path))
        for module in _imported_modules(_parse(path)):
            external.add(module)
            resolved = _module_path(module)
            if resolved is not None:
                queue.append(resolved)
    return external


@pytest.mark.parametrize("path", DECISION_MODULES, ids=lambda p: p.name)
def test_decision_module_reads_no_clock_and_generates_no_identifier(path: Path) -> None:
    """A decision's timestamp and identifier are assigned by persistence, so
    the evaluator never needs either -- and must not be able to reach for
    one, since that is precisely how a "deterministic" function stops being
    reproducible."""
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        assert name not in FORBIDDEN_CALLS, (
            f"{path.name} calls {name}() -- the Decision Engine must not depend on "
            "wall-clock time or generated identifiers (DEC-5.25.1)"
        )


def test_decision_package_cannot_reach_infrastructure_even_transitively() -> None:
    offenders = {
        module
        for module in _transitive_project_imports()
        if module.split(".")[0] in FORBIDDEN_IMPORT_ROOTS
    }
    assert not offenders, (
        f"the Decision Engine transitively imports {sorted(offenders)} -- evaluation "
        "must make no uncontrolled external calls (DEC-5.25.3)"
    )


def test_the_evaluator_is_a_synchronous_function() -> None:
    """Not a style preference. An `async def` evaluator would invite an
    `await` on a repository inside it, which is the exact coupling the pure
    boundary exists to prevent."""
    tree = _parse(DECISION_PACKAGE / "evaluator.py")
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Await)]
