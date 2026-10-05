"""Create a reproducible CodeBuild source ZIP from reviewed source directories."""

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path

ROOT_FILES = {"Dockerfile", ".dockerignore"}
BACKEND_FILES = {"pyproject.toml", "uv.lock", "alembic.ini", "quality-baseline.json"}
FRONTEND_FILES = {
    "package.json",
    "package-lock.json",
    "index.html",
    "vite.config.js",
    "tsconfig.json",
    "vitest.config.ts",
    "playwright.config.ts",
    "lint-baseline.json",
}
DIRECTORIES = {
    "backend/app": {".py", ".json"},
    "backend/alembic": {".py", ".mako"},
    "backend/tests": {".py"},
    "backend/scripts": {".py"},
    "frontend/src": {
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".svg",
        ".png",
        ".jpg",
        ".woff2",
    },
    "frontend/public": {".svg", ".png", ".jpg", ".ico", ".woff2", ".txt"},
    "frontend/scripts": {".ts", ".js"},
    "frontend/tests": {".ts", ".tsx", ".js", ".jsx"},
    "deployment/aws": {".py", ".yml", ".yaml"},
}
BLOCKED_PARTS = {
    ".git",
    ".aws",
    ".codex",
    ".agents",
    ".venv",
    "venv",
    "node_modules",
    "artifacts",
    "__pycache__",
    "dist",
    "test-results",
    "playwright-report",
}


def source_file(path: Path) -> bool:
    parts = path.parts
    if any(part in BLOCKED_PARTS or part.startswith(".env") for part in parts):
        return False
    if any(
        "credentials" in part.lower() or part.lower().startswith("secrets.")
        for part in parts
    ):
        return False
    if path.as_posix() in ROOT_FILES:
        return True
    if len(parts) == 2 and parts[0] == "backend" and parts[1] in BACKEND_FILES:
        return True
    if len(parts) == 2 and parts[0] == "frontend" and parts[1] in FRONTEND_FILES:
        return True
    return any(
        path.as_posix().startswith(f"{directory}/") and path.suffix in suffixes
        for directory, suffixes in DIRECTORIES.items()
    )


def package_source(root: Path, output: Path) -> dict[str, str | int]:
    root = root.resolve(strict=True)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    included = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and path.resolve() != output
        and source_file(path.relative_to(root))
    ]
    required = [
        root / name
        for name in ROOT_FILES | {"backend/uv.lock", "frontend/package-lock.json"}
    ]
    if any(path not in included for path in required):
        raise ValueError("Required build source is missing or excluded")
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in included:
            entry = zipfile.ZipInfo(
                path.relative_to(root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
            )
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    return {
        "file": str(output),
        "files": len(included),
        "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    arguments = parser.parse_args()
    print(json.dumps(package_source(arguments.root, arguments.output)))


if __name__ == "__main__":
    main()
