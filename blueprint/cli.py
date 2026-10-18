"""One-shot local capture. No network, provider call, installation or setting change."""
import argparse,json,platform,sys,os
from pathlib import Path
from datetime import datetime,timezone
from .core import CaptureError,normalize
from .x11 import coherent_capture,parse
from .x11_windows import query as window_query
from .platforms import capabilities

def main(argv=None):
    parser=argparse.ArgumentParser(description='Capture display geometry and create one self-contained AI art PDF. No geometry input required.')
    parser.add_argument('--output',type=Path,default=Path.cwd()/'capture-output')
    parser.add_argument('--fixture',type=Path,help='Developer-only synthetic xrandr fixture instead of host capture')
    parser.add_argument('--metadata-only',action='store_true',help='Print allowlisted canonical data without authoring a PDF')
    args=parser.parse_args(argv)
    try:
        if args.fixture:
            if args.fixture.stat().st_size>262144: raise CaptureError('SOURCE_OUTPUT_LIMIT')
            snapshot=parse(args.fixture.read_text(encoding='utf-8')); snapshot['coherence']={'status':'SYNTHETIC_FIXTURE_NOT_HOST_CAPTURE'}
        elif platform.system()!='Linux': raise CaptureError(platform.system().upper()+'_NATIVE_ADAPTER_NOT_IMPLEMENTED')
        else: snapshot=coherent_capture(window_query=window_query)
        result=normalize(snapshot,datetime.now(timezone.utc).isoformat())
        if args.metadata_only:
            print(json.dumps(result,indent=2)); return 0
        from .export import write_bundle
        destination=write_bundle(args.output,result)
        print(json.dumps({'status':'PARTIAL_CAPTURE_EXPORTED','display_geometry':result['capture']['display_geometry'],'displays':len(result['displays']),'output_directory':str(destination),'primary_file':'AI-brief.pdf','windows':result['window_geometry']['status']}))
        return 0
    except CaptureError as error:
        print(json.dumps({'status':'CAPTURE_INCOMPLETE','code':error.code,'previous_exports':'untouched','capabilities':capabilities(platform.system(),os.environ.get('XDG_SESSION_TYPE','unknown'))}),file=sys.stderr); return 2
    except (OSError,ImportError):
        print(json.dumps({'status':'EXPORT_UNAVAILABLE','code':'LOCAL_IO_OR_DEPENDENCY_UNAVAILABLE','previous_exports':'untouched'}),file=sys.stderr); return 3
    except Exception:
        # Raw provider text and private filesystem paths never appear in console diagnostics.
        print(json.dumps({'status':'CAPTURE_INCOMPLETE','code':'UNEXPECTED_LOCAL_FAILURE','previous_exports':'untouched'}),file=sys.stderr); return 4
