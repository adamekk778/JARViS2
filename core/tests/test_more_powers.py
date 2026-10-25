"""3.5: lists, money (ČNB / crypto / shares + price alerts), the home network, find my phone, the phone's battery."""
import asyncio

import httpx
from conftest import drain

from jarvis import finance, network, tools

CNB = """24.10.2026 #206
země|měna|množství|kód|kurz
EMU|euro|1|EUR|24,350
USA|dolar|1|USD|22,500
Maďarsko|forint|100|HUF|6,250
"""


# ---------------------------------------------------------------------------------------------- lists
async def test_shopping_list_by_voice(rt):
    q = rt.bus.subscribe()
    r = await tools.call("list_add", {"items": ["mléko", "chleba", "Mléko"], "list": "nákupní seznam"}, rt)
    assert r.ok and r.summary == "Přidáno na seznam nákup: mléko, chleba."
    assert (await tools.call("list_add", {"items": ["Interstellar"], "list": "seznam filmů"}, rt)).summary == "Přidáno na seznam filmy: Interstellar."
    assert (await tools.call("list_show", {}, rt)).summary == "Na seznamu nákup (2): mléko, chleba."
    assert (await tools.call("list_done", {"items": ["mleko"]}, rt)).summary == "Odškrtnuto: mléko. Na seznamu nákup zbývá 1."
    assert "filmy (1): Interstellar" in (await tools.call("list_show", {"list": "vše"}, rt)).summary
    assert drain(q)[-1]["lists"] == {"nákup": ["chleba"], "filmy": ["Interstellar"]}
    assert (await tools.call("list_clear", {"list": "nákup"}, rt)).ok
    assert (await tools.call("list_show", {"list": "nakup"}, rt)).summary == "Seznam nákup je prázdný."


# ---------------------------------------------------------------------------------------------- money
def money_transport(calls):
    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if "cnb.cz" in req.url.host:
            return httpx.Response(200, text=CNB)
        if "coingecko" in req.url.host:
            return httpx.Response(200, json={"bitcoin": {"czk": 1_480_000.0, "czk_24h_change": -2.5}})
        if "stooq" in req.url.host:
            return httpx.Response(200, text="Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,2026-10-24,22:00:00,200,210,199,210,1000\n")
        return httpx.Response(404)
    return httpx.MockTransport(handler)


async def test_exchange_crypto_and_shares(rt):
    finance._cnb = (0.0, {})
    calls = []
    rt.transport = money_transport(calls)
    assert (await tools.call("exchange_rate", {"amount": 50, "from_currency": "eur"}, rt)).summary == "50,00 EUR = 1 218 CZK (kurz ČNB)."
    assert (await tools.call("exchange_rate", {"amount": 100, "from_currency": "dolarů", "to_currency": "euro"}, rt)).data["value"] == 100 * 22.5 / 24.35
    assert (await tools.call("price", {"asset": "btc"}, rt)).summary == "bitcoin: 1 480 000 CZK, za den -2,5 %."
    assert (await tools.call("price", {"asset": "AAPL"}, rt)).summary == "AAPL.US: 210,00 USD, za den +5,0 %."
    assert (await tools.call("price", {"asset": "euro"}, rt)).summary == "EUR: 24,35 CZK."
    assert finance.parse_cnb(CNB)["HUF"] == 0.0625


async def test_price_alert_fires_once(rt):
    from jarvis.scheduler import Scheduler

    rt.transport = money_transport([])
    rt.scheduler = Scheduler(rt)
    said = []
    rt.notify = lambda title, body, **k: said.append(body)
    r = await tools.call("price_alert", {"asset": "bitcoin", "direction": "below", "value": 1_500_000}, rt)
    assert r.ok and "teď 1 480 000 CZK" in r.summary
    job = rt.scheduler.list()[0]
    assert job["kind"] == "price" and job["spec"] == {"type": "interval", "minutes": 15}
    await rt.scheduler._run(job)
    assert said == ["bitcoin klesl pod 1 500 000 CZK: teď 1 480 000 CZK."] and rt.scheduler.list() == []


# ---------------------------------------------------------------------------------------------- network
ARP_WIN = """
Interface: 192.168.1.10 --- 0x7
  Internet Address      Physical Address      Type
  192.168.1.1           a4-91-b1-00-11-22     dynamic
  192.168.1.23          3c-22-fb-aa-bb-cc     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
"""
IP_NEIGH = "192.168.1.1 dev wlan0 lladdr a4:91:b1:00:11:22 REACHABLE\n192.168.1.5 dev wlan0  FAILED\n"


def test_parse_neighbors_windows_and_linux():
    assert network.parse_neighbors(ARP_WIN) == [{"ip": "192.168.1.1", "mac": "a4:91:b1:00:11:22"},
                                                {"ip": "192.168.1.23", "mac": "3c:22:fb:aa:bb:cc"}]
    assert network.parse_neighbors(IP_NEIGH) == [{"ip": "192.168.1.1", "mac": "a4:91:b1:00:11:22"}]


async def test_devices_names_new_ones_and_wake(rt, monkeypatch):
    found = [{"ip": "192.168.1.1", "mac": "a4:91:b1:00:11:22"}]
    monkeypatch.setattr(network, "read_neighbors", lambda: [dict(d) for d in found])
    monkeypatch.setattr(network, "_hostname", lambda ip: "router" if ip.endswith(".1") else "")
    r = await tools.call("network_devices", {}, rt)
    assert r.ok and "router – 192.168.1.1" in r.summary and "NOVÉ" not in r.summary     # the first look learns
    found.append({"ip": "192.168.1.66", "mac": "3c:22:fb:aa:bb:cc"})
    r = await tools.call("network_devices", {}, rt)
    assert "1 nových" in r.summary and "bez názvu – 192.168.1.66 (3c:22:fb:aa:bb:cc) – NOVÉ" in r.summary
    assert (await tools.call("name_device", {"device": "192.168.1.66", "name": "Počítač v pracovně"}, rt)).ok
    sent = []
    monkeypatch.setattr(network, "wake", lambda mac: sent.append(mac))
    assert (await tools.call("wake_device", {"device": "pocitac v pracovne"}, rt)).ok and sent == ["3c:22:fb:aa:bb:cc"]
    assert network.magic_packet("3C-22-FB-AA-BB-CC") == b"\xff" * 6 + bytes.fromhex("3c22fbaabbcc") * 16


# ---------------------------------------------------------------------------------------------- phone
async def test_find_my_phone_and_battery(rt):
    from test_phone_link import fake_phone

    seen = []
    task = asyncio.create_task(fake_phone(rt, lambda c: "alarm" if c["kind"] == "find" else "done", seen))
    await asyncio.sleep(0.05)
    assert (await tools.call("find_phone", {}, rt)).summary.startswith("Telefon zvoní naplno")
    assert (await tools.call("find_phone", {"stop": True}, rt)).summary == "Telefon ztišen."
    task.cancel()
    assert [c["kind"] for c in seen] == ["find", "find_stop"]
    said = []
    rt.notify = lambda title, body, **k: said.append(body)
    rt.phone.on_battery(40, False)
    rt.phone.on_battery(14, False)
    rt.phone.on_battery(12, False)
    assert said == ["Telefonu zbývá 14 % baterie. Dejte ho nabít."]
    assert (await tools.call("phone_battery", {}, rt)).summary == "Telefon má 12 %."


def test_poll_carries_the_battery(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    c = TestClient(create_app(rt, manage_runtime=False), client=("192.168.1.50", 5000))
    r = c.get("/api/phone/poll?wait=0&battery=77&charging=1", headers={"Authorization": f"Bearer {rt.cfg.phone.token}"})
    assert r.status_code == 200 and rt.phone.battery["level"] == 77 and rt.phone.battery["charging"] is True


async def test_guardian_tells_about_a_new_device(rt, monkeypatch):
    found = [{"ip": "192.168.1.1", "mac": "a4:91:b1:00:11:22"}]
    monkeypatch.setattr(network, "read_neighbors", lambda: [dict(d) for d in found])
    monkeypatch.setattr(network, "_hostname", lambda ip: "Pavel-iPhone" if ip.endswith(".80") else "")
    said = []
    rt.notify = lambda title, body, **k: said.append(body)
    assert await rt.guardian.check_network() == []          # the first look only learns what is home
    found.append({"ip": "192.168.1.80", "mac": "11:22:33:44:55:66"})
    assert len(await rt.guardian.check_network()) == 1
    assert await rt.guardian.check_network() == []          # said once
    assert said == ["Do sítě se připojilo nové zařízení Pavel-iPhone (192.168.1.80)."]
