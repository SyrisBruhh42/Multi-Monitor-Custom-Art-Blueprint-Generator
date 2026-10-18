"""Truthful local capability inventory; no permission requests or settings changes."""
def capabilities(system, session):
    current = 'linux_x11' if system == 'Linux' and session == 'x11' else ('linux_wayland' if system == 'Linux' and session == 'wayland' else system.lower())
    return {'current':current, 'adapters':{
      'linux_x11':{'displays':'IMPLEMENTED','windows':'IMPLEMENTED_EWMH_MANAGED_WINDOWS','permission':'Existing display connection required; access failure is reported, never changed.'},
      'linux_wayland':{'displays':'NOT_IMPLEMENTED','windows':'NOT_IMPLEMENTED','permission':'Compositor-specific access remains unqualified; XWayland is not complete desktop evidence.'},
      'windows':{'displays':'IMPLEMENTED_CANDIDATE_NATIVE_UNQUALIFIED','windows':'IMPLEMENTED_CANDIDATE_NATIVE_UNQUALIFIED','permission':'Accessible Windows desktop and verified worker-local PMv2 required; native device qualification NOT_RUN.'},
      'darwin':{'displays':'NOT_IMPLEMENTED','windows':'NOT_IMPLEMENTED','permission':'Native display/window APIs and OS privacy permission behavior NOT_RUN.'}},
      'portable_distribution':'NOT_BUILT; an existing Python runtime is still required.'}
