from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BundledExample:
    name: str
    description: str


def _examples_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "examples"


def bundled_example_path(name: str) -> Path:
    return _examples_dir() / name


def _humanize_example_name(name: str) -> str:
    stem = Path(name).stem.replace("_", " ").strip()
    if not stem:
        return "Example pipeline."
    return f"{stem[0].upper()}{stem[1:]} example."


def _first_sentence(text: str) -> str:
    compact = " ".join(text.split()).strip()
    if not compact:
        return ""
    for delimiter in (". ", "!\n", "?\n", "!\r\n", "?\r\n", "!", "?"):
        head, separator, _tail = compact.partition(delimiter)
        if separator:
            sentence = f"{head}{separator.rstrip()}"
            return sentence.strip()
    return compact


def _graph_description(tree: ast.AST) -> str:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        else:
            continue

        if func_name != "Graph":
            continue

        for keyword in node.keywords:
            if keyword.arg != "description":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return _first_sentence(keyword.value.value)
    return ""


def _describe_example(example_path: Path) -> str:
    try:
        source = example_path.read_text(encoding="utf-8")
    except OSError:
        return _humanize_example_name(example_path.name)

    try:
        tree = ast.parse(source, filename=str(example_path))
    except SyntaxError:
        return _humanize_example_name(example_path.name)

    docstring = ast.get_docstring(tree)
    if docstring:
        sentence = _first_sentence(docstring)
        if sentence:
            return sentence

    description = _graph_description(tree)
    if description:
        return description

    return _humanize_example_name(example_path.name)


def bundled_examples() -> tuple[BundledExample, ...]:
    examples = [
        BundledExample(name=path.name, description=_describe_example(path))
        for path in sorted(_examples_dir().glob("*.py"))
    ]
    return tuple(examples)


def bundled_example_names() -> tuple[str, ...]:
    return tuple(example.name for example in bundled_examples())


def read_bundled_example(name: str) -> str:
    if name not in bundled_example_names():
        available = ", ".join(f"`{example}`" for example in bundled_example_names())
        raise ValueError(f"unknown bundled example `{name}` (available: {available}; see `agentflow examples`)")

    example_path = bundled_example_path(name)
    if example_path.exists():
        return example_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"bundled example `{name}` not found")


def default_smoke_pipeline_path() -> str:
    return str(bundled_example_path("airflow_like.py"))
