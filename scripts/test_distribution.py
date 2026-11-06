import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from distribution import SOURCE, discover


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
