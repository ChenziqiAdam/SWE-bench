#!/usr/bin/env python3
"""After ingest, check which repo/version combos appear and flag missing specs."""
import json, sys

try:
    from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
except ImportError:
    MAP_REPO_VERSION_TO_SPECS = {}

instances_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/full_run/instances.jsonl"

versions = {}
with open(instances_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        inst = json.loads(line)
        repo = inst.get("repo", "")
        ver = inst.get("version", "UNKNOWN")
        key = (repo, ver)
        versions[key] = versions.get(key, 0) + 1

print(f"\n{'Repo':<40} {'Version':<12} {'Count':>6}  {'Spec?':>6}")
print("-" * 70)
missing = []
for (repo, ver), count in sorted(versions.items()):
    has_spec = repo in MAP_REPO_VERSION_TO_SPECS and ver in MAP_REPO_VERSION_TO_SPECS[repo]
    flag = "✓" if has_spec else "✗ MISSING"
    print(f"{repo:<40} {ver:<12} {count:>6}  {flag}")
    if not has_spec:
        missing.append((repo, ver, count))

if missing:
    print(f"\n⚠  {len(missing)} repo/version combo(s) missing specs — Docker eval will fail for these instances:")
    for repo, ver, count in missing:
        print(f"   {repo} v{ver} ({count} instances)")
else:
    print("\n✓ All versions have specs.")
