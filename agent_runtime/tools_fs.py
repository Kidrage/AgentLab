"""Safe filesystem helper skeletons.

These helpers are intentionally small and conservative. Write helpers refuse to
overwrite existing files by default.
"""

from pathlib import Path

from policies import assert_path_allowed


def read_text(path: Path, allowed_root: Path) -> str:
    target = assert_path_allowed(path, allowed_root)
    return target.read_text(encoding="utf-8")


def write_text_if_missing(path: Path, content: str, allowed_root: Path) -> Path:
    target = assert_path_allowed(path, allowed_root)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def ensure_dir(path: Path, allowed_root: Path) -> Path:
    target = assert_path_allowed(path, allowed_root)
    target.mkdir(parents=True, exist_ok=True)
    return target
