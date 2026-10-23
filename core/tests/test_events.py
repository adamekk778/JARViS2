from jarvis.events import Bus


async def test_two_subscribers():
    bus = Bus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish("state", state="idle")
    assert (await a.get()) == {"type": "state", "state": "idle"}
    assert (await b.get())["state"] == "idle"
    bus.unsubscribe(a)
    bus.publish("x")
    assert a.empty()
