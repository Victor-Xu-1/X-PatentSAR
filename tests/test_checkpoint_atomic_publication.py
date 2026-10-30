"""Concurrent readers must never see a partially copied checkpoint JSON."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.web import file_publication
from patent_sar_extractor.web.attempts import CheckpointCopy
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import SafeFiles
from tests import test_job_attempts as attempt_controls


def split_writer(during_write, *, fail=False, short=False):
    actual = os.fdopen

    class Split:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, key):
            return getattr(self.stream, key)

        def write(self, content):
            middle = len(content) // 2
            self.stream.write(content[:middle])
            self.stream.flush()
            during_write()
            if fail:
                raise OSError("Controlled interrupted copy")
            if short:
                return middle
            self.stream.write(content[middle:])
            return len(content)

    def intercepted(fd, mode, *args, **kwargs):
        stream = actual(fd, mode, *args, **kwargs)
        return Split(stream) if mode == "wb" else stream

    return patch("os.fdopen", side_effect=intercepted)


class CheckpointAtomicPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="checkpoint-publication-control-"
        )
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        self.target = self.root / "target"
        self.path = "page_classification/observed.json"
        self.payload = {"source": "CONTROLLED", "literal": "x" * 32000}
        self.content = json.dumps(self.payload).encode()

    def test_reader_sees_absent_or_complete_json_never_a_written_prefix(self):
        copied = CheckpointCopy(self.source, self.target)
        during = []

        def observe():
            try:
                during.append(SafeFiles(self.target).json(self.path))
            except WebError as error:
                during.append(error.code)

        with split_writer(observe):
            copied.put(self.path, self.content)
        self.assertEqual(during, [None])
        self.assertEqual(SafeFiles(self.target).json(self.path), self.payload)
        self.assertEqual(
            copied.content[self.path], hashlib.sha256(self.content).hexdigest()
        )
        self.assertEqual(copied.total, len(self.content))
        self.assertEqual((self.target / self.path).stat().st_nlink, 1)
        self.assertEqual((self.target / self.path).stat().st_mode & 0o777, 0o600)

    def test_interrupted_write_leaves_no_published_prefix_or_count(self):
        copied = CheckpointCopy(self.source, self.target)
        with split_writer(lambda: None, fail=True), self.assertRaises(OSError):
            copied.put(self.path, self.content)
        self.assertIsNone(SafeFiles(self.target).json(self.path))
        self.assertEqual(copied.content, {})
        self.assertEqual(copied.total, 0)
        self.assertEqual(list((self.target / self.path).parent.iterdir()), [])
        copied.put(self.path, self.content)
        self.assertEqual(SafeFiles(self.target).json(self.path), self.payload)

    def test_cancel_before_publication_keeps_bytes_and_counts_unpublished(self):
        calls = 0

        def check_cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise WebError(409, "checkpoint_cancelled", "Controlled cancellation")

        copied = CheckpointCopy(self.source, self.target, check_cancel=check_cancel)
        with self.assertRaisesRegex(WebError, "Controlled cancellation"):
            copied.put(self.path, self.content)
        self.assertEqual(calls, 2)
        self.assertIsNone(SafeFiles(self.target).json(self.path))
        self.assertEqual(copied.content, {})
        self.assertEqual(copied.total, 0)

    def test_existing_file_is_never_overwritten_or_counted(self):
        copied = CheckpointCopy(self.source, self.target)
        destination = self.target / self.path
        destination.parent.mkdir(mode=0o700)
        destination.write_bytes(b"original unrelated bytes")
        before = destination.stat()
        with self.assertRaises(FileExistsError):
            copied.put(self.path, self.content)
        self.assertEqual(destination.read_bytes(), b"original unrelated bytes")
        self.assertEqual(destination.stat().st_ino, before.st_ino)
        self.assertEqual(list(destination.parent.iterdir()), [destination])
        self.assertEqual(copied.content, {})

    def test_source_inode_is_never_linked_to_the_completed_copy(self):
        original = self.source / "original.json"
        original.write_bytes(self.content)
        copied = CheckpointCopy(self.source, self.target)
        copied.put(self.path, original.read_bytes())
        destination = self.target / self.path
        self.assertNotEqual(original.stat().st_ino, destination.stat().st_ino)
        self.assertEqual(destination.stat().st_nlink, 1)
        original.write_bytes(b"changed controlled source")
        self.assertEqual(destination.read_bytes(), self.content)

    def test_leaf_symlink_and_replaced_ancestor_never_write_outside_the_target(self):
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        original = outside / "retained.json"
        original.write_bytes(b"outside original")
        copied = CheckpointCopy(self.source, self.target)
        destination = self.target / self.path
        destination.parent.mkdir(mode=0o700)
        destination.symlink_to(original)
        with self.assertRaises(FileExistsError):
            copied.put(self.path, self.content)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(original.read_bytes(), b"outside original")
        # Remove ONLY this test-owned symlink, not its unrelated destination.
        destination.unlink()
        actual = file_publication.directory_descriptor

        def replaced_parent(path):
            self.assertEqual(path, destination.parent)
            path.rmdir()  # Known empty, controlled temporary parent only.
            path.symlink_to(outside, target_is_directory=True)
            return actual(path)

        with (
            patch.object(
                file_publication, "directory_descriptor", side_effect=replaced_parent
            ),
            self.assertRaises(OSError),
        ):
            copied.put(self.path, self.content)
        self.assertEqual(list(outside.iterdir()), [original])
        self.assertEqual(original.read_bytes(), b"outside original")
        self.assertEqual(copied.content, {})

    def test_fsync_failure_before_publish_preserves_no_partial_final(self):
        copied = CheckpointCopy(self.source, self.target)
        with (
            patch("os.fsync", side_effect=OSError("Controlled fsync failure")),
            self.assertRaises(OSError),
        ):
            copied.put(self.path, self.content)
        self.assertIsNone(SafeFiles(self.target).json(self.path))
        self.assertEqual(list((self.target / self.path).parent.iterdir()), [])
        self.assertEqual(copied.content, {})

    def test_genuinely_corrupt_complete_json_still_refuses(self):
        copied = CheckpointCopy(self.source, self.target)
        copied.put(self.path, b"{complete but invalid JSON")
        with self.assertRaises(WebError) as captured:
            SafeFiles(self.target).json(self.path)
        self.assertEqual(captured.exception.code, "invalid_artifact")

    def test_short_write_is_not_published_as_complete(self):
        copied = CheckpointCopy(self.source, self.target)
        with split_writer(lambda: None, short=True), self.assertRaises(OSError):
            copied.put(self.path, self.content)
        self.assertIsNone(SafeFiles(self.target).json(self.path))
        self.assertEqual(copied.content, {})

    def test_stream_open_failure_closes_the_owned_descriptor_and_temporary(self):
        copied = CheckpointCopy(self.source, self.target)
        descriptors = []

        def failed_open(descriptor, _mode):
            descriptors.append(descriptor)
            raise OSError("Controlled stream-open failure")

        with patch("os.fdopen", side_effect=failed_open), self.assertRaises(OSError):
            copied.put(self.path, self.content)
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])
        self.assertIsNone(SafeFiles(self.target).json(self.path))
        self.assertEqual(list((self.target / self.path).parent.iterdir()), [])


class AttemptHistoryAtomicPublicationTests(unittest.TestCase):
    def test_real_terminal_history_is_absent_or_complete_without_status_promotion(self):
        control = attempt_controls.AttemptTests(
            "test_terminal_history_is_write_once_and_independent_of_mutated_output"
        )
        control.setUp()
        self.addCleanup(control.doCleanups)
        service, _project, queue, job, specification = control.draft()
        control.summary(specification)
        path = control.state / "job-history" / (job.id + ".json")
        during = []

        def observe():
            try:
                during.append(SafeFiles(path.parent).json(path.name))
            except WebError as error:
                during.append(error.code)

        with split_writer(observe):
            control.finish(service, queue, job, status="failed")
        self.assertEqual(during, [None])
        observed = service.job(job.id)
        self.assertEqual(observed.status, "failed")
        self.assertTrue(observed.history_available)
        self.assertEqual(SafeFiles(path.parent).json(path.name)["status"], "failed")
