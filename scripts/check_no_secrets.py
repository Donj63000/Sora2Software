import argparse
import pathlib
import re
import subprocess
import sys
from typing import Iterable


ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCKED_NAMES = {".env"}
BLOCKED_PREFIXES = (".env.",)
ALLOWED_ENV_FILES = {".env.example"}
SECRET_PATTERNS = [
    re.compile(r"OPENAI_API_KEY\s*=\s*[\"']?(?!your-openai-api-key)[^\"'\s]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b"),
]


def iter_staged_files() -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Impossible de lire les fichiers stagés.")
    files: list[pathlib.Path] = []
    for raw_line in result.stdout.splitlines():
        relative = raw_line.strip()
        if not relative:
            continue
        files.append((ROOT / relative).resolve())
    return files


def is_blocked_env_file(path: pathlib.Path) -> bool:
    name = path.name
    if name in ALLOWED_ENV_FILES:
        return False
    if name in BLOCKED_NAMES:
        return True
    return name.startswith(BLOCKED_PREFIXES)


def scan_files(paths: Iterable[pathlib.Path]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        if is_blocked_env_file(path):
            errors.append(f"{relative}: les fichiers .env locaux ne doivent jamais être commités.")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            errors.append(f"{relative}: lecture impossible ({exc}).")
            continue

        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                errors.append(f"{relative}: secret détecté, commit bloqué.")
                break
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true", help="Scan les fichiers Git stagés.")
    parser.add_argument("paths", nargs="*", help="Fichiers à scanner.")
    args = parser.parse_args()

    try:
        if args.staged:
            paths = iter_staged_files()
        else:
            paths = [(ROOT / raw_path).resolve() for raw_path in args.paths]
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    errors = scan_files(paths)
    if errors:
        print("Commit refusé :", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
