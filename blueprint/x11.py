"""Read-only XRandR adapter. Raw output stays in memory and never enters exported errors."""
import os,re,subprocess,selectors,time,json
from fractions import Fraction
from .core import CaptureError,integer

OUTPUT_LIMIT=262144
HEADER=re.compile(r'^(\S+) (connected|disconnected)(?: (primary))?(?: (\d+)x(\d+)([+-]\d+)([+-]\d+))?(.*)$')
MODE=re.compile(r'^\s+(\S+) \(0x[0-9a-fA-F]+\).*MHz')
IDENTITY=[['1','0','0'],['0','1','0'],['0','0','1']]

def bounded_query(timeout=2,limit=OUTPUT_LIMIT,command=None):
    command=command or ['xrandr','--query','--verbose']
    try: process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env={**os.environ,'LC_ALL':'C'},close_fds=True)
    except FileNotFoundError: raise CaptureError('XRANDR_NOT_FOUND') from None
    except OSError: raise CaptureError('DISPLAY_QUERY_UNAVAILABLE') from None
    data=bytearray(); deadline=time.monotonic()+timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0: raise CaptureError('CAPTURE_TIMEOUT')
                for key,_ in selector.select(min(.1,remaining)):
                    block=os.read(key.fd,65536)
                    if not block: selector.unregister(key.fileobj); break
                    data.extend(block)
                    if len(data)>limit: raise CaptureError('SOURCE_OUTPUT_LIMIT')
            remaining=deadline-time.monotonic()
            if remaining<=0: raise CaptureError('CAPTURE_TIMEOUT')
            if process.wait(timeout=remaining)!=0: raise CaptureError('DISPLAY_QUERY_DENIED')
    except subprocess.TimeoutExpired: raise CaptureError('CAPTURE_TIMEOUT') from None
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=1)
        process.stdout.close()
    try: return data.decode('utf-8',errors='strict')
    except UnicodeDecodeError: raise CaptureError('MALFORMED_SOURCE_ENCODING') from None

def parse(text):
    if len(text.encode('utf-8'))>OUTPUT_LIMIT: raise CaptureError('SOURCE_OUTPUT_LIMIT')
    displays=[]; current=None; mode=None; transform_rows=0; inactive=0; seen=set()
    for line in text.splitlines():
        match=HEADER.match(line)
        if match:
            if transform_rows: raise CaptureError('MALFORMED_TRANSFORM')
            mode=None; transform_rows=0
            name,connection,primary,w,h,x,y,tail=match.groups()
            if name in seen: raise CaptureError('DUPLICATE_OUTPUT')
            seen.add(name)
            if connection!='connected' or w is None:
                current=None; inactive+=1; continue
            suffix=re.sub(r'^\s*\(0x[0-9a-fA-F]+\)\s*','',tail).strip()
            orientation=suffix.split('(',1)[0].strip()
            rot=next((v for k,v in [('normal',0),('left',90),('inverted',180),('right',270)] if re.match(r'^'+k+r'\b',orientation)),None)
            mm=re.search(r'(\d+)mm x (\d+)mm',tail)
            current={'_connector':name,'_crtc':None,'primary':bool(primary),'desktop_rect':[int(x),int(y),int(w),int(h)],'rotation_deg':rot,
              'reflection':'none' if 'x axis' not in orientation and 'y axis' not in orientation else 'reflected',
              'reported_panel_mm':[int(mm[1]),int(mm[2])] if mm else None,'transform':None,'panning_present':False,'scanout_mode_px':None,'supported_modes':[],'refresh_millihz':None}
            displays.append(current); continue
        if current is None: continue
        if line.strip().lower().startswith(('panning:','tracking:','border:')):
            # Panning/overscan changes visible bounds; retain uncertainty rather than inventing a mapping.
            numbers=re.findall(r'-?\d+',line.split(':',1)[1])
            current['panning_present']=current['panning_present'] or any(int(v)!=0 for v in numbers)
        if line.strip().startswith('CRTC:'):
            number=re.search(r'CRTC:\s*(\d+)',line)
            current['_crtc']=int(number[1]) if number else None
        if line.strip().startswith('Transform:'):
            transform_rows=3; current['transform']=[]; line=line.split('Transform:',1)[1]
        if transform_rows:
            values=line.split()
            if len(values)!=3: raise CaptureError('MALFORMED_TRANSFORM')
            try:
                fractions=[Fraction(v) for v in values]
                if any(abs(v)>1_000_000 for v in fractions): raise ValueError()
            except (ValueError,ZeroDivisionError): raise CaptureError('MALFORMED_TRANSFORM') from None
            current['transform'].append([str(v) for v in fractions]); transform_rows-=1; continue
        if MODE.match(line):
            mode={'current':'*current' in line,'size_px':[None,None],'refresh_millihz':None,'interlaced':bool(re.search(r'\bInterlace\b',line,re.I))}; continue
        if mode is not None:
            horizontal=re.search(r'h: width\s+(\d+)',line)
            vertical=re.search(r'v: height\s+(\d+).*clock\s+([\d.]+)Hz',line)
            if horizontal: mode['size_px'][0]=int(horizontal[1])
            if vertical:
                try: mode['size_px'][1]=int(vertical[1]); mode['refresh_millihz']=None if mode['interlaced'] else round(Fraction(vertical[2])*1000)
                except (ValueError,ZeroDivisionError): raise CaptureError('MALFORMED_MODE') from None
                if None in mode['size_px']: raise CaptureError('MALFORMED_MODE')
                current['supported_modes'].append({'size_px':mode['size_px'],'refresh_millihz':mode['refresh_millihz']})
                if mode['current']:
                    if current['scanout_mode_px'] is not None: raise CaptureError('MULTIPLE_CURRENT_MODES')
                    current['scanout_mode_px']=mode['size_px']; current['refresh_millihz']=mode['refresh_millihz']
                mode=None
    if transform_rows: raise CaptureError('MALFORMED_TRANSFORM')
    if not displays: raise CaptureError('NO_ACTIVE_DISPLAYS')
    for d in displays:
        if d['scanout_mode_px'] is None: raise CaptureError('CURRENT_MODE_MISSING')
        w,h=d['scanout_mode_px']; oriented=[h,w] if d['rotation_deg'] in [90,270] else [w,h]
        d['mapping_known']=(not d['panning_present'] and d['transform']==IDENTITY and d['reflection']=='none' and d['rotation_deg'] is not None and oriented==d['desktop_rect'][2:])
        d['mapping_reason']=None if d['mapping_known'] else 'Nonidentity, missing or reflected transform, unknown rotation or mode/desktop mismatch; exact crop mapping is withheld.'
        for value in d['desktop_rect']: integer(value)
    return {'backend':'xrandr --query --verbose (LC_ALL=C)','desktop_unit':'x11_root_framebuffer_px','displays':displays,'inactive_output_count':inactive,'errors':[]}

def coherent_capture(query=bounded_query,budget=5,attempts=3,session=None,window_query=None):
    session=session if session is not None else os.environ.get('XDG_SESSION_TYPE','')
    if session=='wayland' or (session!='x11' and os.environ.get('WAYLAND_DISPLAY')):
        raise CaptureError('WAYLAND_NATIVE_ADAPTER_NOT_IMPLEMENTED')
    if session not in ['','x11']: raise CaptureError('SESSION_NOT_SUPPORTED')
    deadline=time.monotonic()+budget
    stable_displays=None
    for attempt in range(1,attempts+1):
        snapshots=[]
        for _ in range(2):
            remaining=deadline-time.monotonic()
            if remaining<=0: raise CaptureError('CAPTURE_TIMEOUT')
            snapshot=parse(query(timeout=min(2,remaining)))
            if window_query is not None:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise CaptureError('CAPTURE_TIMEOUT')
                try:snapshot['windows']=window_query(timeout=min(2,remaining))
                except CaptureError:snapshot['windows']={'status':'UNAVAILABLE','code':'WINDOW_QUERY_FAILED'}
                if snapshot['windows'].get('status')!='CAPTURED_MANAGED_WINDOWS':snapshot['errors'].append('WINDOW_GEOMETRY_UNAVAILABLE')
            snapshots.append(snapshot)
        display_only=[{k:v for k,v in snap.items() if k not in ('windows','errors')} for snap in snapshots]
        stable_displays=snapshots[1] if display_only[0]==display_only[1] else None
        if json.dumps(snapshots[0],sort_keys=True)==json.dumps(snapshots[1],sort_keys=True):
            snapshots[1]['coherence']={'status':'TWO_MATCHING_SNAPSHOTS','attempt':attempt,'queries':attempt*2,'comparison':'All parsed output/mode/transform fields, internal output/CRTC identities and requested numeric window metadata; raw identifiers not exported.','limitation':'Two matching reads are bounded coherence evidence, not an atomic server transaction; ABA hotplug remains possible.'}
            return snapshots[1]
    if stable_displays is not None and window_query is not None:
        stable_displays['windows']={'status':'UNAVAILABLE','code':'WINDOWS_CHANGED_DURING_CAPTURE'}
        stable_displays['errors']=['WINDOWS_CHANGED_DURING_CAPTURE']
        stable_displays['coherence']={'status':'MATCHING_DISPLAY_PAIR_WINDOW_CAPTURE_UNSTABLE','queries':attempts*2,'limitation':'Window metadata changed across bounded observations and was withheld; displays matched within a retained pair. No atomic desktop snapshot is claimed.'}
        return stable_displays
    raise CaptureError('TOPOLOGY_CHANGED_DURING_CAPTURE')
