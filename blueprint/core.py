"""Pure geometry and allowlisted canonical export. Pixel-edge rectangles are half-open."""
from fractions import Fraction
from math import gcd
import json

SCHEMA_VERSION = '1.0.0'
MAX_DISPLAYS = 64
LIMIT = 10_000_000

class CaptureError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def integer(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > LIMIT or (positive and value <= 0):
        raise CaptureError('INVALID_GEOMETRY')
    return value

def rect(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise CaptureError('INVALID_GEOMETRY')
    return [integer(value[0]), integer(value[1]), integer(value[2], True), integer(value[3], True)]

def ratio(value):
    f = Fraction(value)
    return [f.numerator, f.denominator]

def dimensions(value):
    if value is None: return None
    if not isinstance(value,(list,tuple)) or len(value)!=2: raise CaptureError('INVALID_SIZE')
    return [integer(value[0],True),integer(value[1],True)]

def refresh(value):
    return None if value is None else integer(value,True)

def transform(value):
    if value is None: return None
    if not isinstance(value,list) or len(value)!=3: raise CaptureError('MALFORMED_TRANSFORM')
    result=[]
    try:
        for row in value:
            if not isinstance(row,list) or len(row)!=3: raise ValueError()
            values=[Fraction(v) for v in row]
            if any(abs(v)>1_000_000 for v in values): raise ValueError()
            result.append([str(v) for v in values])
    except (TypeError,ValueError,ZeroDivisionError): raise CaptureError('MALFORMED_TRANSFORM') from None
    return result

def partition(rectangles, bounds):
    """Exact disjoint rectangle mask and holes; no raster allocation or physical-gap inference."""
    bx, by, bw, bh = bounds
    xs = sorted({bx, bx+bw} | {x for x,y,w,h in rectangles} | {x+w for x,y,w,h in rectangles})
    ys = sorted({by, by+bh} | {y for x,y,w,h in rectangles} | {y+h for x,y,w,h in rectangles})
    mask, holes = [], []
    for x0,x1 in zip(xs,xs[1:]):
        for y0,y1 in zip(ys,ys[1:]):
            occupied = any(x <= x0 and x1 <= x+w and y <= y0 and y1 <= y+h for x,y,w,h in rectangles)
            (mask if occupied else holes).append([x0,y0,x1-x0,y1-y0])
    return mask, holes

def native_transform(rotation, width, height):
    # Continuous pixel-edge coordinates. Keep upright wallpaper outputs; rotate only for raw panel use.
    return {0:[1,0,0,0,1,0], 90:[0,-1,width,1,0,0],
            180:[-1,0,width,0,-1,height], 270:[0,1,0,-1,0,height]}[rotation]

def normalize(snapshot, timestamp, os_family='Linux', session='x11'):
    source = snapshot.get('displays', [])
    if not source or len(source) > MAX_DISPLAYS:
        raise CaptureError('NO_ACTIVE_DISPLAYS' if not source else 'TOO_MANY_DISPLAYS')
    ordered = sorted(source, key=lambda d: (rect(d['desktop_rect'])[0], rect(d['desktop_rect'])[1], d.get('_connector','')))
    rectangles = [rect(d['desktop_rect']) for d in ordered]
    left=min(r[0] for r in rectangles); top=min(r[1] for r in rectangles)
    width=max(r[0]+r[2] for r in rectangles)-left; height=max(r[1]+r[3] for r in rectangles)-top
    if width > LIMIT or height > LIMIT: raise CaptureError('CANVAS_LIMIT')
    unit = snapshot.get('desktop_unit','x11_root_framebuffer_px')
    if unit not in ['x11_root_framebuffer_px','logical_px','logical_points']:
        raise CaptureError('UNKNOWN_COORDINATE_SPACE')
    displays=[]; crtc_groups={}
    for i,(d,r) in enumerate(zip(ordered,rectangles),1):
        native = d.get('scanout_mode_px')
        if native is not None:
            if len(native)!=2: raise CaptureError('INVALID_MODE')
            native=[integer(native[0],True),integer(native[1],True)]
        rotation=d.get('rotation_deg')
        if rotation not in [0,90,180,270,None]: raise CaptureError('INVALID_ROTATION')
        oriented = None if native is None or rotation is None else (native[::-1] if rotation in [90,270] else native[:])
        physical=d.get('reported_panel_mm')
        if physical is not None:
            if len(physical)!=2: raise CaptureError('INVALID_PHYSICAL_SIZE')
            physical=[integer(physical[0]),integer(physical[1])]
            if any(v<=0 for v in physical): physical=None
        oriented_mm=None if physical is None or rotation is None else (physical[::-1] if rotation in [90,270] else physical[:])
        normalized=[r[0]-left,r[1]-top,r[2],r[3]]
        mapping=bool(d.get('mapping_known')) and oriented is not None
        sx=Fraction(oriented[0],r[2]) if mapping else None
        sy=Fraction(oriented[1],r[3]) if mapping else None
        native_id=f'D{i}'
        mode_list=[]
        if len(d.get('supported_modes',[]))>2048: raise CaptureError('MODE_COUNT_LIMIT')
        for mode in d.get('supported_modes',[]):
            size=mode.get('size_px')
            if not isinstance(size,list) or len(size)!=2: raise CaptureError('INVALID_MODE')
            mode_list.append({'size_px':[integer(size[0],True),integer(size[1],True)],'refresh_millihz':refresh(mode.get('refresh_millihz'))})
        display={
            'id':native_id,'connector_alias':f'output-{i}','primary':bool(d.get('primary')),'active':True,
            'desktop_rect':{'xywh':r,'unit':unit,'source':'platform adapter'},
            'normalized_rect':{'xywh':normalized,'unit':unit},
            'logical_rect':{'xywh':r,'unit':unit} if unit in ['logical_px','logical_points'] else None,
            'logical_rect_reason':None if unit in ['logical_px','logical_points'] else 'UI logical scaling not queried; X11 root coordinates are kept separately.',
            'backing_size_px':dimensions(d.get('backing_size_px')),'backing_size_reason':None if d.get('backing_size_px') else 'No application backing-store API queried.',
            'scanout_mode_px':native,'oriented_output_px':oriented,'rotation_deg':rotation,
            'randr_transform':transform(d.get('transform')), 'reflection':d.get('reflection') if d.get('reflection') in ['none','reflected'] else 'unknown',
            'ui_scale':None,'ui_scale_reason':'Not observable from this collector; physical PPI is not UI scale.',
            'reported_physical_mm':{'panel_axes':physical,'oriented_axes':oriented_mm,'source':'XRandR reported output dimensions' if physical else None,'quality':'REPORTED_NOT_MEASURED' if physical else 'UNKNOWN','reason':None if physical else 'Zero, absent or invalid reported dimensions; no DPI fallback.'},
            'refresh_millihz':refresh(d.get('refresh_millihz')),'refresh_source':'Adapter-reported timing; utility-rounded for XRandR, not a playback measurement',
            'supported_modes':mode_list,'internal':None,'virtual':None,
            'color_hdr':{'capability':None,'enabled':None,'reason':'Not qualified by this adapter.'},
            'mapping_status':'EXACT_DIGITAL_AFFINE' if mapping else 'UNRESOLVED',
            'mapping_reason':None if mapping else 'Adapter could not qualify the display-to-desktop mapping; do not infer an exact crop.',
            'master_to_output_affine_rationals':[ratio(sx),[0,1],ratio(-normalized[0]*sx),[0,1],ratio(sy),ratio(-normalized[1]*sy)] if mapping else None,
            'oriented_to_native_pixel_edge_affine':native_transform(rotation,*native) if native is not None and rotation is not None else None,
            'crop_contract':{'master_xywh':normalized,'master_unit':unit,'output_size_px':oriented,'rule':'Crop first in the shared canvas coordinate space, then resample that local crop to this output. Never scale global positions by per-display UI scale.','rotation':'Already upright in oriented_output_px; do not rotate twice.'} if mapping else None,
            'physical_placement':{'bezel_mm':None,'gap_mm':None,'angle_deg':None,'depth_mm':None,'reason':'Not observable from OS desktop placement.'}
        }
        displays.append(display)
        if d.get('_crtc') is not None: crtc_groups.setdefault(d['_crtc'],[]).append(native_id)
    groups=[{'id':f'clone-{i+1}','members':members,'evidence':'Same active XRandR CRTC; not inferred from overlap.'} for i,members in enumerate(v for v in crtc_groups.values() if len(v)>1)]
    normalized_rects=[d['normalized_rect']['xywh'] for d in displays]
    mask,holes=partition(normalized_rects,[0,0,width,height])
    overlaps=[]
    for i,a in enumerate(normalized_rects):
        for j,b in enumerate(normalized_rects[i+1:],i+1):
            x=max(a[0],b[0]); y=max(a[1],b[1]); right=min(a[0]+a[2],b[0]+b[2]); bottom=min(a[1]+a[3],b[1]+b[3])
            if right>x and bottom>y: overlaps.append({'displays':[displays[i]['id'],displays[j]['id']],'xywh':[x,y,right-x,bottom-y],'relation':'confirmed_clone' if any(displays[i]['id'] in g['members'] and displays[j]['id'] in g['members'] for g in groups) else 'overlap_only_mirroring_unknown'})
    g=gcd(width,height)
    mapping_complete=all(d['mapping_status']=='EXACT_DIGITAL_AFFINE' for d in displays)
    return {
        'schema_version':SCHEMA_VERSION,'tool_version':'0.1.0-proposal',
        'capture':{'utc':timestamp,'os_family':os_family,'session_protocol':session,'backend':snapshot.get('backend','fixture'),
                   'overall_completeness':'PARTIAL','display_geometry':'COMPLETE' if mapping_complete else 'INCOMPLETE',
                   'snapshot_coherence':snapshot.get('coherence',{'status':'FIXTURE'}),'source_errors':snapshot.get('errors',[]),
                   'privacy':'Allowlisted metadata only: no pixels, raw EDID, serials, titles, usernames, paths, hostname or network identifiers.'},
        'canvas':{'source_origin':[left,top],'normalized_origin':[0,0],'size':[width,height],'unit':unit,'aspect_ratio':[width//g,height//g],
                  'coordinate_rule':'Top-left origin, x right, y down. Rectangles are half-open pixel/coordinate edges [x,x+w) x [y,y+h).',
                  'physical_continuity':'UNVERIFIED; digital desktop placement does not measure desk gaps or bezels.'},
        'displays':displays,'active_mask_disjoint_rects':mask,'unused_canvas_rects':holes,
        'clone_groups':groups,'overlaps':overlaps,'inactive_output_count':snapshot.get('inactive_output_count',0),
        'window_geometry':{'status':'NOT_IMPLEMENTED','items':None,'reason':'Title-free per-window bounds, work areas, occlusion and privacy behavior remain required product work.'},
        'media_contract':{'exact_crops_available':mapping_complete,'master_size': [width,height],
          'fit_rule':'Inspect actual generated dimensions. Fit one shared master to the canvas before any per-display crop; never fit displays independently. Any crop, padding or upscale must be declared.',
          'mask_rule':'Only active_mask_disjoint_rects are visible. unused_canvas_rects are digital holes, not measured physical gaps. Duplicate clone crops must not enlarge the canvas.',
          'motion_rule':'Use one shared frame timeline, duration and fps for every output. Locked camera and low motion are defaults; codec, decode headroom, playback sync and seamless looping are NOT_TESTED.',
          'focus_rule':'Keep critical subjects within an individual display rectangle; seams and unused areas should contain expendable scenery. No application/window-safe region is known.'},
        'remaining_gates':['Windows native collector NOT_IMPLEMENTED','macOS native collector NOT_IMPLEMENTED','Wayland native collector NOT_IMPLEMENTED','Window geometry NOT_IMPLEMENTED','Signed portable packaging NOT_BUILT','PDF ingestion by target AI NOT_TESTED','Generated media fit/crop/video export NOT_IMPLEMENTED','Actual synchronized wallpaper playback NOT_TESTED']
    }

def canonical_json(manifest):
    return json.dumps(manifest,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)

def prompts(manifest):
    w,h=manifest['canvas']['aspect_ratio']; limit=14
    supported=max(w,h)<=limit*min(w,h)
    still=(f'A tranquil panoramic fantasy landscape at blue hour, one continuous world across the complete canvas, coherent horizon and lighting, spacious detailed atmospheric scenery, critical focal subjects inside a single screen region, no text, no screen borders --ar {w}:{h}') if supported else None
    return {'provider_policy_date':'2026-10-18','still_status':'READY_TEMPLATE_NOT_GENERATED' if supported else 'UNSUPPORTED_ASPECT_RATIO',
      'midjourney_still':still,'midjourney_motion':'Locked camera; gentle foliage movement and drifting mist; preserve composition and horizon; subtle continuous motion returning smoothly to the starting scene --motion low --loop --raw --bs 1',
      'motion_use':'First generate/select the shared master still, then use it as the starting image in the web animation UI. This motion prompt has no still-only --ar parameter. No upload or provider call occurs here.',
      'general_ai':'Read the complete canonical JSON appendix as the geometry contract. Design one shared master with the stated canvas aspect, honor the active mask and crop rules, and explicitly distinguish observed digital geometry from unknown physical spacing and missing window bounds. Return a tailored still-image prompt and a compatible low-motion animation prompt. Do not claim exact pixel dimensions from prompt text alone.',
      'provider_limits':'Still ratio does not guarantee output pixels; video may adjust ratio. Verify and fit generated media before cropping. The 14:1 non-HD still policy must be refreshed before release; extreme-ratio layouts are rejected, not silently truncated. No model-version flag is hardcoded.',
      'sources':['https://docs.midjourney.com/hc/en-us/articles/31894244298125-Aspect-Ratio','https://docs.midjourney.com/hc/en-us/articles/32199405667853-Version','https://docs.midjourney.com/hc/en-us/articles/37460773864589-Video']}
