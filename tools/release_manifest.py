"""SHA-256 checksums for the files in Launch's GitHub releases, so a copy can be checked against the original.

Each release (`ledger` and every `ledger-YYYY-qN`) carries two small files that list every other file in it with its
size and SHA-256:

* `launch-manifest.json` (`launch-manifest/1`): repository, release, and per file its name, size, SHA-256 and when
  GitHub last saw it uploaded;
* `SHA256SUMS`, in the form `sha256sum` reads: `sha256sum -c SHA256SUMS --ignore-missing` checks the files beside it.

The workflow writes them after its uploads. A file it uploaded in the same run is hashed from the local copy and
must match the SHA-256 GitHub reports for the upload, or the step fails; any other file in the release is taken
from GitHub's own digest of it. Nothing in either file depends on the time it was written, so an unchanged release
gives the same bytes.

    python tools/release_manifest.py release <tag> --local-dir data/release-copy --local-dir data --out-dir <dir>
    python tools/release_manifest.py verify <dir>/launch-manifest.json --dir <downloads>

Standard library only (and the `gh` command in the workflow).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FORMAT = "launch-manifest/1"
SUMS = "SHA256SUMS"
JSON_NAME = "launch-manifest.json"
OWN = (SUMS, JSON_NAME)


def sha256_file(path: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


class Mismatch(ValueError):
    pass


def build(repo: str, tag: str, assets: list[dict], local_dirs: tuple[Path, ...] = ()) -> dict:
    """The manifest of one release from GitHub's asset list (name, size, digest 'sha256:<hex>', updated_at).

    A file with a local copy in one of `local_dirs` (the first that has it) is hashed here and checked against
    GitHub's size and digest."""
    files = []
    for a in sorted(assets, key=lambda a: a["name"]):
        name = a["name"]
        if name in OWN:
            continue
        digest = (a.get("digest") or "")
        remote = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
        local = next((d / name for d in local_dirs if (d / name).is_file()), None)
        if local is not None:
            sha, size = sha256_file(local)
            if size != a.get("size") or (remote and remote != sha):
                raise Mismatch(f"{tag}/{name}: the local copy (sha256 {sha}, {size} bytes) is not what GitHub holds "
                               f"(sha256 {remote}, {a.get('size')} bytes)")
        elif remote:
            sha, size = remote, a.get("size")
        else:
            raise Mismatch(f"{tag}/{name}: GitHub gives no SHA-256 and there is no local copy to hash")
        files.append({"name": name, "size": size, "sha256": sha, "updated_at": a.get("updated_at")})
    return {"format": FORMAT, "repository": repo, "release": tag, "algorithm": "sha256",
            "how_to_check": f"sha256sum -c {SUMS} --ignore-missing (Linux), shasum -a 256 -c {SUMS} (macOS), or "
                            "Get-FileHash <file> -Algorithm SHA256 (PowerShell) and compare with sha256 here.",
            "files": files}


def sums_text(manifest: dict) -> str:
    """Two spaces between hash and name, as sha256sum writes and reads it (text mode)."""
    return "".join(f"{f['sha256']}  {f['name']}\n" for f in manifest["files"])


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def verify(manifest: dict, folder: Path) -> list[str]:
    """Problems with the files in `folder` that the manifest names (a file not there is skipped)."""
    problems = []
    for f in manifest["files"]:
        p = folder / f["name"]
        if not p.is_file():
            continue
        sha, size = sha256_file(p)
        if sha != f["sha256"] or size != f["size"]:
            problems.append(f"{f['name']}: sha256 {sha}, {size} bytes; the manifest says {f['sha256']}, {f['size']}")
    return problems


def _gh(*args: str) -> str:
    return subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def _gh_assets(repo: str, tag: str) -> list[dict]:
    """Every asset of the release, all pages (a quarter of dated copies passes one page of 100)."""
    release_id = _gh(f"repos/{repo}/releases/tags/{tag}", "--jq", ".id").strip()
    out = _gh("--paginate", f"repos/{repo}/releases/{release_id}/assets?per_page=100", "--jq", ".[]")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def release(repo: str, tag: str, out_dir: Path, local_dirs: tuple[Path, ...] = (),
            assets: list[dict] | None = None) -> bool:
    """Write the two files for one release into out_dir. True when they differ from what the release holds."""
    assets = _gh_assets(repo, tag) if assets is None else assets
    m = build(repo, tag, assets, local_dirs)
    out_dir.mkdir(parents=True, exist_ok=True)
    body, sums = manifest_bytes(m), sums_text(m).encode("utf-8")
    (out_dir / JSON_NAME).write_bytes(body)
    (out_dir / SUMS).write_bytes(sums)
    held = {a["name"]: (a.get("digest") or "") for a in assets}
    return (held.get(JSON_NAME) != "sha256:" + hashlib.sha256(body).hexdigest()
            or held.get(SUMS) != "sha256:" + hashlib.sha256(sums).hexdigest())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SHA-256 manifests for Launch's releases.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("release", help="write launch-manifest.json and SHA256SUMS for one release")
    r.add_argument("tag")
    r.add_argument("--repo", default="metacog-osint/launch")
    r.add_argument("--out-dir", required=True)
    r.add_argument("--local-dir", action="append", default=[],
                   help="folder holding files uploaded this run, hashed and checked against GitHub (repeatable)")
    v = sub.add_parser("verify", help="check downloaded files against a launch-manifest.json")
    v.add_argument("manifest")
    v.add_argument("--dir", default=".")
    args = ap.parse_args(argv)
    if args.cmd == "release":
        changed = release(args.repo, args.tag, Path(args.out_dir), tuple(Path(d) for d in args.local_dir))
        print("changed" if changed else "unchanged")
        return 0
    m = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    problems = verify(m, Path(args.dir))
    for p in problems:
        print(p, file=sys.stderr)
    print(f"{len(m['files'])} files listed; {len(problems)} do not match")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
