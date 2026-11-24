"""JARVIS 2."""
try:  # written by CI at build time
    from ._version import VERSION as __version__
except ImportError:  # pragma: no cover
    __version__ = "3.10.0"

# 3.13 the label of the newest batch of features: "Co je nového" shows it once after an update (the builds are all
# 3.10.N, so the version number alone never changed and the window stayed quiet). Bump it with the next batch.
NEWS = "3.18"
