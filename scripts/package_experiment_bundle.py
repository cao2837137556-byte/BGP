import argparse
import json
import shutil
from pathlib import Path


RUN_SUMMARY_FILES = [
    "run.json",
    "events/event_units_summary.json",
    "baseline/baseline_summary.json",
    "candidates/candidate_summary.json",
    "scores/score_summary.json",
    "gating/gating_summary.json",
    "augmentation/augmentation_summary.json",
    "final/final_report.json",
]


def copy_path(src: Path, dst_root: Path, workdir: Path) -> str:
    src = src.resolve()
    try:
        rel = src.relative_to(workdir.resolve())
    except ValueError:
        rel = Path(src.name)
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return rel.as_posix()


def main() -> None:
    ap = argparse.ArgumentParser(description="Package experiment outputs and run summaries into a single zip bundle.")
    ap.add_argument("--bundle-name", required=True, help="Bundle base name, e.g. e9a_tuned_compare_v01")
    ap.add_argument("--output-dir", default="outputs/bundles", help="Directory for generated bundle.")
    ap.add_argument("--path", action="append", default=[], help="Repo-relative file or directory to include. Repeatable.")
    ap.add_argument("--run-id", action="append", default=[], help="Run ids under data/runs/<run_id> to include summaries for. Repeatable.")
    ap.add_argument("--include-run-summaries", default="true", help="Whether to include standard run summary files.")
    args = ap.parse_args()

    workdir = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_root = output_dir / f"{args.bundle_name}_stage"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, list[str]] = {"paths": [], "run_summaries": []}

    for raw in args.path:
        src = Path(raw)
        if not src.exists():
            raise SystemExit(f"path not found: {src}")
        manifest["paths"].append(copy_path(src, stage_root, workdir))

    if str(args.include_run_summaries).strip().lower() in {"1", "true", "yes", "y", "on"}:
        for run_id in args.run_id:
            run_dir = workdir / "data" / "runs" / run_id
            if not run_dir.exists():
                raise SystemExit(f"run dir not found: {run_dir}")
            for rel in RUN_SUMMARY_FILES:
                src = run_dir / rel
                if src.exists():
                    manifest["run_summaries"].append(copy_path(src, stage_root, workdir))

    manifest_path = stage_root / "bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    archive_base = output_dir / args.bundle_name
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=stage_root)
    print(f"bundle_stage={stage_root}")
    print(f"bundle_zip={archive_path}")


if __name__ == "__main__":
    main()
