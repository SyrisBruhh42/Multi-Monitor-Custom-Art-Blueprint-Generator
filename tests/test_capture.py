import copy,io,json,sys,time,unittest
from contextlib import redirect_stderr,redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fractions import Fraction
from blueprint.core import CaptureError,normalize,canonical_json,prompts,native_transform
from blueprint.x11 import parse,coherent_capture,bounded_query,OUTPUT_LIMIT
from blueprint.cli import main

STAMP='2026-10-18T20:00:00+00:00'

def output(name='FAKE-1',x=0,y=0,width=1920,height=1080,rotation='normal',mm=(600,340),crtc=0,transform='1 0 0\n  0 1 0\n  0 0 1',rate='60.00',extra=''):
    ow,oh=(height,width) if rotation in ['left','right'] else (width,height)
    return f'''{name} connected primary {ow}x{oh}{x:+d}{y:+d} (0xabc) {rotation} (normal left inverted right x axis y axis) {mm[0]}mm x {mm[1]}mm
    CRTC: {crtc}
    Transform: {transform}
{extra}
  {width}x{height} (0xabc) 100.0MHz +HSync +VSync *current
        h: width {width} start 1 end 2 total 3
        v: height {height} start 1 end 2 total 3 clock {rate}Hz
'''

def three():
    return output('LEFT',rotation='left',mm=(527,296),crtc=1)+output('CENTRE',x=1080,y=840,rate='180.00',crtc=0)+output('RIGHT',x=3000,rotation='right',mm=(527,296),crtc=2)

def manifest(text=None): return normalize(parse(text or three()),STAMP)
def code(test,expected,call):
    with test.assertRaises(CaptureError) as caught: call()
    test.assertEqual(caught.exception.code,expected)

class Geometry(unittest.TestCase):
    def test_three_monitor_contract(self):
        m=manifest(); self.assertEqual(m['canvas']['size'],[4080,1920]); self.assertEqual(m['canvas']['aspect_ratio'],[17,8])
        self.assertEqual(m['unused_canvas_rects'],[[1080,0,1920,840]])
        self.assertEqual([d['reported_physical_mm']['oriented_axes'] for d in m['displays']],[[296,527],[600,340],[296,527]])
        self.assertEqual(m['displays'][1]['refresh_millihz'],180000)
        self.assertEqual(m['capture']['overall_completeness'],'PARTIAL'); self.assertIsNone(m['window_geometry']['items'])
    def test_negative_origin_single_translation(self):
        m=manifest(output(x=-1920,y=-150)+output('B',x=0,y=70,crtc=1))
        self.assertEqual(m['canvas']['source_origin'],[-1920,-150]); self.assertEqual(m['canvas']['size'],[3840,1300])
        self.assertEqual([d['normalized_rect']['xywh'][:2] for d in m['displays']],[[0,0],[1920,220]])
    def test_mixed_logical_backing_and_scanout(self):
        snap=parse(output()+output('B',x=1920,crtc=1)); snap['desktop_unit']='logical_points'
        snap['displays'][1]['scanout_mode_px']=[3840,2160]; snap['displays'][1]['backing_size_px']=[3840,2160]
        m=normalize(snap,STAMP); second=m['displays'][1]
        self.assertEqual(m['canvas']['size'],[3840,1080]); self.assertEqual(second['normalized_rect']['xywh'],[1920,0,1920,1080])
        self.assertEqual(second['logical_rect']['xywh'],[1920,0,1920,1080]); self.assertEqual(second['backing_size_px'],[3840,2160])
        self.assertEqual(second['master_to_output_affine_rationals'],[[2,1],[0,1],[-3840,1],[0,1],[2,1],[0,1]])
    def test_master_affines_map_crop_edges(self):
        for d in manifest()['displays']:
            x,y,w,h=d['normalized_rect']['xywh']; a,b,c,e,f,g=map(lambda q:Fraction(*q),d['master_to_output_affine_rationals'])
            self.assertEqual([a*x+b*y+c,e*x+f*y+g],[0,0]); self.assertEqual([a*(x+w)+b*(y+h)+c,e*(x+w)+f*(y+h)+g],d['oriented_output_px'])
    def test_documented_nonorigin_scaled_master_example(self):
        snap=parse(output()+output('B',x=1920,crtc=1)); snap['desktop_unit']='logical_points'
        snap['displays'][1]['scanout_mode_px']=[3840,2160]
        d=normalize(snap,STAMP)['displays'][1]
        a,b,c,e,f,g=[Fraction(*q) for q in d['master_to_output_affine_rationals']]
        mapping=lambda x,y:[a*x+b*y+c,e*x+f*y+g]
        self.assertEqual(mapping(1920,0),[0,0]); self.assertEqual(mapping(3840,1080),[3840,2160])
        self.assertEqual(mapping(0,0),[-3840,0]) # Local offsets must NOT enter the master affine.
    def test_rotation_pixel_edges_all_four_orientations(self):
        for rotation in [0,90,180,270]:
            a,b,c,d,e,f=native_transform(rotation,1920,1080); w,h=([1080,1920] if rotation in [90,270] else [1920,1080])
            corners={(a*x+b*y+c,d*x+e*y+f) for x,y in [(0,0),(w,0),(0,h),(w,h)]}
            self.assertEqual(corners,{(0,0),(1920,0),(0,1080),(1920,1080)})
        self.assertEqual(native_transform(90,1920,1080),[0,-1,1920,1,0,0])
        self.assertEqual(native_transform(270,1920,1080),[0,1,0,-1,0,1080])
    def test_mask_exact_union_disjoint_no_double_count(self):
        m=manifest(output(width=4,height=3)+output('B',x=2,y=1,width=4,height=3,crtc=1)); mask=m['active_mask_disjoint_rects']; holes=m['unused_canvas_rects']
        def points(rects): return [(x,y) for rx,ry,w,h in rects for x in range(rx,rx+w) for y in range(ry,ry+h)]
        visible=points(mask); empty=points(holes); self.assertEqual(len(visible),len(set(visible))); self.assertFalse(set(visible)&set(empty)); self.assertEqual(len(visible)+len(empty),24)
        self.assertEqual(set(visible),set(points([[0,0,4,3],[2,1,4,3]])))
    def test_clones_require_crtc_evidence(self):
        m=manifest(output()+output('B')); self.assertEqual(m['canvas']['size'],[1920,1080]); self.assertEqual(len(m['clone_groups']),1)
        m=manifest(output()+output('B',crtc=1)); self.assertEqual(m['clone_groups'],[]); self.assertEqual(m['overlaps'][0]['relation'],'overlap_only_mirroring_unknown')
    def test_zero_mm_does_not_invent_physical_size(self):
        d=manifest(output(mm=(0,0)))['displays'][0]; self.assertIsNone(d['reported_physical_mm']['panel_axes']); self.assertIsNone(d['ui_scale'])
    def test_mappings_withheld_for_unresolved_transform(self):
        for raw in [output(transform='2 0 0\n  0 2 0\n  0 0 1'),output(rotation='normal x axis'),output(extra='    Panning: 3000x1080+0+0')]:
            m=manifest(raw); self.assertFalse(m['media_contract']['exact_crops_available']); self.assertIsNone(m['displays'][0]['crop_contract'])
    def test_privacy_canaries_not_exported(self):
        raw=output('CANARY_SERIAL_ABC',extra='    EDID:\n        CANARY_RAW_EDID\n    title: CANARY_PRIVATE_TITLE\n    path: /home/CANARY_USER/private.png')
        text=canonical_json(manifest(raw)); self.assertNotIn('CANARY',text); self.assertNotIn('/home/',text)
    def test_numeric_geometry_bounds(self):
        for changed in [dict(desktop_rect=[0,0,0,1080]),dict(desktop_rect=[0,0,10000001,1080]),dict(scanout_mode_px=[1920,False]),dict(refresh_millihz=-1)]:
            snap=parse(output()); snap['displays'][0].update(changed)
            with self.assertRaises(CaptureError): normalize(snap,STAMP)
    def test_ratio_limits_explicit_no_silent_truncation(self):
        p=prompts(manifest()); self.assertIn('--ar 17:8',p['midjourney_still']); self.assertNotIn('--ar',p['midjourney_motion'])
        m=manifest(output(width=15000,height=1000)); self.assertIsNone(prompts(m)['midjourney_still'])

class Sources(unittest.TestCase):
    def test_hotplug_retries_to_stable_pair(self):
        values=iter([output(),output(x=3),output(x=5),output(x=5)])
        s=coherent_capture(query=lambda **kwargs:next(values),session='x11'); self.assertEqual(s['coherence']['queries'],4); self.assertEqual(s['displays'][0]['desktop_rect'][0],5)
    def test_unstable_topology_fails(self):
        values=iter(output(x=i) for i in range(6)); code(self,'TOPOLOGY_CHANGED_DURING_CAPTURE',lambda:coherent_capture(query=lambda **kwargs:next(values),session='x11'))
    def test_wayland_not_misreported_as_complete_x11(self):
        code(self,'WAYLAND_NATIVE_ADAPTER_NOT_IMPLEMENTED',lambda:coherent_capture(session='wayland'))
    def test_current_mode_required(self): code(self,'CURRENT_MODE_MISSING',lambda:parse(output().replace('*current','')))
    def test_truncated_transform_fails_at_next_header(self): code(self,'MALFORMED_TRANSFORM',lambda:parse('A connected 1920x1080+0+0 normal\n Transform: 1 0 0\n'+output('B')))
    def test_malformed_transform(self): code(self,'MALFORMED_TRANSFORM',lambda:parse(output(transform='nan 0 0\n  0 1 0\n  0 0 1')))
    def test_malformed_rate(self): code(self,'MALFORMED_MODE',lambda:parse(output(rate='60..0')))
    def test_duplicate_outputs_fail(self): code(self,'DUPLICATE_OUTPUT',lambda:parse(output()+output()))
    def test_disconnected_output_count(self): self.assertEqual(parse(output()+'B disconnected (normal left right)\n')['inactive_output_count'],1)
    def test_interlaced_rate_withheld(self): self.assertIsNone(parse(output().replace('*current','*current Interlace'))['displays'][0]['refresh_millihz'])
    def test_timeout_is_bounded_and_sanitized(self):
        start=time.monotonic(); code(self,'CAPTURE_TIMEOUT',lambda:bounded_query(timeout=.15,command=[sys.executable,'-c','import time; time.sleep(3)'])); self.assertLess(time.monotonic()-start,1.5)
    def test_output_limit(self): code(self,'SOURCE_OUTPUT_LIMIT',lambda:bounded_query(command=[sys.executable,'-c','print("X"*300000)']))
    def test_encoding_error(self): code(self,'MALFORMED_SOURCE_ENCODING',lambda:bounded_query(command=[sys.executable,'-c','import os;os.write(1,b"\\xff")']))
    def test_exit_error_sanitized(self): code(self,'DISPLAY_QUERY_DENIED',lambda:bounded_query(command=[sys.executable,'-c','import sys;print("PRIVATE",file=sys.stderr);sys.exit(2)']))
    def test_parser_size_limit(self): code(self,'SOURCE_OUTPUT_LIMIT',lambda:parse('X'*(OUTPUT_LIMIT+1)))
    def test_failed_export_preserves_existing_file(self):
        with TemporaryDirectory() as tmp:
            fixture=Path(tmp)/'fixture.txt'; fixture.write_text(output()); target=Path(tmp)/'existing'; target.write_text('keep me')
            with redirect_stderr(io.StringIO()) as error:
                status=main(['--fixture',str(fixture),'--output',str(target)])
            self.assertEqual(status,3); self.assertEqual(target.read_text(),'keep me'); self.assertNotIn(tmp,error.getvalue())

if __name__=='__main__': unittest.main(verbosity=2)
