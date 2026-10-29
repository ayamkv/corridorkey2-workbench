"""CorridorKey2 Workbench: an unofficial desktop front-end for CorridorKey 2.0.

The app never imports torch. Rendering happens in the engine process, which runs
upstream ``infer.py`` (through ``engine/ck_run.py``) in the CorridorKey venv.
CorridorKey's license asks derivatives to keep the CorridorKey name; it leads the app's name.
Corridor Digital's own paid app is also called Workbench, so "unofficial" stays visible.
"""
APP_NAME = "CorridorKey2 Workbench"
APP_ID = "CorridorKey2Workbench"     # state folder, Windows app id
__version__ = "0.3.0"
