"""Windows-only allowlisted geometry. No X11 semantics are inferred."""
from .core import CaptureError,rect,dimensions
from .window_geometry import intersection,normalized
from .windows import UNIT,SCALING,SCALES,boolean,u32,fraction

def display_fields(observation,origin):
    data=observation.get('_windows')
    if not isinstance(data,dict):raise CaptureError('WINDOWS_MALFORMED_OBSERVATION')
    scale=data.get('ui_scale_percent')
    if scale is not None and (type(scale) is not int or scale not in SCALES):raise CaptureError('WINDOWS_MALFORMED_OBSERVATION')
    work=rect(data.get('work_area'));image=data.get('desktop_image')
    if image is not None:
        image={'path_size':dimensions(image.get('path_size')),'region':rect(image.get('region')),'clip':rect(image.get('clip'))}
    return {
      'logical_rect_reason':'No unified UI-logical desktop is inferred from per-monitor scaling; desktop coordinates are PMv2/CCD physical pixels.',
      'ui_scale':[scale,100] if scale is not None else None,
      'ui_scale_reason':None if scale is not None else 'GetScaleFactorForMonitor unavailable, failed or returned an unqualified value; no 96dpi fallback.',
      'reported_physical_mm':{'panel_axes':None,'oriented_axes':None,'source':None,'quality':'UNKNOWN','reason':'Physical dimensions not queried by this Windows collector; no EDID, registry or DPI-derived estimate.'},
      'refresh_source':'CCD target signal vertical frequency, progressive/no divider/no dynamic-rate flag only; not measured playback',
      'oriented_to_native_pixel_edge_affine':None,
      'native_panel_mapping_reason':'CCD clockwise rotation is retained; raw panel-axis transform has not been independently qualified.',
      'windows':{'rotation_convention':'CCD_CLOCKWISE','path_scaling':data.get('path_scaling') if data.get('path_scaling') in SCALING.values() else 'unknown',
        'target_signal_active_px':dimensions(data.get('target_signal_active_px')),'desktop_image':image,
        'virtual_mode_aware_path':boolean(data.get('virtual_mode_aware_path')),
        'target_refresh_rational':fraction(data['target_refresh_rational']) if data.get('target_refresh_rational') else None,
        'path_refresh_rational':fraction(data['path_refresh_rational']) if data.get('path_refresh_rational') else None,
        'scanline_ordering':u32(data['scanline_ordering']) if data.get('scanline_ordering') is not None else None,
        'vsync_divider':u32(data['vsync_divider']) if data.get('vsync_divider') is not None else None,
        'dynamic_refresh_flag':boolean(data.get('dynamic_refresh_flag')),
        'scale_source':'GetScaleFactorForMonitor S_OK' if scale else None,
        'work_area':{'source_xywh':work,'normalized_xywh':normalized(work,origin),'unit':UNIT,'source':'GetMonitorInfoW.rcWork'}}}

def normalize_windows(raw,canvas,displays):
    if canvas['unit']!=UNIT:raise CaptureError('WINDOW_COORDINATE_MISMATCH')
    result={'status':'UNAVAILABLE','items':None,'unit':UNIT,'coverage':'BOUNDS_ONLY_NOT_AN_OCCLUSION_OR_PRIVACY_MASK',
      'scope':'EnumWindows top-level desktop-app windows on the accessible desktop only; child windows, other sessions and compositor surfaces may be absent.',
      'privacy':'No titles, class, PID, executable, content, pixels or persistent window identifiers are queried/exported.',
      'limitations':['Two matching observations are not atomic; movement, handle reuse and ABA changes remain possible.',
        'Visible style and noncloaked state do not establish occlusion, transparency, rounded corners, shadows or actual wallpaper visibility.',
        'Virtual-desktop membership and client-area geometry were not queried; enumeration order is not a qualified stacking order.',
        'Current rectangles are temporary composition hints, not permanent forbidden art regions.'],
      'work_area':{'reported_xywh':None,'status':'PER_MONITOR_ONLY','reason':'Each display has its own reported work area; no single desktop work rectangle is invented.'},
      'work_areas':[{'display':d['id'],**d['windows']['work_area']} for d in displays]}
    if not isinstance(raw,dict) or raw.get('status')!='CAPTURED_TOPLEVEL_WINDOWS':return result
    source=raw.get('items')
    if not isinstance(source,list) or len(source)>256:raise CaptureError('WINDOWS_WINDOW_COUNT_LIMIT')
    origin=canvas['source_origin'];items=[];seen=set()
    for i,item in enumerate(source,1):
        if not isinstance(item,dict):raise CaptureError('WINDOWS_MALFORMED_OBSERVATION')
        handle=item.get('_handle')
        if type(handle) is not int or not 0<handle<2**64 or handle in seen:raise CaptureError('WINDOWS_WINDOW_ID_INVALID')
        seen.add(handle)
        outer=rect(item['outer_rect']) if item.get('outer_rect') is not None else None
        frame=rect(item['frame_rect']) if item.get('frame_rect') is not None else None
        visible=boolean(item.get('visible_style'));minimized=boolean(item.get('minimized'));cloak=item.get('cloaked')
        if cloak is not None:u32(cloak)
        # Future cloak flags do not become an invented visible state.
        eligible=visible and not minimized and cloak==0
        bounds=frame or outer;cover=[]
        if eligible and bounds:
            candidate=normalized(bounds,origin)
            for display in displays:
                overlap=intersection(candidate,display['normalized_rect']['xywh'])
                if overlap:cover.append({'display':display['id'],'xywh':overlap})
        items.append({'id':f'W{i}','enumeration_order':i-1,'stacking_order_bottom_to_top':None,
          'client_rect':None,'normalized_client_rect':None,'client_reason':'NOT_COLLECTED; outer/frame rectangles are not client-area geometry.',
          'outer_rect':outer,'normalized_outer_rect':normalized(outer,origin) if outer else None,
          'outer_reason':None if outer else 'Zero or empty outer rectangle; no current bounds inferred.',
          'frame_rect':frame,'normalized_frame_rect':normalized(frame,origin) if frame else None,
          'frame_reason':None if frame else 'DWM extended frame bounds unavailable or empty; outer rectangle may include invisible resize borders.',
          'map_state':'minimized' if minimized else 'visible_style' if visible else 'hidden_style',
          'visible_style':visible,'minimized':minimized,'cloaked':cloak,'on_current_desktop':None,
          'possible_cover_rects':cover,'cover_basis':'dwm_frame_bounds' if frame else 'outer_bounds_including_possible_invisible_borders',
          'actual_visibility':'UNKNOWN'})
    result.update(status='CAPTURED_TOPLEVEL_WINDOWS',items=items)
    return result
