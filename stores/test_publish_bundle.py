"""Offline bundle planning and protection against managed/concurrently edited READMEs."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
import publish_bundle as bundle


class PublishBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch_root = patch.object(bundle, 'REPO', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)

    def file(self, relative, body=b'committed bytes\n'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def git(self, tracked, dirty=''):
        def result(*args):
            if args[0] == 'ls-files':
                return '\0'.join(tracked) + '\0'
            if args[0] == 'status':
                return dirty
            if args[0] == 'rev-parse':
                return 'test-commit\n'
            raise AssertionError(args)
        return result

    def client(self):
        client = Mock()
        client.create_multipart_upload.return_value = {'UploadId': 'upload'}
        client.upload_part.return_value = {'ETag': 'part'}
        return client

    def response(self, body=b'# Manual prose\n'):
        return {'Body': io.BytesIO(body), 'ETag': '"readme-etag"'}

    def test_plan_includes_auth_helper_but_excludes_development_tests_and_runtime_data(self):
        tracked = ['source-coop/README.md', 'stores/README.md', 'stores/requirements.txt',
                   'stores/roms_hiig/README.md', 'stores/icechunk_utils.py', 'stores/smoke_test.py',
                   'upload/source_coop_credentials.py', 'stores/test_icechunk_auth.py',
                   'stores/test_publish_bundle.py', 'stores/roms_hiig/test_update_store.py',
                   'stores/.gitignore', 'stores/tests/example.py', 'stores/__pycache__/cache.pyc']
        with patch.object(bundle, 'git', side_effect=self.git(tracked)):
            rows = bundle.bundle()
        mapping = {key: path for path, key, _ in rows}
        self.assertEqual(set(mapping), {'pacioos/README.md', 'pacioos/requirements.txt',
            'pacioos/roms_hiig/README.md', 'pacioos/icechunk_utils.py', 'pacioos/smoke_test.py',
            'pacioos/source_coop_credentials.py'})
        self.assertEqual(mapping['pacioos/source_coop_credentials.py'],
                         self.root / 'upload/source_coop_credentials.py')

    def test_dirty_files_can_only_be_previewed_and_dry_run_has_no_credentials_or_writes(self):
        with patch.object(bundle, 'git', side_effect=self.git(['source-coop/README.md'], ' M source-coop/README.md')):
            with self.assertRaisesRegex(SystemExit, 'uncommitted changes'):
                bundle.bundle()
            with patch('sys.argv', ['publish_bundle.py', '--dry-run']), \
                 patch('icechunk_utils.get_source_credentials') as credentials, \
                 patch('boto3.client') as client, contextlib.redirect_stdout(io.StringIO()) as output:
                bundle.main()
        self.assertIn('working tree preview', output.getvalue())
        credentials.assert_not_called()
        client.assert_not_called()

    def test_team_wrf_directory_is_refused(self):
        with patch.object(bundle, 'git', side_effect=self.git(['stores/wrf_hi/README.md'])):
            with self.assertRaisesRegex(SystemExit, 'not in a known dataset'):
                bundle.bundle()

    def test_managed_or_malformed_readme_aborts_all_uploads_during_preflight(self):
        rows = [(self.file('code.py'), 'pacioos/code.py', 'text/x-python'),
                (self.file('README.md'), 'pacioos/README.md', 'text/markdown'),
                (self.file('model/README.md'), 'pacioos/roms_hiig/README.md', 'text/markdown')]
        for marker in (b'<!-- icechunker:global-attributes:start -->',
                       b'<!-- icechunker:global-attributes:end -->'):
            client = self.client()
            client.get_object.side_effect = [self.response(), self.response(b'# Team edits\n' + marker)]
            with self.assertRaisesRegex(ValueError, 'managed README'):
                bundle.upload(client, rows)
            self.assertEqual(client.get_object.call_count, 2)
            client.upload_file.assert_not_called()
            client.create_multipart_upload.assert_not_called()

    def test_conditionally_uploads_exact_file_bytes_and_keeps_content_type(self):
        body = '# Hawaiʻi\n\nReviewed, committed prose.\n'.encode()
        path = self.file('README.md', body)
        client = self.client()
        client.get_object.return_value = self.response()
        bundle.upload(client, [(path, 'pacioos/roms_hiig/README.md', 'text/markdown; charset=utf-8')])
        self.assertEqual(client.upload_part.call_args.kwargs['Body'], body)
        self.assertEqual(client.complete_multipart_upload.call_args.kwargs['IfMatch'], '"readme-etag"')
        self.assertEqual(client.create_multipart_upload.call_args.kwargs['ContentType'],
                         'text/markdown; charset=utf-8')
        client.upload_file.assert_not_called()

    def test_only_missing_object_allows_conditional_creation(self):
        path = self.file('README.md')
        rows = [(path, 'pacioos/README.md', 'text/markdown')]
        client = self.client()
        client.get_object.side_effect = ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        bundle.upload(client, rows)
        self.assertEqual(client.complete_multipart_upload.call_args.kwargs['IfNoneMatch'], '*')
        for code in ('AccessDenied', 'NoSuchBucket', 'InternalError'):
            client = self.client()
            client.get_object.side_effect = ClientError({'Error': {'Code': code}}, 'GetObject')
            with self.assertRaises(ClientError):
                bundle.upload(client, rows)
            client.create_multipart_upload.assert_not_called()

    def test_concurrent_edit_fails_at_completion_and_aborts_upload(self):
        path = self.file('README.md')
        client = self.client()
        client.get_object.return_value = self.response()
        conflict = ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'CompleteMultipartUpload')
        client.complete_multipart_upload.side_effect = conflict
        client.abort_multipart_upload.side_effect = RuntimeError('cleanup unavailable')
        with self.assertRaises(ClientError) as raised:
            bundle.upload(client, [(path, 'pacioos/roms_hiig/README.md', 'text/markdown')])
        self.assertIs(raised.exception, conflict)
        self.assertEqual(client.complete_multipart_upload.call_args.kwargs['IfMatch'], '"readme-etag"')
        client.abort_multipart_upload.assert_called_once_with(
            Bucket='ocean-icechunks', Key='pacioos/roms_hiig/README.md', UploadId='upload')

    def test_non_readme_files_still_use_original_content_types_and_layout(self):
        path = self.file('module.py')
        client = self.client()
        bundle.upload(client, [(path, 'pacioos/module.py', 'text/x-python; charset=utf-8')])
        client.get_object.assert_not_called()
        client.upload_file.assert_called_once_with(Filename=str(path), Bucket='ocean-icechunks',
            Key='pacioos/module.py', ExtraArgs={'ContentType': 'text/x-python; charset=utf-8',
                                              'CacheControl': 'public, max-age=300'})


if __name__ == '__main__':
    unittest.main()
