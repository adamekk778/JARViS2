"""Audio device names for the settings (microphone and speaker selection)."""
from __future__ import annotations


def list_devices() -> dict:
    try:
        import sounddevice as sd

        devs = sd.query_devices()
    except Exception:
        return {"inputs": [], "outputs": []}
    ins = sorted({d["name"] for d in devs if d.get("max_input_channels", 0) > 0})
    outs = sorted({d["name"] for d in devs if d.get("max_output_channels", 0) > 0})
    return {"inputs": ins, "outputs": outs}


def output_index(name: str):
    """sounddevice device id for a name, None = system default."""
    if not name:
        return None
    try:
        import sounddevice as sd

        for i, d in enumerate(sd.query_devices()):
            if d["name"] == name and d.get("max_output_channels", 0) > 0:
                return i
    except Exception:
        pass
    return None
