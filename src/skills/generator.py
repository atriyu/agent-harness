"""Auto-generate API reference skills from Python source modules.

Extracts class docstrings, method signatures, type hints, and docstrings
from networking helper modules and writes them as skill markdown files.
This ensures the codegen agent always has an accurate, up-to-date API reference.
"""

from __future__ import annotations

import ast
import inspect
import importlib
import logging
import textwrap
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKILL_TEMPLATE = """\
---
name: {name}
description: {description}
domain: api-reference
applies_to: [codegen, repair]
priority: 2
tags: [api, auto-generated]
---

{content}
"""


def _extract_from_ast(source_path: Path) -> str:
    """Extract class/method info from a Python file using AST parsing.

    This works without importing the module, so it's safe to run even
    if dependencies aren't installed.
    """
    source = source_path.read_text()
    tree = ast.parse(source)
    lines: list[str] = []

    module_doc = ast.get_docstring(tree)
    if module_doc:
        lines.append(f"> {module_doc.split(chr(10))[0]}\n")

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_doc = ast.get_docstring(node) or ""
            lines.append(f"## `{node.name}`\n")
            if class_doc:
                lines.append(f"{class_doc}\n")

            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    sig = _format_function_sig(item)
                    func_doc = ast.get_docstring(item) or ""
                    lines.append(f"### `{item.name}()`\n")
                    lines.append(f"```python\n{sig}\n```\n")
                    if func_doc:
                        lines.append(f"{func_doc}\n")

        elif isinstance(node, ast.ClassDef) is False and isinstance(node, ast.FunctionDef):
            # Top-level functions
            if not node.name.startswith("_") and node.col_offset == 0:
                sig = _format_function_sig(node)
                func_doc = ast.get_docstring(node) or ""
                lines.append(f"### `{node.name}()`\n")
                lines.append(f"```python\n{sig}\n```\n")
                if func_doc:
                    lines.append(f"{func_doc}\n")

    # Also extract dataclass/dataclass-like classes
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and not any(
            isinstance(base, ast.Name) and base.id in ("ABC",)
            for base in node.bases
        ):
            # Check if it's a dataclass (has @dataclass decorator)
            is_dataclass = any(
                (isinstance(d, ast.Name) and d.id == "dataclass") or
                (isinstance(d, ast.Attribute) and d.attr == "dataclass")
                for d in node.decorator_list
            )
            if is_dataclass and node.name not in [l for l in lines if node.name in l]:
                lines.append(f"## `{node.name}` (dataclass)\n")
                doc = ast.get_docstring(node) or ""
                if doc:
                    lines.append(f"{doc}\n")
                # Extract fields
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field_name = item.target.id
                        annotation = ast.unparse(item.annotation) if item.annotation else "Any"
                        default = f" = {ast.unparse(item.value)}" if item.value else ""
                        fields.append(f"  {field_name}: {annotation}{default}")
                if fields:
                    lines.append("```python\n" + "\n".join(fields) + "\n```\n")

    return "\n".join(lines)


def _format_function_sig(node: ast.FunctionDef) -> str:
    """Format a function signature from AST."""
    args = []
    defaults_offset = len(node.args.args) - len(node.args.defaults)

    for i, arg in enumerate(node.args.args):
        if arg.arg == "self":
            continue
        ann = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        default_idx = i - defaults_offset
        default = f" = {ast.unparse(node.args.defaults[default_idx])}" if default_idx >= 0 else ""
        args.append(f"{arg.arg}{ann}{default}")

    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    args_str = ", ".join(args)
    return f"def {node.name}({args_str}){returns}"


def generate_api_skill(
    source_path: str | Path,
    output_path: str | Path,
    skill_name: str | None = None,
    description: str | None = None,
) -> Path:
    """Generate an API reference skill from a Python source file.

    Args:
        source_path: Path to the Python module.
        output_path: Where to write the skill markdown file.
        skill_name: Override skill name (default: derived from filename).
        description: Override description.

    Returns:
        Path to the generated skill file.
    """
    src = Path(source_path)
    out = Path(output_path)

    if not src.exists():
        raise FileNotFoundError(f"Source module not found: {src}")

    name = skill_name or f"{src.stem}-api"
    desc = description or f"API reference for {src.stem} module (auto-generated)"

    content = _extract_from_ast(src)

    skill_text = _SKILL_TEMPLATE.format(
        name=name,
        description=desc,
        content=content,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(skill_text)
    logger.info("Generated API skill: %s -> %s", src.name, out)
    return out


def generate_all_api_skills(
    networking_dir: str | Path = "src/networking",
    output_dir: str | Path = "skills/api-reference",
) -> list[Path]:
    """Generate API reference skills for all networking helper modules."""
    net_dir = Path(networking_dir)
    out_dir = Path(output_dir)

    if not net_dir.exists():
        logger.warning("Networking directory not found: %s", net_dir)
        return []

    generated = []
    module_descriptions = {
        "vpn": "VPN testing API: tunnel management, leak detection, kill switch",
        "traffic": "Traffic generation API: iperf3, scapy, HTTP, bulk connections",
        "protocol": "Protocol validation API: testssl.sh, nmap, TLS verification",
        "capture": "Packet capture API: tcpdump/tshark start, stop, analyze",
    }

    for py_file in sorted(net_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        stem = py_file.stem
        desc = module_descriptions.get(stem, f"API reference for {stem}")
        out_path = out_dir / f"{stem}-api.md"

        try:
            path = generate_api_skill(py_file, out_path, f"{stem}-api", desc)
            generated.append(path)
        except Exception as e:
            logger.warning("Failed to generate API skill for %s: %s", py_file, e)

    logger.info("Generated %d API reference skills", len(generated))
    return generated
