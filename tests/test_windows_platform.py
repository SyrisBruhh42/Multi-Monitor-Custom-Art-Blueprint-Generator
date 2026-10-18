"""Synthetic Windows observations, explicitly not native Windows evidence."""
import copy,io,json,sys,time,unittest
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
from blueprint.core import CaptureError,normalize,canonical_json
from blueprint.windows import parse,coherent_capture,bounded_worker,UNIT
from blueprint.cli import main

STAMP='2026-10-18T22:00:00+00:00'
def fixture():
    return {'status':'CAPTURED','dpi_context_verified':True,'paths':[{
      'source_adapter':[7,0],'source_id':0,'source_index':0,'target_adapter':[7,0],'target_id':1,'target_index':1,
      'flags':1,'rotation':1,'scaling':1,'target_available':True,'path_refresh':[60000,1000],'_gdi':'PRIVATE_GDI_CANARY'}],
      'modes':[{'kind':1,'id':0,'adapter':[7,0],'rect':[0,0,1920,1080]},
        {'kind':2,'id':1,'adapter':[7,0],'active_size':[1920,1080],'refresh':[60000,1000],'scanline':1,'vsync_divider':0}],
      'monitors':[{'_gdi':'PRIVATE_GDI_CANARY','rect':[0,0,1920,1080],'work':[0,0,1920,1040],'primary':True,'scale_percent':125}],
      'windows':{'status':'CAPTURED_TOPLEVEL_WINDOWS','items':[{'_handle':987654321123,'outer_rect':[40,50,800,600],'frame_rect':[47,50,786,593],'visible_style':True,'minimized':False,'cloaked':0,'title':'PRIVATE_TITLE_CANARY'}]}}

def second(raw,x=-1080,y=-500,rotation=2,scale=150):
    path=copy.deepcopy(raw['paths'][0]);path.update(source_id=1,target_id=2,source_index=2,target_index=3,rotation=rotation,_gdi='PRIVATE_SECOND_CANARY')
    raw['paths'].append(path)
    size=[1080,1920] if rotation in (2,4) else [1920,1080]
    raw['modes'] += [{'kind':1,'id':1,'adapter':[7,0],'rect':[x,y,*size]},
      {'kind':2,'id':2,'adapter':[7,0],'active_size':[1920,1080],'refresh':[60000,1001],'scanline':1,'vsync_divider':0}]
    raw['monitors'].append({'_gdi':'PRIVATE_SECOND_CANARY','rect':[x,y,*size],'work':[x,y,*size],'primary':False,'scale_percent':scale})
    return raw
def manifest(raw=None):
    snapshot=parse(raw or fixture());snapshot['coherence']={'status':'SYNTHETIC_FIXTURE_NOT_HOST_CAPTURE'}
    return normalize(snapshot,STAMP,os_family='Windows',session='windows_desktop')
def code(test,expected,fn):
    with test.assertRaises(CaptureError) as error:fn()
    test.assertEqual(error.exception.code,expected)

class WindowsGeometry(unittest.TestCase):
    def test_explicit_windows_space_and_unknowns(self):
        m=manifest();d=m['displays'][0]
        self.assertEqual(m['schema_version'],'1.2.0');self.assertEqual(m['canvas']['unit'],UNIT)
        self.assertEqual(d['ui_scale'],[125,100]);self.assertIsNone(d['logical_rect']);self.assertIsNone(d['backing_size_px'])
        self.assertIsNone(d['reported_physical_mm']['panel_axes']);self.assertIsNone(d['oriented_to_native_pixel_edge_affine'])
        self.assertEqual(d['windows']['rotation_convention'],'CCD_CLOCKWISE')
        self.assertEqual(m['capture']['overall_completeness'],'PARTIAL')
    def test_negative_origin_portrait_and_mixed_scale_do_not_scale_positions(self):
        m=manifest(second(fixture()));self.assertEqual(m['canvas']['source_origin'],[-1080,-500])
        self.assertEqual(m['canvas']['size'],[3000,1920]);self.assertEqual(m['displays'][0]['oriented_output_px'],[1080,1920])
        self.assertEqual(m['displays'][1]['normalized_rect']['xywh'],[1080,500,1920,1080])
        self.assertEqual(m['displays'][1]['master_to_output_affine_rationals'],[[1,1],[0,1],[-1080,1],[0,1],[1,1],[-500,1]])
        self.assertEqual(m['window_geometry']['items'][0]['normalized_outer_rect'],[1120,550,800,600])
    def test_all_rotations_and_scale_metadata(self):
        for rotation in [1,2,3,4]:
            for scale in [100,125,150,200]:
                raw=second(fixture(),rotation=rotation,scale=scale);m=manifest(raw)
                self.assertEqual(m['displays'][0]['rotation_deg'],(rotation-1)*90)
                self.assertEqual(m['displays'][0]['ui_scale'],[scale,100]);self.assertTrue(m['media_contract']['exact_crops_available'])
    def test_clone_requires_same_source_not_overlap(self):
        raw=fixture();p=copy.deepcopy(raw['paths'][0]);p.update(target_id=2,target_index=2);raw['paths'].append(p)
        t=copy.deepcopy(raw['modes'][1]);t['id']=2;raw['modes'].append(t)
        m=manifest(raw);self.assertEqual(len(m['clone_groups']),1);self.assertEqual(m['canvas']['size'],[1920,1080])
        self.assertIn('CCD',m['clone_groups'][0]['evidence'])
        raw=second(fixture(),x=0,y=1,rotation=1);m=manifest(raw)
        self.assertFalse(m['clone_groups']);self.assertEqual(m['overlaps'][0]['relation'],'overlap_only_mirroring_unknown')
    def test_virtual_indexes_and_full_image_remain_role_unqualified(self):
        raw=fixture();raw['paths'][0].update(flags=9,source_index=0xffff,target_index=(1<<16)|2)
        raw['modes'].append({'kind':3,'id':1,'adapter':[7,0],'path_size':[1920,1080],'region':[0,0,1920,1080],'clip':[0,0,1920,1080]})
        self.assertFalse(manifest(raw)['media_contract']['exact_crops_available'])
        raw['modes'][2]['clip']=[0,0,1800,1080]
        self.assertFalse(manifest(raw)['media_contract']['exact_crops_available'])
    def test_desktop_image_malformed_id_refuses(self):
        for identity in (None,True,False,'private-invalid-identity',-1,2**32):
            with self.subTest(identity=identity):
                raw=fixture();raw['paths'][0].update(flags=9,source_index=0xffff,target_index=(1<<16)|2)
                raw['modes'].append({'kind':3,'id':identity,'adapter':[7,0],'path_size':[1920,1080],'region':[0,0,1920,1080],'clip':[0,0,1920,1080]})
                code(self,'WINDOWS_MALFORMED_OBSERVATION',lambda:manifest(raw))
    def test_desktop_image_foreign_id_refuses(self):
        raw=fixture();raw['paths'][0].update(flags=9,source_index=0xffff,target_index=(1<<16)|2)
        raw['modes'].append({'kind':3,'id':999,'adapter':[7,0],'path_size':[1920,1080],'region':[0,0,1920,1080],'clip':[0,0,1920,1080]})
        code(self,'WINDOWS_MODE_IDENTITY_MISMATCH',lambda:manifest(raw))
    def test_desktop_image_endpoint_role_stays_unqualified(self):
        for identity in (0,1):
            with self.subTest(identity=identity):
                raw=fixture();raw['paths'][0].update(flags=9,source_index=0xffff,target_index=(1<<16)|2)
                raw['modes'].append({'kind':3,'id':identity,'adapter':[7,0],'path_size':[1920,1080],'region':[0,0,1920,1080],'clip':[0,0,1920,1080]})
                m=manifest(raw)
                self.assertFalse(m['media_contract']['exact_crops_available'])
                self.assertIsNone(m['displays'][0]['crop_contract'])
                self.assertIn('WINDOWS_DESKTOP_IMAGE_IDENTITY_ROLE_UNQUALIFIED',m['capture']['source_errors'])
    def test_desktop_image_cross_adapter_pair_cannot_be_mixed(self):
        for image_adapter,identity,accepted in [([7,0],0,True),([8,0],1,True),([7,0],1,False),([8,0],0,False),([9,0],0,False)]:
            with self.subTest(adapter=image_adapter,identity=identity):
                raw=fixture();raw['paths'][0].update(flags=9,source_index=0xffff,target_index=(1<<16)|2,target_adapter=[8,0]);raw['modes'][1]['adapter']=[8,0]
                raw['modes'].append({'kind':3,'id':identity,'adapter':image_adapter,'path_size':[1920,1080],'region':[0,0,1920,1080],'clip':[0,0,1920,1080]})
                if accepted:
                    self.assertFalse(manifest(raw)['media_contract']['exact_crops_available'])
                else:
                    code(self,'WINDOWS_MODE_IDENTITY_MISMATCH',lambda:manifest(raw))
    def test_virtual_image_missing_withholds_exact_crop(self):
        raw=fixture();raw['paths'][0].update(flags=9,source_index=0xffff,target_index=(1<<16)|0xffff)
        m=manifest(raw);self.assertFalse(m['media_contract']['exact_crops_available']);self.assertIsNone(m['displays'][0]['crop_contract'])
    def test_nonidentity_and_unknown_rotation_withhold_mapping(self):
        for field,values in [('scaling',[2,3,4,5,128,999]),('rotation',[0,99])]:
            for value in values:
                raw=fixture();raw['paths'][0][field]=value;m=manifest(raw)
                self.assertFalse(m['media_contract']['exact_crops_available'])
    def test_missing_target_keeps_source_but_no_output_invention(self):
        raw=fixture();raw['paths'][0]['target_index']=0xffffffff;m=manifest(raw)
        self.assertIsNone(m['displays'][0]['scanout_mode_px']);self.assertFalse(m['media_contract']['exact_crops_available'])
    def test_unknown_ui_scale_never_falls_back_to_one(self):
        for value in [None,123,False]:
            raw=fixture();raw['monitors'][0]['scale_percent']=value;m=manifest(raw)
            self.assertIsNone(m['displays'][0]['ui_scale']);self.assertIn('WINDOWS_UI_SCALE_UNAVAILABLE',m['capture']['source_errors'])
    def test_refresh_ambiguity_remains_null(self):
        for changes in [{'refresh':[1,0]},{'scanline':2},{'vsync_divider':1}]:
            raw=fixture();raw['modes'][1].update(changes);self.assertIsNone(manifest(raw)['displays'][0]['refresh_millihz'])
        raw=fixture();raw['paths'][0]['flags']|=16;self.assertIsNone(manifest(raw)['displays'][0]['refresh_millihz'])
    def test_windows_outer_and_frame_are_not_client_or_visibility(self):
        w=manifest()['window_geometry']['items'][0]
        self.assertIsNone(w['client_rect']);self.assertEqual(w['outer_rect'],[40,50,800,600]);self.assertEqual(w['frame_rect'],[47,50,786,593])
        self.assertIsNone(w['on_current_desktop']);self.assertIsNone(w['stacking_order_bottom_to_top']);self.assertEqual(w['actual_visibility'],'UNKNOWN')
        self.assertEqual(w['possible_cover_rects'][0]['xywh'],[47,50,786,593])
    def test_missing_frame_and_cloak_do_not_invent_current_cover(self):
        raw=fixture();raw['windows']['items'][0].update(frame_rect=None,cloaked=None)
        w=manifest(raw)['window_geometry']['items'][0];self.assertIsNone(w['frame_rect']);self.assertEqual(w['possible_cover_rects'],[])
    def test_hidden_minimized_cloaked_and_empty_bounds(self):
        for changes in [{'visible_style':False},{'minimized':True},{'cloaked':1},{'outer_rect':None,'frame_rect':None}]:
            raw=fixture();raw['windows']['items'][0].update(changes)
            self.assertEqual(manifest(raw)['window_geometry']['items'][0]['possible_cover_rects'],[])
    def test_window_failure_keeps_display_capture(self):
        raw=fixture();raw['windows']={'status':'UNAVAILABLE','code':'PRIVATE_CANARY'};m=manifest(raw)
        self.assertEqual(m['window_geometry']['status'],'UNAVAILABLE');self.assertIsNone(m['window_geometry']['items'])
        self.assertEqual(m['capture']['display_geometry'],'COMPLETE');self.assertNotIn('PRIVATE',canonical_json(m))
    def test_privacy_identifiers_and_unknown_properties_never_export(self):
        raw=fixture();raw.update(path='PRIVATE_FILE_CANARY',EDID='PRIVATE_EDID_CANARY');raw['modes'][0]['private']='PRIVATE_SERIAL_CANARY'
        text=canonical_json(manifest(raw));self.assertNotIn('PRIVATE',text);self.assertNotIn('987654321123',text)
    def test_invalid_mode_identity_and_sentinels_refuse(self):
        for change in [{'source_index':0xffffffff},{'source_index':50},{'target_id':22},{'source_adapter':[8,0]}]:
            raw=fixture();raw['paths'][0].update(change)
            with self.assertRaises(CaptureError):parse(raw)
        raw=fixture();raw['modes'][0]['kind']=2;code(self,'WINDOWS_MODE_IDENTITY_MISMATCH',lambda:parse(raw))
    def test_join_unavailable_target_duplicate_and_primary_refuse(self):
        for mutate in [lambda r:r['monitors'][0].update(rect=[1,0,1920,1080]),lambda r:r['paths'][0].update(target_available=False),lambda r:r['paths'].append(copy.deepcopy(r['paths'][0])),lambda r:r['monitors'][0].update(primary=False)]:
            raw=fixture();mutate(raw)
            with self.assertRaises(CaptureError):parse(raw)
    def test_window_id_and_boolean_validation(self):
        for change in [{'_handle':0},{'_handle':True},{'visible_style':1},{'cloaked':True},{'outer_rect':[0,0,0,1]}]:
            raw=fixture();raw['windows']['items'][0].update(change)
            with self.assertRaises(CaptureError):manifest(raw)
    def test_counts_and_bad_payloads_refuse(self):
        for raw in ['{"status":"CAPTURED","status":"CAPTURED"}','{"x":NaN}','[]']:
            with self.assertRaises(CaptureError):parse(raw)
        raw=fixture();raw['paths']*=65;code(self,'WINDOWS_COUNT_OR_SHAPE_INVALID',lambda:parse(raw))
    def test_unavailable_worker_code_allowlist(self):
        code(self,'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE',lambda:parse({'status':'UNAVAILABLE','code':'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE'}))
        code(self,'WINDOWS_WORKER_INVALID_RESPONSE',lambda:parse({'status':'UNAVAILABLE','code':'PRIVATE_PATH'}))

class WindowsCoherence(unittest.TestCase):
    def test_hotplug_retries_then_matches(self):
        a=fixture();b=second(fixture());values=iter([a,b,b,b]);s=coherent_capture(query=lambda **_:next(values))
        self.assertEqual(s['coherence']['queries'],4);self.assertEqual(len(s['displays']),2)
    def test_continuous_changes_fail(self):
        values=iter([fixture(),second(fixture())]*3)
        code(self,'TOPOLOGY_CHANGED_DURING_CAPTURE',lambda:coherent_capture(query=lambda **_:next(values)))
    def test_unstable_windows_withhold_all_items_keep_display_warnings(self):
        values=[]
        for i in range(6):
            r=fixture();r['monitors'][0]['scale_percent']=None;r['windows']['items'][0]['outer_rect'][0]+=i;values.append(r)
        it=iter(values);s=coherent_capture(query=lambda **_:next(it))
        self.assertEqual(s['windows']['status'],'UNAVAILABLE');self.assertIn('WINDOWS_UI_SCALE_UNAVAILABLE',s['errors'])
    def test_intermittent_window_access_still_preserves_stable_displays(self):
        a=fixture();a['windows']={'status':'UNAVAILABLE'};values=iter([a,fixture()]*3)
        s=coherent_capture(query=lambda **_:next(values))
        self.assertEqual(s['windows']['status'],'UNAVAILABLE');self.assertEqual(len(s['displays']),1)
        self.assertIn('WINDOWS_CHANGED_DURING_CAPTURE',s['errors'])
    def test_timeout_overflow_invalid_encoding_and_exit(self):
        for expected,script in [('CAPTURE_TIMEOUT','import time;time.sleep(3)'),('SOURCE_OUTPUT_LIMIT','print("X"*300000)'),('MALFORMED_SOURCE_ENCODING','import os;os.write(1,b"\\xff")'),('WINDOWS_WORKER_FAILED','import sys;sys.exit(4)')]:
            start=time.monotonic();code(self,expected,lambda:bounded_worker(timeout=.2 if expected=='CAPTURE_TIMEOUT' else 2,command=[sys.executable,'-c',script]))
            self.assertLess(time.monotonic()-start,4)
    def test_cli_routes_windows_without_reading_linux_host(self):
        snapshot=parse(fixture());snapshot['coherence']={'status':'SYNTHETIC_FIXTURE_NOT_HOST_CAPTURE'}
        with patch('blueprint.cli.platform.system',return_value='Windows'),patch('blueprint.windows.coherent_capture',return_value=snapshot),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--metadata-only']),0)
        value=json.loads(out.getvalue());self.assertEqual(value['capture']['os_family'],'Windows');self.assertEqual(value['platform_capabilities']['current'],'windows')
    def test_cli_missing_desktop_does_not_emit_success(self):
        with patch('blueprint.cli.platform.system',return_value='Windows'),patch('blueprint.windows.coherent_capture',side_effect=CaptureError('WINDOWS_DESKTOP_ACCESS_UNAVAILABLE')),redirect_stdout(io.StringIO()) as out,redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(['--metadata-only']),2)
        self.assertEqual(out.getvalue(),'');self.assertEqual(json.loads(err.getvalue())['code'],'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE')

if __name__=='__main__':unittest.main(verbosity=2)
