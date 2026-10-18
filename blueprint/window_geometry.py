"""Allowlisted window bounds in the shared canvas; no pixel/opacity inference."""
from .core import CaptureError,rect,integer
MAX_WINDOWS=256
ALLOWED_STATES={'hidden','fullscreen','maximized_vert','maximized_horz','shaded','sticky','above','below'}
ALLOWED_TYPES={'normal','dialog','dock','desktop','utility','toolbar','menu','splash','notification','unknown'}

def normalized(value,origin):
    x,y,w,h=rect(value);return [x-origin[0],y-origin[1],w,h]
def intersection(a,b):
    x=max(a[0],b[0]);y=max(a[1],b[1]);r=min(a[0]+a[2],b[0]+b[2]);bottom=min(a[1]+a[3],b[1]+b[3])
    return [x,y,r-x,bottom-y] if r>x and bottom>y else None

def normalize_windows(raw,canvas,displays):
    result={'status':'NOT_COLLECTED','items':None,'unit':'x11_root_framebuffer_px','coverage':'BOUNDS_ONLY_NOT_AN_OCCLUSION_OR_PRIVACY_MASK',
      'scope':'EWMH-managed clients only; override-redirect popups, compositor surfaces and other X screens may be absent.',
      'privacy':'No titles, class, PID, executable, content, pixels or persistent window identifiers are queried/exported.',
      'limitations':['Two matching observations are not atomic; movement and ABA changes remain possible.','Transparency, rounded corners, shadows, stacking effects and actual visible wallpaper pixels are not measured.','Current rectangles are temporary composition hints, not permanent forbidden art regions.']}
    if not isinstance(raw,dict):return result
    if raw.get('status')!='CAPTURED_MANAGED_WINDOWS':
        result['status']='UNAVAILABLE';result['reason']='Window access, protocol support or coherent capture unavailable; inspect capture source errors.';return result
    if canvas.get('unit')!='x11_root_framebuffer_px':raise CaptureError('WINDOW_COORDINATE_MISMATCH')
    source=raw.get('items')
    if not isinstance(source,list) or len(source)>MAX_WINDOWS:raise CaptureError('WINDOW_COUNT_LIMIT')
    origin=canvas['source_origin'];current=raw.get('current_desktop');count=raw.get('desktop_count')
    if current is not None and (type(current) is not int or type(count) is not int or not 0<=current<count<=256):raise CaptureError('DESKTOP_INDEX_INVALID')
    items=[]
    for i,w in enumerate(source,1):
        client=rect(w.get('client_rect'));border=integer(w.get('border_width',0))
        if border<0:raise CaptureError('INVALID_WINDOW_BORDER')
        frame=w.get('frame_extents');outer=None
        if frame is not None:
            if not isinstance(frame,list) or len(frame)!=4 or any(integer(v)<0 for v in frame):raise CaptureError('FRAME_EXTENTS_INVALID')
            left,right,top,bottom=frame
            # TranslateCoordinates(0,0) is client interior; include its X border
            # separately from window-manager-added frame extents.
            outer=rect([client[0]-border-left,client[1]-border-top,client[2]+2*border+left+right,client[3]+2*border+top+bottom])
        state=w.get('states')
        if state is not None and (not isinstance(state,list) or any(v not in ALLOWED_STATES for v in state)):raise CaptureError('INVALID_WINDOW_STATE')
        kind=w.get('type','unknown')
        if kind not in ALLOWED_TYPES:kind='unknown'
        desktop=w.get('desktop');on_current=None
        if desktop is not None:
            if type(desktop) is not int or not 0<=desktop<=0xffffffff:raise CaptureError('DESKTOP_INDEX_INVALID')
            if desktop==0xffffffff:on_current=True
            elif current is not None:on_current=desktop==current
        mapping=w.get('map_state')
        if type(mapping) is not int or mapping not in (0,1,2):raise CaptureError('INVALID_WINDOW_MAP_STATE')
        mapped={0:'unmapped',1:'unviewable',2:'viewable'}[mapping]
        candidate=normalized(outer or client,origin)
        intersections=[]
        if mapped=='viewable' and on_current is True and 'hidden' not in (state or []) and kind!='desktop':
            for display in displays:
                overlap=intersection(candidate,display['normalized_rect']['xywh'])
                if overlap:intersections.append({'display':display['id'],'xywh':overlap})
        items.append({'id':f'W{i}','stacking_order_bottom_to_top':i-1,'client_rect':client,'normalized_client_rect':normalized(client,origin),
          'frame_rect':outer,'normalized_frame_rect':normalized(outer,origin) if outer else None,'frame_reason':None if outer else 'Window-manager frame extents unavailable; client bounds are not the full decorated frame.',
          'border_width':border,'frame_extents':frame,'map_state':mapped,'desktop_index':desktop,'on_current_desktop':on_current,'reported_type':kind,'reported_states':state,
          'possible_cover_rects':intersections,'cover_basis':'frame_bounds' if outer else 'client_bounds_only','actual_visibility':'UNKNOWN'})
    work=raw.get('work_area');viewport=raw.get('viewport')
    work=rect(work) if work is not None else None
    if viewport is not None:
        if not isinstance(viewport,list) or len(viewport)!=2:raise CaptureError('VIEWPORT_INVALID')
        viewport=[integer(v) for v in viewport]
    result.update(status='CAPTURED_MANAGED_WINDOWS',items=items,current_desktop=current,desktop_count=count,
      work_area={'reported_xywh':work,'viewport':viewport,'normalized_xywh':normalized(work,origin) if work and viewport==[0,0] else None,
      'status':'REPORTED_CURRENT_WORKAREA' if work and viewport==[0,0] else 'UNRESOLVED',
      'reason':'EWMH current work area is a desktop-level rectangle, not exact per-monitor dock/strut geometry; nonzero or unknown viewport mapping is withheld.'})
    return result
