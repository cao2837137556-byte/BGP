import argparse
import bz2
import gzip
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


ASN_RE = re.compile(r"\d+")


def open_text_any(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("r", encoding="utf-8", errors="ignore")


def load_caida_rel(path: Path) -> dict:
    # rel meaning:
    # -1: as1 is provider, as2 is customer (p2c for as1->as2)
    #  0: peer-to-peer
    #  1: as1 is customer, as2 is provider (c2p for as1->as2)
    rel_map = {}
    with open_text_any(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            try:
                as1 = int(parts[0])
                as2 = int(parts[1])
                rel = int(parts[2])
            except ValueError:
                continue

            if rel == 0:
                rel_map[(as1, as2)] = "p2p"
                rel_map[(as2, as1)] = "p2p"
            elif rel == -1:
                rel_map[(as1, as2)] = "p2c"
                rel_map[(as2, as1)] = "c2p"
            elif rel == 1:
                rel_map[(as1, as2)] = "c2p"
                rel_map[(as2, as1)] = "p2c"
    return rel_map


def parse_as_path(value) -> list:
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []

    s = str(value)
    if not s or s.lower() == "nan":
        return []

    nums = [int(x) for x in ASN_RE.findall(s)]
    if not nums:
        return []

    cleaned = []
    prev = None
    for n in nums:
        if n != prev:
            cleaned.append(n)
            prev = n
    return cleaned


def add_suffix(path: Path, suffix: str) -> Path:
    return path.with_name(path.stem + suffix + path.suffix)


def annotate_df(df: pd.DataFrame, rel_map: dict) -> pd.DataFrame:
    if "as_path" not in df.columns:
        raise ValueError("missing column: as_path")

    as_path_clean = []
    origin_as = []
    as_path_len = []
    rel_seq = []
    rel_unknown_cnt = []
    rel_has_unknown = []

    for raw in df["as_path"]:
        seq = parse_as_path(raw)
        if seq:
            as_path_clean.append(" ".join(str(x) for x in seq))
            origin_as.append(seq[-1])
            as_path_len.append(len(seq))
            if len(seq) > 1:
                rels = [rel_map.get((seq[i], seq[i + 1]), "unk") for i in range(len(seq) - 1)]
                rel_seq.append("|".join(rels))
                unk_cnt = sum(1 for r in rels if r == "unk")
                rel_unknown_cnt.append(unk_cnt)
                rel_has_unknown.append(unk_cnt > 0)
            else:
                rel_seq.append("")
                rel_unknown_cnt.append(0)
                rel_has_unknown.append(False)
        else:
            as_path_clean.append("")
            origin_as.append(None)
            as_path_len.append(0)
            rel_seq.append("")
            rel_unknown_cnt.append(0)
            rel_has_unknown.append(False)

    df = df.copy()
    df["as_path_clean"] = as_path_clean
    df["origin_as"] = origin_as
    df["as_path_len"] = as_path_len
    df["rel_seq"] = rel_seq
    df["rel_unknown_cnt"] = rel_unknown_cnt
    df["rel_has_unknown"] = rel_has_unknown
    return df


def annotate_file(in_path: Path, rel_map: dict, suffix: str, overwrite: bool, print_head: int):
    out_path = add_suffix(in_path, suffix)
    if out_path.exists() and not overwrite:
        print(f"[SKIP] exists: {out_path}")
        return None

    df = pd.read_parquet(in_path)
    df = annotate_df(df, rel_map)
    df.to_parquet(out_path, index=False)

    print(f"[OK] {in_path} -> {out_path}")
    if print_head:
        print(df.head(print_head).to_string(index=False))
    return out_path


def iter_parquet_files(run_dir: Path, suffix: str):
    for path in run_dir.rglob("*.parquet"):
        if path.stem.endswith(suffix):
            continue
        yield path


def update_run_json(run_dir: Path, caida_rel: Path, suffix: str, outputs: list):
    run_json = run_dir / "run.json"
    if not run_json.exists():
        return

    data = {}
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}

    data["caida_annotation"] = {
        "caida_rel_file": str(caida_rel).replace("\\", "/"),
        "suffix": suffix,
        "outputs": [str(p).replace("\\", "/") for p in outputs],
        "annotated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    run_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(
        description="Annotate updates parquet with CAIDA AS-relationship labels."
    )
    ap.add_argument("--in", dest="in_file", help="Annotate a single parquet file.")
    ap.add_argument("--run-dir", dest="run_dir", help="Annotate all parquet files under a run directory.")
    ap.add_argument(
        "--caida-rel",
        default="data/caida/as-relationships/serial-2/20170701.as-rel2.txt",
        help="Path to CAIDA as-rel2 file (txt/gz/bz2).",
    )
    ap.add_argument("--suffix", default="__rel")
    ap.add_argument("--overwrite", action="store_true", help="Allow overwriting output parquet.")
    ap.add_argument("--print-head", type=int, default=0, help="Print head(N) after annotation.")

    args = ap.parse_args()
    if (args.in_file and args.run_dir) or (not args.in_file and not args.run_dir):
        raise SystemExit("Please pass exactly one of --in or --run-dir.")

    caida_rel = Path(args.caida_rel)
    if not caida_rel.exists():
        raise SystemExit(f"CAIDA file not found: {caida_rel}")

    rel_map = load_caida_rel(caida_rel)

    outputs = []
    if args.in_file:
        in_path = Path(args.in_file)
        if not in_path.exists():
            raise SystemExit(f"Input not found: {in_path}")
        out = annotate_file(in_path, rel_map, args.suffix, args.overwrite, args.print_head)
        if out is not None:
            outputs.append(out)
    else:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            raise SystemExit(f"Run dir not found: {run_dir}")
        for path in iter_parquet_files(run_dir, args.suffix):
            out = annotate_file(path, rel_map, args.suffix, args.overwrite, args.print_head)
            if out is not None:
                outputs.append(out)
        update_run_json(run_dir, caida_rel, args.suffix, outputs)

    print(f"[DONE] outputs={len(outputs)}")


if __name__ == "__main__":
    main()
