# Podpis instalátoru a aplikace

Bez podpisu Windows SmartScreen při prvním spuštění `JARVIS-Setup.exe` ukáže „Systém Windows ochránil počítač“
a Defender občas soubor zdrží. Podepsaný instalátor tohle varování nemá (u OV certifikátu po nasbírání reputace,
u EV certifikátu hned).

## Windows (JARVIS.exe, JARVIS-debug.exe, JARVIS-Setup.exe)
CI podepisuje samo, jakmile jsou v repozitáři dvě tajemství (GitHub → Settings → Secrets and variables → Actions):

| Tajemství | Obsah |
|---|---|
| `WINDOWS_CERT_PFX` | certifikát pro podpis kódu (.pfx) zakódovaný v base64: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))` |
| `WINDOWS_CERT_PASSWORD` | heslo k .pfx |

Podpis používá SHA-256 a časové razítko DigiCert, takže zůstane platný i po vypršení certifikátu.
Bez tajemství se krok přeskočí a build je stejný jako dřív (nepodepsaný).

Kde certifikát získat: certifikační autority (Certum má levný Open Source Code Signing pro jednotlivce, Sectigo,
DigiCert) nebo Azure Trusted Signing (měsíční poplatek, bez fyzického tokenu). EV certifikáty se dnes vydávají jen
na hardwarový token – pro CI je pak vhodnější Azure Trusted Signing.

## Android (JARVIS.apk)
APK je podepsané stálým klíčem `mobile/debug.keystore`, aby se každá nová verze nainstalovala přes starou.
Změna klíče by znamenala, že stávající instalace se jednou musí odinstalovat (Android jiný podpis nepřijme),
proto se klíč nemění automaticky. Pro Google Play by se APK/AAB podepsal vlastním upload klíčem.
