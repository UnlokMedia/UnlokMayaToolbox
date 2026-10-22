# Log Noise: original deformer (reference)

`log_noise.py` is the original logNoise deformer handed over by another
session: a paste-and-run script that writes a Python plug-in into Maya's
plug-ins folder. The toolbox doesn't use it. Its Log Noise tool (Modeling
tab) ports the same noise with no plugin, because secure Mayas can't write
plugin files and scenes would need the plugin on every machine.

It's kept because `tests/test_log_noise.py` loads it, from a temp folder, to
check that the port gives identical shapes. `log_noise_preview.png` shows a
plain cylinder next to four seeds at the default settings.
