"""Read only numeric Xlib/EWMH geometry in a disposable bounded subprocess.

No name, class, PID, contents, image, input or property-writing API is used.
Atom lookup uses only_if_exists=True so no server atoms are created.
"""
import ctypes as C
import ctypes.util
import json,sys
from .core import CaptureError
from .x11 import bounded_query
MAX_WINDOWS=256
MAX_DESKTOPS=256
PROPERTY_LIMIT=4096
TYPES=('NORMAL','DIALOG','DOCK','DESKTOP','UTILITY','TOOLBAR','MENU','SPLASH','NOTIFICATION')
STATES=('HIDDEN','FULLSCREEN','MAXIMIZED_VERT','MAXIMIZED_HORZ','SHADED','STICKY','ABOVE','BELOW')
PROPERTIES=frozenset(('_NET_CLIENT_LIST_STACKING','_NET_CURRENT_DESKTOP','_NET_NUMBER_OF_DESKTOPS','_NET_WORKAREA','_NET_DESKTOP_VIEWPORT','_NET_WM_DESKTOP','_NET_WM_STATE','_NET_WM_WINDOW_TYPE','_NET_FRAME_EXTENTS'))
ATOM_NAMES=PROPERTIES | {'_NET_WM_STATE_'+s for s in STATES} | {'_NET_WM_WINDOW_TYPE_'+t for t in TYPES}
class Attributes(C.Structure):
    _fields_=[('x',C.c_int),('y',C.c_int),('width',C.c_int),('height',C.c_int),('border_width',C.c_int),('depth',C.c_int),('visual',C.c_void_p),('root',C.c_ulong),('class_',C.c_int),('bit_gravity',C.c_int),('win_gravity',C.c_int),('backing_store',C.c_int),('backing_planes',C.c_ulong),('backing_pixel',C.c_ulong),('save_under',C.c_int),('colormap',C.c_ulong),('map_installed',C.c_int),('map_state',C.c_int),('all_event_masks',C.c_long),('your_event_mask',C.c_long),('do_not_propagate_mask',C.c_long),('override_redirect',C.c_int),('screen',C.c_void_p)]
class Native:
    def __init__(self):
        name=ctypes.util.find_library('X11')
        if not name: raise CaptureError('XLIB_UNAVAILABLE')
        self.lib=C.CDLL(name);self.display=None;self.error=False
        signatures={
          'XOpenDisplay':([C.c_char_p],C.c_void_p),'XCloseDisplay':([C.c_void_p],C.c_int),
          'XDefaultRootWindow':([C.c_void_p],C.c_ulong),'XInternAtom':([C.c_void_p,C.c_char_p,C.c_int],C.c_ulong),
          'XGetWindowProperty':([C.c_void_p,C.c_ulong,C.c_ulong,C.c_long,C.c_long,C.c_int,C.c_ulong,C.POINTER(C.c_ulong),C.POINTER(C.c_int),C.POINTER(C.c_ulong),C.POINTER(C.c_ulong),C.POINTER(C.POINTER(C.c_ubyte))],C.c_int),
          'XGetWindowAttributes':([C.c_void_p,C.c_ulong,C.POINTER(Attributes)],C.c_int),
          'XTranslateCoordinates':([C.c_void_p,C.c_ulong,C.c_ulong,C.c_int,C.c_int,C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(C.c_ulong)],C.c_int),
          'XFree':([C.c_void_p],C.c_int),'XSync':([C.c_void_p,C.c_int],C.c_int)}
        for function,(args,result) in signatures.items():
            method=getattr(self.lib,function);method.argtypes=args;method.restype=result
        self.handler_type=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_void_p)
        self.handler=self.handler_type(self._error)
        self.lib.XSetErrorHandler.argtypes=[self.handler_type];self.lib.XSetErrorHandler.restype=C.c_void_p
        self.lib.XSetErrorHandler(self.handler)
        self.display=self.lib.XOpenDisplay(None)
        if not self.display:raise CaptureError('X11_WINDOW_ACCESS_UNAVAILABLE')
        self.root=self.lib.XDefaultRootWindow(self.display)
        self.atoms={name:self.lib.XInternAtom(self.display,name.encode('ascii'),1) for name in ATOM_NAMES}
    def _error(self,*_):self.error=True;return 0
    def close(self):
        if self.display:self.lib.XCloseDisplay(self.display);self.display=None
    def prop(self,window,name,expected_type,maximum):
        if name not in PROPERTIES:raise CaptureError('PROPERTY_NOT_ALLOWLISTED')
        if not self.atoms[name]:return None
        actual=C.c_ulong();fmt=C.c_int();count=C.c_ulong();remaining=C.c_ulong();data=C.POINTER(C.c_ubyte)()
        self.error=False
        status=self.lib.XGetWindowProperty(self.display,window,self.atoms[name],0,maximum+1,0,expected_type,C.byref(actual),C.byref(fmt),C.byref(count),C.byref(remaining),C.byref(data))
        try:
            if status or self.error:raise CaptureError('WINDOW_CHANGED_DURING_QUERY')
            if actual.value==0:return None
            if actual.value!=expected_type or fmt.value!=32 or count.value>maximum or remaining.value:raise CaptureError('WINDOW_PROPERTY_INVALID_OR_LIMIT')
            if count.value and not data:raise CaptureError('WINDOW_PROPERTY_INVALID_OR_LIMIT')
            return [int(C.cast(data,C.POINTER(C.c_ulong))[i]) & 0xffffffff for i in range(count.value)]
        finally:
            if data:self.lib.XFree(data)
    def geometry(self,window):
        attributes=Attributes();x=C.c_int();y=C.c_int();child=C.c_ulong();self.error=False
        if not self.lib.XGetWindowAttributes(self.display,window,C.byref(attributes)) or self.error:raise CaptureError('WINDOW_CHANGED_DURING_QUERY')
        if attributes.root!=self.root:raise CaptureError('WINDOW_ROOT_MISMATCH')
        if not self.lib.XTranslateCoordinates(self.display,window,self.root,0,0,C.byref(x),C.byref(y),C.byref(child)) or self.error:raise CaptureError('WINDOW_CHANGED_DURING_QUERY')
        return {'client_rect':[x.value,y.value,attributes.width,attributes.height],'border_width':attributes.border_width,'map_state':attributes.map_state,'override_redirect':bool(attributes.override_redirect)}

def singleton(value):
    if value is None:return None
    if len(value)!=1:raise CaptureError('WINDOW_PROPERTY_INVALID_OR_LIMIT')
    return value[0]

def collect(api):
    windows=api.prop(api.root,'_NET_CLIENT_LIST_STACKING',33,MAX_WINDOWS)
    if windows is None:raise CaptureError('EWMH_CLIENT_LIST_UNAVAILABLE')
    if len(set(windows))!=len(windows):raise CaptureError('DUPLICATE_WINDOW_ID')
    current=singleton(api.prop(api.root,'_NET_CURRENT_DESKTOP',6,1))
    count=singleton(api.prop(api.root,'_NET_NUMBER_OF_DESKTOPS',6,1))
    if count is not None and not 1<=count<=MAX_DESKTOPS:raise CaptureError('DESKTOP_COUNT_LIMIT')
    if current is not None and (count is None or current>=count):raise CaptureError('DESKTOP_INDEX_INVALID')
    workareas=api.prop(api.root,'_NET_WORKAREA',6,MAX_DESKTOPS*4)
    viewports=api.prop(api.root,'_NET_DESKTOP_VIEWPORT',6,MAX_DESKTOPS*2)
    if workareas is not None and (count is None or len(workareas)!=count*4):raise CaptureError('WORKAREA_INVALID')
    if viewports is not None and (count is None or len(viewports)!=count*2):raise CaptureError('VIEWPORT_INVALID')
    items=[]
    for wid in windows:
        item=api.geometry(wid);item['_window_id']=wid
        item['desktop']=singleton(api.prop(wid,'_NET_WM_DESKTOP',6,1))
        frame=api.prop(wid,'_NET_FRAME_EXTENTS',6,4)
        if frame is not None and len(frame)!=4:raise CaptureError('FRAME_EXTENTS_INVALID')
        item['frame_extents']=frame
        states=api.prop(wid,'_NET_WM_STATE',4,PROPERTY_LIMIT)
        kinds=api.prop(wid,'_NET_WM_WINDOW_TYPE',4,PROPERTY_LIMIT)
        item['states']=None if states is None else [s.lower() for s in STATES if api.atoms['_NET_WM_STATE_'+s] and api.atoms['_NET_WM_STATE_'+s] in states]
        item['type']=next((t.lower() for atom in kinds or [] for t in TYPES if atom and api.atoms['_NET_WM_WINDOW_TYPE_'+t]==atom),'unknown')
        items.append(item)
    return {'status':'CAPTURED_MANAGED_WINDOWS','items':items,'current_desktop':current,'desktop_count':count,
      'work_area':workareas[current*4:current*4+4] if current is not None and workareas is not None else None,
      'viewport':viewports[current*2:current*2+2] if current is not None and viewports is not None else None}

def query(timeout=2):
    raw=bounded_query(timeout=timeout,command=[sys.executable,'-B','-m','blueprint.x11_windows'])
    try:
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError()
        if value.get('status')=='UNAVAILABLE':
            code=value.get('code')
            if code not in ERROR_CODES:raise ValueError()
        elif value.get('status')!='CAPTURED_MANAGED_WINDOWS':raise ValueError()
        return value
    except (ValueError,TypeError):raise CaptureError('WINDOW_WORKER_INVALID_RESPONSE') from None

ERROR_CODES=frozenset(('XLIB_UNAVAILABLE','X11_WINDOW_ACCESS_UNAVAILABLE','WINDOW_CHANGED_DURING_QUERY','WINDOW_ROOT_MISMATCH','WINDOW_PROPERTY_INVALID_OR_LIMIT','EWMH_CLIENT_LIST_UNAVAILABLE','DUPLICATE_WINDOW_ID','DESKTOP_COUNT_LIMIT','DESKTOP_INDEX_INVALID','WORKAREA_INVALID','VIEWPORT_INVALID','FRAME_EXTENTS_INVALID','WINDOW_QUERY_FAILED'))
def main():
    api=None
    try:api=Native();value=collect(api)
    except CaptureError as error:value={'status':'UNAVAILABLE','code':error.code if error.code in ERROR_CODES else 'WINDOW_QUERY_FAILED'}
    except Exception:value={'status':'UNAVAILABLE','code':'WINDOW_QUERY_FAILED'}
    finally:
        if api is not None:api.close()
    print(json.dumps(value,separators=(',',':')))
if __name__=='__main__':main()
