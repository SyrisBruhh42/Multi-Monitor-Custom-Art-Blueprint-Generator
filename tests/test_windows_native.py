"""ABI/fault checks; --native-readonly is a separate, strict native gate.

Ordinary unittest discovery never mistakes these fixtures for native capture.
The explicit gate returns nonzero for inaccessible/absent desktop or Windows.
"""
import ctypes as C
import hashlib,json,platform,sys,unittest
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

def native_probe(destination):
    """CI-only invocation: actual read-only data or nonzero unqualified result."""
    from blueprint.windows import coherent_capture
    result={'kind':'NATIVE_WINDOWS_READONLY_QUALIFICATION','os':platform.system(),'os_release':platform.release(),
      'architecture':platform.machine(),'python':platform.python_version(),'native_capture':'NOT_RUN',
      'device_matrix':'NOT_RUN','portable_distribution':'NOT_BUILT'}
    exit_code=2
    try:
        if sys.platform!='win32':raise CaptureError('WINDOWS_NATIVE_PLATFORM_REQUIRED')
        n.validate_abi();result['abi']='PASS_NATIVE_WINDOWS_STRUCT_LAYOUT'
        snapshot=coherent_capture()
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
    Path(destination).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,separators=(',',':')))
    return exit_code

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--native-readonly':sys.exit(native_probe(sys.argv[2]))
    unittest.main(verbosity=2)
