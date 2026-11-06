"""Publish a checked game pack and render the official download index."""

import argparse
from datetime import datetime, timezone
from hashlib import file_digest
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import quote


REGISTRY = Path("registry.json")
SOURCE = "https://github.com/gray-raven-star/ApexAudio"


def read_registry():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if registry["schemaVersion"] != 1:
        raise ValueError("Unsupported registry schema")
    return registry


def version_key(version):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError(f"Invalid package version: {version}")
    return tuple(map(int, version.split(".")))


def gh(*args):
    return subprocess.check_output(["gh", *args], encoding="utf-8").strip()


def checksum(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def publish(directory, slug, version):
    pack = json.loads((directory / "package.json").read_text(encoding="utf-8-sig"))
    version_key(version)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or (slug, version) != (pack["slug"], pack["version"]):
        raise ValueError("The checked package does not match the requested slug and version")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,79}", pack["packId"]):
        raise ValueError("Invalid package ID")
    if not re.fullmatch(r"[0-9a-f]{40}", pack["sourceCommit"]):
        raise ValueError("Invalid source commit")

    registry = read_registry()
    for entry in registry["packs"]:
        if (entry["slug"] == slug) != (entry["packId"] == pack["packId"]):
            raise ValueError("The slug and package ID disagree with the registry")

    repo = os.environ["GITHUB_REPOSITORY"]
    tag = f"pack/{slug}/v{version}"
    notes = f'Source: {SOURCE}/tree/{pack["sourceCommit"]}/gamepacks/{slug}'
    asset = directory / f'{pack["packId"]}.gpack'
    sums = asset.with_suffix(".sha256")
    sums.write_text(f"{checksum(asset)}  {asset.name}\n", encoding="utf-8")

    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    release = next((item for page in pages for item in page if item["tag_name"] == tag), None)
    if release is None:
        gh("release", "create", tag, "--repo", repo, "--target", os.environ["GITHUB_SHA"],
           "--draft", "--title", f'{pack["game"]} v{version}', "--notes", notes)
    elif release["body"].strip() != notes:
        raise ValueError(f"Release {tag} already exists with different source provenance")

    if release is None or release["draft"]:
        gh("release", "upload", tag, str(asset), str(sums), "--repo", repo, "--clobber")
        gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest=false")

    # The public attachments are authoritative on retries, including non-reproducible rebuilds.
    with TemporaryDirectory() as temp:
        gh("release", "download", tag, "--repo", repo, "--dir", temp,
           "--pattern", asset.name, "--pattern", sums.name)
        digest = checksum(Path(temp) / asset.name)
        if (Path(temp) / sums.name).read_text(encoding="utf-8").split() != [digest, asset.name]:
            raise ValueError(f"Release {tag} has an invalid checksum attachment")

    release_url = f"https://github.com/{repo}/releases/tag/{tag}"
    entry = {
        **pack,
        "sourceUrl": notes.removeprefix("Source: "),
        "releaseUrl": release_url,
        "downloadUrl": f"https://github.com/{repo}/releases/download/{tag}/{quote(asset.name)}",
        "sha256": digest,
    }
    entries = registry["packs"]
    previous = next((item for item in entries if (item["slug"], item["version"]) == (slug, version)), None)
    if previous == entry:
        return
    if previous is not None:
        entries.remove(previous)
    entries.append(entry)
    entries.sort(key=lambda item: (item["slug"], version_key(item["version"])))
    registry["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render(output):
    registry = read_registry()
    games = {}
    for pack in registry["packs"]:
        games.setdefault(pack["slug"], []).append(pack)

    rows = []
    for releases in games.values():
        releases.sort(key=lambda pack: version_key(pack["version"]), reverse=True)
        latest = releases[0]
        history = "".join(
            f'<li><a href="{escape(pack["releaseUrl"])}">v{escape(pack["version"])}</a></li>'
            for pack in releases
        )
        builds = "<br>".join(
            f'{escape(build["executable"])} <code>{escape(build["sha256"])}</code>'
            for build in latest["compatibility"]["gameBuilds"]
        )
        rows.append(
            f'<tr><th scope="row">{escape(latest["game"])}</th><td>{escape(latest["version"])}</td>'
            f'<td>{escape(latest["engine"])}</td><td>{builds or "Unknown"}</td>'
            f'<td><a href="{escape(latest["downloadUrl"])}">Download</a></td>'
            f'<td><details><summary>Releases</summary><ul>{history}</ul></details></td></tr>'
        )

    body = "".join(rows) or '<tr><td colspan="6">No official packs have been published here yet.</td></tr>'
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ApexAudio GamePacks</title>
<style>
body {{ font: 1rem system-ui, sans-serif; margin: 2rem auto; max-width: 75rem; padding: 0 1rem; }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th, td {{ border-bottom: 1px solid gray; padding: .6rem; vertical-align: top; }}
code {{ overflow-wrap: anywhere; }}
</style>
<h1>ApexAudio GamePacks</h1>
<p>Official packages for <a href="{SOURCE}">ApexAudio</a> · <a href="registry.json">JSON registry</a></p>
<table>
<thead><tr><th>Game</th><th>Latest</th><th>Engine</th><th>Game builds (SHA-256)</th><th>Package</th><th>History</th></tr></thead>
<tbody>{body}</tbody>
</table>
</html>
""", encoding="utf-8")
    (output / "registry.json").write_bytes(REGISTRY.read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish_command = commands.add_parser("publish")
    publish_command.add_argument("directory", type=Path)
    publish_command.add_argument("slug")
    publish_command.add_argument("version")
    render_command = commands.add_parser("render")
    render_command.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "publish":
        publish(args.directory, args.slug, args.version)
    else:
        render(args.directory)
