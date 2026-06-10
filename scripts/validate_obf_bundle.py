"""Post-PyArmor / post-PyInstaller validation for frozen backend builds.

Invariants enforced:
1. Only the single entry script may contain module-level PyArmor protection hooks.
2. obf/ tree must include all expected top-level packages (app.db, app.api, ...).
3. Optional: frozen exe --validate-frozen smoke test after PyInstaller.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# PyArmor 7 injects these names into *entry* scripts only (readable in obfuscated .py).
_PROTECTION_MARKERS = (
    "protect_pytransform",
    "check_lib_pytransform",
    "pyarmor_runtime",
)

# Top-level app subpackages that must exist under obf/app/ (directory names).
_REQUIRED_APP_PACKAGES = (
    "api",
    "core",
    "db",
    "utils",
    "agent",
    "middleware",
)

# Modules imported early at runtime (smoke test via --validate-frozen).
_FROZEN_SMOKE_MODULES = (
    "secret",
    "app.main",
    "app.db.init_db",
    "app.utils.paths",
    "app.utils.frozen_metadata_shim",
    "app.core.license",
    "app.api.process",
)


def _rel(obf_root: Path, path: Path) -> str:
    return str(path.relative_to(obf_root)).replace("\\", "/")


def validate_single_entry_protection(obf_root: Path, entry_name: str = "start_backend.py") -> list[str]:
    """Fail if any obfuscated file other than the entry contains protection markers."""
    errors: list[str] = []
    offenders: list[str] = []
    entry = obf_root / entry_name
    if not entry.is_file():
        errors.append(f"missing entry script: {entry}")
        return errors

    for py in sorted(obf_root.rglob("*.py")):
        if py.name == "__init__.py" and "pytransform" in py.parts:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            errors.append(f"cannot read {_rel(obf_root, py)}: {e}")
            continue
        if not any(m in text for m in _PROTECTION_MARKERS):
            continue
        rel = _rel(obf_root, py)
        if rel.replace("\\", "/") == entry_name:
            continue
        offenders.append(rel)

    if offenders:
        errors.append(
            "PyArmor protection code found outside the single entry script "
            f"({entry_name}). These files must NOT be listed as pyarmor obfuscate "
            f"entry scripts (only --recursive obfuscation):\n  - "
            + "\n  - ".join(offenders)
        )
    return errors


def validate_obf_layout(obf_root: Path) -> list[str]:
    errors: list[str] = []
    app_root = obf_root / "app"
    if not app_root.is_dir():
        errors.append(f"missing obf app package: {app_root}")
        return errors

    for pkg in _REQUIRED_APP_PACKAGES:
        if not (app_root / pkg).is_dir():
            errors.append(f"missing obf app subpackage: app/{pkg}")

    secret = obf_root / "secret.py"
    if not secret.is_file():
        errors.append(f"missing obfuscated secret.py: {secret}")

    pytransform = obf_root / "pytransform" / "_pytransform.dll"
    if not pytransform.is_file():
        errors.append(f"missing pytransform runtime: {pytransform}")

    return errors


def validate_frozen_exe(exe: Path, timeout_sec: int = 120) -> list[str]:
    if not exe.is_file():
        return [f"frozen exe not found: {exe}"]
    proc = subprocess.run(
        [str(exe), "--validate-frozen"],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode == 0:
        return []
    detail = (proc.stderr or proc.stdout or "").strip()
    return [f"frozen smoke test failed (exit {proc.returncode}): {detail[:2000]}"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PyArmor obf tree / frozen exe")
    parser.add_argument("--obf-dir", type=Path, help="dist/_pyarmor_pyinstaller/obf")
    parser.add_argument("--exe", type=Path, help="dist/backend/lx_smartclip_backend.exe")
    parser.add_argument("--entry", default="start_backend.py", help="sole PyArmor entry script name")
    parser.add_argument("--skip-exe", action="store_true", help="skip frozen exe smoke test")
    args = parser.parse_args()

    errors: list[str] = []
    if args.obf_dir:
        obf = args.obf_dir.resolve()
        errors.extend(validate_obf_layout(obf))
        errors.extend(validate_single_entry_protection(obf, args.entry))

    if args.exe and not args.skip_exe:
        errors.extend(validate_frozen_exe(args.exe.resolve()))

    if not args.obf_dir and not args.exe:
        parser.error("provide --obf-dir and/or --exe")

    if errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("validation ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
