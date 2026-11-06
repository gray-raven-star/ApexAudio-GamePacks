"""Publish a checked game pack and generate the README download table."""

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
import urllib.request


REGISTRY = Path("registry.json")
README = Path("README.md")
SOURCE = "https://github.com/gray-raven-star/ApexAudio"
RAW_BASE = "https://raw.githubusercontent.com/gray-raven-star/ApexAudio"
START = "<!-- BEGIN GENERATED DOWNLOADS -->"
END = "<!-- END GENERATED DOWNLOADS -->"
TAG_PATTERN = re.compile(
    r"pack/([a-z0-9]+(?:-[a-z0-9]+)*)/v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))"
)
DIGEST_PATTERN = re.compile(r"sha256:([0-9a-fA-F]{64})")


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


def releases_by_tag():
    repo = os.environ["GITHUB_REPOSITORY"]
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    return {release["tag_name"]: release for page in pages for release in page}


def raw_json(commit, path):
    request = urllib.request.Request(
        f"{RAW_BASE}/{commit}/{path}",
        headers={"User-Agent": "ApexAudio-distribution"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def source_commit(body, slug):
    match = re.fullmatch(
        rf"Source: {re.escape(SOURCE)}/tree/([0-9a-f]{{40}})/gamepacks/{re.escape(slug)}",
        (body or "").strip(),
    )
    return match[1] if match else None


def digest_of(release, name):
    for asset in release.get("assets") or []:
        if asset.get("name") != name:
            continue
        match = DIGEST_PATTERN.fullmatch(asset.get("digest") or "")
        if match:
            return match[1].lower()
        break
    raise ValueError(f"Release {release['tag_name']} has no SHA-256 digest for {name}")


def recover_package(release, slug, version, raw=raw_json):
    tag = release["tag_name"]
    commit = source_commit(release.get("body"), slug)
    if not commit:
        raise ValueError(f"Cannot recover {tag} without its source commit")
    manifest = raw(commit, f"gamepacks/{slug}/manifest.json")
    game = raw(commit, f"gamepacks/{slug}/game.json")
    if manifest.get("version") != version:
        raise ValueError(f"{tag} does not match the manifest version")
    pack_id = manifest.get("id", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,79}", pack_id):
        raise ValueError(f"{tag} has an invalid package ID")
    asset = f"{pack_id}.gpack"
    repo = os.environ["GITHUB_REPOSITORY"]
    source = f"{SOURCE}/tree/{commit}/gamepacks/{slug}"
    return {
        "game": manifest["name"],
        "sourceCommit": commit,
        "version": version,
        "packId": pack_id,
        "slug": slug,
        "compatibility": {"gameBuilds": manifest.get("games", [])},
        "engine": game.get("backend", ""),
        "sourceUrl": source,
        "releaseUrl": f"https://github.com/{repo}/releases/tag/{tag}",
        "downloadUrl": f"https://github.com/{repo}/releases/download/{tag}/{quote(asset)}",
        "sha256": digest_of(release, asset),
    }


def bump_version(latest, slug, version):
    latest[slug] = max(latest.get(slug, (0, 0, 0)), version_key(version))


def discover(source, indexed, releases, thresholds=None):
    source_ref = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    latest = {}
    for pack in indexed:
        bump_version(latest, pack["slug"], pack["version"])
    for slug, version in (thresholds or {}).items():
        bump_version(latest, slug, version)

    selected = []
    for manifest in sorted((source / "gamepacks").glob("*/manifest.json")):
        slug = manifest.parent.name
        if slug.startswith("_"):
            continue
        version = json.loads(manifest.read_text(encoding="utf-8-sig"))["version"]
        if version_key(version) <= latest.get(slug, (0, 0, 0)):
            continue
        ref = source_ref
        previous = releases.get(f"pack/{slug}/v{version}")
        if previous:
            # A prior run may have published the assets before its registry commit failed.
            commit = source_commit(previous.get("body"), slug)
            if not commit:
                raise ValueError(f"Cannot recover {previous['tag_name']} without its source commit")
            ref = commit
        selected.append({"slug": slug, "version": version, "source_ref": ref})
    return selected


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

    release = releases_by_tag().get(tag)
    if release is None:
        gh("release", "create", tag, "--repo", repo, "--target", os.environ["GITHUB_SHA"],
           "--draft", "--title", f'适配包：{pack["game"]} v{version}', "--notes", notes)
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
    thresholds = registry.setdefault("thresholds", {})
    if version_key(version) > version_key(thresholds.get(slug, "0.0.0")):
        thresholds[slug] = version
    registry["thresholds"] = dict(sorted(thresholds.items()))
    registry["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reconcile(registry, releases, raw=raw_json):
    """Align the index with the public releases and remember removed versions."""
    latest = {}
    for slug, version in (registry.get("thresholds") or {}).items():
        bump_version(latest, slug, version)

    kept = []
    removed = []
    for pack in registry["packs"]:
        bump_version(latest, pack["slug"], pack["version"])
        tag = f'pack/{pack["slug"]}/v{pack["version"]}'
        release = releases.get(tag)
        if release is None or release.get("draft"):
            removed.append(tag)
        else:
            kept.append(pack)

    present = {(pack["slug"], pack["version"]) for pack in kept}
    recovered = []
    warnings = []
    for tag in sorted(releases):
        release = releases[tag]
        if release.get("draft"):
            continue
        match = TAG_PATTERN.fullmatch(tag)
        if not match:
            continue
        slug, version = match.groups()
        bump_version(latest, slug, version)
        if (slug, version) in present:
            continue
        try:
            entry = recover_package(release, slug, version, raw)
        except Exception as error:  # A single bad release must not block the whole scan.
            warnings.append(f"{tag}: {error}")
            continue
        kept.append(entry)
        recovered.append(tag)

    kept.sort(key=lambda pack: (pack["slug"], version_key(pack["version"])))
    thresholds = {slug: ".".join(map(str, version)) for slug, version in sorted(latest.items())}
    changed = kept != registry["packs"] or thresholds != (registry.get("thresholds") or {})
    if changed:
        registry["packs"] = kept
        registry["thresholds"] = thresholds
        registry["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"removed": removed, "recovered": recovered, "warnings": warnings, "changed": changed}


def markdown_cell(value):
    text = escape(" ".join(value.split())).replace("|", "&#124;")
    return re.sub(r"([\\`*_\[\]~])", r"\\\1", text)


def markdown_link(label, url):
    if not url.startswith("https://github.com/"):
        raise ValueError(f"Expected a GitHub download or release URL: {url}")
    return f"[{label}](<{quote(url, safe=':/%.-_~')}>)"


def render(check):
    registry = read_registry()
    games = {}
    for pack in registry["packs"]:
        games.setdefault(pack["slug"], []).append(pack)

    rows = [
        "| Game | Latest | Engine | Game builds (SHA-256) | Package | History |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for _, releases in sorted(games.items()):
        releases.sort(key=lambda pack: version_key(pack["version"]), reverse=True)
        latest = releases[0]
        history = ", ".join(
            markdown_link(f'v{pack["version"]}', pack["releaseUrl"])
            for pack in releases
        )
        builds = "<br>".join(
            f'{markdown_cell(build["executable"])} <code>{markdown_cell(build["sha256"])}</code>'
            for build in latest["compatibility"]["gameBuilds"]
        )
        cells = (
            markdown_cell(latest["game"]), latest["version"], markdown_cell(latest["engine"]),
            builds or "Unknown", markdown_link("Download", latest["downloadUrl"]), history,
        )
        rows.append("| " + " | ".join(cells) + " |")

    body = "\n".join(rows) if games else "No official packs have been published here yet."
    readme = README.read_text(encoding="utf-8")
    if readme.count(START) != 1 or readme.count(END) != 1 or readme.index(START) > readme.index(END):
        raise ValueError("README must contain one ordered pair of generated-download markers")
    prefix = readme.split(START, 1)[0]
    suffix = readme.split(END, 1)[1]
    expected = f"{prefix}{START}\n\n{body}\n\n{END}{suffix}"
    if check and readme != expected:
        raise SystemExit("README download table is stale. Run python scripts/distribution.py render.")
    if readme != expected:
        README.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish_command = commands.add_parser("publish")
    publish_command.add_argument("directory", type=Path)
    publish_command.add_argument("slug")
    publish_command.add_argument("version")
    discover_command = commands.add_parser("discover")
    discover_command.add_argument("source", type=Path)
    reconcile_command = commands.add_parser("reconcile")
    render_command = commands.add_parser("render")
    render_command.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.command == "publish":
        publish(args.directory, args.slug, args.version)
    elif args.command == "discover":
        registry = read_registry()
        print(json.dumps(discover(args.source, registry["packs"], releases_by_tag(), registry.get("thresholds"))))
    elif args.command == "reconcile":
        registry = read_registry()
        result = reconcile(registry, releases_by_tag())
        if result["changed"]:
            REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            render(False)
        print(json.dumps(result, ensure_ascii=False))
    else:
        render(args.check)
