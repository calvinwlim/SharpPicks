"""One-command refresh of all bundled UFC data after new events.

Runs the four builders in dependency order — dataset -> winmodel -> finishmodel
-> comps — so you don't have to remember the sequence. Streams each builder's
output, and exits non-zero the moment one fails so a scheduled run surfaces the
problem instead of silently shipping stale data.

    python scripts/refresh_mma_data.py

Schedule it weekly (UFC cards are ~weekly) so the fighter dataset stays current
and you stop hitting "no rate-stat data for <fighter>". Run it midweek so the
public ufcstats mirror has caught up after the weekend's card. On Windows,
register a Task Scheduler job (run once from the repo root):

    schtasks /Create /TN "SharpPicks-MMA-refresh" /SC WEEKLY /D TUE /ST 06:00 /F ^
      /TR "\"%CD%\.venv\Scripts\python.exe\" \"%CD%\scripts\refresh_mma_data.py\""

On macOS/Linux, a weekly crontab line (Tuesdays 06:00):

    0 6 * * 2  cd /path/to/SharpPicks && .venv/bin/python scripts/refresh_mma_data.py

Note: the builders rewrite the four files under backend/data/, so after a run
you'll have uncommitted changes to review and commit.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDERS = [
    "build_ufc_dataset.py",       # fighter rate stats -> ufc_fighters.json
    "build_mma_winmodel.py",      # winner logistic    -> ufc_winmodel.json
    "build_mma_finishmodel.py",   # distance / KO|finish-> ufc_finishmodel.json
    "build_mma_comps.py",         # matchup vectors    -> ufc_fight_vectors.json
]


def main() -> int:
    start = time.time()
    print(f"[refresh] {time.strftime('%Y-%m-%d %H:%M:%S')} refreshing UFC data in {ROOT}")
    for name in BUILDERS:
        script = ROOT / "scripts" / name
        print(f"\n[refresh] === running {name} ===", flush=True)
        result = subprocess.run([sys.executable, str(script)], cwd=str(ROOT))
        if result.returncode != 0:
            print(f"\n[refresh] FAILED at {name} (exit {result.returncode}) — aborting, "
                  f"data left as-is.", file=sys.stderr)
            return result.returncode
    print(f"\n[refresh] done — all {len(BUILDERS)} builders succeeded in "
          f"{time.time() - start:.0f}s. Review & commit backend/data/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
