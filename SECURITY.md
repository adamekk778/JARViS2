# Bezpečnost JARVISe

JARVIS ovládá počítač, telefon a domácnost, takže chyby v zabezpečení bereme vážně.

## Jak nahlásit zranitelnost

- **Nepiš ji do veřejného issue.** Použij soukromé hlášení na GitHubu: záložka **Security → Report a vulnerability**
  v tomto repozitáři (soukromé hlášení zranitelností musí mít vlastník repozitáře zapnuté).
- Napiš, co se dá zneužít, jak to zopakovat (kroky, verze JARVISe, Windows / Android) a jaký je dopad.
- Neposílej cizí data a netestuj na cizích počítačích ani účtech.

## Co se stane potom

- Do 7 dní potvrdíme přijetí, do 30 dní pošleme odhad opravy.
- Oprava vyjde v nejbližší verzi; v poznámkách k vydání uvedeme, co se opravilo (a tebe, pokud chceš).
- Než oprava vyjde, podrobnosti nezveřejňuj.

## Co sem patří

Obejití potvrzení u nebezpečných akcí, únik klíčů nebo dat z PC či telefonu, vzdálené spuštění kódu, obejití párování
telefonu nebo hodinek, prompt injection, která přiměje JARVISe něco udělat bez tvého souhlasu, a chyby v podepisování
dovedností (`.jarvisskill`).

## Podporované verze

Opravy dostává poslední vydaná verze (3.20). Starší verze se aktualizují samy na poslední.
