"""3.14 Kdo je doma (návrh 33): the people of the household recognised by face – only with their consent, only on this PC.

- two small open models from OpenCV's model zoo (a face finder ~0.3 MB, a face print ~37 MB), downloaded once after you
  say yes (Nastavení → Bezpečí, or "nastav rozpoznávání obličejů")
- "nauč se můj obličej" / "nauč se Janu": 5 looks at the camera → a face print (numbers, not a photo) stored in the data
  folder; "zapomeň obličej Jany" deletes it
- "kdo je u počítače?" → the names of the people it knows, "host" for anyone else
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {"detector": ("face_detection_yunet_2023mar.onnx", f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
          "recognizer": ("face_recognition_sface_2021dec.onnx", f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx")}
MATCH = 0.363          # SFace cosine similarity threshold published with the model
SAMPLES = 5


def folder() -> Path:
    from . import paths

    p = paths.sub("faces")
    return p


def models_ready() -> bool:
    return all((folder() / name).exists() for name, _url in MODELS.values())


async def download(rt: Any) -> dict:
    got = []
    async with rt.http() as c:
        for name, url in MODELS.values():
            dst = folder() / name
            if dst.exists():
                continue
            r = await c.get(url, timeout=120)
            r.raise_for_status()
            if len(r.content) < 100_000:
                raise ValueError(f"{name}: stažený soubor je podezřele malý")
            dst.write_bytes(r.content)
            got.append(name)
    return {"downloaded": got, "ready": models_ready()}


def cosine(a: list[float], b: list[float]) -> float:
    import numpy as np

    va, vb = np.asarray(a, dtype="float32"), np.asarray(b, dtype="float32")
    return float(va @ vb / ((np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0))


class People:
    FILE = "people.json"

    def __init__(self, base: Path | None = None):
        self.base = base or folder()
        try:
            self.people: dict[str, list[list[float]]] = json.loads((self.base / self.FILE).read_text("utf-8"))
        except (OSError, ValueError):
            self.people = {}

    def save(self) -> None:
        (self.base / self.FILE).write_text(json.dumps(self.people), "utf-8")

    def add(self, name: str, prints: list[list[float]]) -> None:
        self.people[name] = (self.people.get(name, []) + prints)[-12:]
        self.save()

    def forget(self, name: str) -> bool:
        hit = next((k for k in self.people if k.lower() == name.lower()), None)
        if hit is None:
            return False
        del self.people[hit]
        self.save()
        return True

    def who(self, vec: list[float]) -> tuple[str, float]:
        best, score = "", 0.0
        for name, prints in self.people.items():
            s = max((cosine(vec, p) for p in prints), default=0.0)
            if s > score:
                best, score = name, s
        return (best, score) if score >= MATCH else ("", score)


class Engine:
    """YuNet finds faces, SFace turns each into a 128-number print."""

    def __init__(self) -> None:
        import cv2

        d, r = folder() / MODELS["detector"][0], folder() / MODELS["recognizer"][0]
        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(str(d), "", (320, 320), 0.8, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF.create(str(r), "")

    def prints(self, frame: Any) -> list[list[float]]:
        h, w = frame.shape[:2]
        self.det.setInputSize((w, h))
        _ok, found = self.det.detect(frame)
        out = []
        for f in (found if found is not None else []):
            aligned = self.rec.alignCrop(frame, f)
            out.append([float(x) for x in self.rec.feature(aligned).flatten()])
        return out


def _engine() -> Engine:
    if not models_ready():
        raise RuntimeError("Rozpoznávání obličejů ještě není nastavené – řekni „nastav rozpoznávání obličejů“.")
    return Engine()


def enroll(rt: Any, name: str, looks: int = SAMPLES, pause: float = 0.6) -> dict:
    from . import webcam

    eng = _engine()
    got: list[list[float]] = []
    cap = webcam.open_camera(int(getattr(rt.cfg.voice, "camera_index", 0) or 0))
    try:
        for _ in range(looks * 4):
            frame = webcam.read(cap)
            ps = eng.prints(frame)
            if len(ps) == 1:                          # exactly one face: the person being taught
                got.append(ps[0])
                if len(got) >= looks:
                    break
            time.sleep(pause)
    finally:
        cap.release()
    webcam.log_use(rt, "face_enroll", f"učení obličeje: {name}")
    if len(got) < 3:
        raise ValueError("Neviděl jsem obličej dost dobře – sedni si čelem ke kameře, na světlo, sám, a zkus to znovu.")
    People().add(name, got)
    return {"name": name, "samples": len(got)}


def who_is_here(rt: Any) -> dict:
    from . import webcam

    eng = _engine()
    frame = webcam.grab(int(getattr(rt.cfg.voice, "camera_index", 0) or 0))
    webcam.log_use(rt, "who_is_here", "kdo je u počítače")
    people = People()
    found = []
    for vec in eng.prints(frame):
        name, score = people.who(vec)
        found.append({"name": name or "host", "score": round(score, 3)})
    return {"people": found, "count": len(found)}
