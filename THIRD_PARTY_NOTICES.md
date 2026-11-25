# Attribution and third-party notices

CorridorKey2 Workbench is an independent app by ayamkv. It is not affiliated with or endorsed
by Corridor Digital. The application is released free under the Corridor Key Licence 2.0
included in `LICENSE`, following this project's existing licensing policy.

The public package contains this application's source, assets and setup scripts. It does not
redistribute CorridorKey's inference runtime, model weights, Python, FFmpeg or installed libraries.
Setup downloads those components separately from their publishers. Their licences continue to apply.

- **CorridorKey 2.0**, Corridor Digital: Corridor Key Licence 2.0, including CC BY-NC-SA 4.0
  and additional terms. Setup pins commit `485f5e9ab759ead6138cc990776184b59d6ea971`.
  The full upstream licence text is retained in `LICENSE`. Output images/videos remain yours;
  organisations over the licence's revenue threshold require seats from Corridor Digital.
- **Geist / Geist Mono**, Vercel: SIL Open Font License 1.1. Bundled fonts and full notice:
  `ckapp/app/assets/fonts/OFL-Geist.txt`.
- **Lucide icons**, Lucide contributors: ISC licence, retained in `licenses/Lucide.txt`.
  The other Workbench icons were drawn for this application.
- **SAM 2.1 Tiny**, Meta: Apache 2.0. Used through Hugging Face Transformers; model download
  occurs only when requested in the mask tool. No SAM checkpoint is bundled.
- **PySide6 / Qt**: LGPLv3/GPLv3/commercial terms; installed as unmodified Python wheels.
- **PyOpenGL**: BSD-style terms; **NumPy**: BSD 3-Clause; **OpenCV**: Apache 2.0;
  **FastAPI / Uvicorn**: MIT. These are installed dependencies, not bundled binaries.
- **FFmpeg**: upstream LGPL/GPL terms depend on build configuration; setup uses Gyan's
  essentials build and retains its distribution files.
- **uv**, Astral: MIT or Apache 2.0; downloaded separately by setup.

Design ideas from the official Workbench and the Sceledrus GUI are described in the planning
history. This is an independent frontend; upstream engine files are not modified on disk.
