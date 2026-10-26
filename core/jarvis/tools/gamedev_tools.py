"""OMEGA wave 25 by voice: the game development studio – world map, dialogue and quest checks, economy, loot odds,
spawn fairness, level generator, save validation, animation state machines, server capacity, telemetry, colour
blindness, unit balance."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Annotated, Any

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _out(name: str, ext: str = "png"):
    return paths.data_dir() / "hry" / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.{ext}"


def _json_arg(value: Any, file: str) -> Any:
    if value:
        return value
    if not file:
        raise ValueError("Zadej data přímo, nebo cestu k souboru JSON.")
    p = resolve(file)
    if not p.is_file():
        raise ValueError(f"Soubor neexistuje: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise ValueError(f"{p.name} není platný JSON: {e}") from e


@tool("game_world", "Vygeneruje mapu herního světa ze semínka (výška, vlhkost → oceán, pláže, poušť, louky, lesy, hory, sníh) "
      "jako obrázek; stejné semínko = stejný svět. Řekne podíl biomů, ostrovy a kde začít.", category="hry")
async def game_world(ctx, seed: int = 1, size: int = 128, sea_level: float = 0.45, scale: int = 32) -> ToolResult:
    from .. import gamedev

    size = max(32, min(size, 512))
    r = await asyncio.to_thread(gamedev.world, seed, _out(f"svet-{seed}"), size, size, max(4, scale), 4, min(max(sea_level, 0.0), 1.0))
    top = ", ".join(f"{k} {v} %" for k, v in sorted(r["biomes"].items(), key=lambda x: -x[1])[:4])
    return ToolResult(True, f"Svět {seed}: pevnina {r['land_pct']} %, {r['islands']} ostrovů; {top}. Start {r['spawn']}.", data=r, attachments=[r["path"]])


@tool("dialogue_check", "Zkontroluje strom dialogu NPC (JSON): odkazy na neexistující uzly, nedosažitelné uzly, slepé větve, "
      "smyčky bez konce, podmínky, které se nikde nenastaví, neznámé proměnné. Volitelně ho přehraje podle voleb.", category="hry", perm="files_read")
async def dialogue_check(ctx, tree: Annotated[dict | None, "{start, nodes: {id: {text, end?, choices: [{text, next, if?, set?}]}}}"] = None,
                         file: str = "", variables: list[str] | None = None, play: Annotated[list[int] | None, "pořadí voleb 0,1,…"] = None) -> ToolResult:
    from .. import gamedev

    try:
        t = _json_arg(tree, file)
    except ValueError as e:
        return ToolResult(False, str(e))
    r = gamedev.dialogue_check(t, variables)
    if play is not None:
        r["play"] = gamedev.dialogue_play(t, play, {v: v for v in variables or []})
    msg = (f"Dialog v pořádku: {r['nodes']} uzlů, konce {', '.join(r['ends'])}." if r["ok"]
           else f"{len(r['issues'])} problémů: " + "; ".join(r["issues"][:6]) + ".")
    if play is not None:
        msg += " Přehrání: " + " → ".join(x["node"] for x in r["play"]["log"]) + (" (konec)" if r["play"]["ended"] else "")
    return ToolResult(True, msg, data=r)


@tool("quest_check", "Projde questy jako hráč (předpoklady, úroveň, potřebné a získané předměty): pořadí, úroveň na konci, "
      "zlato a které questy nejdou splnit a proč.", category="hry")
async def quest_check(ctx, quests: Annotated[list[dict], "[{id, name, requires: [], level, xp, gold, gives: [], needs: []}]"],
                      xp_per_level: float = 100, start_items: list[str] | None = None) -> ToolResult:
    from .. import gamedev

    if not quests or any("id" not in q for q in quests):
        return ToolResult(False, "Každý quest potřebuje id.")
    r = gamedev.quest_check(quests, max(1, xp_per_level), 1, start_items)
    msg = f"Hratelných {len(r['order'])} z {len(quests)}, hráč skončí na úrovni {r['final_level']} se {r['gold']:g} zlata."
    if r["blocked"]:
        msg += " Nejde: " + "; ".join(f"{b['id']} ({', '.join(b['why'])})" for b in r["blocked"][:5]) + "."
    return ToolResult(True, msg, data=r)


@tool("economy_sim", "Simulace herní ekonomiky po dnech: odkud zlato přitéká (odměny, prodej) a kudy odtéká (opravy, daně, "
      "% z peněženky) → jestli hrozí inflace, kde se peněženky ustálí a jak velký odtok by to vyrovnal.", category="hry")
async def economy_sim(ctx, sources: Annotated[list[dict], "[{name, per_player_day}]"], sinks: Annotated[list[dict], "[{name, per_player_day} nebo {name, pct_of_wallet}]"],
                      days: int = 30, players: float = 1000, growth_pct: float = 0, start_gold: float = 0) -> ToolResult:
    from .. import gamedev

    r = gamedev.economy_sim(max(1, min(days, 3650)), players, growth_pct, sources, sinks, start_gold)
    msg = f"{r['verdict'].capitalize()}: peněženka {r['start']:g} → {r['end']:g} za {days} dní, čistý přítok {r['net_per_day']:g}/den."
    if r["steady_wallet"]:
        msg += f" Ustálí se kolem {r['steady_wallet']:g}."
    if r["sink_to_balance"]:
        msg += f" K vyrovnání chybí odtok {r['sink_to_balance']:g} na hráče a den."
    return ToolResult(True, msg, data=r)


@tool("loot_odds", "Šance na předměty z tabulky dropů (váhy): % na jeden pokus, kolik pokusů průměrně, šance za N pokusů, "
      "kolik pokusů na 50 % / 90 %, a s „pity“ (jistota nejpozději na K-tý pokus).", category="hry")
async def loot_odds(ctx, table: Annotated[list[dict], "[{item, weight, value?}]"], tries: int = 10, pity: int = 0) -> ToolResult:
    from .. import gamedev

    try:
        r = gamedev.loot(table, max(1, tries), max(0, pity))
    except (ValueError, KeyError) as e:
        return ToolResult(False, f"Tabulka nesedí: {e}")
    return ToolResult(True, "; ".join(f"{x['item']} {x['chance']:g} % (průměrně {x['expected_rolls']} pokusů, za {tries} = {x['within']:g} %)"
                                      for x in r["items"][:6]) + ".", data=r)


@tool("spawn_balance", "Férovost mapy: jak daleko to má každý tým ze spawnu k cílům, kdo má výhodu a které spawny jsou moc blízko "
      "nepříteli.", category="hry")
async def spawn_balance(ctx, spawns: Annotated[list[dict], "[{team, x, y}]"], objectives: Annotated[list[dict], "[{name, x, y}]"],
                        min_enemy_distance: float = 0) -> ToolResult:
    from .. import gamedev

    r = gamedev.spawn_balance(spawns, objectives, min_enemy_distance)
    return ToolResult(True, "Mapa je férová." if r["fair"] else "Nefér: " + "; ".join(r["issues"][:5]) + ".", data=r)


@tool("level_generator", "Vygeneruje level (místnosti propojené chodbami, start a východ co nejdál od sebe) ze semínka, ověří, "
      "že se dá projít, a uloží ho jako obrázek i text.", category="hry")
async def level_generator(ctx, seed: int = 1, width: int = 60, height: int = 40, rooms: int = 10) -> ToolResult:
    from .. import gamedev

    try:
        r = await asyncio.to_thread(gamedev.dungeon, seed, max(20, min(width, 200)), max(15, min(height, 150)), max(2, min(rooms, 40)), _out(f"level-{seed}"))
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"{r['rooms']} místností, cesta start → východ {r['path_length']} polí, {r['dead_ends']} slepých konců, "
                            f"{'průchozí' if r['connected'] else 'NEPRŮCHOZÍ'}.", data=r, attachments=[r["path"]])


@tool("save_validate", "Zkontroluje uloženou hru (JSON) podle pravidel (typ, rozsah, povinné, jedinečné) a proti předchozímu "
      "uložení najde podezřelé skoky (zlato ×100, záporné hodnoty).", category="hry", perm="files_read")
async def save_validate(ctx, file: str, rules: Annotated[dict[str, dict], "{'player.level': {type: int, min: 1, max: 99}, 'inventory[].id': {unique: true}}"],
                        previous_file: str = "", max_jump: float = 10) -> ToolResult:
    from .. import gamedev

    try:
        data = _json_arg(None, file)
        prev = _json_arg(None, previous_file) if previous_file else None
    except ValueError as e:
        return ToolResult(False, str(e))
    r = gamedev.save_validate(data, rules, prev, max(1.0, max_jump))
    if r["ok"]:
        return ToolResult(True, "Uložená hra odpovídá pravidlům.", data=r)
    msg = "; ".join(r["errors"][:6])
    if r["suspicious"]:
        msg += ("; " if msg else "") + "podezřelé: " + ", ".join(f"{j['path']} {j['before']} → {j['after']}" for j in r["suspicious"][:5])
    return ToolResult(True, msg + ".", data=r)


@tool("animation_fsm", "Zkontroluje stavový automat animací postavy (stavy, přechody s podmínkami): nedosažitelné stavy, stavy "
      "bez odchodu, dva přechody na stejnou podmínku, neznámé parametry; vrátí i diagram (Mermaid).", category="hry")
async def animation_fsm(ctx, states: list[str], transitions: Annotated[list[dict], "[{from, to, when}] – from '*' = z kteréhokoli"],
                        entry: str, params: list[str] | None = None, terminal: list[str] | None = None) -> ToolResult:
    from .. import gamedev

    r = gamedev.anim_fsm(states, transitions, entry, params, terminal)
    return ToolResult(True, "Automat je v pořádku." if r["ok"] else "; ".join(r["issues"][:6]) + ".", data=r)


@tool("server_capacity", "Kapacita herního serveru: zátěž procesoru za tick, odchozí datový tok, kolik hráčů unese procesor a "
      "kolik linka, a co dojde dřív.", category="hry")
async def server_capacity(ctx, players: int, tick_rate: float = 30, cpu_ms_per_player: float = 0.2, bytes_per_entity: float = 40,
                          cores: int = 1, uplink_mbps: float = 100, visible_players: int = 0) -> ToolResult:
    from .. import gamedev

    if tick_rate <= 0 or players < 1:
        return ToolResult(False, "Tick a počet hráčů musí být kladné.")
    r = gamedev.server_capacity(players, tick_rate, cpu_ms_per_player, bytes_per_entity, cores, uplink_mbps, visible_players)
    return ToolResult(True, f"{players} hráčů: procesor {r['cpu_load_pct']} % ticku, linka {r['uplink_mbps']} Mbit/s ({r['uplink_pct']} %). "
                            f"Max {r['max_players']} hráčů, dřív dojde {r['bottleneck']}.", data=r)


@tool("game_telemetry", "Rozbor herní telemetrie (CSV: hráč, událost, level, čas, x, y): kolik hráčů level dohraje, kde umírají, "
      "kde odcházejí, nejtěžší level a místa nejčastější smrti.", category="hry", perm="files_read")
async def game_telemetry(ctx, file: str, cell: float = 10) -> ToolResult:
    from .. import gamedev
    from ..science import read_csv

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    header, rows, _, _ = await asyncio.to_thread(read_csv, p)
    try:
        r = gamedev.telemetry(header, rows, max(1.0, cell))
    except ValueError as e:
        return ToolResult(False, str(e))
    msg = f"{r['players']} hráčů; " + ", ".join(f"{x['level']}: dohraje {x['completion_pct']} %" for x in r["levels"][:6] if x["completion_pct"] is not None)
    if r["hardest"]:
        msg += f". Nejtěžší {r['hardest']}"
    if r["death_spots"]:
        s = r["death_spots"][0]
        msg += f", nejvíc smrtí kolem ({s['x']:g}, {s['y']:g}) – {s['deaths']}×"
    return ToolResult(True, msg + ".", data=r)


@tool("colorblind_check", "Jak hru / obrázek vidí barvoslepí (protanopie, deuteranopie, tritanopie): uloží simulace a řekne, které "
      "hlavní barvy splynou. Nebo porovná dvě barvy (#rrggbb).", category="hry", perm="files_read")
async def colorblind_check(ctx, image: str = "", color_a: str = "", color_b: str = "") -> ToolResult:
    from .. import gamedev

    if color_a and color_b:
        try:
            r = gamedev.color_pair(color_a, color_b)
        except ValueError:
            return ToolResult(False, "Barvy zadej jako #rrggbb.")
        bad = [k for k in gamedev.CVD if r[k] < gamedev.CONFUSE]
        return ToolResult(True, f"Rozdíl normálně {r['normal']}; " + ", ".join(f"{k} {r[k]}" for k in gamedev.CVD) +
                          (f". Splynou při: {', '.join(bad)}." if bad else ". Rozliší je všichni."), data=r)
    p = resolve(image)
    if not p.is_file():
        return ToolResult(False, "Zadej obrázek, nebo dvě barvy.")
    try:
        r = await asyncio.to_thread(gamedev.colorblind, p, paths.data_dir() / "hry" / "barvoslepost")
    except OSError as e:
        return ToolResult(False, f"Obrázek nejde otevřít: {e}")
    if r["ok"]:
        return ToolResult(True, "Hlavní barvy rozliší i barvoslepí.", data=r, attachments=list(r["images"].values()))
    return ToolResult(True, "Splynou: " + "; ".join(f"{k}: " + ", ".join(f"{c['a']}/{c['b']}" for c in v[:3]) for k, v in r["confusions"].items() if v) + ".",
                      data=r, attachments=list(r["images"].values()))


@tool("balance_sim", "Herní balanc: nechá jednotky (životy, poškození, rychlost útoku, brnění, přesnost, kritické zásahy) "
      "stokrát proti sobě bojovat → matice výher, kdo je moc silný a kdo slabý.", category="hry")
async def balance_sim(ctx, units: Annotated[list[dict], "[{name, hp, damage, attack_speed, armor?, accuracy?, crit_chance?, crit_mult?}]"],
                      fights: int = 500, seed: int = 1) -> ToolResult:
    from .. import gamedev

    try:
        r = await asyncio.to_thread(gamedev.balance_sim, units, max(10, min(fights, 5000)), seed)
    except (ValueError, KeyError) as e:
        return ToolResult(False, f"Jednotky nesedí: {e}")
    msg = "Výhry: " + ", ".join(f"{n} {w:g} %" for n, w in sorted(r["win_rate"].items(), key=lambda x: -x[1])) + "."
    if r["dominant"]:
        msg += f" Moc silné: {', '.join(r['dominant'])}."
    if r["weak"]:
        msg += f" Slabé: {', '.join(r['weak'])}."
    return ToolResult(True, msg, data=r)
