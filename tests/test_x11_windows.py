import copy,unittest
from unittest.mock import patch
from blueprint.core import CaptureError
from blueprint.x11_windows import collect,Native,PROPERTIES,ATOM_NAMES,query
class Fake:
    root=1
    def __init__(self):
        self.atoms={s:i+100 for i,s in enumerate(sorted(ATOM_NAMES))};self.calls=[]
        self.props={(1,'_NET_CLIENT_LIST_STACKING'):[2],(1,'_NET_CURRENT_DESKTOP'):[0],(1,'_NET_NUMBER_OF_DESKTOPS'):[1],(1,'_NET_WORKAREA'):[0,25,1920,1055],(1,'_NET_DESKTOP_VIEWPORT'):[0,0],(2,'_NET_WM_DESKTOP'):[0],(2,'_NET_FRAME_EXTENTS'):[2,2,20,2],(2,'_NET_WM_STATE'):[self.atoms['_NET_WM_STATE_MAXIMIZED_VERT']],(2,'_NET_WM_WINDOW_TYPE'):[self.atoms['_NET_WM_WINDOW_TYPE_NORMAL']]}
    def prop(self,window,name,kind,maximum):
        self.calls.append(name)
        assert name in PROPERTIES
        result=self.props.get((window,name))
        if result is not None and len(result)>maximum:raise CaptureError('WINDOW_PROPERTY_INVALID_OR_LIMIT')
        return result
    def geometry(self,wid):return {'client_rect':[10,20,800,600],'border_width':0,'map_state':2,'override_redirect':False}
class Adapter(unittest.TestCase):
    def test_numeric_only_allowlist_and_actual_property_semantics(self):
        api=Fake();snapshot=collect(api)
        self.assertEqual(snapshot['items'][0]['states'],['maximized_vert']);self.assertEqual(snapshot['items'][0]['type'],'normal')
        self.assertEqual(snapshot['work_area'],[0,25,1920,1055]);self.assertTrue(set(api.calls)<=PROPERTIES)
        self.assertFalse(any('NAME' in prop or 'PID' in prop or 'CLASS' in prop for prop in api.calls))
    def test_native_rejects_private_property_before_any_library_call(self):
        api=Native.__new__(Native)
        with self.assertRaises(CaptureError):api.prop(1,'_NET_WM_NAME',0,1)
    def test_malformed_and_overflowing_arrays_fail_closed(self):
        for key,value in [((1,'_NET_CLIENT_LIST_STACKING'),[2,2]),((1,'_NET_CLIENT_LIST_STACKING'),list(range(257))),((1,'_NET_CURRENT_DESKTOP'),[1]),((1,'_NET_NUMBER_OF_DESKTOPS'),[257]),((1,'_NET_WORKAREA'),[1]),((2,'_NET_FRAME_EXTENTS'),[1,2])]:
            api=Fake();api.props[key]=value
            with self.subTest(key=key),self.assertRaises(CaptureError):collect(api)
    def test_unknown_worker_response_is_sanitized(self):
        for raw in ('PRIVATE ERROR','[]','{"status":"UNAVAILABLE","code":"PRIVATE_PATH"}'):
            with patch('blueprint.x11_windows.bounded_query',return_value=raw),self.assertRaises(CaptureError) as failure:query()
            self.assertEqual(failure.exception.code,'WINDOW_WORKER_INVALID_RESPONSE')
    def test_closed_window_errors_propagate_without_title_or_retry(self):
        api=Fake()
        with patch.object(api,'geometry',side_effect=CaptureError('WINDOW_CHANGED_DURING_QUERY')):
            with self.assertRaises(CaptureError):collect(api)
