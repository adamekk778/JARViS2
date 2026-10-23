# Overrides the contrib hook, which looks for metadata of "webrtcvad" (we ship the "webrtcvad-wheels" build).
from PyInstaller.utils.hooks import copy_metadata

try:
    datas = copy_metadata("webrtcvad-wheels")
except Exception:
    datas = []
