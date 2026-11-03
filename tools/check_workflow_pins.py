"""Review guard: remote actions are immutable and checkout leaves no Git token."""

from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
count = 0
for workflow in sorted((root / ".github/workflows").glob("*.yml")):
    lines = workflow.read_text(encoding="utf8").splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", line)
        if not match:
            continue
        action = match[1].strip("'\"")
        if action.startswith("./"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[a-f0-9]{40}", action):
            raise ValueError(f"Unpinned remote action in {workflow.name}:{i + 1}")
        count += 1
        if action.startswith("actions/checkout@"):
            following = []
            indent = len(line) - len(line.lstrip())
            for candidate in lines[i + 1 :]:
                if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                    break
                following.append(candidate)
            if not re.search(r"^\s*persist-credentials:\s*false\s*$", "\n".join(following), re.M):
                raise ValueError(f"Checkout persists Git credentials in {workflow.name}:{i + 1}")
if not count:
    raise ValueError("No pinned remote actions were checked")
print(f"{count} remote action references pinned; checkout credential persistence disabled")
