import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copyfile(build.ROOT / "site.json", self.root / "site.json")
        for folder in ["content", "assets", "public"]:
            (self.root / folder).mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, metadata, body):
        path = self.root / "content" / name
        path.write_text("---\n" + json.dumps(metadata) + "\n---\n" + body)
        return path

    def page(self, path="/about/", published=True):
        return {"title": "Test", "path": path, "kind": "page", "published": published}

    def test_private_and_future_content_does_not_leak(self):
        self.write("draft.md", self.page(published=False), "PRIVATE_SENTINEL_41")
        self.write("future.md", {**self.page("/future/"), "kind": "entry", "date": "2099-01-01T00:00:00Z",
                               "authorship": "ai", "source_note_recorded": True}, "FUTURE_SENTINEL_52")
        build.build(self.root)
        public = "".join(p.read_text() for p in (self.root / "dist").rglob("*") if p.is_file())
        self.assertNotIn("PRIVATE_SENTINEL_41", public)
        self.assertNotIn("FUTURE_SENTINEL_52", public)

    def test_unsafe_path_is_rejected(self):
        for route in ["/../../private/", "//elsewhere/", "/a/../b/", "/assets/hijack/"]:
            with self.subTest(route=route):
                p = self.write("bad.md", self.page(route), "text")
                with self.assertRaises(ValueError):
                    build.read_document(p)

    def test_html_and_script_urls_are_not_executable(self):
        p = self.write("about.md", self.page(), '<script>alert(1)</script>\n\n[click](javascript:alert(2))')
        rendered = build.read_document(p)["_html"]
        self.assertNotIn("<script>", rendered)
        self.assertNotIn('href="javascript:', rendered)

    def test_ai_entry_requires_disclosure(self):
        self.write("entry.md", {**self.page("/entry/"), "kind": "entry", "date": "2026-01-01T00:00:00Z",
                               "authorship": "ai", "source_note_recorded": True}, "Documented words.")
        with self.assertRaisesRegex(ValueError, "authorship disclosure"):
            build.build(self.root)

    def test_ai_entry_requires_private_source_record(self):
        p = self.write("entry.md", {**self.page("/entry/"), "kind": "entry",
                                  "date": "2026-01-01T00:00:00Z", "authorship": "ai"}, "Words.")
        with self.assertRaisesRegex(ValueError, "source note"):
            build.read_document(p)

    def test_manifest_matches_all_generated_files(self):
        self.write("page.md", self.page(), "Public words.")
        manifest = build.build(self.root)
        import hashlib
        for file in manifest["files"]:
            data = (self.root / "dist" / file["path"]).read_bytes()
            self.assertEqual(len(data), file["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), file["sha256"])

    def test_duplicate_routes_fail(self):
        self.write("one.md", self.page(), "One")
        self.write("two.md", self.page(), "Two")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build.build(self.root)

    def test_ai_attribution_and_archive_dates_survive(self):
        self.write("authorship.md", self.page("/authorship/"), "Disclosure")
        self.write("entry.md", {**self.page("/entry/"), "kind": "entry", "date": "2025-01-05T00:00:00Z",
                               "authorship": "ai", "source_note_recorded": True}, "Words.")
        build.build(self.root)
        page = (self.root / "dist/entry/index.html").read_text()
        self.assertIn("January 5, 2025", page)
        self.assertIn("does not routinely review", page)
        self.assertIn("AI Editor", page)


if __name__ == "__main__":
    unittest.main()
