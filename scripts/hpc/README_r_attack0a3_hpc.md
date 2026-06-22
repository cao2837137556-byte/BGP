# R-ATTACK-0A-3 HPC Handoff

Remote base:

```text
/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline
```

Expected container:

```text
containers/bgpstream-py-e9a.sif
```

## Upload Order

1. Upload and extract the small code bundle into `repo/`.
2. Run the preflight.
3. Read `required_upload_packs` in
   `logs/r_attack0a3_remote_preflight.json`.
4. Upload/extract only the reported asset packs.
5. Rerun preflight, then submit the Slurm job.

Do not upload the complete old run directory. The background pack contains only:

- 144 clean raw chunks;
- three baseline parquet tables plus summary;
- clean baseline event parquet plus summary.

The evidence pack contains only:

- RPKI/VRP `2024-04-16`;
- CAIDA AS-rel `2024-04-01`;
- their metadata files.

## Remote Commands

```bash
BASE=/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline
cd "$BASE/repo"
tar -xzf /path/to/r_attack0a3_code_bundle.tar.gz
bash scripts/hpc/r_attack0a3_preflight.sh
```

If preflight reports a missing pack:

```bash
cd "$BASE/repo"
tar -xzf /path/to/r_attack0a3_background_assets.tar.gz
tar -xzf /path/to/r_attack0a3_evidence_assets.tar.gz
bash scripts/hpc/r_attack0a3_preflight.sh
```

Submit only after preflight succeeds:

```bash
cd "$BASE/repo"
JOB_ID=$(sbatch --parsable scripts/hpc/r_attack0a3_full_replay.slurm)
echo "$JOB_ID"
squeue -j "$JOB_ID"
```

Status and logs:

```bash
sacct -j "$JOB_ID" --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS
tail -f "$BASE/logs/r_attack0a3_${JOB_ID}.live.log"
```

Successful small result bundle:

```text
repo/outputs/r_attack_0a3/
  s2a_attack0a2_hardened_origin_smoke_6h_april16_v02/
    full_replay_validation.json
    r_attack0a3_small_results.tar.gz
```

The job refuses to run if the derived run or output directory already exists.
It does not overwrite the clean source run.
