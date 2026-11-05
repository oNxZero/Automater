"""Check documentation and runtime asset references, including dynamic themes."""

import ast
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from automater import theme
from automater.palettes import PALETTES

ROOT = Path(__file__).resolve().parents[1]


def main():
    references = set()
    for document in [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md")]:
        for target in re.findall(
            r"""(?:\]\(|(?:src|href)=["'])([^"'\s)>]+)""", document.read_text()
        ):
            parsed = urlsplit(target)
            if not parsed.scheme and not parsed.netloc and parsed.path:
                references.add((document.parent / unquote(parsed.path)).resolve())
    # Evaluate the actual stylesheet so light variants are not mistaken for dead assets.
    for name, overrides in [
        *((name, {}) for name in PALETTES),
        ("automater", {"accent": "#000000"}),
        ("daylight", {"accent": "#ffffff"}),
    ]:
        theme.activate(name, overrides)
        references.update(
            Path(path).resolve() for path in re.findall(r'url\("([^"]+)"\)', theme.stylesheet())
        )
    for source in ROOT.glob("src/automater/*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("src/")
                and node.value.endswith(".svg")
            ):
                references.add((ROOT / node.value).resolve())
    assets = {
        path.resolve()
        for directory in (ROOT / "docs", ROOT / "src/automater/assets")
        for path in directory.rglob("*")
        if path.suffix in (".png", ".svg", ".gif", ".jpg", ".webp", ".ico")
    }
    missing = sorted(path for path in references if not path.is_file())
    unused = sorted(assets - references)
    for label, paths in (("Missing reference", missing), ("Unused asset", unused)):
        for path in paths:
            print(f"{label}: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    if missing or unused:
        return 1
    print(f"Checked {len(assets)} assets: all referenced, including dynamic theme variants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
