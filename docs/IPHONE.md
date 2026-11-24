# JARVIS na iPhonu (bez Macu a bez App Store)

Nativní aplikaci pro iPhone nejde postavit bez Macu s Xcode a placeného účtu Apple Developer. JARVIS ale na iPhonu
funguje jako webová aplikace na ploše – s chatem, hlasovým režimem a **upozorněními** (Web Push, iOS 16.4 a novější).

## Co potřebuješ

iOS dovolí upozornění (a mikrofon) jen stránce na **HTTPS adrese s platným certifikátem**. Doma v síti JARVIS běží
na `http://…:8765`, takže před něj dej jeden z těchto „tunelů“ (oba zdarma):

### Možnost A – Tailscale (doporučeno, jen pro tvoje zařízení)

1. Nainstaluj Tailscale do PC i do iPhonu a přihlas se stejným účtem.
2. Na PC v příkazovém řádku: `tailscale serve --bg 8765`
3. Tailscale vypíše adresu typu `https://tvoje-pc.tvuj-tailnet.ts.net` – ta má platný certifikát a je vidět jen
   z tvých zařízení v Tailscale.

### Možnost B – Cloudflare Tunnel (adresa na vlastní doméně)

1. Nainstaluj `cloudflared` a přihlas se ke Cloudflare (`cloudflared tunnel login`).
2. `cloudflared tunnel create jarvis`, pak v DNS nasměruj např. `jarvis.tvoje-domena.cz` na tunel.
3. Spusť `cloudflared tunnel run --url http://localhost:8765 jarvis`.
4. Adresa je veřejná – JARVIS bez spárování nic neukáže (každé zařízení potřebuje svůj klíč), ale zvaž v Cloudflare
   ještě Access (přihlášení e-mailem).

## Na iPhonu

1. V Safari otevři `https://…/mobile` (adresu z tunelu) a spáruj se s PC (Nastavení → Telefon na PC ukáže odkaz).
2. **Sdílet → Přidat na plochu.** Otevři JARVIS z ikony na ploše (ne ze Safari).
3. Více → **Upozornění v tomhle prohlížeči → Zapnout** a povol upozornění. Tlačítkem **Vyzkoušet** pošleš zkušební.

Upozornění chodí stejně jako do aplikace pro Android: když nejsi u PC (a co je pro telefon). Každé je zašifrované jen
pro tvůj iPhone (RFC 8291) a podepsané klíčem tvého PC (VAPID) – push služba Apple obsah nepřečte.

## Co na iPhonu není

- widgety, sdílení do JARVISe, zrcadlení obrazovky a další věci, které má nativní aplikace pro Android,
- upozornění, když web aplikace nebyla přidána na plochu (to iOS nedovolí).
