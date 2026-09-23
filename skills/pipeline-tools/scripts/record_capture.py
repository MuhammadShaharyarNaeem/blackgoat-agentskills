#!/usr/bin/env python3
"""Write a provenance sidecar for one rendered screenshot.

WHY THIS EXISTS
----------------
A UI builder (Nova) could not reach the running application, so it rendered
a static HTML mockup, screenshotted `file:///.../mockup.html`, saved the PNG
to the evidence folder, and reported the milestone COMPLETE.
`check_commit_gate.py --require-rendered-evidence` checks a cited PNG's
magic bytes, non-empty size and mtime, but records nothing about WHERE the
pixels came from -- a screenshot of a static mockup is indistinguishable
from a screenshot of the running app to a check that only reads the file.

This script is the write side of the fix: every screenshot cited as
rendered evidence gets a sidecar, `<screenshot>.meta.json`, recording the
URL the browser had open at capture time. `check_commit_gate.py` then
refuses any cited PNG that carries no sidecar, or whose sidecar names a
non-http(s) origin, or whose sidecar's recorded sha256 no longer matches
the PNG's current bytes (the PNG was swapped out after being recorded).

RULE: a rendered capture is evidence only when it proves the RUNNING
application. A `file://`, `about:`, `data:` or empty URL proves a static
document was open, not a served one -- a mockup, not evidence. When the
running application cannot be reached, the correct state is BLOCKED, never
a substitute render of a document that was never running.

Sidecar shape (written next to the PNG, e.g. `m2.png` -> `m2.png.meta.json`):

    {"schema": 1, "url": "<the URL open at capture time>",
     "tool": "<capturing tool, e.g. chrome-devtools, playwright>",
     "captured_at": "<ISO-8601 UTC, Z suffix>",
     "sha256": "<hex sha256 of the PNG bytes at record time>"}

Usage:
    python record_capture.py <png> --url <url> --tool <name> [--force]
    python record_capture.py --self-test

Exit codes:
    0  recorded -- the sidecar was written (or overwritten with --force).
    1  refused -- the request is well-formed but violates the evidence
       rule: a non-http(s) --url (problem: bad_origin), the PNG's leading
       bytes are not the PNG magic (problem: bad_magic), or a sidecar
       already exists and --force was not given (problem: sidecar_exists).
    2  structural/usage error -- a required argument is missing (problem:
       missing_argument), <png> does not exist or cannot be read (problem:
       png_not_found), or the sidecar could not be written, e.g. an
       unwritable directory (problem: write_failed).

Every exit path prints exactly one JSON object to stdout:
`{"recorded": true, "png", "sidecar", "record"}` on success,
`{"recorded": false, "problem", "error"}` otherwise -- `problem` is always
one of the codes named above, so a caller can branch on it without parsing
`error`'s prose.

Pure standard library. See ../SKILL.md for the pipeline-tools family
conventions this follows (a dedicated GateError type, JSON-per-invocation
output, `--self-test`); this script duplicates `sha256_file` from its
siblings (mark_milestone.py, record_run.py, check_commit_gate.py) rather
than sharing a module, by the same family convention (one file each).
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
VALID_URL_SCHEMES = ("http://", "https://")
SCHEMA_VERSION = 1


class CaptureError(Exception):
    """Structural/usage failure -- maps to exit 2. Unused directly here (every
    failure path is handled inline so it can name its own problem code), kept
    for parity with the sibling scripts' GateError and for anyone extending
    this file to raise a genuinely unhandled structural condition.
    """


def sha256_file(path):
    """Hex sha256 of a file's bytes.

    Duplicated from the sibling gates (mark_milestone.py, record_run.py,
    check_commit_gate.py) by family convention: one file each, no shared
    module.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar_path_for(png_path):
    """`<png>.meta.json` -- appended to the full filename, not swapped in."""
    return Path(str(png_path) + ".meta.json")


def check_png(png_path):
    """(problem, detail) if `png_path` is unusable, else (None, None).

    `png_not_found` covers both "does not exist" and "cannot be read" --
    either way there are no bytes to hash or record. `bad_magic` is a
    separate problem: the file exists and is readable, it simply is not a
    PNG (a renamed file, a truncated one, a text stub).
    """
    p = Path(png_path)
    if not p.is_file():
        return "png_not_found", f"no such file: {png_path}"
    try:
        with open(p, "rb") as fh:
            head = fh.read(len(PNG_MAGIC))
    except OSError as exc:
        return "png_not_found", f"{png_path} could not be read: {exc}"
    if head != PNG_MAGIC:
        return "bad_magic", (
            f"{png_path} does not start with the PNG magic bytes -- a "
            "rendered capture must be a real PNG, not a renamed or "
            "corrupt file")
    return None, None


def check_url(url):
    """(problem, detail) if `url` is not an http(s) origin, else (None, None)."""
    if not url or not url.startswith(VALID_URL_SCHEMES):
        return "bad_origin", (
            f"url {url!r} is not http(s) -- a rendered capture proves the "
            "RUNNING application; a file:// (or about:, data:, or empty) "
            "origin proves a static document was open, not the served "
            "app -- a mockup, not evidence. When the running application "
            "cannot be reached the correct state is BLOCKED, never a "
            "substitute render of a document that was never running.")
    return None, None


def build_record(url, tool, sha256):
    return {
        "schema": SCHEMA_VERSION,
        "url": url,
        "tool": tool,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha256,
    }


PURPOSE = ("Records a PNG's provenance sidecar naming the URL the browser had "
           "open, so a mockup render stops looking real.")

EPILOG = """Reads:
  <png> -- the screenshot's bytes: its leading bytes must be the PNG magic
    (bad_magic otherwise), and its sha256 over those bytes is what the
    sidecar records.
  <png>.meta.json -- only to refuse when it already exists (sidecar_exists);
    --force overwrites instead. A capture is recorded once per PNG unless
    the PNG was re-taken.

Writes:
  <png>.meta.json -- the sidecar name is the FULL filename plus .meta.json
    (m2.png -> m2.png.meta.json). Shape, exactly what
    check_commit_gate.py --require-rendered-evidence reads back:
      {"schema": 1,
       "url": "<the URL open at capture time, http(s) only>",
       "tool": "<capturing tool, e.g. chrome-devtools, playwright>",
       "captured_at": "<ISO-8601 UTC, Z suffix>",
       "sha256": "<hex sha256 of the PNG's bytes at record time>"}

Problem codes:
  missing_argument   <png>, --url or --tool was not given (exit 2)
  png_not_found      the PNG does not exist or cannot be read (exit 2)
  write_failed       the sidecar could not be written (exit 2)
  bad_magic          the file does not start with the PNG magic (exit 1)
  bad_origin         --url is not http(s) -- file:, about:, data:, empty
  sidecar_exists     a sidecar is already there and --force was not given

JSON keys:
  on success recorded (true), png, sidecar, record (the sidecar object);
  on a refusal recorded (false), problem, error.

Exit codes:
  0  the sidecar was written
  1  bad_origin, bad_magic or sidecar_exists
  2  missing_argument, png_not_found or write_failed

Self-test:
  python record_capture.py --self-test   (11 cases)
"""


class PurposeFirstParser(argparse.ArgumentParser):
    """`--help` whose FIRST line is the one-line purpose, then usage/args/epilog.

    argparse prints usage before the description; the registry's
    `description` must equal help line 1 verbatim, so the description is
    lifted out and re-emitted ahead of the standard body.
    """

    def format_help(self):
        purpose = (self.description or "").strip()
        saved, self.description = self.description, None
        try:
            body = super().format_help()
        finally:
            self.description = saved
        return purpose + "\n\n" + body if purpose else body


def build_parser():
    parser = PurposeFirstParser(
        prog="record_capture.py",
        description=PURPOSE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG)
    parser.add_argument("png", nargs="?",
                        help="path to the screenshot PNG this sidecar "
                             "describes")
    parser.add_argument(
        "--url",
        help="the URL the browser had open at capture time; must start "
             "with http:// or https:// -- a file://, about:, data: or "
             "empty origin is refused (problem: bad_origin)")
    parser.add_argument(
        "--tool",
        help="the capturing tool, e.g. chrome-devtools, playwright; "
             "recorded verbatim")
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite an existing sidecar instead of refusing (problem: "
             "sidecar_exists without this flag)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    def fail(code, problem, message):
        print(json.dumps({"recorded": False, "problem": problem,
                          "error": message}))
        return code

    # `is None` rather than a truthiness check: an omitted flag is None, but
    # `--url ""` was DELIBERATELY given an empty origin, which is a distinct
    # refusal (bad_origin, via check_url below) from never supplying --url.
    missing = [n for n, v in (("png", args.png), ("--url", args.url),
                              ("--tool", args.tool)) if v is None]
    if missing:
        return fail(2, "missing_argument",
                    "missing required argument(s): {0}".format(
                        ", ".join(missing)))

    problem, detail = check_png(args.png)
    if problem:
        return fail(2 if problem == "png_not_found" else 1, problem, detail)

    problem, detail = check_url(args.url)
    if problem:
        return fail(1, problem, detail)

    sidecar = sidecar_path_for(args.png)
    if sidecar.exists() and not args.force:
        return fail(1, "sidecar_exists",
                    f"sidecar already exists at {sidecar}: pass --force to "
                    "overwrite it (a capture is recorded once per PNG "
                    "unless the PNG was re-taken)")

    record = build_record(args.url, args.tool, sha256_file(args.png))
    try:
        sidecar.write_text(json.dumps(record, indent=2) + "\n",
                          encoding="utf-8")
    except OSError as exc:
        return fail(2, "write_failed", f"could not write {sidecar}: {exc}")

    print(json.dumps({"recorded": True, "png": str(args.png),
                      "sidecar": str(sidecar), "record": record}, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile
    import unittest

    PNG_BYTES = PNG_MAGIC + b"\x00\x00\x00\x0dIHDR" + b"\x00" * 13

    class RecordCaptureTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.png = self.dir / "m2.png"
            self.png.write_bytes(PNG_BYTES)

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _sidecar(self):
            return sidecar_path_for(self.png)

        def _run(self, argv):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(argv)
            return rc, json.loads(buf.getvalue())

        # ---- happy path ----

        def test_happy_path_writes_a_conforming_sidecar(self):
            rc, out = self._run([str(self.png), "--url",
                                 "http://localhost:5173/x", "--tool",
                                 "chrome-devtools"])
            self.assertEqual(rc, 0)
            self.assertTrue(out["recorded"])
            sidecar = self._sidecar()
            self.assertTrue(sidecar.is_file())
            rec = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(rec["schema"], 1)
            self.assertEqual(rec["url"], "http://localhost:5173/x")
            self.assertEqual(rec["tool"], "chrome-devtools")
            self.assertEqual(rec["sha256"], sha256_file(self.png))
            self.assertTrue(rec["captured_at"].endswith("Z"))

        def test_https_is_accepted(self):
            rc, _ = self._run([str(self.png), "--url",
                               "https://app.example.com/y", "--tool",
                               "playwright"])
            self.assertEqual(rc, 0)

        # ---- file:// (and other non-http) refusal ----

        def test_file_url_is_refused(self):
            rc, out = self._run([str(self.png), "--url",
                                 "file:///C:/tmp/mock.html", "--tool",
                                 "chrome-devtools"])
            self.assertEqual(rc, 1)
            self.assertEqual(out["problem"], "bad_origin")
            self.assertIn("file", out["error"].lower())
            self.assertFalse(self._sidecar().exists())

        def test_about_data_and_empty_url_are_refused(self):
            for url in ("about:blank", "data:text/html,hi", ""):
                rc, out = self._run([str(self.png), "--url", url,
                                     "--tool", "x"])
                self.assertEqual(rc, 1, url)
                self.assertEqual(out["problem"], "bad_origin", url)
                self.assertFalse(self._sidecar().exists(), url)

        # ---- missing png ----

        def test_missing_png_is_exit_2(self):
            rc, out = self._run([str(self.dir / "nope.png"), "--url",
                                 "http://localhost/x", "--tool",
                                 "chrome-devtools"])
            self.assertEqual(rc, 2)
            self.assertEqual(out["problem"], "png_not_found")

        # ---- bad magic bytes ----

        def test_bad_magic_bytes_is_refused(self):
            fake = self.dir / "fake.png"
            fake.write_bytes(b"not a real png")
            rc, out = self._run([str(fake), "--url", "http://localhost/x",
                                 "--tool", "chrome-devtools"])
            self.assertEqual(rc, 1)
            self.assertEqual(out["problem"], "bad_magic")
            self.assertFalse(sidecar_path_for(fake).exists())

        def test_zero_byte_png_is_bad_magic_not_a_crash(self):
            empty = self.dir / "empty.png"
            empty.write_bytes(b"")
            rc, out = self._run([str(empty), "--url", "http://localhost/x",
                                 "--tool", "x"])
            self.assertEqual(rc, 1)
            self.assertEqual(out["problem"], "bad_magic")

        # ---- existing-sidecar refusal ----

        def test_existing_sidecar_is_refused_without_force(self):
            rc, _ = self._run([str(self.png), "--url", "http://localhost/x",
                               "--tool", "x"])
            self.assertEqual(rc, 0)
            rc, out = self._run([str(self.png), "--url",
                                 "http://localhost/y", "--tool", "x"])
            self.assertEqual(rc, 1)
            self.assertEqual(out["problem"], "sidecar_exists")
            rec = json.loads(self._sidecar().read_text(encoding="utf-8"))
            self.assertEqual(rec["url"], "http://localhost/x")  # unchanged

        def test_force_overwrites_the_sidecar(self):
            self._run([str(self.png), "--url", "http://localhost/x",
                      "--tool", "x"])
            rc, out = self._run([str(self.png), "--url",
                                 "http://localhost/y", "--tool", "x",
                                 "--force"])
            self.assertEqual(rc, 0)
            rec = json.loads(self._sidecar().read_text(encoding="utf-8"))
            self.assertEqual(rec["url"], "http://localhost/y")

        # ---- usage errors ----

        def test_missing_required_arguments_is_exit_2(self):
            self.assertEqual(main([str(self.png), "--tool", "x"]), 2)
            self.assertEqual(
                main([str(self.png), "--url", "http://localhost/x"]), 2)
            self.assertEqual(
                main(["--url", "http://localhost/x", "--tool", "x"]), 2)

        def test_sha256_reflects_the_actual_bytes(self):
            self._run([str(self.png), "--url", "http://localhost/x",
                      "--tool", "x"])
            rec = json.loads(self._sidecar().read_text(encoding="utf-8"))
            self.assertEqual(rec["sha256"],
                            hashlib.sha256(PNG_BYTES).hexdigest())

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecordCaptureTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
