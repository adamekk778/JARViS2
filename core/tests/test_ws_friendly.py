"""Whatever breaks in a request, the person reads a sentence – never a Python exception name."""
from jarvis.server.ws import friendly_error


def test_python_errors_become_sentences():
    for e in (KeyError("id"), TypeError("x"), AttributeError("'int' object has no attribute 'strip'"),
              ValueError("invalid literal for int() with base 10: 'zz'")):
        msg = friendly_error(e)
        assert "Error" not in msg and "literal" not in msg and msg.endswith(".")
    assert friendly_error(FileNotFoundError(2, "No such file", "x")) == "Ten soubor nebo složka neexistuje."
    assert friendly_error(OSError("[Errno 5] bad")).startswith("Něco se pokazilo")


def test_our_own_messages_pass_through():
    assert friendly_error(ValueError("Heslo zálohy musí mít aspoň 8 znaků.")) == "Heslo zálohy musí mít aspoň 8 znaků."
