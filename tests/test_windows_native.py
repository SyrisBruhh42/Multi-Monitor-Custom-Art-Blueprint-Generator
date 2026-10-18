"""ABI/fault checks; --native-readonly is a separate, strict native gate.

Ordinary unittest discovery never mistakes these fixtures for native capture.
The explicit gate returns nonzero for inaccessible/absent desktop or Windows.
"""
import ctypes as C
import hashlib,io,json,platform,sys,unittest
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from blueprint.core import CaptureError,normalize,canonical_json
from blueprint import windows_native as n

class Fake:
    def __init__(self):self.events=[];self.verified=True;self.failure=None
    def enter_dpi(self):self.events.append('enter');return 123
    def verify_dpi(self):self.events.append('verify');return self.verified
    def restore_dpi(self,old):self.events.append(('restore',old))
    def displays(self):
        self.events.append('displays')
        if self.failure:raise self.failure
        return [],[]
    def monitors(self):return []
    def windows(self):return {'status':'CAPTURED_TOPLEVEL_WINDOWS','items':[]}

class WindowsABI(unittest.TestCase):
    def test_fixed_width_structures_and_offsets(self):
        n.validate_abi()
        self.assertEqual({key:C.sizeof(getattr(n,key)) for key in n.EXPECTED_SIZES},n.EXPECTED_SIZES)
        self.assertEqual(C.sizeof(n.U32),4);self.assertEqual(C.sizeof(n.I32),4)
        self.assertEqual(n.PathTarget.refresh.offset,28);self.assertEqual(n.DisplayPath.flags.offset,68)
    def test_abi_mismatch_refuses(self):
        with patch.dict(n.EXPECTED_SIZES,{'Mode':1}):
            with self.assertRaises(CaptureError) as caught:n.validate_abi()
        self.assertEqual(caught.exception.code,'WINDOWS_ABI_UNQUALIFIED')
    def test_utf16_is_not_host_wchar(self):
        value=(C.c_uint16*32)();encoded='DISPLAY-Ω'.encode('utf-16-le')
        C.memmove(value,encoded,len(encoded));self.assertEqual(n.utf16(value),'DISPLAY-Ω')
    def test_import_does_not_load_native_dlls(self):
        with patch.object(n.sys,'platform','linux'):
            with self.assertRaises(CaptureError) as caught:n.Native()
        self.assertEqual(caught.exception.code,'WINDOWS_NATIVE_PLATFORM_REQUIRED')
    def test_dpi_context_restored_after_success(self):
        api=Fake();self.assertTrue(n.collect(api)['dpi_context_verified']);self.assertEqual(api.events[-1],('restore',123))
    def test_dpi_context_mismatch_refuses_before_geometry(self):
        api=Fake();api.verified=False
        with self.assertRaises(CaptureError):n.collect(api)
        self.assertNotIn('displays',api.events);self.assertEqual(api.events[-1],('restore',123))
    def test_query_failure_still_restores_and_preserves_fixed_error(self):
        api=Fake();api.failure=CaptureError('WINDOWS_DESKTOP_ACCESS_UNAVAILABLE')
        with self.assertRaises(CaptureError) as caught:n.collect(api)
        self.assertEqual(caught.exception.code,'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE');self.assertEqual(api.events[-1],('restore',123))
    def test_late_dpi_change_refuses(self):
        api=Fake();values=iter([True,False]);api.verify_dpi=lambda:next(values)
        with self.assertRaises(CaptureError):n.collect(api)
        self.assertEqual(api.events[-1],('restore',123))
    def test_window_failure_does_not_erase_display_observation(self):
        api=Fake();api.windows=lambda:(_ for _ in ()).throw(RuntimeError('PRIVATE'))
        value=n.collect(api);self.assertEqual(value['windows'],{'status':'UNAVAILABLE','code':'WINDOWS_WINDOW_QUERY_FAILED'})
    def test_buffer_count_refused_before_allocation_or_query(self):
        api=n.Native.__new__(n.Native);calls=[]
        def sizes(flags,paths,modes):paths._obj.value=65;modes._obj.value=2;return 0
        api.user=SimpleNamespace(GetDisplayConfigBufferSizes=sizes,QueryDisplayConfig=lambda *_:calls.append(1))
        with self.assertRaises(CaptureError) as caught:api.displays()
        self.assertEqual(caught.exception.code,'WINDOWS_DISPLAY_COUNT_LIMIT');self.assertFalse(calls)
    def test_insufficient_buffer_retry_has_fixed_bound(self):
        api=n.Native.__new__(n.Native);calls=[]
        def sizes(flags,paths,modes):paths._obj.value=1;modes._obj.value=2;return 0
        def query(*_):calls.append(1);return 122
        api.user=SimpleNamespace(GetDisplayConfigBufferSizes=sizes,QueryDisplayConfig=query)
        with self.assertRaises(CaptureError) as caught:api.displays()
        self.assertEqual(caught.exception.code,'WINDOWS_TOPOLOGY_CHANGED');self.assertEqual(len(calls),3)
    def test_access_denied_is_fixed_code(self):
        api=n.Native.__new__(n.Native);api.user=SimpleNamespace(GetDisplayConfigBufferSizes=lambda *_:5)
        with self.assertRaises(CaptureError) as caught:api.displays()
        self.assertEqual(caught.exception.code,'WINDOWS_DESKTOP_ACCESS_UNAVAILABLE')
    def test_scale_failure_discards_plausible_fallback_value(self):
        api=n.Native.__new__(n.Native)
        def info(handle,pointer):
            value=pointer._obj;value.monitor=n.Rect(0,0,1920,1080);value.work=n.Rect(0,0,1920,1040);value.flags=1
            encoded='DISPLAY'.encode('utf-16-le');C.memmove(C.addressof(value)+n.MonitorInfo.device.offset,encoded,len(encoded));return 1
        api.user=SimpleNamespace(EnumDisplayMonitors=lambda a,b,cb,d:cb(1,None,None,0),GetMonitorInfoW=info)
        def scale(_handle,pointer):pointer._obj.value=150;return 1
        api.shcore=SimpleNamespace(GetScaleFactorForMonitor=scale)
        self.assertIsNone(api.monitors()[0]['scale_percent'])
    def test_missing_optional_dwm_keeps_outer_bounds_with_unknown_frame(self):
        api=n.Native.__new__(n.Native);api.dwm=None
        def bounds(_handle,pointer):
            pointer._obj.left=5;pointer._obj.top=6;pointer._obj.right=105;pointer._obj.bottom=206;return 1
        api.user=SimpleNamespace(EnumWindows=lambda cb,data:cb(123,data),GetWindowRect=bounds,IsWindowVisible=lambda _:1,IsIconic=lambda _:0)
        item=api.windows()['items'][0]
        self.assertEqual(item['outer_rect'],[5,6,100,200]);self.assertIsNone(item['frame_rect']);self.assertIsNone(item['cloaked'])
    def test_successful_native_struct_decoding_uses_matching_tables(self):
        api=n.Native.__new__(n.Native)
        def sizes(flags,paths,modes):paths._obj.value=1;modes._obj.value=2;return 0
        def query(flags,np,paths,nm,modes,topology):
            self.assertEqual(flags,0x12);self.assertIsNone(topology)
            paths[0].source.adapter=n.LUID(7,0);paths[0].source.id=0;paths[0].source.index=0
            paths[0].target.adapter=n.LUID(7,0);paths[0].target.id=1;paths[0].target.index=1
            paths[0].target.rotation=1;paths[0].target.scaling=1;paths[0].target.available=1;paths[0].flags=1
            modes[0].kind=1;modes[0].id=0;modes[0].adapter=n.LUID(7,0)
            modes[0].value.source=n.SourceMode(1920,1080,4,n.Point(0,0))
            modes[1].kind=2;modes[1].id=1;modes[1].adapter=n.LUID(7,0)
            modes[1].value.target.active=n.Size(1920,1080);modes[1].value.target.v_sync=n.Rational(60000,1001);modes[1].value.target.scanline=1
            return 0
        def device(pointer):
            value=C.cast(pointer,C.POINTER(n.SourceName)).contents
            self.assertEqual(value.header.kind,1);self.assertEqual(value.header.size,84)
            encoded='DISPLAY'.encode('utf-16-le');C.memmove(C.addressof(value)+n.SourceName.name.offset,encoded,len(encoded));return 0
        api.user=SimpleNamespace(GetDisplayConfigBufferSizes=sizes,QueryDisplayConfig=query,DisplayConfigGetDeviceInfo=device)
        paths,modes=api.displays();self.assertEqual(paths[0]['_gdi'],'DISPLAY')
        self.assertEqual(modes[0]['rect'],[0,0,1920,1080]);self.assertEqual(modes[1]['refresh'],[60000,1001])
    def test_production_api_surface_excludes_content_and_mutation(self):
        text=Path(n.__file__).read_text()
        for forbidden in ['GetWindowText','GetClassName','GetWindowThreadProcessId','GetDC(','BitBlt','PrintWindow','SetDisplayConfig','ChangeDisplaySettings','SetWindowPos','ShowWindow','CreateWindow','OpenProcess','RegOpenKey','DwmSetWindowAttribute']:
            self.assertNotIn(forbidden,text)

def structural_summary(raw):
    """CI diagnostic only: bounded flags/indexes/types, never native identities."""
    from blueprint.windows import OUTPUT_LIMIT,MAX_PATHS,MAX_MODES
    if not isinstance(raw,str) or len(raw.encode('utf-8',errors='replace'))>OUTPUT_LIMIT:
        return {'status':'STRUCTURAL_RESPONSE_UNAVAILABLE'}
    try:value=json.loads(raw)
    except (ValueError,TypeError):return {'status':'STRUCTURAL_RESPONSE_UNAVAILABLE'}
    if not isinstance(value,dict) or value.get('status')!='CAPTURED':
        return {'status':'STRUCTURAL_RESPONSE_UNAVAILABLE'}
    paths=value.get('paths');modes=value.get('modes')
    if not isinstance(paths,list) or not isinstance(modes,list):
        return {'status':'STRUCTURAL_RESPONSE_UNAVAILABLE'}
    def number(v):return v if type(v) is int and 0<=v<=0xffffffff else None
    return {'status':'STRUCTURAL_ONLY_NOT_CAPTURE_ACCEPTANCE','query_flags':n.FLAGS,
      'path_count':len(paths),'mode_count':len(modes),
      'truncated':len(paths)>MAX_PATHS or len(modes)>MAX_MODES,
      'paths':[{key:number(item.get(key)) if isinstance(item,dict) else None
        for key in ('flags','source_index','target_index')} for item in paths[:MAX_PATHS]],
      'mode_types':[number(item.get('kind')) if isinstance(item,dict) else None for item in modes[:MAX_MODES]]}

class NativeReceiptDiagnostics(unittest.TestCase):
    def test_structural_summary_excludes_identity_geometry_and_canary_fields(self):
        from test_windows_platform import fixture
        raw=fixture();raw['paths'][0].update(source_id=123456789,target_id=234567890,source_adapter=[345678901,0],secret='CANARY_PATH')
        raw['modes'][0].update(id=456789012,adapter=[567890123,0],secret='CANARY_MODE')
        result=structural_summary(json.dumps(raw))
        self.assertEqual(result,{'status':'STRUCTURAL_ONLY_NOT_CAPTURE_ACCEPTANCE','query_flags':18,'path_count':1,'mode_count':2,'truncated':False,'paths':[{'flags':1,'source_index':0,'target_index':1}],'mode_types':[1,2]})
        for private in ['CANARY','PRIVATE','123456789','234567890','345678901','456789012','567890123','987654321123']:
            self.assertNotIn(private,json.dumps(result))
    def test_structural_summary_is_bounded_and_strict_numeric_only(self):
        raw={'status':'CAPTURED','paths':[{'flags':True,'source_index':'CANARY','target_index':-1}]*65,'modes':[{'kind':2**32}]*193}
        result=structural_summary(json.dumps(raw))
        self.assertTrue(result['truncated']);self.assertEqual(len(result['paths']),64);self.assertEqual(len(result['mode_types']),192)
        self.assertEqual(result['paths'][0],{'flags':None,'source_index':None,'target_index':None});self.assertIsNone(result['mode_types'][0])
    def test_structural_summary_keeps_virtual_union_words_without_interpretation(self):
        raw={'status':'CAPTURED','paths':[{'flags':9,'source_index':0xffff,'target_index':(1<<16)|0xffff}],'modes':[{'kind':1},{'kind':2}]}
        self.assertEqual(structural_summary(json.dumps(raw))['paths'],raw['paths'])
    def test_structural_summary_rejects_malformed_or_oversized_payload(self):
        for raw in ['CANARY','[]','{"status":"CAPTURED","paths":null}',json.dumps({'status':'UNAVAILABLE','code':'CANARY'}),'X'*262145,None]:
            self.assertEqual(structural_summary(raw),{'status':'STRUCTURAL_RESPONSE_UNAVAILABLE'})
    def probe(self,raw):
        with TemporaryDirectory() as tmp,patch.object(sys,'platform','win32'),patch('blueprint.windows.bounded_worker',return_value=json.dumps(raw)),redirect_stdout(io.StringIO()):
            destination=Path(tmp)/'receipt.json';exit_code=native_probe(destination)
            return exit_code,json.loads(destination.read_text())
    def test_invalid_mode_index_remains_failure_with_structural_diagnostic(self):
        from test_windows_platform import fixture
        raw=fixture();raw['paths'][0]['target_index']=999
        exit_code,result=self.probe(raw)
        self.assertEqual(exit_code,2);self.assertEqual(result['code'],'WINDOWS_MODE_INDEX_INVALID')
        self.assertEqual(result['native_capture'],'UNQUALIFIED_UNAVAILABLE')
        self.assertEqual(result['structural_diagnostics']['queries_with_response'],1)
        self.assertEqual(result['structural_diagnostics']['last_responses'][0]['paths'][0]['target_index'],999)
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('987654321123',json.dumps(result))
    def test_only_last_two_bounded_responses_are_retained(self):
        from test_windows_platform import fixture,second
        values=[json.dumps(fixture()),json.dumps(second(fixture()))]*3
        with TemporaryDirectory() as tmp,patch.object(sys,'platform','win32'),patch('blueprint.windows.bounded_worker',side_effect=values),redirect_stdout(io.StringIO()):
            destination=Path(tmp)/'receipt.json';self.assertEqual(native_probe(destination),2)
            result=json.loads(destination.read_text())
        self.assertEqual(result['code'],'TOPOLOGY_CHANGED_DURING_CAPTURE')
        self.assertEqual(result['structural_diagnostics']['queries_with_response'],6)
        self.assertEqual(len(result['structural_diagnostics']['last_responses']),2)
        self.assertEqual([r['path_count'] for r in result['structural_diagnostics']['last_responses']],[1,2])
    def test_diagnostics_preserve_existing_success_and_virtual_hold_gates(self):
        from test_windows_platform import fixture
        exit_code,result=self.probe(fixture())
        self.assertEqual(exit_code,0);self.assertEqual(result['native_capture'],'PASS_BOUNDED_RUNNER_READONLY')
        raw=fixture();raw['paths'][0].update(flags=9,source_index=0xffff,target_index=0x1ffff)
        exit_code,result=self.probe(raw)
        self.assertEqual(exit_code,2);self.assertEqual(result['native_capture'],'UNQUALIFIED_INCOMPLETE_OBSERVATION')
        self.assertEqual(result['structural_diagnostics']['queries_with_response'],2)

def native_probe(destination):
    """CI-only invocation: actual read-only data or nonzero unqualified result."""
    from blueprint.windows import coherent_capture,bounded_worker
    result={'kind':'NATIVE_WINDOWS_READONLY_QUALIFICATION','os':platform.system(),'os_release':platform.release(),
      'architecture':platform.machine(),'python':platform.python_version(),'native_capture':'NOT_RUN',
      'device_matrix':'NOT_RUN','portable_distribution':'NOT_BUILT'}
    exit_code=2;responses=[];query_count=0
    def observed_query(**kwargs):
        nonlocal query_count
        raw=bounded_worker(**kwargs);query_count+=1
        responses.append(structural_summary(raw));del responses[:-2]
        return raw
    try:
        if sys.platform!='win32':raise CaptureError('WINDOWS_NATIVE_PLATFORM_REQUIRED')
        n.validate_abi();result['abi']='PASS_NATIVE_WINDOWS_STRUCT_LAYOUT'
        snapshot=coherent_capture(query=observed_query)
        manifest=normalize(snapshot,datetime.now(timezone.utc).isoformat(),os_family='Windows',session='windows_desktop')
        result['display_count']=len(manifest['displays']);result['display_geometry']=manifest['capture']['display_geometry']
        result['windows']=manifest['window_geometry']['status'];result['window_count']=len(manifest['window_geometry']['items'] or [])
        result['frame_bounds_count']=sum(item['frame_rect'] is not None for item in manifest['window_geometry']['items'] or [])
        result['coherence']=manifest['capture']['snapshot_coherence']['status'];result['source_errors']=manifest['capture']['source_errors']
        result['canonical_manifest_sha256']=hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
        if result['display_geometry']=='COMPLETE' and result['windows']=='CAPTURED_TOPLEVEL_WINDOWS' and result['frame_bounds_count']>0 and result['coherence']=='TWO_MATCHING_SNAPSHOTS' and not result['source_errors']:
            result['native_capture']='PASS_BOUNDED_RUNNER_READONLY';exit_code=0
        else:result['native_capture']='UNQUALIFIED_INCOMPLETE_OBSERVATION'
    except CaptureError as error:result.update(native_capture='UNQUALIFIED_UNAVAILABLE',code=error.code)
    except Exception:result.update(native_capture='FAILED',code='NATIVE_PROBE_UNEXPECTED_FAILURE')
    result['structural_diagnostics']={'queries_with_response':query_count,'last_responses':responses}
    Path(destination).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,separators=(',',':')))
    return exit_code

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--native-readonly':sys.exit(native_probe(sys.argv[2]))
    unittest.main(verbosity=2)
