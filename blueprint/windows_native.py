"""Read-only Windows metadata worker; no DLLs are loaded at import time.

Only source GDI names (in memory for joins), numeric handles and geometry are
read. No title, class, PID, device path, EDID, content or setting API is bound.
Fixed-width Windows types keep fixture ABI checks meaningful on other hosts.
"""
import ctypes as C
import json
import sys
from .core import CaptureError

U32=C.c_uint32
I32=C.c_int32
U64=C.c_uint64
HANDLE=C.c_void_p
CALLBACK=getattr(C,'WINFUNCTYPE',C.CFUNCTYPE)
FLAGS=0x12  # Strict qualification keeps ONLY_ACTIVE_PATHS | VIRTUAL_MODE_AWARE
QUERY_POLICIES={2:"WINDOWS_LEGACY_DESKTOP_LAYOUT",18:"WINDOWS_VIRTUAL_AWARE_STRICT"}
MAX_PATHS=64
MAX_MODES=192
MAX_WINDOWS=256

class LUID(C.Structure):
    _fields_=[('low',U32),('high',I32)]
class Point(C.Structure):
    _fields_=[('x',I32),('y',I32)]
class Rect(C.Structure):
    _fields_=[('left',I32),('top',I32),('right',I32),('bottom',I32)]
class Size(C.Structure):
    _fields_=[('width',U32),('height',U32)]
class Rational(C.Structure):
    _fields_=[('numerator',U32),('denominator',U32)]
class Signal(C.Structure):
    _fields_=[('pixel_rate',U64),('h_sync',Rational),('v_sync',Rational),('active',Size),('total',Size),('additional',U32),('scanline',U32)]
class SourceMode(C.Structure):
    _fields_=[('width',U32),('height',U32),('pixel_format',U32),('position',Point)]
class DesktopImage(C.Structure):
    _fields_=[('path_size',Point),('region',Rect),('clip',Rect)]
class ModeUnion(C.Union):
    _fields_=[('target',Signal),('source',SourceMode),('desktop',DesktopImage)]
class Mode(C.Structure):
    _fields_=[('kind',U32),('id',U32),('adapter',LUID),('value',ModeUnion)]
class PathSource(C.Structure):
    _fields_=[('adapter',LUID),('id',U32),('index',U32),('status',U32)]
class PathTarget(C.Structure):
    _fields_=[('adapter',LUID),('id',U32),('index',U32),('technology',U32),('rotation',U32),('scaling',U32),('refresh',Rational),('scanline',U32),('available',I32),('status',U32)]
class DisplayPath(C.Structure):
    _fields_=[('source',PathSource),('target',PathTarget),('flags',U32)]
class MonitorInfo(C.Structure):
    _fields_=[('size',U32),('monitor',Rect),('work',Rect),('flags',U32),('device',C.c_uint16*32)]
class DeviceHeader(C.Structure):
    _fields_=[('kind',U32),('size',U32),('adapter',LUID),('id',U32)]
class SourceName(C.Structure):
    _fields_=[('header',DeviceHeader),('name',C.c_uint16*32)]

MONITOR_CALLBACK=CALLBACK(I32,HANDLE,HANDLE,C.POINTER(Rect),C.c_ssize_t)
WINDOW_CALLBACK=CALLBACK(I32,HANDLE,C.c_ssize_t)
EXPECTED_SIZES={'LUID':8,'Point':8,'Rect':16,'Signal':48,'SourceMode':20,'DesktopImage':40,'Mode':64,'PathSource':20,'PathTarget':48,'DisplayPath':72,'MonitorInfo':104,'DeviceHeader':20,'SourceName':84}

def validate_abi():
    if any(C.sizeof(globals()[name])!=size for name,size in EXPECTED_SIZES.items()):
        raise CaptureError('WINDOWS_ABI_UNQUALIFIED')
    if Mode.value.offset!=16 or DisplayPath.target.offset!=20 or MonitorInfo.device.offset!=40:
        raise CaptureError('WINDOWS_ABI_UNQUALIFIED')

def luid(value):return [value.low,value.high]
def xywh(value):return [value.left,value.top,value.right-value.left,value.bottom-value.top]
def rational(value):return [value.numerator,value.denominator]
def utf16(value):
    # Fixed WCHAR array, not host wchar_t (which is 4 bytes on Linux).
    text=bytes(value).decode('utf-16-le',errors='strict').split('\0',1)[0]
    if not text or len(text)>31:raise CaptureError('WINDOWS_SOURCE_JOIN_UNAVAILABLE')
    return text

def query_error(code):
    return {5:'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE',50:'WINDOWS_DRIVER_UNSUPPORTED',87:'WINDOWS_API_UNSUPPORTED'}.get(code,'WINDOWS_DISPLAY_QUERY_FAILED')

class Native:
    def __init__(self):
        if sys.platform!='win32':raise CaptureError('WINDOWS_NATIVE_PLATFORM_REQUIRED')
        validate_abi()
        # Use System32 DLL search only. Never load a DLL from the export/current folder.
        self.user=C.WinDLL('user32.dll',use_last_error=True,winmode=0x800)
        try:self.dwm=C.WinDLL('dwmapi.dll',use_last_error=True,winmode=0x800)
        except OSError:self.dwm=None
        try:self.shcore=C.WinDLL('shcore.dll',use_last_error=True,winmode=0x800)
        except OSError:self.shcore=None
        signatures={
          'SetThreadDpiAwarenessContext':([HANDLE],HANDLE),
          'GetThreadDpiAwarenessContext':([],HANDLE),
          'AreDpiAwarenessContextsEqual':([HANDLE,HANDLE],I32),
          'GetDisplayConfigBufferSizes':([U32,C.POINTER(U32),C.POINTER(U32)],I32),
          'QueryDisplayConfig':([U32,C.POINTER(U32),C.POINTER(DisplayPath),C.POINTER(U32),C.POINTER(Mode),C.c_void_p],I32),
          'DisplayConfigGetDeviceInfo':([C.POINTER(DeviceHeader)],I32),
          'EnumDisplayMonitors':([HANDLE,C.POINTER(Rect),MONITOR_CALLBACK,C.c_ssize_t],I32),
          'GetMonitorInfoW':([HANDLE,C.POINTER(MonitorInfo)],I32),
          'EnumWindows':([WINDOW_CALLBACK,C.c_ssize_t],I32),
          'GetWindowRect':([HANDLE,C.POINTER(Rect)],I32),
          'IsWindowVisible':([HANDLE],I32),'IsIconic':([HANDLE],I32)}
        try:
            for name,(args,result) in signatures.items():
                function=getattr(self.user,name);function.argtypes=args;function.restype=result
        except AttributeError:raise CaptureError('WINDOWS_API_UNSUPPORTED') from None
        try:
            if self.dwm:
                self.dwm.DwmGetWindowAttribute.argtypes=[HANDLE,U32,C.c_void_p,U32]
                self.dwm.DwmGetWindowAttribute.restype=I32
        except AttributeError:self.dwm=None
        try:
            if self.shcore:
                self.shcore.GetScaleFactorForMonitor.argtypes=[HANDLE,C.POINTER(I32)]
                self.shcore.GetScaleFactorForMonitor.restype=I32
        except AttributeError:self.shcore=None

    def enter_dpi(self):
        old=self.user.SetThreadDpiAwarenessContext(HANDLE(-4))
        if not old:raise CaptureError('WINDOWS_DPI_CONTEXT_UNAVAILABLE')
        return old
    def verify_dpi(self):
        return bool(self.user.AreDpiAwarenessContextsEqual(self.user.GetThreadDpiAwarenessContext(),HANDLE(-4)))
    def restore_dpi(self,old):
        if not self.user.SetThreadDpiAwarenessContext(old):raise CaptureError('WINDOWS_DPI_RESTORE_FAILED')
        if not self.user.AreDpiAwarenessContextsEqual(self.user.GetThreadDpiAwarenessContext(),old):raise CaptureError('WINDOWS_DPI_RESTORE_FAILED')

    def displays(self,query_flags=None):
        query_flags=FLAGS if query_flags is None else query_flags
        if type(query_flags) is not int or query_flags not in QUERY_POLICIES:raise CaptureError("WINDOWS_QUERY_POLICY_INVALID")
        for _ in range(3):
            np=U32();nm=U32()
            code=self.user.GetDisplayConfigBufferSizes(query_flags,C.byref(np),C.byref(nm))
            if code:raise CaptureError(query_error(code))
            if not 0<np.value<=MAX_PATHS or not 0<nm.value<=MAX_MODES:raise CaptureError('WINDOWS_DISPLAY_COUNT_LIMIT')
            path_capacity=np.value;mode_capacity=nm.value
            paths=(DisplayPath*path_capacity)();modes=(Mode*mode_capacity)()
            code=self.user.QueryDisplayConfig(query_flags,C.byref(np),paths,C.byref(nm),modes,None)
            if code==122:continue
            if code:raise CaptureError(query_error(code))
            if not 0<np.value<=path_capacity or not 0<nm.value<=mode_capacity:raise CaptureError('WINDOWS_DISPLAY_COUNT_LIMIT')
            break
        else:raise CaptureError('WINDOWS_TOPOLOGY_CHANGED')
        observations=[]
        for mode in modes[:nm.value]:
            item={'kind':mode.kind,'id':mode.id,'adapter':luid(mode.adapter)}
            if mode.kind==1:
                s=mode.value.source;item.update(rect=[s.position.x,s.position.y,s.width,s.height])
            elif mode.kind==2:
                t=mode.value.target;item.update(active_size=[t.active.width,t.active.height],refresh=rational(t.v_sync),scanline=t.scanline,vsync_divider=(t.additional>>16)&63)
            elif mode.kind==3:
                d=mode.value.desktop;item.update(path_size=[d.path_size.x,d.path_size.y],region=xywh(d.region),clip=xywh(d.clip))
            observations.append(item)
        result=[];names={}
        for path in paths[:np.value]:
            s,t=path.source,path.target;key=(*luid(s.adapter),s.id)
            if key not in names:
                name=SourceName();name.header=DeviceHeader(1,C.sizeof(SourceName),s.adapter,s.id)
                if self.user.DisplayConfigGetDeviceInfo(C.byref(name.header)):raise CaptureError('WINDOWS_SOURCE_JOIN_UNAVAILABLE')
                names[key]=utf16(name.name)
            result.append({'source_adapter':luid(s.adapter),'source_id':s.id,'source_index':s.index,
              'target_adapter':luid(t.adapter),'target_id':t.id,'target_index':t.index,'flags':path.flags,
              'rotation':t.rotation,'scaling':t.scaling,'target_available':bool(t.available),
              'path_refresh':rational(t.refresh),'_gdi':names[key]})
        return result,observations

    def monitors(self):
        result=[];failure=[]
        def callback(handle,_dc,_rect,_data):
            try:
                if len(result)>=MAX_PATHS:raise CaptureError('WINDOWS_DISPLAY_COUNT_LIMIT')
                info=MonitorInfo();info.size=C.sizeof(info)
                if not self.user.GetMonitorInfoW(handle,C.byref(info)):raise CaptureError('WINDOWS_MONITOR_QUERY_FAILED')
                scale=I32();ok=self.shcore is not None and self.shcore.GetScaleFactorForMonitor(handle,C.byref(scale))==0
                result.append({'_gdi':utf16(info.device),'rect':xywh(info.monitor),'work':xywh(info.work),'primary':bool(info.flags&1),'scale_percent':scale.value if ok else None})
                return 1
            except Exception as error:failure.append(error);return 0
        cb=MONITOR_CALLBACK(callback)
        success=self.user.EnumDisplayMonitors(None,None,cb,0)
        if failure:raise failure[0]
        if not success:raise CaptureError('WINDOWS_MONITOR_QUERY_FAILED')
        return result

    def windows(self):
        result=[];failure=[]
        def callback(handle,_data):
            try:
                if len(result)>=MAX_WINDOWS:raise CaptureError('WINDOWS_WINDOW_COUNT_LIMIT')
                outer=Rect();frame=Rect();cloak=U32()
                if not self.user.GetWindowRect(handle,C.byref(outer)):raise CaptureError('WINDOWS_WINDOW_CHANGED')
                bounds=xywh(outer);visible=bool(self.user.IsWindowVisible(handle));minimized=bool(self.user.IsIconic(handle))
                frame_ok=self.dwm is not None and self.dwm.DwmGetWindowAttribute(handle,9,C.byref(frame),C.sizeof(frame))==0
                cloak_ok=self.dwm is not None and self.dwm.DwmGetWindowAttribute(handle,14,C.byref(cloak),C.sizeof(cloak))==0
                f=xywh(frame)
                result.append({'_handle':int(handle),'outer_rect':bounds if bounds[2]>0 and bounds[3]>0 else None,
                  'frame_rect':f if frame_ok and f[2]>0 and f[3]>0 else None,'visible_style':visible,'minimized':minimized,'cloaked':cloak.value if cloak_ok else None})
                return 1
            except Exception as error:failure.append(error);return 0
        cb=WINDOW_CALLBACK(callback)
        success=self.user.EnumWindows(cb,0)
        if failure:raise failure[0]
        if not success:raise CaptureError('WINDOWS_WINDOW_QUERY_FAILED')
        return {'status':'CAPTURED_TOPLEVEL_WINDOWS','items':result}

def collect(api,query_flags=FLAGS):
    if type(query_flags) is not int or query_flags not in QUERY_POLICIES:raise CaptureError("WINDOWS_QUERY_POLICY_INVALID")
    old=api.enter_dpi()
    try:
        if not api.verify_dpi():raise CaptureError('WINDOWS_DPI_CONTEXT_UNAVAILABLE')
        paths,modes=api.displays(query_flags=query_flags);monitors=api.monitors()
        try:windows=api.windows()
        except Exception:windows={'status':'UNAVAILABLE','code':'WINDOWS_WINDOW_QUERY_FAILED'}
        if not api.verify_dpi():raise CaptureError('WINDOWS_DPI_CONTEXT_UNAVAILABLE')
        return {'status':'CAPTURED','query_flags':query_flags,'query_policy':QUERY_POLICIES[query_flags],'dpi_context_verified':True,'paths':paths,'modes':modes,'monitors':monitors,'windows':windows}
    finally:api.restore_dpi(old)

ERROR_CODES=frozenset(('WINDOWS_QUERY_POLICY_INVALID','WINDOWS_NATIVE_PLATFORM_REQUIRED','WINDOWS_ABI_UNQUALIFIED','WINDOWS_API_UNSUPPORTED','WINDOWS_DPI_CONTEXT_UNAVAILABLE','WINDOWS_DPI_RESTORE_FAILED','WINDOWS_DESKTOP_ACCESS_UNAVAILABLE','WINDOWS_DRIVER_UNSUPPORTED','WINDOWS_DISPLAY_QUERY_FAILED','WINDOWS_DISPLAY_COUNT_LIMIT','WINDOWS_TOPOLOGY_CHANGED','WINDOWS_SOURCE_JOIN_UNAVAILABLE','WINDOWS_MONITOR_QUERY_FAILED'))
def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    try:
        if args not in ([],['--desktop-layout']):raise CaptureError('WINDOWS_QUERY_POLICY_INVALID')
        value=collect(Native(),query_flags=2 if args else FLAGS)
    except CaptureError as error:value={'status':'UNAVAILABLE','code':error.code if error.code in ERROR_CODES else 'WINDOWS_DISPLAY_QUERY_FAILED'}
    except Exception:value={'status':'UNAVAILABLE','code':'WINDOWS_DISPLAY_QUERY_FAILED'}
    encoded=json.dumps(value,separators=(',',':'),allow_nan=False)
    if len(encoded.encode('utf-8'))>262144:encoded='{"status":"UNAVAILABLE","code":"WINDOWS_DISPLAY_COUNT_LIMIT"}'
    print(encoded)

if __name__=='__main__':main()
