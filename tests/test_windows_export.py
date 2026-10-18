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

if __name__=='__main__':unittest.main(verbosity=2)
