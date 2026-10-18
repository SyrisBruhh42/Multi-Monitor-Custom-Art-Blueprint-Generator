# Display Blueprint — local capture proposal

Run once to create a self-contained, searchable PDF describing the current display layout for an AI wallpaper workflow. No monitor dimensions, photographs, account, API key or art-provider access are needed. This source candidate captures **Linux X11** displays and anonymous EWMH-managed window rectangles. It also contains a **Windows collector candidate whose native device qualification has not run**. The complete user scope remains open: Windows device acceptance, macOS, Wayland, complete compositor/unmanaged-window visibility, and a portable USB application without installation remain required and **not delivered yet**.

This isolated Windows proposal starts from merged source `0d70be02b1354fa088bb9b97fc87dee10525e0e7` in `SyrisBruhh42/Multi-Monitor-Custom-Art-Blueprint-Generator` (ID `1262286053`). It is an uncoordinated local checkout, not a published release. A verified complete-history bundle and an 18-file restoration checkpoint precede these edits. No repository settings changed.

## Run the candidate

Use an existing Python 3.10+ interpreter with ReportLab available:

```sh
python3 -m blueprint
```

The program automatically selects the current Windows or Linux X11 adapter, reads the active display configuration and creates a unique `capture-output/capture-…/` folder containing:

- `AI-brief.pdf`: primary handoff; synthetic layout, geometry/crop rules, still/motion prompts, all missing-data gates and the complete searchable canonical JSON appendix.
- `layout.json`: the same canonical JSON. Numbered JSON string fragments in the PDF reconstruct these exact bytes. Each line is `Jnnnnnn|"encoded fragment"|END`; parse the enclosed fragment as a JSON string and concatenate decoded strings in numeric order. Spaces are escaped as `\u0020` to survive readers that collapse PDF whitespace.
- `layout.svg`: synthetic diagram without desktop pixels.
- `prompts.txt`: prompts for an AI reader and Midjourney. No provider calls or uploads occur.

`--output PATH` chooses a destination. `--metadata-only` prints allowlisted metadata without requiring ReportLab. Neither option is required. Missing dependencies or display access produce a short error; no packages are automatically installed. `--fixture PATH` is for developers and labels the capture as synthetic. Output folders are unique; failed PDF exports retain a `.partial-…` checkpoint rather than replacing a previous successful export.

The source is usable with an existing runtime, not a finished zero-install product. Future distribution should bundle Python/ReportLab per OS, provide a one-action launcher, include dependency/font licenses, sign/notarize where applicable, and offer local output selection. Packaging and each operating-system adapter need real device qualification before calling it portable. No installer, background service or Electron layer is part of this candidate.

## Data and geometry contract

Display metadata comes from `xrandr --query --verbose` with `LC_ALL=C`; anonymous window geometry comes from a disposable Python/Xlib subprocess. Each query has at most a two-second deadline and a 256-KiB output cap. Up to three pairs of queries share a five-second acquisition budget, plus bounded subprocess cleanup. The raw output exists in memory only. Each paired observation contains display metadata and, when accessible, window metadata. Two matching parsed snapshots establish bounded consistency, not an atomic RandR transaction; hotplug changing away and back between observations remains possible.

Only allowlisted metadata is exported. It excludes screen pixels, raw EDID, serial numbers, real output names, window titles, usernames, hostnames, file paths and network identifiers. The CLI's success message identifies the local output folder; that path does not enter exported files. Anonymized D1/D2/D3 labels belong to a single capture and are not persistent hardware identities.

`schema_version: 1.1.0` defines a pure geometry manifest. Every rectangle is `[x,y,width,height]`, half-open on its right/bottom edges. The normalized canvas subtracts one shared minimum origin, preserving negative source origins and relative positions. Root-framebuffer coordinates, logical coordinates, backing pixels, scanout pixels and reported physical millimeters are separate fields. Unknown values are `null` with a reason, never an inferred DPI value.

Portrait rotation swaps native scanout axes and reported panel millimeter axes once. Each confirmed digital mapping supplies rational affine coefficients for master-to-output sampling, plus an upright-to-native pixel-edge transform for raw panel use. Crop the shared master first; resample only each local crop. Do not multiply global positions by each screen's UI scale, rotate an already upright output twice, or resize independently before cropping.

The exact active mask is a union of disjoint rectangles; holes are unused digital canvas, not measured physical gaps. An overlap is a clone only when the active XRandR CRTC agrees. Same-position outputs with different CRTCs remain an unresolved relationship. Identity transforms, non-reflected rotation, equal oriented desktop/mode dimensions and no reported active panning are required for exact X11 crop mappings. Other transforms retain the observed rectangles but withhold exact crop contracts. Hardware overscan/border behavior that the utility does not expose, physical bezels, desk angles/depth, viewer position and actual playback are unmeasured.

Reported refresh timings come from xrandr's rounded vertical clock, not a measured playback rate. Interlaced values are withheld. Modes are reported capabilities, not a promise that every combination is usable. Display capture fails closed for Wayland rather than presenting XWayland's partial view as a complete desktop.

## Automatic anonymous window capture

The native X11 adapter reads only a fixed numeric-property allowlist: managed stacking list, desktop indexes/count, current work area/viewport, frame extents, window types and states. Xlib attributes and root-coordinate translation supply client rectangles, border width and mapping state. Atom lookup uses `only_if_exists`; no window, property, permission, cursor or display setting is changed. It never queries titles, classes, PIDs, executable paths, screenshots or input. Native window IDs are used internally for coherence and replaced by capture-local W1/W2 identifiers before export.

Each child has a two-second deadline and 256-KiB output bound, within the shared acquisition budget. Window count is capped at 256, as is desktop count. Missing EWMH, denied display access, vanished windows, malformed properties, timeout or changing windows produce an explicit incomplete window status. A matching latest display pair can still be exported if window geometry is unstable; all window items are then withheld. Existing exports are untouched. The collector never changes host permissions to obtain more data.

Client rectangles, decorated frame rectangles and desktop work areas are distinct. Frame bounds require reported window-manager extents; missing extents are not replaced by an invented border. Root coordinates use the same single origin translation as display geometry. Window rectangles are never multiplied by a display's UI scale. Nonzero/unknown desktop viewport mapping leaves the normalized work area unresolved. A desktop-level work-area rectangle is not precise per-monitor dock/strut geometry.

Mapped current-desktop bounds are clipped to each display as possible cover rectangles. These are temporary composition hints. Transparency, rounded corners, shadows and actual occlusion are unknown; no guaranteed visible-background or privacy-safe mask is claimed. Unmanaged override-redirect popups, compositor surfaces and other X screens may be absent. Hidden/other-workspace/unmapped windows do not create current-cover hints. The export contains no window names or contents.

The manifest and error response list every target platform. Linux X11 is the previously observed native platform. The Windows source candidate described below is implemented but native-device-unqualified. macOS native APIs and privacy permission semantics remain unqualified; Wayland requires compositor-specific work and is never represented by partial XWayland evidence. The source still needs an existing Python/ReportLab runtime, and USB distribution is not built.

Native API references: [EWMH](https://specifications.freedesktop.org/wm/latest-single/) and [Xlib](https://xorg.freedesktop.org/archive/current/doc/libX11/libX11/libX11.html).

## Windows collector candidate

The API floor is Windows 10 version 1703 with a usable desktop session and per-monitor-v2 awareness APIs. The first qualification target is x64. This is an API requirement, **not a tested Windows support claim**; ARM64/x86, physical multi-monitor devices, Remote Desktop and locked/denied desktops remain explicit device gates.

The same one-run command selects a disposable Python worker using only existing Windows DLLs and the standard library. It temporarily enters PMv2 awareness on its own thread, verifies it through the documented context comparison API, then restores the previous context even on failure. It does not change system DPI, display settings, window positions, focus, permissions, registry or services. DLL lookup is restricted to System32.

`QueryDisplayConfig(ONLY_ACTIVE_PATHS | VIRTUAL_MODE_AWARE)` supplies paired path/mode tables. Numeric indexes, mode types, adapter/source/target identities, active/available flags and limits are checked before use. `EnumDisplayMonitors` and `GetMonitorInfoW` supply source rectangles and per-monitor work areas; only in-memory GDI source names join those observations. Unmatched pseudo-monitor metadata is withheld. Display IDs, adapter LUIDs and names do not enter exports. No target name, EDID, serial, WMI, registry or device-path query is used.

Windows schema `1.2.0` identifies `windows_virtual_desktop_physical_px`. Negative origins survive one shared normalization. CCD source pixels, target-signal active pixels, logical coordinates, application backing pixels and physical millimeters stay separate. Reported UI scale comes from `GetScaleFactorForMonitor` only on success; its failure fallback is discarded. UI scale never multiplies desktop positions. Logical coordinates, backing sizes and physical millimeters remain unknown. Supported-mode inventory is not collected; the current signal does not imply native/preferred panel resolution.

CCD quarter-turn rotation is explicitly clockwise. Scanout axes are oriented once for upright dimensions. The raw panel-axis affine remains unknown pending independent qualification. Exact digital crops require identity path scaling, matching source/monitor/oriented target dimensions, and a complete identity desktop-image region/clip. Other scaling, clipping, missing target modes or unknown rotation preserve observed desktop geometry while withholding exact crops. Clone groups require the same CCD adapter/source surface; overlap alone is not mirroring. Refresh is source-reported metadata, withheld for interlace, missing/zero rationals, divider or dynamic-refresh ambiguity. No bezel, gap, panel angle, native physical dimensions or playback performance is guessed.

`EnumWindows` reads anonymous top-level desktop-app rectangles with visible-style/minimized state. `GetWindowRect` outer bounds and DWM extended frame bounds are separate: outer bounds may contain invisible resize borders. DWM failure stays null. Client-area geometry, actual stacking, virtual-desktop membership, child/compositor surfaces, opacity and occlusion are not established. Visible-style, nonminimized and noncloaked bounds can produce **possible** cover hints only. The collector never reads titles, classes, PIDs, executable paths, content, pixels or input.

At most 64 active targets, 192 mode entries and 256 windows are accepted. A Windows-compatible pipe-reader enforces a 256-KiB worker output bound and two-second deadline. Up to three matching-pair attempts share five seconds plus bounded cleanup. A changing window snapshot is withheld while a matching latest display pair can still be exported. Two observations cannot exclude ABA changes or handle reuse and are not an atomic transaction. Console access failure, unsupported driver/API, wrong awareness or malformed joins produce fixed incomplete/error codes. No native success is synthesized when running this code on Linux.

### Qualification boundaries

The proposed workflow has independent Linux/PDF, Windows source/ABI and **actual Windows read-only capture** jobs. An inaccessible/empty runner desktop leaves the native gate unqualified and exits nonzero. It is never converted into a skipped passing native test. A passing hosted runner capture would establish only that runner's observed configuration; it would not qualify consumer Windows 10/11 devices, mixed scaling, rotated/cloned physical monitors, arbitrary application borders or USB launch.

Run the explicit native gate only on the intended isolated Windows test session, with the repository on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = $PWD.Path
python tests/test_windows_native.py --native-readonly native-qualification.json
```

The receipt contains anonymous counts, fixed status codes and runtime versions. It does not upload captured desktop metadata. Production collection does not create or manipulate test windows. Independent owned-window border comparisons and the physical-device matrix remain required and **NOT_RUN**. Current Python/ReportLab dependency requirements are unchanged; this is not yet the no-install USB distribution.

Primary API references: [CCD query](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig), [thread DPI awareness](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext), [monitor scale](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getscalefactorformonitor), [window bounds](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect), and [top-level window scope](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumwindows).

## AI and media boundaries

The PDF supplies a complete geometry brief and conservative ready-to-copy creative templates. Default scenery is a suggested starting composition, not inferred personal taste. The user's style can be refined downstream without asking them to measure their screens.

Midjourney's official version/aspect/video documentation was checked on 2026-10-18: standard still aspect ratio limit 14:1, HD limit 4:1. The template assumes standard still generation, rejects more extreme ratios explicitly, and does not hardcode a model version. A selected HD mode can impose a narrower limit; refresh these rules before release. Still aspect parameters are not reused in animation prompts. The motion template is for the web starting-image workflow, with low motion and a loop request. Neither prompt guarantees output dimensions or a seamless loop.

The AI reader must inspect generated dimensions, fit one shared master to the canvas with an explicit crop/pad/upscale choice, then apply each crop. Animated outputs must share timeline, duration and frame rate. Generated-media slicing, encoding, playback synchronization, codec/device capacity and ingestion of this PDF by an actual AI provider are not tested or implemented here. The PDF retains all these gates visibly.

Official references:
- https://xorg.freedesktop.org/archive/current/doc/randrproto/randrproto.txt
- https://docs.midjourney.com/hc/en-us/articles/31894244298125-Aspect-Ratio
- https://docs.midjourney.com/hc/en-us/articles/32199405667853-Version
- https://docs.midjourney.com/hc/en-us/articles/37460773864589-Video

## Verification and recovery

```sh
python3 -m unittest discover -s tests -v
python3 -m blueprint --fixture fixtures/three-displays.txt --output /tmp/display-blueprint-fixture
```

The complete test command needs the dependencies in `requirements-dev.txt` and an existing Poppler `pdftotext` executable. PDF regression tests verify both pypdf and Poppler extraction, including repeated spaces, boundary spaces, escaped quotes, Unicode and literal end markers. The affine example tests normalized master coordinates on a non-origin, 2x output; local crop offsets must not receive the affine translation twice.

The tests cover geometry/crop edges, portrait physical axes, negative coordinates, mixed logical/backing sizes, mask overlap, mirrors, zero reported physical dimensions, private-data canaries, transform/panning uncertainty, malformed input, hotplug instability, timeouts/output limits, and preservation of existing exports. Native acceptance is separate from fixture proof.

Before the first source edit, the parent work record preserved the remote identity, HTTP 409 empty-ref response and absence of this local folder. No earlier project source or save was overwritten. To stop using this proposal, retain its source archive and evidence and stop invoking it; it has no service, schedule, changed display setting or installed component to undo.

This continuation captured a full-history Git bundle before source edits. Source restore evidence, native metadata qualification and PDF visual/extraction checks are retained by the lead task. No host permission, installation, service, setting, schedule or repository publication was changed.
