"""3.14 OBS Studio (návrhy 102, 103) through obs-websocket 5 (built into OBS 28+: Nástroje → Nastavení WebSocket
serveru). Scenes, recording, streaming, and the replay buffer for highlights ("ulož to" right after a great moment).

The password is kept in the OS keyring ("obs"); the address in Nastavení → Propojení (default localhost:4455).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from typing import Any


def auth_string(password: str, salt: str, challenge: str) -> str:
    """obs-websocket 5: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsError(RuntimeError):
    pass


class Obs:
    def __init__(self, url: str = "ws://127.0.0.1:4455", password: str = "", connect=None):
        self.url = url
        self.password = password
        self._connect = connect          # tests pass a fake websocket factory

    async def request(self, request_type: str, data: dict | None = None, timeout: float = 8.0) -> dict:
        if self._connect is not None:
            conn = self._connect(self.url)
        else:
            from websockets.asyncio.client import connect

            conn = connect(self.url, open_timeout=timeout, max_size=2**22)
        try:
            async with conn as ws:
                hello = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                ident: dict[str, Any] = {"rpcVersion": 1}
                a = (hello.get("d") or {}).get("authentication")
                if a:
                    if not self.password:
                        raise ObsError("OBS chce heslo – vlož ho v Nastavení → Propojení → OBS")
                    ident["authentication"] = auth_string(self.password, a["salt"], a["challenge"])
                await ws.send(json.dumps({"op": 1, "d": ident}))
                ok = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if ok.get("op") != 2:
                    raise ObsError("OBS spojení odmítlo (špatné heslo?)")
                rid = uuid.uuid4().hex[:8]
                await ws.send(json.dumps({"op": 6, "d": {"requestType": request_type, "requestId": rid, "requestData": data or {}}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                    d = msg.get("d") or {}
                    if msg.get("op") == 7 and d.get("requestId") == rid:
                        st = d.get("requestStatus") or {}
                        if not st.get("result"):
                            raise ObsError(f"OBS: {st.get('comment') or st.get('code')}")
                        return d.get("responseData") or {}
        except (OSError, asyncio.TimeoutError) as e:
            raise ObsError("OBS neodpovídá – běží a má zapnutý WebSocket server (Nástroje → Nastavení WebSocket serveru)?") from e

    # ---------- the things people ask for ----------
    async def scenes(self) -> dict:
        d = await self.request("GetSceneList")
        return {"current": d.get("currentProgramSceneName", ""), "scenes": [s.get("sceneName") for s in d.get("scenes", [])][::-1]}

    async def set_scene(self, name: str) -> str:
        sc = await self.scenes()
        want = next((s for s in sc["scenes"] if s and s.lower() == name.lower()), None) or \
            next((s for s in sc["scenes"] if s and name.lower() in s.lower()), None)
        if not want:
            raise ObsError(f"Scénu „{name}“ v OBS nemám. Mám: {', '.join(s for s in sc['scenes'] if s)}")
        await self.request("SetCurrentProgramScene", {"sceneName": want})
        return want

    async def record(self, action: str) -> dict:
        req = {"start": "StartRecord", "stop": "StopRecord", "toggle": "ToggleRecord", "pause": "PauseRecord", "resume": "ResumeRecord"}
        if action == "status":
            return await self.request("GetRecordStatus")
        return await self.request(req[action])

    async def stream(self, action: str) -> dict:
        req = {"start": "StartStream", "stop": "StopStream", "toggle": "ToggleStream"}
        if action == "status":
            return await self.request("GetStreamStatus")
        return await self.request(req[action])

    async def save_replay(self) -> str:
        """The last seconds of the replay buffer → a file (starts the buffer first if it is off)."""
        st = await self.request("GetReplayBufferStatus")
        if not st.get("outputActive"):
            await self.request("StartReplayBuffer")
            raise ObsError("Zapnul jsem záznam posledních chvil (replay buffer) – od teď umím uložit, co se právě stalo.")
        await self.request("SaveReplayBuffer")
        try:
            last = await self.request("GetLastReplayBufferReplay")
            return str(last.get("savedReplayPath", ""))
        except ObsError:
            return ""


def from_config(rt: Any) -> Obs:
    from . import secrets

    url = getattr(getattr(rt.cfg, "integrations", None), "obs_url", "") or "ws://127.0.0.1:4455"
    return Obs(url, secrets.get("obs") or "")
