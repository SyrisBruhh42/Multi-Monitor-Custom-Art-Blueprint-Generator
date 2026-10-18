"""Complete synthetic Windows brief, distinct from actual Windows acceptance."""
import json,subprocess,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from pypdf import PdfReader
from blueprint.export import write_bundle
from blueprint.core import canonical_json
from test_windows_platform import fixture,second,manifest
from test_pdf_roundtrip import recover

class WindowsExport(unittest.TestCase):
    def test_full_windows_pdf_roundtrip_and_truthful_labels(self):
        raw=second(fixture());raw['windows']['items'][0]['frame_rect']=None
        with TemporaryDirectory() as tmp:
            folder=write_bundle(tmp,manifest(raw));expected=(folder/'layout.json').read_bytes()
            text='\n'.join(p.extract_text() for p in PdfReader(folder/'AI-brief.pdf').pages)
            poppler=subprocess.run(['pdftotext','-layout',str(folder/'AI-brief.pdf'),'-'],capture_output=True,check=True,timeout=10).stdout.decode()
            self.assertEqual(recover(text),expected);self.assertEqual(recover(poppler),expected)
            prose=' '.join(text.split())
            for phrase in ['SYNTHETIC_FIXTURE_NOT_HOST_CAPTURE','Outer x, y','DWM frame bounds','Virtual-desktop membership is unknown','Client-area geometry was not collected','Enumeration order does not establish stacking','native device qualification NOT_RUN']:
                self.assertIn(phrase,prose)
            for p in folder.iterdir():
                if p.suffix!='.pdf':self.assertNotIn('PRIVATE',p.read_text())
            self.assertNotIn('PRIVATE',text);self.assertEqual(json.loads(expected)['canvas']['size'],[3000,1920])
    def test_unavailable_windows_retained_in_single_upload(self):
        raw=fixture();raw['windows']={'status':'UNAVAILABLE'}
        with TemporaryDirectory() as tmp:
            folder=write_bundle(tmp,manifest(raw))
            text='\n'.join(p.extract_text() for p in PdfReader(folder/'AI-brief.pdf').pages)
            data=json.loads(recover(text));self.assertEqual(data['window_geometry']['status'],'UNAVAILABLE')
            self.assertIsNone(data['window_geometry']['items']);self.assertEqual(len(data['displays']),1)
    def test_linux_geometry_contract_unchanged(self):
        from test_capture import manifest as linux_manifest
        m=linux_manifest()
        self.assertEqual(m['schema_version'],'1.1.0');self.assertEqual(m['canvas']['size'],[4080,1920]);self.assertEqual(m['canvas']['unit'],'x11_root_framebuffer_px')
        self.assertEqual(m['displays'][0]['oriented_to_native_pixel_edge_affine'],[0,-1,1920,1,0,0])
        self.assertNotIn('windows',m['displays'][0]);self.assertEqual(m['displays'][0]['reported_physical_mm']['oriented_axes'],[296,527])

class LegacyDesktopExport(unittest.TestCase):
    def test_partial_pdf_and_both_extractors_keep_full_useful_contract(self):
        from test_windows_platform import legacy_fixture,desktop_manifest
        from blueprint.core import prompts
        m=desktop_manifest(second(legacy_fixture()))
        with TemporaryDirectory() as tmp:
            folder=write_bundle(tmp,m);expected=(folder/'layout.json').read_bytes()
            text='\n'.join(page.extract_text() for page in PdfReader(folder/'AI-brief.pdf').pages)
            poppler=subprocess.run(['pdftotext','-layout',str(folder/'AI-brief.pdf'),'-'],check=True,capture_output=True,timeout=10).stdout.decode()
            self.assertEqual(recover(text),expected);self.assertEqual(recover(poppler),expected)
            prose=' '.join(text.split())
            for phrase in ['Desktop layout captured. Exact per-screen crops are unavailable.','WINDOWS_LEGACY_DESKTOP_LAYOUT','Reported target px (unqualified)','Desktop region [x,y,w,h]','No per-display affine transforms or exact panel crops are supplied','Exact per-panel output sizes, cuts and transforms are unavailable','Virtual-desktop membership is unknown']:
                self.assertIn(phrase,prose)
            self.assertNotIn('Exact digital mapping and mask rules',prose)
            data=json.loads(expected);self.assertEqual(data['schema_version'],'1.3.0')
            self.assertEqual(data['canvas']['size'],[3000,1920]);self.assertFalse(data['media_contract']['exact_crops_available'])
            self.assertEqual(data['capture']['overall_completeness'],'PARTIAL');self.assertEqual(data['clone_groups'],[])
            self.assertIn('do not claim validated per-panel cuts',prompts(data)['general_ai'])
            for d in data['displays']:
                self.assertIsNone(d['crop_contract']);self.assertIsNone(d['master_to_output_affine_rationals']);self.assertIsNone(d['windows']['virtual_mode_aware_path'])
            for f in folder.iterdir():
                if f.suffix!='.pdf':self.assertNotIn('PRIVATE',f.read_text())
            self.assertNotIn('PRIVATE',text)
    def test_mismatched_schema_refuses_before_creating_any_output(self):
        from test_windows_platform import desktop_manifest
        from blueprint.core import CaptureError
        from blueprint.export import write_pdf
        m=desktop_manifest();m['schema_version']='1.2.0'
        with TemporaryDirectory() as tmp:
            output=Path(tmp)/'not-created'
            with self.assertRaises(CaptureError):write_bundle(output,m)
            self.assertFalse(output.exists())
            with self.assertRaises(CaptureError):write_pdf(Path(tmp)/'invalid.pdf',m)
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_zero_input_windows_cli_exports_partial_and_summarizes_limits(self):
        import io
        from unittest.mock import patch
        from contextlib import redirect_stdout
        from test_windows_platform import legacy_fixture
        from blueprint.cli import main
        with TemporaryDirectory() as tmp,patch('blueprint.cli.platform.system',return_value='Windows'),patch('blueprint.windows.bounded_worker',return_value=json.dumps(legacy_fixture())),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--output',tmp]),0)
            summary=json.loads(out.getvalue());folder=Path(summary['output_directory'])
            self.assertTrue((folder/'AI-brief.pdf').is_file());self.assertEqual(summary['status'],'PARTIAL_CAPTURE_EXPORTED')
            self.assertEqual(summary['desktop_layout'],'OBSERVED_COHERENT');self.assertFalse(summary['exact_crops_available'])
            self.assertEqual(summary['windows_query']['query_flags'],2)
            data=json.loads((folder/'layout.json').read_text());self.assertIsNone(data['displays'][0]['crop_contract'])

if __name__=='__main__':unittest.main(verbosity=2)
