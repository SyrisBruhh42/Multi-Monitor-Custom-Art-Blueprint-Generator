"""Export failure and privacy boundaries; no PDF dependency or provider requests needed."""
import json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from blueprint.export import write_bundle
from test_capture import manifest

class ExportFailures(unittest.TestCase):
    def test_window_manifest_survives_bundle_without_private_source_fields(self):
        from test_windows import manifest as window_manifest
        with TemporaryDirectory() as tmp:
            with patch('blueprint.export.write_pdf',side_effect=lambda path,_:path.write_bytes(b'synthetic-placeholder')):
                folder=write_bundle(tmp,window_manifest())
            data=json.loads((folder/'layout.json').read_text())
            self.assertEqual(data['window_geometry']['status'],'CAPTURED_MANAGED_WINDOWS')
            self.assertNotIn('PRIVATE_TITLE_CANARY',(folder/'layout.json').read_text())
            self.assertIn('temporary composition hints',data['prompts']['general_ai'])
    def test_failed_pdf_retains_partial_and_previous_export(self):
        with TemporaryDirectory() as tmp:
            parent=Path(tmp); previous=parent/'capture-existing'; previous.mkdir(); (previous/'AI-brief.pdf').write_bytes(b'preserve')
            with patch('blueprint.export.write_pdf',side_effect=OSError('private path must not enter failure record')):
                with self.assertRaises(OSError): write_bundle(parent,manifest())
            self.assertEqual((previous/'AI-brief.pdf').read_bytes(),b'preserve')
            partials=list(parent.glob('.partial-*')); self.assertEqual(len(partials),1)
            status=json.loads((partials[0]/'failure.json').read_text()); self.assertEqual(status,{'status':'EXPORT_FAILED','previous_exports':'untouched'})
            self.assertTrue((partials[0]/'layout.json').exists()); self.assertFalse(any('private path' in p.read_text() for p in partials[0].glob('*')))
    def test_successful_directory_promotion_never_overwrites(self):
        with TemporaryDirectory() as tmp:
            with patch('blueprint.export.write_pdf',side_effect=lambda path,_:path.write_bytes(b'synthetic-placeholder')):
                first=write_bundle(tmp,manifest()); second=write_bundle(tmp,manifest())
            self.assertNotEqual(first,second); self.assertTrue(first.is_dir() and second.is_dir())
            self.assertEqual(list(Path(tmp).glob('.partial-*')),[])

if __name__=='__main__': unittest.main(verbosity=2)
