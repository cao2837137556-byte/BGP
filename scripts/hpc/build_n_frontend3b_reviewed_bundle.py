#!/usr/bin/env python3
"""Build a deterministic git-archive N-FRONTEND-3B review bundle."""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from n_frontend3b_contract import PACKAGE_PATHS
INCLUDE_PATHS = PACKAGE_PATHS


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=text)


def missing_local_imports(
    tracked: set[str], files: dict[str, bytes]
) -> list[dict[str, str]]:
    local_modules = {
        Path(path).stem: path
        for path in tracked
        if path.startswith("scripts/")
        and path.count("/") == 1
        and path.endswith(".py")
    }
    missing: list[dict[str, str]] = []
    for source_path, content in files.items():
        if not source_path.endswith(".py"):
            continue
        tree = ast.parse(content.decode("utf-8"), filename=source_path)
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        for module in sorted(imported_roots):
            dependency = local_modules.get(module)
            if dependency and dependency not in files:
                missing.append(
                    {
                        "source": source_path,
                        "module": module,
                        "required_path": dependency,
                    }
                )
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-commit")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    output = Path(args.output).resolve()
    commit = str(git(repo, "rev-parse", "HEAD")).strip()
    if args.expected_commit and commit != args.expected_commit:
        raise SystemExit(f"HEAD mismatch: expected {args.expected_commit}, observed {commit}")
    tracked = set(str(git(repo, "ls-tree", "-r", "--name-only", commit)).splitlines())
    missing = sorted(set(INCLUDE_PATHS) - tracked)
    if missing:
        raise SystemExit(f"bundle paths are not committed: {missing}")

    entries = []
    files: dict[str, bytes] = {}
    for path in INCLUDE_PATHS:
        content = git(repo, "show", f"{commit}:{path}", text=False)
        assert isinstance(content, bytes)
        canonical = content.replace(b"\r\n", b"\n")
        blob_oid = str(git(repo, "rev-parse", f"{commit}:{path}")).strip()
        entries.append(
            {
                "path": path,
                "git_blob_oid": blob_oid,
                "canonical_lf_sha256": sha256(canonical),
                "packaged_sha256": sha256(content),
                "line_ending_normalized_equal": canonical == content,
            }
        )
        files[path] = content
    import_closure_failures = missing_local_imports(tracked, files)
    if import_closure_failures:
        raise SystemExit(
            "review bundle omits repository-local Python imports: "
            + json.dumps(import_closure_failures, sort_keys=True)
        )
    manifest = {
        "phase": "N-FRONTEND-3B",
        "source_commit": commit,
        "line_ending_policy": "git-archive committed bytes; text inputs must equal LF-normalized bytes",
        "git_archive_or_lf_normalized": True,
        "all_entries_passed": all(entry["line_ending_normalized_equal"] for entry in entries),
        "local_python_import_closure_passed": True,
        "entries": entries,
    }
    if not manifest["all_entries_passed"]:
        raise SystemExit("one or more committed files are not canonical LF bytes")
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    files["N_FRONTEND3B_PACKAGE_MANIFEST.json"] = manifest_bytes

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        with tarfile.open(temp_path, "w") as archive:
            for path in sorted(files):
                value = files[path]
                info = tarfile.TarInfo(path)
                info.size = len(value)
                info.mode = 0o755 if path.endswith((".sh", ".py")) else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(value))
        with temp_path.open("rb") as source, output.open("wb") as raw_output:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw_output,
                mtime=0,
            ) as compressed:
                shutil.copyfileobj(source, compressed)
    finally:
        temp_path.unlink(missing_ok=True)
    sidecar = output.with_suffix(output.suffix + ".sha256")
    sidecar.write_text(f"{sha256(output.read_bytes())}  {output.name}\n", encoding="ascii")
    receipt = output.with_suffix(output.suffix + ".receipt.json")
    receipt.write_text(json.dumps({
        "source_commit": commit, "bundle_sha256": sha256(output.read_bytes()),
        "package_manifest_sha256": sha256(manifest_bytes),
    }, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(f"bundle={output}")
    print(f"sha256={sha256(output.read_bytes())}")
    print(f"source_commit={commit}")
    print(f"package_manifest_sha256={sha256(manifest_bytes)}")


if __name__ == "__main__":
    main()
