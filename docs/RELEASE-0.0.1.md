# CorridorKey2 Workbench 0.0.1

The first public preview of this independent Windows desktop app for CorridorKey 2.0.
It provides project folders, a GPU comparison viewer, frame ranges, a background/held render
queue, click-to-mask hints, live composite despill, and EXR/video export controls.

## Install

1. Download `CorridorKey2-Workbench-0.0.1.zip` and optionally check its SHA-256 against
   `CorridorKey2-Workbench-0.0.1.zip.sha256` using `Get-FileHash` in PowerShell.
2. Extract the ZIP to a permanent writable folder, for example `D:\CorridorKey2 Workbench`.
3. Open the extracted `CorridorKey2 Workbench` folder and run `Setup.bat`.
4. Choose model download or an existing CorridorKey 2.0 folder. Setup obtains Python,
   the upstream engine, dependencies and ffmpeg. The ZIP itself contains no models or engine.
5. Start the app from the created shortcut or `CorridorKey2 Workbench.bat`, create a project,
   import footage, choose an in/out range and render.

Windows 10/11 x64 and NVIDIA RTX 30-series or newer are required. Minimum VRAM is 4 GB;
resolution and temporal settings depend on available memory. Allow around 15 GB of disk space
and internet access for first setup. Use a plain ASCII installation path for this preview.

## Validation and limitations

Release checks: **121 tests passed, 1 skipped** on Windows. Engine, application logic,
offscreen UI and package tests use synthetic media and fake inference/model
workers. The ZIP's complete file list, sizes, SHA-256 hashes and licence notices were verified.
Previous development-machine GPU runs verified rendering, one-click SAM masking,
hinted frame-range rendering and composite despill. Automated tests do not establish quality
on every clip or compatibility with every machine.

- A full clean-machine `Setup.bat` installation has not been completed. Its external download
  pins and the release ZIP are checked, but dependency installation still needs user testing.
- Project reopening/moving, held jobs across projects and multi-click mask edits need broader
  hands-on testing.
- The offscreen GL pixel test is skipped where a real OpenGL context is unavailable.
- macOS, Linux, remote/LAN rendering and tracked roto are outside this release.
- Hints are first-frame click masks or externally supplied full hint sequences; SAM tracking,
  SAM 3 and MatAnyone 2 are not included.

Report reproducible failures at https://github.com/ayamkv/corridorkey2-workbench/issues.
For setup failures, include the relevant part of `setup.log`; remove tokens and private paths.

## Alternatives

Checked on 2026-11-25 against the projects' own public descriptions; these are advertised
features, not a comparative quality or speed benchmark.

| App | Broader capabilities | Workbench's focus |
| --- | --- | --- |
| [Official CorridorKey](https://corridorkey.com) | Supported paid product, Windows/Mac, standalone and DCC integrations | Free independent Windows workflow |
| [ck2-gui v0.5.1](https://github.com/roosaramendis/ck2-gui/releases/tag/v0.5.1) | Windows/Linux/Mac installers, tracked hints, SAM 3 and optional MatAnyone 2 roto, DCC installation | Project folders, GPU comparisons and held/background jobs |
| [Sceledrus GUI](https://github.com/sceledrus/CorridorKey2.0-GUI) | Another free Windows desktop interface | Our own engine queue and GPU viewer implementation |

The official product and ck2-gui offer broader coverage. This preview is useful for people who
want the project's particular viewer, project and queue workflow, rather than a feature-complete alternative.
