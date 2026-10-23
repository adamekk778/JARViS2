from jarvis.memory import DB, Memory


def test_messages_and_conversations(tmp_path):
    m = Memory(DB(tmp_path / "m.db"))
    m.add_message("user", "Ahoj JARVISi, jak se máš?")
    m.add_message("assistant", "Skvěle, pane.")
    rec = m.recent(20)
    assert [x["role"] for x in rec] == ["user", "assistant"]
    assert m.list_conversations()[0]["title"].startswith("Ahoj JARVISi")
    old = m.current_conversation
    m.new_conversation()
    assert m.recent() == []
    assert m.switch(old) and len(m.recent()) == 2
    assert m.search("Skvěle")[0]["text"] == "Skvěle, pane."
    # persists current conversation across restarts
    assert Memory(DB(tmp_path / "m.db")).current_conversation == old


def test_regenerate_helper(tmp_path):
    m = Memory(DB(tmp_path / "m.db"))
    m.add_message("user", "otázka")
    m.add_message("assistant", "špatná odpověď")
    u = m.delete_last_assistant()
    assert u["text"] == "otázka" and [x["role"] for x in m.recent()] == ["user"]
