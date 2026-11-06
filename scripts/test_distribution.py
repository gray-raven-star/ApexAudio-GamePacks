import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from distribution import SOURCE, discover, reconcile


class DiscoverTests(unittest.TestCase):
    def test_selects_versions_above_baseline_and_registry_and_recovers_previous_source(self):
        with TemporaryDirectory() as directory:
            source = Path(directory)
            for slug, version in {
                "unchanged": "0.0.0",
                "indexed": "1.3.0",
                "older": "1.9.0",
                "upgraded": "1.10.0",
                "retry": "2.0.0",
                "new": "0.0.1",
                "_archive": "9.0.0",
            }.items():
                manifest = source / "gamepacks" / slug / "manifest.json"
                manifest.parent.mkdir(parents=True)
                manifest.write_text(json.dumps({"version": version}), encoding="utf-8")

            indexed = [
                {"slug": "indexed", "version": "1.3.0"},
                {"slug": "older", "version": "1.10.0"},
                {"slug": "upgraded", "version": "1.9.0"},
            ]
            tag = "pack/retry/v2.0.0"
            current, previous = "a" * 40, "b" * 40
            releases = {tag: {"tag_name": tag, "body": f"Source: {SOURCE}/tree/{previous}/gamepacks/retry"}}

            with patch("distribution.subprocess.check_output", return_value=current + "\n"):
                result = discover(source, indexed, releases)
            self.assertEqual(result, [
                {"slug": "new", "version": "0.0.1", "source_ref": current},
                {"slug": "retry", "version": "2.0.0", "source_ref": previous},
                {"slug": "upgraded", "version": "1.10.0", "source_ref": current},
            ])

    def test_threshold_blocks_versions_whose_release_was_removed(self):
        with TemporaryDirectory() as directory:
            source = Path(directory)
            manifest = source / "gamepacks" / "mhw" / "manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"version": "1.1.0"}), encoding="utf-8")
            current = "a" * 40
            with patch("distribution.subprocess.check_output", return_value=current + "\n"):
                self.assertEqual(discover(source, [], {}, {"mhw": "1.1.0"}), [])
                self.assertEqual(discover(source, [], {}, {}), [
                    {"slug": "mhw", "version": "1.1.0", "source_ref": current},
                ])


class ReconcileTests(unittest.TestCase):
    def test_removes_unpublished_release_and_recovers_public_release_missing_from_index(self):
        commit = "c" * 40
        repo = "gray-raven-star/ApexAudio-GamePacks"
        recovered_tag = "pack/recovered/v2.0.0"
        releases = {
            "pack/kept/v1.0.0": {"tag_name": "pack/kept/v1.0.0", "draft": False, "body": "", "assets": []},
            recovered_tag: {
                "tag_name": recovered_tag,
                "draft": False,
                "body": f"Source: {SOURCE}/tree/{commit}/gamepacks/recovered",
                "assets": [
                    {"name": "local.recovered.gpack", "digest": "sha256:" + "D" * 64},
                    {"name": "local.recovered.sha256", "digest": "sha256:" + "E" * 64},
                ],
            },
        }
        registry = {
            "schemaVersion": 1,
            "packs": [
                {"slug": "kept", "version": "1.0.0", "packId": "local.kept"},
                {"slug": "gone", "version": "1.2.0", "packId": "local.gone"},
            ],
        }

        def raw(commit_arg, path):
            if path.endswith("manifest.json"):
                return {
                    "version": "2.0.0", "id": "local.recovered", "name": "Recovered",
                    "games": [{"executable": "game.exe", "sha256": "A" * 64}],
                }
            return {"backend": "Wwise"}

        with patch.dict(os.environ, {"GITHUB_REPOSITORY": repo}):
            result = reconcile(registry, releases, raw)

        self.assertEqual(result["removed"], ["pack/gone/v1.2.0"])
        self.assertEqual(result["recovered"], [recovered_tag])
        self.assertEqual(result["warnings"], [])
        self.assertTrue(result["changed"])
        self.assertEqual([pack["slug"] for pack in registry["packs"]], ["kept", "recovered"])
        self.assertEqual(registry["thresholds"], {
            "gone": "1.2.0", "kept": "1.0.0", "recovered": "2.0.0",
        })
        recovered = registry["packs"][1]
        self.assertEqual(recovered["packId"], "local.recovered")
        self.assertEqual(recovered["sourceCommit"], commit)
        self.assertEqual(recovered["engine"], "Wwise")
        self.assertEqual(recovered["sha256"], "d" * 64)
        self.assertEqual(
            recovered["downloadUrl"],
            f"https://github.com/{repo}/releases/download/{recovered_tag}/local.recovered.gpack",
        )

    def test_unreadable_release_is_reported_without_joining_the_index(self):
        registry = {"schemaVersion": 1, "packs": []}
        tag = "pack/bad/v1.0.0"
        releases = {tag: {"tag_name": tag, "draft": False, "body": "no source", "assets": []}}

        result = reconcile(registry, releases, lambda commit, path: {})

        self.assertEqual(registry["packs"], [])
        self.assertEqual(registry["thresholds"], {"bad": "1.0.0"})
        self.assertEqual(result["recovered"], [])
        self.assertTrue(any(tag in warning for warning in result["warnings"]))

    def test_draft_release_is_ignored_until_it_is_public(self):
        registry = {"schemaVersion": 1, "packs": []}
        tag = "pack/pending/v1.0.0"
        releases = {tag: {"tag_name": tag, "draft": True, "body": "", "assets": []}}

        result = reconcile(registry, releases, lambda commit, path: {})

        self.assertFalse(result["changed"])
        self.assertEqual(registry["packs"], [])
        self.assertNotIn("thresholds", registry)
