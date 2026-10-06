# Contributing

Submit original scripts, documentation and synthetic tests only. Never attach
game assemblies, decompiled game code, textures, meshes, manifests, screenshots
or generated Blender scenes to commits, pull requests, issues or releases.

Keep changes narrow. Add tests for source selection, reference resolution, channel
handling and checkpoint behavior when changing those contracts. Use small invented
data rather than samples copied from the game. Run the tests and tracked-file audit
listed in `AGENTS.md`. CI deliberately has no game access and uploads no artifacts.

For compatibility reports, provide game/Unity/Blender versions, Mono versus IL2CPP,
the failing phase and a short redacted exception. The repository cannot diagnose
from a successful compile alone; describe the actual validation you performed.
