import argparse
import hashlib
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify frozen assets required by the R-ATTACK-0A-3 full replay."
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--size-only", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest)
    repo_root = Path(args.repo_root)
    container = Path(args.container)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    rows = []
    for item in manifest["assets"]:
        path = repo_root / item["path"]
        status = "ok"
        actual_size = None
        actual_sha256 = ""
        if not path.exists():
            status = "missing"
        elif not path.is_file():
            status = "not_a_file"
        else:
            actual_size = path.stat().st_size
            if actual_size != int(item["size_bytes"]):
                status = "size_mismatch"
            elif not args.size_only:
                actual_sha256 = sha256_file(path)
                if actual_sha256 != item["sha256"]:
                    status = "sha256_mismatch"
        rows.append(
            {
                **item,
                "status": status,
                "actual_size_bytes": actual_size,
                "actual_sha256": actual_sha256,
            }
        )

    missing_by_pack = {}
    for row in rows:
        if row["status"] == "ok":
            continue
        missing_by_pack.setdefault(row["asset_pack"], []).append(row["path"])

    summary = {
        "phase": "R-ATTACK-0A-3",
        "manifest": str(manifest_path),
        "repo_root": str(repo_root),
        "container": str(container),
        "container_exists": container.is_file(),
        "size_only": args.size_only,
        "asset_count": len(rows),
        "ok_count": sum(row["status"] == "ok" for row in rows),
        "problem_count": sum(row["status"] != "ok" for row in rows),
        "status_counts": {
            status: sum(row["status"] == status for row in rows)
            for status in sorted({row["status"] for row in rows})
        },
        "required_upload_packs": sorted(missing_by_pack),
        "problem_paths_by_pack": missing_by_pack,
        "ready": container.is_file() and not missing_by_pack,
        "assets": rows,
    }
    output = (
        Path(args.output)
        if args.output
        else manifest_path.with_name("r_attack0a3_remote_preflight.json")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary["ready"] else 2)


if __name__ == "__main__":
    main()
