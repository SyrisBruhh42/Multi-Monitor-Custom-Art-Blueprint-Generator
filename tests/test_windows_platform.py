"""Synthetic Windows observations, explicitly not native Windows evidence."""
import copy,io,json,sys,time,unittest
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
from blueprint.core import CaptureError,normalize,canonical_json
from blueprint.windows import parse,coherent_capture,bounded_worker,UNIT
from blueprint.cli import main

STAMP='2026-10-18T22:00:00+00:00'
def fixture():
    return {'status':'CAPTURED','query_flags':18,'query_policy':'WINDOWS_VIRTUAL_AWARE_STRICT','dpi_context_verified':True,'paths':[{
      'source_adapter':[7,0],'source_id':0,'source_index':0,'target_adapter':[7,0],'target_id':1,'target_index':1,
      'flags':1,'rotation':1,'scaling':1,'target_available':True,'path_refresh':[60000,1000],'_gdi':'PRIVATE_GDI_CANARY'}],
      'modes':[{'kind':1,'id':0,'adapter':[7,0],'rect':[0,0,1920,1080]},
        {'kind':2,'id':1,'adapter':[7,0],'active_size':[1920,1080],'refresh':[60000,1000],'scanline':1,'vsync_divider':0}],
      'monitors':[{'_gdi':'PRIVATE_GDI_CANARY','rect':[0,0,1920,1080],'work':[0,0,1920,1040],'primary':True,'scale_percent':125}],
      'windows':{'status':'CAPTURED_TOPLEVEL_WINDOWS','items':[{'_handle':987654321123,'outer_rect':[40,50,800,600],'frame_rect':[47,50,786,593],'visible_style':True,'minimized':False,'cloaked':0,'title':'PRIVATE_TITLE_CANARY'}]}}

def legacy_fixture():
    raw=fixture();raw.update(query_flags=2,query_policy='WINDOWS_LEGACY_DESKTOP_LAYOUT');return raw

def desktop_manifest(raw=None):
    snapshot=parse(raw or legacy_fixture(),expected_query_flags=2)
    snapshot['coherence']={'status':'SYNTHETIC_FIXTURE_NOT_HOST_CAPTURE'}
    return normalize(snapshot,STAMP,os_family='Windows',session='windows_desktop')

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
        self.assertEqual(m['schema_version'],'1.3.0');self.assertEqual(m['canvas']['unit'],UNIT)
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
        snapshot=parse(legacy_fixture(),expected_query_flags=2);snapshot['coherence']={'status':'SYNTHETIC_FIXTURE_NOT_HOST_CAPTURE'}
        with patch('blueprint.cli.platform.system',return_value='Windows'),patch('blueprint.windows.desktop_capture',return_value=snapshot),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--metadata-only']),0)
        value=json.loads(out.getvalue());self.assertEqual(value['capture']['os_family'],'Windows');self.assertEqual(value['platform_capabilities']['current'],'windows')
    def test_cli_missing_desktop_does_not_emit_success(self):
        with patch('blueprint.cli.platform.system',return_value='Windows'),patch('blueprint.windows.coherent_capture',side_effect=CaptureError('WINDOWS_DESKTOP_ACCESS_UNAVAILABLE')),redirect_stdout(io.StringIO()) as out,redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(['--metadata-only']),2)
        self.assertEqual(out.getvalue(),'');self.assertEqual(json.loads(err.getvalue())['code'],'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE')

class LegacyDesktopPolicy(unittest.TestCase):
    def test_coherent_desktop_is_useful_but_never_panel_exact(self):
        from blueprint.windows import desktop_capture
        raw=second(legacy_fixture());snapshot=desktop_capture(query=lambda **_:copy.deepcopy(raw))
        m=normalize(snapshot,STAMP,os_family='Windows',session='windows_desktop')
        self.assertEqual(m['capture']['desktop_layout'],'OBSERVED_COHERENT')
        self.assertEqual(m['canvas']['size'],[3000,1920]);self.assertEqual(m['canvas']['source_origin'],[-1080,-500])
        self.assertEqual(m['displays'][1]['normalized_rect']['xywh'],[1080,500,1920,1080])
        self.assertEqual(m['window_geometry']['items'][0]['normalized_frame_rect'],[1127,550,786,593])
        self.assertEqual(m['capture']['display_geometry'],'INCOMPLETE');self.assertEqual(m['capture']['target_mapping'],'UNRESOLVED')
        self.assertEqual(m['schema_version'],'1.3.0');self.assertFalse(m['media_contract']['exact_crops_available'])
        self.assertEqual(m['capture']['windows_query']['query_flags'],2)
        for d in m['displays']:
            self.assertIsNone(d['windows']['virtual_mode_aware_path']);self.assertEqual(d['windows']['virtual_mode_awareness'],'NOT_REQUESTED')
            self.assertEqual(d['windows']['target_signal_active_px'],[1920,1080]);self.assertEqual(d['mapping_status'],'UNRESOLVED')
            for key in ('scanout_mode_px','oriented_output_px','crop_contract','master_to_output_affine_rationals','oriented_to_native_pixel_edge_affine','refresh_millihz'):
                self.assertIsNone(d[key])
        self.assertNotIn('PRIVATE',canonical_json(m));self.assertNotIn('987654321123',canonical_json(m))
    def test_matching_legacy_source_is_not_confirmed_physical_clone(self):
        raw=legacy_fixture();p=copy.deepcopy(raw['paths'][0]);p.update(target_id=2,target_index=2);raw['paths'].append(p)
        t=copy.deepcopy(raw['modes'][1]);t['id']=2;raw['modes'].append(t)
        m=desktop_manifest(raw);self.assertEqual(m['clone_groups'],[]);self.assertEqual(m['canvas']['size'],[1920,1080])
        self.assertEqual(m['overlaps'][0]['relation'],'overlap_only_mirroring_unknown')
    def test_explicit_backend_schema_and_per_display_agreement(self):
        from blueprint.core import validate_manifest_backend
        changes=[lambda m:m.update(schema_version='1.2.0'),lambda m:m['capture'].update(backend='Windows CCD + PMv2 User32/DWM read-only worker'),
          lambda m:m['capture'].update(os_family='Linux'),lambda m:m['capture'].update(session_protocol='x11'),
          lambda m:m['capture']['windows_query'].update(query_flags=18),lambda m:m['displays'][0]['windows'].update(query_flags=18,query_policy='WINDOWS_VIRTUAL_AWARE_STRICT')]
        for change in changes:
            with self.subTest(change=change):
                m=desktop_manifest();change(m)
                with self.assertRaises(CaptureError):validate_manifest_backend(m)
    def test_export_cannot_assert_legacy_crop_or_virtual_knowledge(self):
        from blueprint.core import validate_manifest_backend
        changes=[lambda m:m['media_contract'].update(exact_crops_available=True),lambda m:m['displays'][0].update(crop_contract={}),
          lambda m:m['displays'][0].update(oriented_output_px=[1920,1080]),lambda m:m['displays'][0].update(mapping_status='EXACT_DIGITAL_AFFINE'),
          lambda m:m.update(clone_groups=[{}]),lambda m:m['displays'][0]['windows'].update(virtual_mode_aware_path=False),
          lambda m:m['capture']['windows_query'].update(virtual_mode_awareness='REQUESTED')]
        for change in changes:
            with self.subTest(change=change):
                m=desktop_manifest();change(m)
                code(self,'WINDOWS_LEGACY_MAPPING_ASSERTION_INVALID',lambda:validate_manifest_backend(m))
    def test_raw_policy_required_and_strictly_typed(self):
        for updates in ({'query_flags':True},{'query_flags':False},{'query_flags':'2'},{'query_flags':None},{'query_flags':3},{'query_policy':'PRIVATE'}):
            raw=legacy_fixture();raw.update(updates)
            code(self,'WINDOWS_QUERY_POLICY_INVALID',lambda:parse(raw,expected_query_flags=2))
        raw=legacy_fixture();del raw['query_flags'];code(self,'WINDOWS_QUERY_POLICY_INVALID',lambda:parse(raw,expected_query_flags=2))
    def test_worker_cannot_silently_switch_backend(self):
        code(self,'WINDOWS_QUERY_POLICY_MISMATCH',lambda:parse(legacy_fixture()))
        code(self,'WINDOWS_QUERY_POLICY_MISMATCH',lambda:parse(fixture(),expected_query_flags=2))
        from blueprint.windows import desktop_capture
        values=iter([legacy_fixture(),fixture()])
        code(self,'WINDOWS_QUERY_POLICY_MISMATCH',lambda:desktop_capture(query=lambda **_:next(values)))
    def test_observed_packed_looking_words_are_never_reinterpreted(self):
        for raw in (fixture(),legacy_fixture()):
            raw['modes'].reverse();raw['paths'][0].update(source_index=131071,target_index=65535)
            code(self,'WINDOWS_MODE_INDEX_INVALID',lambda:parse(raw,expected_query_flags=raw['query_flags']))
    def test_legacy_virtual_flag_and_endpoint_corruption_refuse(self):
        raw=legacy_fixture();raw['paths'][0]['flags']=9
        code(self,'WINDOWS_LEGACY_VIRTUAL_PATH_UNQUALIFIED',lambda:parse(raw,expected_query_flags=2))
        for change in ({'source_index':0xffffffff},{'source_index':True},{'target_index':99},{'target_id':999},{'source_adapter':[8,0]}):
            raw=legacy_fixture();raw['paths'][0].update(change)
            with self.assertRaises(CaptureError):parse(raw,expected_query_flags=2)
    def test_legacy_optional_metadata_is_partial_never_invented(self):
        raw=legacy_fixture();raw['paths'][0]['target_index']=0xffffffff;raw['monitors'][0]['scale_percent']=None
        raw['windows']={'status':'UNAVAILABLE'};m=desktop_manifest(raw)
        self.assertIsNone(m['displays'][0]['ui_scale']);self.assertIsNone(m['displays'][0]['windows']['target_signal_active_px'])
        self.assertEqual(m['window_geometry']['status'],'UNAVAILABLE');self.assertFalse(m['media_contract']['exact_crops_available'])
    def test_legacy_window_instability_preserves_only_matching_desktop(self):
        from blueprint.windows import desktop_capture
        values=[]
        for i in range(6):
            raw=legacy_fixture();raw['windows']['items'][0]['outer_rect'][0]+=i;values.append(raw)
        it=iter(values);m=normalize(desktop_capture(query=lambda **_:next(it)),STAMP,os_family='Windows',session='windows_desktop')
        self.assertEqual(m['capture']['desktop_layout'],'OBSERVED_COHERENT');self.assertIsNone(m['window_geometry']['items'])
        self.assertEqual(m['capture']['snapshot_coherence']['status'],'MATCHING_DISPLAY_PAIR_WINDOW_CAPTURE_UNSTABLE')
    def test_legacy_topology_change_refuses(self):
        from blueprint.windows import desktop_capture
        it=iter([legacy_fixture(),second(legacy_fixture())]*3)
        code(self,'TOPOLOGY_CHANGED_DURING_CAPTURE',lambda:desktop_capture(query=lambda **_:next(it)))
    def test_legacy_source_identity_change_is_not_hidden_by_withheld_clone_export(self):
        from blueprint.windows import desktop_capture
        a=legacy_fixture();b=legacy_fixture();b['paths'][0]['source_id']=9;b['modes'][0]['id']=9
        it=iter([a,b]*3)
        code(self,'TOPOLOGY_CHANGED_DURING_CAPTURE',lambda:desktop_capture(query=lambda **_:next(it)))
    def test_default_desktop_worker_is_explicit_and_does_not_fallback(self):
        from blueprint.windows import desktop_capture
        calls=[]
        def query(**kwargs):calls.append(kwargs);return json.dumps(legacy_fixture())
        with patch('blueprint.windows.bounded_worker',side_effect=query):snapshot=desktop_capture()
        self.assertEqual(len(calls),2)
        for call in calls:self.assertEqual(call['command'],[sys.executable,'-B','-m','blueprint.windows_native','--desktop-layout'])
        with patch('blueprint.windows.bounded_worker',side_effect=CaptureError('WINDOWS_DESKTOP_ACCESS_UNAVAILABLE')) as mocked:
            code(self,'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE',desktop_capture)
            self.assertEqual(mocked.call_count,1)
    def test_cli_metadata_default_route_captures_partial_without_geometry_input(self):
        with patch('blueprint.cli.platform.system',return_value='Windows'),patch('blueprint.windows.bounded_worker',return_value=json.dumps(legacy_fixture())),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--metadata-only']),0)
        m=json.loads(out.getvalue());self.assertEqual(m['capture']['desktop_layout'],'OBSERVED_COHERENT')
        self.assertEqual(m['capture']['windows_query']['query_policy'],'WINDOWS_LEGACY_DESKTOP_LAYOUT')
        self.assertFalse(m['media_contract']['exact_crops_available'])

if __name__=='__main__':unittest.main(verbosity=2)
