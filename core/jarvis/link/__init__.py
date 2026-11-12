"""3.12 JARVIS Link – our own Tailscale: reach JARVIS on the PC from anywhere, Wi-Fi or mobile data.

Two ways, used together:
  * direct  – an encrypted (TLS) port on this PC; the home router opens it by itself (UPnP), IPv6 when the home has it
  * relay   – your own tiny server on the internet (relay_server.py, a free VPS); the PC keeps a few connections open to
              it and the phone meets the PC there. The relay only passes bytes along: it never sees the key or the data.
The phone pins this PC's certificate fingerprint (learnt at home, over the paired connection), so nothing in between –
the router, the mobile network, the relay – can read or change anything.
"""
