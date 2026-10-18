import copy,json,unittest
from blueprint.core import normalize,canonical_json,CaptureError
from blueprint.platforms import capabilities
from blueprint.x11 import parse,coherent_capture
from test_capture import output,STAMP

def windows(**overrides):
    item={'_window_id':123456789,'client_rect':[-150,20,500,300],'frame_extents':[5,5,25,5],'border_width':1,'map_state':2,'override_redirect':False,'desktop':0,'type':'normal','states':[],
      'title':'PRIVATE_TITLE_CANARY','class':'PRIVATE_CLASS_CANARY','pid':99999999,'pixels':'PRIVATE_PIXELS_CANARY'}
    item.update(overrides)
    return {'status':'CAPTURED_MANAGED_WINDOWS','items':[item],'current_desktop':0,'desktop_count':2,'work_area':[0,30,1920,1050],'viewport':[0,0]}
def manifest(raw=None):
    snap=parse(output(x=-1920)+output('B',x=0,crtc=1));snap['windows']=windows() if raw is None else raw
    return normalize(snap,STAMP)
class Windows(unittest.TestCase):
    def test_negative_origin_frame_border_clip_and_private_canaries(self):
        m=manifest();w=m['window_geometry']['items'][0]
        self.assertEqual(w['frame_rect'],[-156,-6,512,332]);self.assertEqual(w['normalized_frame_rect'],[1764,-6,512,332])
        self.assertEqual(w['possible_cover_rects'],[{'display':'D1','xywh':[1764,0,156,326]},{'display':'D2','xywh':[1920,0,356,326]}])
        text=canonical_json(m)
        for private in ('PRIVATE_TITLE_CANARY','PRIVATE_CLASS_CANARY','PRIVATE_PIXELS_CANARY','123456789','99999999'):self.assertNotIn(private,text)
        self.assertEqual(w['actual_visibility'],'UNKNOWN')
    def test_hidden_other_desktop_unmapped_and_desktop_surface_not_coverage(self):
        for change in ({'states':['hidden']},{'desktop':1},{'map_state':0},{'map_state':1},{'type':'desktop'},{'desktop':None}):
            with self.subTest(change=change):self.assertEqual(manifest(windows(**change))['window_geometry']['items'][0]['possible_cover_rects'],[])
        self.assertTrue(manifest(windows(desktop=0xffffffff))['window_geometry']['items'][0]['on_current_desktop'])
    def test_missing_frame_and_nonzero_viewport_are_unknown(self):
        raw=windows(frame_extents=None);raw['viewport']=[1920,0]
        result=manifest(raw)['window_geometry'];self.assertIsNone(result['items'][0]['frame_rect']);self.assertEqual(result['items'][0]['cover_basis'],'client_bounds_only')
        self.assertIsNone(result['work_area']['normalized_xywh']);self.assertEqual(result['work_area']['status'],'UNRESOLVED')
    def test_malformed_geometry_and_bounds_rejected(self):
        for change in ({'frame_extents':[-1,0,0,0]},{'frame_extents':[1,2]},{'border_width':-1},{'map_state':True},{'client_rect':[0,0,0,1]},{'states':['PRIVATE_UNKNOWN_STATE']}):
            with self.subTest(change=change),self.assertRaises(CaptureError):manifest(windows(**change))
        raw=windows();raw['items']*=257
        with self.assertRaises(CaptureError):manifest(raw)
    def test_window_coordinates_are_not_reinterpreted_as_logical_scale(self):
        snap=parse(output());snap['desktop_unit']='logical_points';snap['windows']=windows()
        with self.assertRaises(CaptureError):normalize(snap,STAMP)
    def test_unknown_platforms_never_claim_implementation_or_permission(self):
        for system,session,key in [('Windows','','windows'),('Darwin','','darwin'),('Linux','wayland','linux_wayland')]:
            c=capabilities(system,session);self.assertEqual(c['current'],key)
            self.assertEqual(c['adapters'][key]['windows'],'IMPLEMENTED_CANDIDATE_NATIVE_UNQUALIFIED' if key=='windows' else 'NOT_IMPLEMENTED')
    def test_full_pair_coherence_and_window_instability_preserve_qualified_displays(self):
        count=[0]
        def moving(**kwargs):count[0]+=1;return windows(client_rect=[count[0],0,100,100])
        result=coherent_capture(query=lambda **_:output(),window_query=lambda **_:windows(),session='x11')
        self.assertEqual(result['coherence']['status'],'TWO_MATCHING_SNAPSHOTS')
        result=coherent_capture(query=lambda **_:output(),window_query=moving,session='x11')
        self.assertEqual(result['windows']['status'],'UNAVAILABLE');self.assertIn('WINDOWS_CHANGED_DURING_CAPTURE',result['errors'])
    def test_permission_failure_does_not_erase_display_geometry(self):
        result=coherent_capture(query=lambda **_:output(),window_query=lambda **_:{'status':'UNAVAILABLE','code':'X11_WINDOW_ACCESS_UNAVAILABLE'},session='x11')
        m=normalize(result,STAMP);self.assertEqual(m['capture']['display_geometry'],'COMPLETE');self.assertEqual(m['window_geometry']['status'],'UNAVAILABLE')
