# Display Blueprint — local capture proposal

Run once to create a self-contained, searchable PDF describing the current display layout for an AI wallpaper workflow. No monitor dimensions, photographs, account, API key or art-provider access are needed. This first source candidate captures **Linux X11** displays. The complete user scope remains open: Windows, macOS, Wayland, title-free window geometry, and a portable USB application without installation are required and **not delivered yet**.

This folder is an isolated proposal for the empty, archived `SyrisBruhh42/Multi-Monitor-Custom-Art-Blueprint-Generator` repository (ID `1262286053`). It is not a checkout or published release. No archive status or repository settings changed.

## Run the candidate

Use an existing Python 3.10+ interpreter with ReportLab available:

```sh
python3 -m blueprint
```

The program automatically reads the active X11 display configuration and creates a unique `capture-output/capture-…/` folder containing:

- `AI-brief.pdf`: primary handoff; synthetic layout, geometry/crop rules, still/motion prompts, all missing-data gates and the complete searchable canonical JSON appendix.
- `layout.json`: the same canonical JSON. Numbered JSON string fragments in the PDF reconstruct these exact bytes. Each line is `Jnnnnnn|"encoded fragment"|END`; parse the enclosed fragment as a JSON string and concatenate decoded strings in numeric order. Spaces are escaped as `\u0020` to survive readers that collapse PDF whitespace.
- `layout.svg`: synthetic diagram without desktop pixels.
- `prompts.txt`: prompts for an AI reader and Midjourney. No provider calls or uploads occur.

`--output PATH` chooses a destination. `--metadata-only` prints allowlisted metadata without requiring ReportLab. Neither option is required. Missing dependencies or display access produce a short error; no packages are automatically installed. `--fixture PATH` is for developers and labels the capture as synthetic. Output folders are unique; failed PDF exports retain a `.partial-…` checkpoint rather than replacing a previous successful export.

The source is usable with an existing runtime, not a finished zero-install product. Future distribution should bundle Python/ReportLab per OS, provide a one-action launcher, include dependency/font licenses, sign/notarize where applicable, and offer local output selection. Packaging and each operating-system adapter need real device qualification before calling it portable. No installer, background service or Electron layer is part of this candidate.

## Data and geometry contract

The collector calls only `xrandr --query --verbose` with `LC_ALL=C`. Each query has at most a two-second deadline and a 256-KiB output cap. Up to three pairs of queries share a five-second acquisition budget, plus bounded subprocess cleanup. The raw output exists in memory only. Two matching parsed snapshots establish bounded consistency, not an atomic RandR transaction; hotplug changing away and back between observations remains possible.

Only allowlisted metadata is exported. It excludes screen pixels, raw EDID, serial numbers, real output names, window titles, usernames, hostnames, file paths and network identifiers. The CLI's success message identifies the local output folder; that path does not enter exported files. Anonymized D1/D2/D3 labels belong to a single capture and are not persistent hardware identities.

`schema_version: 1.0.0` defines a pure geometry manifest. Every rectangle is `[x,y,width,height]`, half-open on its right/bottom edges. The normalized canvas subtracts one shared minimum origin, preserving negative source origins and relative positions. Root-framebuffer coordinates, logical coordinates, backing pixels, scanout pixels and reported physical millimeters are separate fields. Unknown values are `null` with a reason, never an inferred DPI value.

Portrait rotation swaps native scanout axes and reported panel millimeter axes once. Each confirmed digital mapping supplies rational affine coefficients for master-to-output sampling, plus an upright-to-native pixel-edge transform for raw panel use. Crop the shared master first; resample only each local crop. Do not multiply global positions by each screen's UI scale, rotate an already upright output twice, or resize independently before cropping.

The exact active mask is a union of disjoint rectangles; holes are unused digital canvas, not measured physical gaps. An overlap is a clone only when the active XRandR CRTC agrees. Same-position outputs with different CRTCs remain an unresolved relationship. Identity transforms, non-reflected rotation, equal oriented desktop/mode dimensions and no reported active panning are required for exact X11 crop mappings. Other transforms retain the observed rectangles but withhold exact crop contracts. Hardware overscan/border behavior that the utility does not expose, physical bezels, desk angles/depth, viewer position and actual playback are unmeasured.

Reported refresh timings come from xrandr's rounded vertical clock, not a measured playback rate. Interlaced values are withheld. Modes are reported capabilities, not a promise that every combination is usable. Display capture fails closed for Wayland rather than presenting XWayland's partial view as a complete desktop.

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
