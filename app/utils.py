import subprocess
from pathlib import Path


def run(cmd, cwd=None) -> str:
    """Run a command (no shell). Raise RuntimeError with the stderr tail on failure."""
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"{Path(str(cmd[0])).name} failed:\n{tail}")
    return proc.stdout


def even(n: float) -> int:
    return int(n) // 2 * 2
