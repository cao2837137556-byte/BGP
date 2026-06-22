import argparse
import hashlib
import json
from pathlib import Path


SOURCE_RUN_ID = "s2a_baseline_v01_pilot_6h_april16"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the frozen asset manifest for R-ATTACK-0A-3."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--output", default="configs/r_attack0a3_required_assets_manifest.json"
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    root = Path(args.repo_root).resolve()
    run_root = root / "data" / "runs" / SOURCE_RUN_ID
    raw_files = sorted(
        path
        for path in run_root.glob("collector=*/date=2024-04-16/updates__*.parquet")
        if "__rel" not in path.name
    )
    if len(raw_files) != 144:
        raise ValueError(f"expected 144 raw chunks, found {len(raw_files)}")

    background_files = [
        *raw_files,
        run_root / "baseline" / "baseline_prefix.parquet",
        run_root / "baseline" / "baseline_prefix_origin.parquet",
        run_root / "baseline" / "baseline_path.parquet",
        run_root / "baseline" / "baseline_summary.json",
        run_root / "events" / "event_units.parquet",
        run_root / "events" / "event_units_summary.json",
    ]
    evidence_files = [
        root / "data" / "evidence" / "rpki" / "vrp_2024-04-16.parquet",
        root / "data" / "evidence" / "rpki" / "vrp_2024-04-16.metadata.json",
        root
        / "data"
        / "evidence"
        / "as_relationships"
        / "as_rel_2024-04-01.parquet",
        root
        / "data"
        / "evidence"
        / "as_relationships"
        / "as_rel_2024-04-01.metadata.json",
    ]

    assets = []
    for pack, paths in (
        ("background_assets", background_files),
        ("evidence_assets", evidence_files),
    ):
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(path)
            assets.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "asset_pack": pack,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )

    pack_summary = {}
    for pack in sorted({item["asset_pack"] for item in assets}):
        selected = [item for item in assets if item["asset_pack"] == pack]
        pack_summary[pack] = {
            "file_count": len(selected),
            "total_bytes": sum(item["size_bytes"] for item in selected),
        }
    manifest = {
        "phase": "R-ATTACK-0A-3",
        "source_run_id": SOURCE_RUN_ID,
        "run_date": "2024-04-16",
        "asset_count": len(assets),
        "pack_summary": pack_summary,
        "container_expected_path": (
            "/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/"
            "containers/bgpstream-py-e9a.sif"
        ),
        "assets": assets,
    }
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **pack_summary}, indent=2))


if __name__ == "__main__":
    main()
