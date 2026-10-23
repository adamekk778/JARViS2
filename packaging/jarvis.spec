# PyInstaller spec: builds dist/JARVIS/JARVIS.exe (one folder, no console window).
# Run from the packaging/ directory:  pyinstaller jarvis.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
PKGS = [
    "jarvis", "uvicorn", "fastapi", "starlette", "pydantic", "httpx", "anyio", "websockets", "multipart",
    "faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub", "openwakeword", "onnxruntime", "piper",
    "webrtcvad", "sounddevice", "_sounddevice_data", "av", "edge_tts", "aiohttp", "certifi",
    "webview", "clr_loader", "pythonnet", "pystray", "keyboard", "pyautogui", "pyscreeze", "pymsgbox", "pytweening",
    "mouseinfo", "mss", "pyperclip", "pycaw", "comtypes", "winsdk", "uiautomation", "playwright", "keyring", "win32ctypes",
    "trafilatura", "justext", "lxml", "htmldate", "courlan", "dateparser", "ddgs", "primp", "yt_dlp",
    "pypdf", "docx", "openpyxl", "pptx", "PIL", "qrcode", "psutil",
    "matplotlib", "numpy", "send2trash", "soundcard", "cffi", "_cffi_backend",
]
for pkg in PKGS:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # optional package not installed
        print(f"[spec] skip {pkg}: {e}")
# mcp: skip the optional CLI (needs typer), keep the client
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
hiddenimports += collect_submodules("mcp", filter=lambda n: not n.startswith(("mcp.cli", "mcp.server.fastmcp")))
datas += collect_data_files("mcp") + copy_metadata("mcp")
hiddenimports += collect_submodules("jarvis") + collect_submodules("uvicorn")

web_dist = os.path.abspath(os.path.join(SPECPATH, "..", "web", "dist"))
assert os.path.exists(os.path.join(web_dist, "index.html")), "build the web UI first (cd web && npm run build)"
datas += [(web_dist, "web/dist"), (os.path.join(SPECPATH, "jarvis.ico"), ".")]

a = Analysis(
    [os.path.join(SPECPATH, "jarvis_entry.py")],
    pathex=[os.path.abspath(os.path.join(SPECPATH, "..", "core"))],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(SPECPATH, "hooks")],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "jupyter", "pytest", "matplotlib.tests",
              "numpy.tests", "torch", "tensorflow", "cv2", "rapidocr_onnxruntime"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JARVIS", icon=os.path.join(SPECPATH, "jarvis.ico"),
          console=False, upx=False, version=None)
# same program with a console window: shows errors when something goes wrong (and is used by CI)
exe_debug = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JARVIS-debug", icon=os.path.join(SPECPATH, "jarvis.ico"),
                console=True, upx=False, version=None)
coll = COLLECT(exe, exe_debug, a.binaries, a.datas, name="JARVIS", upx=False)
