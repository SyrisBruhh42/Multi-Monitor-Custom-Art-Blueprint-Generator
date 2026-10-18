"""Explicit PDF dependency checks: pypdf + standard Poppler must agree byte-for-byte."""
import json,re,shutil,subprocess,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from pypdf import PdfReader
from blueprint.core import canonical_json,prompts
from blueprint.export import write_pdf
from test_capture import manifest


def recover(text):
    chunks=re.findall(r'^\s*J(\d{6})\|(.*)\|END\s*$',text,re.M)
    numbers=[int(n) for n,_ in chunks]
    if not chunks or numbers!=list(range(1,len(chunks)+1)):
        raise AssertionError('Incomplete, duplicate or unordered canonical appendix')
    return ''.join(json.loads(chunk) for _,chunk in chunks).encode('utf-8')

class PdfRoundtrip(unittest.TestCase):
    def test_both_extractors_preserve_spaces_punctuation_and_complete_json(self):
        self.assertIsNotNone(shutil.which('pdftotext'),'Poppler pdftotext required for explicit PDF acceptance')
        m=manifest(); m['prompts']=prompts(m)
        # Exercise spaces at many chunk boundaries and within values, literal delimiters and JSON escapes.
        m['capture']['test_only_text']='boundary ' * 100 + '  triple   spaces |END literal \\u0020 quote " unicode \u03b1'
        expected=canonical_json(m).encode()
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.pdf'; write_pdf(path,m)
            pypdf='\n'.join(page.extract_text() for page in PdfReader(path).pages)
            poppler=subprocess.run(['pdftotext','-layout',str(path),'-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=10).stdout.decode()
            self.assertEqual(recover(pypdf),expected)
            self.assertEqual(recover(poppler),expected)
            prose=' '.join(pypdf.split())
            self.assertIn('normalized MASTER coordinates',prose)
            self.assertIn('[1920,0] maps to output [0,0]',prose)
    def test_missing_or_duplicate_line_is_not_accepted(self):
        for text in ['J000002|x|END','J000001|x|END\nJ000001|y|END']:
            with self.assertRaises(AssertionError): recover(text)

if __name__=='__main__': unittest.main(verbosity=2)
