// 3.15 Dílna: the pure parts of the model viewer (no DOM, no three.js) – also used by the tests.

/** Split one triangle soup into its connected pieces (vertices merged by position). Pure – also used by the tests. */
export function components(pos: Float32Array, maxTris = 400_000): number[][] {
  const n = pos.length / 9;
  if (n > maxTris) return [Array.from({ length: n }, (_, i) => i)];
  const key = (i: number) => `${pos[i].toFixed(4)},${pos[i + 1].toFixed(4)},${pos[i + 2].toFixed(4)}`;
  const ids = new Map<string, number>();
  const parent: number[] = [];
  const find = (a: number): number => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
  const tv: number[] = new Array(n * 3);
  for (let v = 0; v < n * 3; v++) {
    const k = key(v * 3);
    let id = ids.get(k);
    if (id === undefined) { id = parent.length; ids.set(k, id); parent.push(id); }
    tv[v] = id;
  }
  for (let t = 0; t < n; t++) {
    const a = find(tv[t * 3]), b = find(tv[t * 3 + 1]), c = find(tv[t * 3 + 2]);
    if (a !== b) parent[b] = a;
    const a2 = find(a), c2 = find(c);
    if (a2 !== c2) parent[c2] = a2;
  }
  const groups = new Map<number, number[]>();
  for (let t = 0; t < n; t++) {
    const r = find(tv[t * 3]);
    let g = groups.get(r);
    if (!g) groups.set(r, (g = []));
    g.push(t);
  }
  return [...groups.values()].sort((x, y) => y.length - x.length);
}

/** Where each part goes at explode = 1: away from the model's centre, a bit further than its own distance. */
export function explodeOffsets(centres: [number, number, number][], size: number): [number, number, number][] {
  const n = centres.length;
  const c = centres.reduce((s, p) => [s[0] + p[0] / n, s[1] + p[1] / n, s[2] + p[2] / n], [0, 0, 0]);
  return centres.map((p, i) => {
    let d = [p[0] - c[0], p[1] - c[1], p[2] - c[2]];
    let len = Math.hypot(d[0], d[1], d[2]);
    if (len < size * 0.02) {                          // a part in the very centre: spread such parts around a circle
      const a = (i / Math.max(1, n)) * Math.PI * 2;
      d = [Math.cos(a), 0.6, Math.sin(a)];
      len = Math.hypot(d[0], d[1], d[2]);
    }
    const dist = len * 0.6 + size * 0.35;                 // farther parts fly farther, every part at least a third of the size
    return [d[0] / len * dist, d[1] / len * dist, d[2] / len * dist];
  });
}
