"""Searchable PDF and synthetic diagram. No private pixels, external fonts or network."""
from pathlib import Path
from hashlib import sha256
from html import escape
from math import ceil
import json,uuid
from .core import canonical_json,prompts,CaptureError,validate_manifest_backend

PALETTE=['#287B8E','#7756A3','#B76E29','#4D8664']

def svg(manifest):
    w,h=manifest['canvas']['size']
    shapes=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="Synthetic display layout">',f'<rect width="{w}" height="{h}" fill="#E9EDF2"/>']
    for i,d in enumerate(manifest['displays']):
        x,y,rw,rh=d['normalized_rect']['xywh']; font=max(10,min(rw,rh)/10)
        shapes += [f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" fill="{PALETTE[i%len(PALETTE)]}" stroke="white" stroke-width="{max(w,h)/600}"/>',f'<text x="{x+rw/2}" y="{y+rh/2}" fill="white" text-anchor="middle" font-family="sans-serif" font-size="{font}">{d["id"]}</text>']
    return '\n'.join(shapes+['</svg>'])

def write_pdf(path,manifest):
    validate_manifest_backend(manifest)
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Preformatted,Flowable
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    # Embed ReportLab's bundled redistributable fonts; no host font install or substitution.
    fonts=Path(reportlab.__file__).parent/'fonts'
    pdfmetrics.registerFont(TTFont('BriefSans',str(fonts/'Vera.ttf')))
    pdfmetrics.registerFont(TTFont('BriefSansBold',str(fonts/'VeraBd.ttf')))
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyBrief',fontName='BriefSans',fontSize=9.5,leading=13,spaceAfter=8,textColor=colors.HexColor('#253344')))
    styles.add(ParagraphStyle(name='SmallBrief',fontName='BriefSans',fontSize=8,leading=11,spaceAfter=6))
    styles.add(ParagraphStyle(name='JsonBrief',fontName='BriefSans',fontSize=8,leading=10))
    for name in ['Title','Heading1','Heading2']: styles[name].fontName='BriefSansBold'
    styles['Title'].textColor=colors.HexColor('#16324B'); styles['Heading1'].textColor=colors.HexColor('#16324B')
    story=[]
    is_windows=manifest['canvas']['unit']=='windows_virtual_desktop_physical_px'
    legacy=is_windows and manifest['capture']['windows_query']['query_flags']==2
    def p(text,style='BodyBrief'): return Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style])
    def add(text,style='BodyBrief'): story.append(p(text,style))
    def table(rows,widths):
        t=Table([[p(str(cell),'SmallBrief') for cell in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E5EDF4')),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#B8C5D1')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),4)])); story.append(t)
    class Diagram(Flowable):
        def __init__(self): Flowable.__init__(self); self.width=490; self.height=245
        def draw(self):
            c=self.canv; w,h=manifest['canvas']['size']; scale=min(470/w,215/h); ox=(490-w*scale)/2; oy=18
            c.setFillColor(colors.HexColor('#E9EDF2')); c.rect(ox,oy,w*scale,h*scale,fill=1,stroke=0)
            for i,d in enumerate(manifest['displays']):
                x,y,rw,rh=d['normalized_rect']['xywh']; px=ox+x*scale; py=oy+(h-y-rh)*scale
                c.setFillColor(colors.HexColor(PALETTE[i%len(PALETTE)])); c.setStrokeColor(colors.white); c.rect(px,py,rw*scale,rh*scale,fill=1,stroke=1)
                c.setFillColor(colors.white); c.setFont('BriefSansBold',12); c.drawCentredString(px+rw*scale/2,py+rh*scale/2+5,d['id'])
                c.setFont('BriefSans',8); c.drawCentredString(px+rw*scale/2,py+rh*scale/2-8,f'{rw} x {rh}')
            c.setFillColor(colors.HexColor('#43566B')); c.setFont('BriefSans',8); c.drawCentredString(245,3,'Synthetic diagram. Gray areas are unused digital canvas, not measured desk gaps.')
    add('Your display-aware art brief','Title')
    add('OFFLINE CAPTURE PROPOSAL  |  Searchable, self-contained AI handoff','SmallBrief')
    add(f'Capture: {manifest["capture"]["utc"]}. Overall result: PARTIAL. Digital geometry: {manifest["capture"]["display_geometry"]}. Window geometry: {manifest["window_geometry"]["status"]}.')
    if legacy:
        add('Desktop layout captured. Exact per-screen crops are unavailable.','Heading2')
        add('This brief contains observed desktop regions and anonymous window bounds. Virtual display mapping, physical screen placement and exact panel outputs remain unknown. Backend: WINDOWS_LEGACY_DESKTOP_LAYOUT, query flags 2.','SmallBrief')
    if is_windows:
        add('Evidence: '+manifest['capture']['snapshot_coherence']['status']+'. Native Windows device qualification remains separate.','SmallBrief')
    w,h=manifest['canvas']['size']; a,b=manifest['canvas']['aspect_ratio']
    add(f'{len(manifest["displays"])} displays - {w} x {h} shared canvas','Heading1')
    add(f'Shared master aspect ratio: {a}:{b}. Diagram preserves desktop proportions.','SmallBrief')
    story.append(Diagram())
    rows=[['Display','Desktop x, y','Reported target px (unqualified)' if legacy else 'Upright pixels','Rotation','Upright size mm (reported)']]
    for d in manifest['displays']:
        r=d['desktop_rect']['xywh']; mm=d['reported_physical_mm']['oriented_axes']
        reported=d['windows']['target_signal_active_px'] if legacy else d['oriented_output_px']
        rows.append([d['id']+(' (primary)' if d['primary'] else ''),f'{r[0]}, {r[1]}',' x '.join(map(str,reported)) if reported else 'Unknown',str(d['rotation_deg'])+' deg' if d['rotation_deg'] is not None else 'Unknown',' x '.join(map(str,mm)) if mm else 'Unknown'])
    table(rows,[76,100,100,70,144]); story.append(Spacer(1,10))
    add('What is known','Heading2'); add('Windows source rectangles use physical desktop pixels under verified per-monitor awareness. Reported UI scale is separate from source-to-target display scaling. Physical millimeters, client/backing geometry and raw panel transforms remain unknown. Native Windows device qualification is still required.' if is_windows else 'Desktop rectangles, current scanout modes and orientation come from the operating system. Portrait physical axes are rotated once. Physical sizes are reported values, not ruler measurements. Logical UI scale, backing pixels, bezel width, desk gaps, monitor angles and the viewer position remain distinct or unknown.')
    add('What this file contains','Heading2'); add(('Observed desktop regions, unresolved panel mappings and composition rules,' if legacy else 'Exact digital mapping and mask rules,')+' still and motion prompts, source limitations, and every canonical JSON character in a searchable text appendix. No screenshot, window title, display serial, raw EDID or private file path is included.')
    story.append(PageBreak())
    add('Windows and desktop work area','Heading1')
    windows=manifest['window_geometry']
    add(f'Window capture: {windows["status"]}. {windows["scope"]}')
    add('Only anonymous numeric rectangles and states are included. Window titles, application names, content and pixels were not collected. Current bounds can guide composition, but do not establish opacity, actual wallpaper visibility or a privacy mask.')
    if windows.get('items') is not None:
        add(f'{len(windows["items"])} top-level windows. Enumeration order does not establish stacking; W identifiers are local to this capture.' if is_windows else f'{len(windows["items"])} managed windows. Order runs from bottom to top; W identifiers are local to this capture.','SmallBrief')
        rows=[['Window','Outer x, y, width, height' if is_windows else 'Client x, y, width, height','DWM frame bounds' if is_windows else 'Frame bounds','State / desktop']]
        for item in windows['items']:
            bounds=item.get('outer_rect') if is_windows else item['client_rect']
            rows.append([item['id'],', '.join(map(str,bounds)) if bounds else 'Unknown',', '.join(map(str,item['frame_rect'])) if item['frame_rect'] else ('Unknown' if is_windows else 'Unknown; client only'),item['map_state']+' / '+('current' if item['on_current_desktop'] is True else 'other' if item['on_current_desktop'] is False else 'unknown')])
        table(rows,[48,157,157,128])
        if is_windows:
            add('Client-area geometry was not collected. Outer bounds may include invisible resize borders. Virtual-desktop membership is unknown.','SmallBrief')
            table([['Display','Reported work area [x,y,w,h]']]+[[item['display'],str(item['source_xywh'])] for item in windows['work_areas']],[76,414])
        work=windows['work_area']
        add(f'Current desktop work area: {work["reported_xywh"] if work["reported_xywh"] else "unknown"}. Mapping: {work["status"]}. {work["reason"]}','SmallBrief')
    for limitation in windows['limitations']:add('- '+limitation,'SmallBrief')
    add('Platform readiness','Heading2')
    table([['Platform','Displays','Windows']]+[[key,value['displays'],value['windows']] for key,value in manifest['platform_capabilities']['adapters'].items()],[110,140,240])
    add(manifest['platform_capabilities']['portable_distribution'],'SmallBrief')
    story.append(PageBreak())
    add('Geometry and output contract','Title')
    add(manifest['canvas']['coordinate_rule']); add('Source desktop origin: '+str(manifest['canvas']['source_origin'])+'. Normalize by subtracting this one shared origin from every display. Units: '+manifest['canvas']['unit']+'.')
    rows=[['Display','Desktop region [x,y,w,h]' if legacy else 'Master crop [x,y,w,h]','Panel output' if legacy else 'Output size','Mapping']]
    for d in manifest['displays']:
        rows.append([d['id'],str(d['normalized_rect']['xywh']),str(d['oriented_output_px']) if d['oriented_output_px'] else 'Unknown',d['mapping_status']])
    table(rows,[50,175,100,165]); story.append(Spacer(1,10))
    add('Crop and scaling rules','Heading2')
    for key in ['fit_rule','mask_rule','motion_rule','focus_rule']: add(manifest['media_contract'][key])
    if legacy:
        add('Per-display affine transforms','Heading2')
        add('No per-display affine transforms or exact panel crops are supplied by this desktop-layout backend. Panel output dimensions and virtual-image mapping remain unknown. Shared desktop positions are never multiplied by per-monitor UI scale.')
    else:
        add('Per-display affine transforms','Heading2'); add('The JSON records six row-major affine coefficients [a,b,c,d,e,f] as exact [numerator,denominator] pairs: output_x=a*master_x+b*master_y+c; output_y=d*master_x+e*master_y+f. Inputs are normalized MASTER coordinates. Translation terms already subtract the crop origin; do not subtract it again before applying this affine. Global desktop positions are never multiplied by per-monitor UI scale. Unknown transforms have no exact crop contract.')
        add('Example: a crop at [1920,0,1920,1080] mapped to [3840,2160] has [2,0,-3840,0,2,0]. Master point [1920,0] maps to output [0,0], and [3840,1080] maps to [3840,2160]. If working with local crop offsets instead, apply only the scale [2,2], without that translation.','SmallBrief')
    add('Desktop regions and unused canvas' if legacy else 'Visible and unused mask','Heading2'); add(('OS-reported disjoint desktop regions: ' if legacy else 'Visible disjoint rectangles: ')+json.dumps(manifest['active_mask_disjoint_rects'])+'.'); add('Unused canvas rectangles: '+json.dumps(manifest['unused_canvas_rects'])+'.')
    add('Mirroring and overlap','Heading2'); add(json.dumps(manifest['clone_groups']) if manifest['clone_groups'] else 'No clone relation was confirmed by this collector. Overlap alone is never called mirroring.'); add('All overlap records and the explicitly unknown raw panel transform are preserved in the appendix.' if is_windows else 'All overlap records and native-panel rotation transforms are preserved in the appendix.')
    if legacy:
        add('Sources checked 2026-10-18','Heading2')
        add('\n'.join(manifest['prompts']['sources']+['https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig','https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect','https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getscalefactorformonitor']),'SmallBrief')
    story.append(PageBreak())
    prompt=manifest['prompts']; add('Ready-to-copy creative prompts','Title')
    add('Shared master still','Heading2'); add(prompt['midjourney_still'] or 'The canvas exceeds the supported aspect policy. Do not silently truncate or substitute a different layout.')
    add('Animate the selected starting image','Heading2'); add(prompt['midjourney_motion']); add(prompt['motion_use'])
    add('General AI instruction','Heading2'); add(prompt['general_ai'])
    add('Provider limits','Heading2'); add(prompt['provider_limits']); add('Templates only: no images or video have been generated, uploaded, purchased, decoded or applied to a desktop. Aspect ratio is not a guarantee of exact output dimensions. A loop flag is not evidence of perceptually seamless motion.')
    add('Remaining product gates','Heading2')
    for item in manifest['remaining_gates']: add('- '+item,'SmallBrief')
    if not legacy:
        add('Sources checked 2026-10-18','Heading2')
        for url in prompt['sources']: add(url,'SmallBrief')
        if is_windows:
            add('Windows topology: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig','SmallBrief')
            add('Window bounds: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect','SmallBrief')
            add('Per-monitor scale: https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getscalefactorformonitor','SmallBrief')
        else:
            add('EWMH: https://specifications.freedesktop.org/wm/latest-single/','SmallBrief')
            add('Xlib: https://xorg.freedesktop.org/archive/current/doc/libX11/libX11/libX11.html','SmallBrief')
            add('XRandR protocol: https://xorg.freedesktop.org/archive/current/doc/randrproto/randrproto.txt','SmallBrief')
    story.append(PageBreak())
    add('Complete canonical JSON','Title')
    canonical=canonical_json(manifest)
    # Index fixed chunks so PDF wrapping cannot silently modify JSON string contents.
    add('The complete canonical JSON follows as lossless JSON string fragments: Jnnnnnn|"encoded fragment"|END. Extract between the first | and final |END, decode that fragment as a JSON string, then concatenate decoded strings in numeric order with NO added spaces or line breaks. Spaces are encoded as \\u0020 so PDF readers cannot collapse or trim them. Quotes and backslashes use normal JSON string escaping. This reconstructs layout.json exactly; no attachment or OCR is needed.','SmallBrief')
    add('Canonical UTF-8 SHA-256: '+sha256(canonical.encode()).hexdigest(),'SmallBrief')
    chunks=[]; position=0
    def encode_chunk(chunk): return json.dumps(chunk,ensure_ascii=True).replace(' ','\\u0020')
    while position<len(canonical):
        length=min(84,len(canonical)-position)
        while pdfmetrics.stringWidth('J000000|'+encode_chunk(canonical[position:position+length])+'|END','BriefSans',8)>485: length-=1
        chunks.append(encode_chunk(canonical[position:position+length])); position+=length
    lines=[f'J{i+1:06d}|{chunk}|END' for i,chunk in enumerate(chunks)]
    for offset in range(0,len(lines),58):
        if offset: story.append(PageBreak()); add('Canonical JSON (continued)','Heading1')
        story.append(Preformatted('\n'.join(lines[offset:offset+58]),styles['JsonBrief'],maxLineLength=None))
    def footer(c,doc):
        c.setStrokeColor(colors.HexColor('#CCD6E0')); c.line(42,36,A4[0]-42,36)
        c.setFont('BriefSans',8); c.setFillColor(colors.HexColor('#53687D')); c.drawString(42,24,'Display art brief - private content excluded - local proposal'); c.drawRightString(A4[0]-42,24,str(doc.page))
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=38,bottomMargin=48,title='Display-aware art brief',author='Display Blueprint',subject='Synthetic geometry and AI wallpaper handoff').build(story,onFirstPage=footer,onLaterPages=footer)

def write_bundle(directory,manifest):
    validate_manifest_backend(manifest)
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex[:12]; staging=directory/('.partial-'+token); staging.mkdir()
    try:
        manifest['prompts']=prompts(manifest)
        (staging/'layout.json').write_text(canonical_json(manifest),encoding='utf-8')
        (staging/'layout.svg').write_text(svg(manifest),encoding='utf-8')
        (staging/'prompts.txt').write_text('\n\n'.join([manifest['prompts']['general_ai'],manifest['prompts']['midjourney_still'] or 'UNSUPPORTED_ASPECT_RATIO',manifest['prompts']['midjourney_motion'],manifest['prompts']['motion_use']]),encoding='utf-8')
        write_pdf(staging/'AI-brief.pdf',manifest)
        final=directory/('capture-'+token)
        staging.rename(final)
        return final
    except Exception:
        (staging/'failure.json').write_text('{"status":"EXPORT_FAILED","previous_exports":"untouched"}\n')
        raise
