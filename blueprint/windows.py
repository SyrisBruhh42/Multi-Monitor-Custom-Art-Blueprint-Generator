"""Bounded Windows observations and pure CCD/monitor validation.

The worker is the only native boundary. Internal names/handles used for joins
and repeat-read comparison never enter the canonical manifest.
"""
import json
import subprocess
import sys
import threading
import time
from fractions import Fraction
from .core import CaptureError,rect,dimensions

UNIT='windows_virtual_desktop_physical_px'
OUTPUT_LIMIT=262144
MAX_PATHS=64
MAX_MODES=192
SCALES=frozenset((100,120,125,140,150,160,175,180,200,225,250,300,350,400,450,500))
SCALING={1:'identity',2:'centered',3:'stretched',4:'aspect_ratio_centered',5:'custom',128:'preferred'}

def bounded_worker(timeout=2,limit=OUTPUT_LIMIT,command=None):
    """Pipe-reader thread works on Windows, unlike selectors on anonymous pipes."""
    command=command or [sys.executable,'-B','-m','blueprint.windows_native']
    try:process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,close_fds=True)
    except OSError:raise CaptureError('WINDOWS_WORKER_UNAVAILABLE') from None
    data=bytearray();done=threading.Event();failure=[]
    def read():
        try:
            while True:
                block=process.stdout.read1(65536)
                if not block:break
                if len(data)+len(block)>limit:
                    failure.append('SOURCE_OUTPUT_LIMIT');break
                data.extend(block)
        except OSError:failure.append('WINDOWS_WORKER_READ_FAILED')
        finally:done.set()
    reader=threading.Thread(target=read,daemon=True);reader.start()
    deadline=time.monotonic()+timeout
    try:
        if not done.wait(max(0,deadline-time.monotonic())):raise CaptureError('CAPTURE_TIMEOUT')
        if failure:raise CaptureError(failure[0])
        remaining=deadline-time.monotonic()
        if remaining<=0:raise CaptureError('CAPTURE_TIMEOUT')
        try:code=process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:raise CaptureError('CAPTURE_TIMEOUT') from None
        if code:raise CaptureError('WINDOWS_WORKER_FAILED')
    finally:
        if process.poll() is None:process.kill()
        process.wait(timeout=1);reader.join(timeout=1)
        if not reader.is_alive():process.stdout.close()
    try:return data.decode('utf-8',errors='strict')
    except UnicodeDecodeError:raise CaptureError('MALFORMED_SOURCE_ENCODING') from None

def u32(value):
    if type(value) is not int or not 0<=value<=0xffffffff:raise CaptureError('WINDOWS_MALFORMED_OBSERVATION')
    return value
def adapter(value):
    if not isinstance(value,list) or len(value)!=2 or type(value[1]) is not int or not -(2**31)<=value[1]<2**31:raise CaptureError('WINDOWS_MALFORMED_OBSERVATION')
    return (u32(value[0]),value[1])
def boolean(value):
    if type(value) is not bool:raise CaptureError('WINDOWS_MALFORMED_OBSERVATION')
    return value
def name(value):
    if not isinstance(value,str) or not 0<len(value)<=31 or '\0' in value:raise CaptureError('WINDOWS_SOURCE_JOIN_UNAVAILABLE')
    return value
def fraction(value):
    if not isinstance(value,list) or len(value)!=2:raise CaptureError('WINDOWS_MALFORMED_OBSERVATION')
    n,d=map(u32,value)
    return [n,d] if n and d else None
def sequence(value,maximum):
    if not isinstance(value,list) or len(value)>maximum or any(not isinstance(v,dict) for v in value):raise CaptureError('WINDOWS_COUNT_OR_SHAPE_INVALID')
    return value

def parse(raw):
    if isinstance(raw,str):
        if len(raw.encode('utf-8'))>OUTPUT_LIMIT:raise CaptureError('SOURCE_OUTPUT_LIMIT')
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError()
                result[key]=value
            return result
        try:raw=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        except (ValueError,TypeError):raise CaptureError('WINDOWS_WORKER_INVALID_RESPONSE') from None
    if not isinstance(raw,dict):raise CaptureError('WINDOWS_WORKER_INVALID_RESPONSE')
    if raw.get('status')=='UNAVAILABLE':
        from .windows_native import ERROR_CODES
        code=raw.get('code')
        raise CaptureError(code if code in ERROR_CODES else 'WINDOWS_WORKER_INVALID_RESPONSE')
    if raw.get('status')!='CAPTURED' or raw.get('dpi_context_verified') is not True:raise CaptureError('WINDOWS_DPI_CONTEXT_UNAVAILABLE')
    paths=sequence(raw.get('paths'),MAX_PATHS);modes=sequence(raw.get('modes'),MAX_MODES);monitors=sequence(raw.get('monitors'),MAX_PATHS)
    if not paths or not monitors:raise CaptureError('NO_ACTIVE_DISPLAYS')
    by_name={};errors=[]
    for monitor in monitors:
        key=name(monitor.get('_gdi'))
        if key in by_name:raise CaptureError('WINDOWS_SOURCE_JOIN_UNAVAILABLE')
        by_name[key]=monitor
    def mode(index,kind,expected_adapter,expected_id=None):
        if index>=len(modes):raise CaptureError('WINDOWS_MODE_INDEX_INVALID')
        value=modes[index]
        if u32(value.get('kind'))!=kind or adapter(value.get('adapter'))!=expected_adapter or (expected_id is not None and u32(value.get('id'))!=expected_id):raise CaptureError('WINDOWS_MODE_IDENTITY_MISMATCH')
        return value
    displays=[];targets=set();used_sources={}
    for path in paths:
        sa=adapter(path.get('source_adapter'));ta=adapter(path.get('target_adapter'))
        sid=u32(path.get('source_id'));tid=u32(path.get('target_id'));flags=u32(path.get('flags'))
        if not flags&1 or not boolean(path.get('target_available')):raise CaptureError('WINDOWS_TOPOLOGY_CHANGED')
        target=(*ta,tid)
        if target in targets:raise CaptureError('WINDOWS_DUPLICATE_TARGET')
        targets.add(target)
        si=u32(path.get('source_index'));ti=u32(path.get('target_index'));virtual=bool(flags&8)
        source_index=(si>>16) if virtual else si;target_index=(ti>>16) if virtual else ti
        invalid=0xffff if virtual else 0xffffffff
        if source_index==invalid:raise CaptureError('WINDOWS_SOURCE_MODE_UNAVAILABLE')
        source=mode(source_index,1,sa,sid);r=rect(source.get('rect'))
        gdi=name(path.get('_gdi'));monitor=by_name.get(gdi)
        if monitor is None or rect(monitor.get('rect'))!=r:raise CaptureError('WINDOWS_SOURCE_JOIN_UNAVAILABLE')
        source_key=(*sa,sid)
        if source_key in used_sources and used_sources[source_key]!=(gdi,r):raise CaptureError('WINDOWS_SOURCE_JOIN_UNAVAILABLE')
        used_sources[source_key]=(gdi,r)
        work=rect(monitor.get('work'))
        if work[0]<r[0] or work[1]<r[1] or work[0]+work[2]>r[0]+r[2] or work[1]+work[3]>r[1]+r[3]:raise CaptureError('WINDOWS_WORK_AREA_INVALID')
        primary=boolean(monitor.get('primary'))
        if primary!=(r[:2]==[0,0]):raise CaptureError('WINDOWS_PRIMARY_MISMATCH')
        scale=monitor.get('scale_percent')
        if scale is not None and (type(scale) is not int or scale not in SCALES):
            scale=None
        if scale is None:errors.append('WINDOWS_UI_SCALE_UNAVAILABLE')
        target_mode=None if target_index==invalid else mode(target_index,2,ta,tid)
        native=dimensions(target_mode.get('active_size')) if target_mode else None
        if native is None:errors.append('WINDOWS_TARGET_MODE_UNAVAILABLE')
        rotation={1:0,2:90,3:180,4:270}.get(u32(path.get('rotation')))
        scaling=SCALING.get(u32(path.get('scaling')),'unknown')
        refresh_raw=fraction(target_mode.get('refresh')) if target_mode else None
        scanline=u32(target_mode.get('scanline')) if target_mode else None
        divider=u32(target_mode.get('vsync_divider',0)) if target_mode else None
        rate=round(Fraction(*refresh_raw)*1000) if refresh_raw and scanline==1 and divider==0 and not flags&16 else None
        if rate is not None and not 0<rate<=10_000_000:rate=None
        # The first slice intentionally does not solve positioned/clipped virtual images.
        image=None;full_image=not virtual
        if virtual and (ti&0xffff)!=0xffff:
            item=mode(ti&0xffff,3,ta)
            size=dimensions(item.get('path_size'));region=rect(item.get('region'));clip=rect(item.get('clip'))
            if region[0]<0 or region[1]<0 or region[0]+region[2]>size[0] or region[1]+region[3]>size[1]:raise CaptureError('WINDOWS_DESKTOP_IMAGE_INVALID')
            image={'path_size':size,'region':region,'clip':clip}
            full_image=size==r[2:] and region==[0,0,*r[2:]] and clip==[0,0,*r[2:]]
        oriented=native[::-1] if native and rotation in (90,270) else native
        known=rotation is not None and scaling=='identity' and full_image and oriented==r[2:]
        if not known:errors.append('WINDOWS_CROP_MAPPING_UNRESOLVED')
        displays.append({'_connector':str(target),'_crtc':source_key,'primary':primary,'desktop_rect':r,
          'scanout_mode_px':native,'rotation_deg':rotation,'mapping_known':known,'supported_modes':[],
          'refresh_millihz':rate,'reported_panel_mm':None,'transform':None,'reflection':'unknown',
          '_windows':{'ui_scale_percent':scale,'work_area':work,'rotation_convention':'CCD_CLOCKWISE',
            'path_scaling':scaling,'target_signal_active_px':native,'desktop_image':image,
            'virtual_mode_aware_path':virtual,'target_refresh_rational':refresh_raw,'path_refresh_rational':fraction(path.get('path_refresh')),
            'scanline_ordering':scanline,'vsync_divider':divider,'dynamic_refresh_flag':bool(flags&16)}})
    if len({s for s,(_,r) in used_sources.items() if r[:2]==[0,0]})!=1:raise CaptureError('WINDOWS_PRIMARY_MISMATCH')
    # Pseudo-monitors cannot silently inflate this physical desktop source inventory.
    if set(by_name)!={v[0] for v in used_sources.values()}:errors.append('WINDOWS_UNMATCHED_MONITOR_METADATA_WITHHELD')
    windows=raw.get('windows')
    if not isinstance(windows,dict) or windows.get('status')!='CAPTURED_TOPLEVEL_WINDOWS':
        windows={'status':'UNAVAILABLE'};errors.append('WINDOWS_WINDOW_GEOMETRY_UNAVAILABLE')
    return {'backend':'Windows CCD + PMv2 User32/DWM read-only worker','desktop_unit':UNIT,'displays':displays,
      'windows':windows,'errors':sorted(set(errors)),'inactive_output_count':None}

def coherent_capture(query=bounded_worker,budget=5,attempts=3):
    deadline=time.monotonic()+budget;stable=None
    for attempt in range(1,attempts+1):
        pair=[]
        for _ in range(2):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise CaptureError('CAPTURE_TIMEOUT')
            pair.append(parse(query(timeout=min(2,remaining))))
        display_pair=[{**{k:v for k,v in s.items() if k not in ('windows','errors')},
          'errors':[e for e in s['errors'] if e!='WINDOWS_WINDOW_GEOMETRY_UNAVAILABLE']} for s in pair]
        stable=pair[1] if display_pair[0]==display_pair[1] else None
        if pair[0]==pair[1]:
            pair[1]['coherence']={'status':'TWO_MATCHING_SNAPSHOTS','queries':attempt*2,'comparison':'CCD/monitor numeric metadata, internal source/target identities and requested window handles/bounds/states.','limitation':'Bounded observations, not an atomic capture; changes away and back or reused handles can be missed.'}
            return pair[1]
    if stable is not None:
        stable['windows']={'status':'UNAVAILABLE'}
        stable['errors']=sorted(set(stable['errors']+['WINDOWS_CHANGED_DURING_CAPTURE']))
        stable['coherence']={'status':'MATCHING_DISPLAY_PAIR_WINDOW_CAPTURE_UNSTABLE','queries':attempts*2,'limitation':'Window metadata withheld; only the retained display pair matched. No atomic snapshot claim.'}
        return stable
    raise CaptureError('TOPOLOGY_CHANGED_DURING_CAPTURE')
