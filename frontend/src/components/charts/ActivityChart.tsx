import { Table2 } from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ActivityBucket } from "../../api/types";
import { cx } from "../../lib/cx";

/**
 * Entries vs exits per bucket: grouped columns, one y-axis (counts).
 * Series colours are CSS roles (--series-1 / --series-2) validated for both themes;
 * text always uses text tokens, never the series colour.
 */
const HEIGHT = 200; // plot + x-axis band; the card never needs a nested scroll
const M = { top: 18, right: 4, bottom: 26, left: 30 };
const MAX_BAR = 24;
const GAP = 2; // surface gap between adjacent bars

const SERIES = [
  { key: "entries", label: "Entries", color: "var(--series-1)" },
  { key: "exits", label: "Exits", color: "var(--series-2)" },
] as const;

function niceTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  if (max <= 5) return Array.from({ length: max + 1 }, (_, i) => i);
  const rough = max / 4;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= rough) ?? 10 * pow;
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: top / step + 1 }, (_, i) => i * step);
}

/** Column with a 4px rounded data end and a square base on the baseline. */
function columnPath(x: number, y: number, w: number, base: number): string {
  const h = base - y;
  const r = Math.min(4, w / 2, h);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
}

export function ActivityChart({ buckets, bucketMinutes, fetching }: { buckets: ActivityBucket[]; bucketMinutes: number; fetching?: boolean }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.floor(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [table]);

  const daily = bucketMinutes >= 1440;
  const fmtStart = (iso: string) =>
    daily
      ? new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric" })
      : new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const fmtRange = (iso: string) => {
    const start = new Date(iso);
    if (daily) return start.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
    const end = new Date(start.getTime() + bucketMinutes * 60_000);
    const t = (d: Date) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    return `${t(start)}–${t(end)}`;
  };

  const totals = useMemo(
    () => ({
      entries: buckets.reduce((s, b) => s + b.entries, 0),
      exits: buckets.reduce((s, b) => s + b.exits, 0),
      observations: buckets.reduce((s, b) => s + b.observations, 0),
    }),
    [buckets],
  );

  const plotW = width - M.left - M.right;
  const plotH = HEIGHT - M.top - M.bottom;
  const max = Math.max(0, ...buckets.map((b) => Math.max(b.entries, b.exits)));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const band = plotW / Math.max(1, buckets.length);
  const barW = Math.max(1, Math.min(MAX_BAR, (band - GAP) / 2 - 2));
  const groupW = barW * 2 + GAP;
  const y = (v: number) => M.top + plotH - (v / top) * plotH;
  const base = M.top + plotH;
  const labelEvery = Math.max(1, Math.ceil(buckets.length / Math.max(2, Math.floor(plotW / 56))));

  // Selective direct label: only the single highest column.
  let peak: { i: number; s: 0 | 1; v: number } | null = null;
  buckets.forEach((b, i) =>
    [b.entries, b.exits].forEach((v, s) => {
      if (v > 0 && (!peak || v > peak.v)) peak = { i, s: s as 0 | 1, v };
    }),
  );
  const peakMark = peak as { i: number; s: 0 | 1; v: number } | null;

  const empty = totals.entries + totals.exits === 0;
  const hovered = hover !== null ? buckets[hover] : null;
  const tipLeft = hover !== null ? Math.min(Math.max(M.left + band * (hover + 0.5), 80), width - 80) : 0;

  return (
    <figure className="space-y-3">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400" aria-label="Legend">
          {SERIES.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
              {s.label}
              <span className="font-semibold text-slate-900 dark:text-white">{totals[s.key]}</span>
            </span>
          ))}
          <span className="text-slate-500 dark:text-slate-400">Sightings {totals.observations}</span>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" aria-pressed={table} onClick={() => setTable((t) => !t)}>
          <Table2 className="h-3.5 w-3.5" aria-hidden />
          {table ? "Show chart" : "Show table"}
        </button>
      </figcaption>

      {table ? (
        <div className="max-h-72 overflow-auto rounded-lg ring-1 ring-slate-200 dark:ring-slate-800">
          <table className="min-w-full text-sm">
            <thead className="table-head sticky top-0">
              <tr>
                <th className="px-3 py-2">{daily ? "Day" : "Time"}</th>
                <th className="px-3 py-2 text-right">Entries</th>
                <th className="px-3 py-2 text-right">Exits</th>
                <th className="px-3 py-2 text-right">Sightings</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums dark:divide-slate-800">
              {buckets.map((b) => (
                <tr key={b.start}>
                  <td className="px-3 py-1.5 text-slate-700 dark:text-slate-300">{fmtRange(b.start)}</td>
                  <td className="px-3 py-1.5 text-right">{b.entries}</td>
                  <td className="px-3 py-1.5 text-right">{b.exits}</td>
                  <td className="px-3 py-1.5 text-right text-slate-500 dark:text-slate-400">{b.observations}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div ref={wrap} className={cx("relative transition-opacity", fetching && "opacity-60")} onPointerLeave={() => setHover(null)}>
          <svg width={width} height={HEIGHT} role="img" aria-label={`Entries and exits per ${daily ? "day" : "hour"}: ${totals.entries} entries, ${totals.exits} exits`}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--chart-axis)" : "var(--chart-grid)"} strokeWidth={1} shapeRendering="crispEdges" />
                <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-slate-500 text-[10px] tabular-nums dark:fill-slate-400">
                  {t}
                </text>
              </g>
            ))}
            {buckets.map((b, i) => {
              const x0 = M.left + band * i + (band - groupW) / 2;
              return (
                <g key={b.start}>
                  {hover === i && <rect x={M.left + band * i} y={M.top} width={band} height={plotH} className="fill-slate-100 dark:fill-slate-800/70" />}
                  {[b.entries, b.exits].map((v, s) =>
                    v > 0 ? <path key={s} d={columnPath(x0 + s * (barW + GAP), y(v), barW, base)} fill={SERIES[s].color} /> : null,
                  )}
                  {i % labelEvery === 0 && (
                    <text x={M.left + band * (i + 0.5)} y={HEIGHT - 8} textAnchor="middle" className="fill-slate-500 text-[10px] dark:fill-slate-400">
                      {fmtStart(b.start)}
                    </text>
                  )}
                </g>
              );
            })}
            {peakMark && (
              <text
                x={M.left + band * peakMark.i + (band - groupW) / 2 + peakMark.s * (barW + GAP) + barW / 2}
                y={y(peakMark.v) - 5}
                textAnchor="middle"
                className="fill-slate-600 text-[10px] font-semibold tabular-nums dark:fill-slate-300"
              >
                {peakMark.v}
              </text>
            )}
            {/* Hit targets: the whole band, larger than the marks; focusable for keyboard users */}
            {buckets.map((b, i) => (
              <rect
                key={b.start}
                x={M.left + band * i}
                y={M.top}
                width={band}
                height={plotH}
                fill="transparent"
                tabIndex={0}
                role="graphics-symbol"
                aria-label={`${fmtRange(b.start)}: ${b.entries} entries, ${b.exits} exits, ${b.observations} sightings`}
                onPointerEnter={() => setHover(i)}
                onPointerMove={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                className="outline-none focus-visible:stroke-sky-500"
                strokeWidth={2}
              />
            ))}
          </svg>
          {empty && (
            <div className="pointer-events-none absolute inset-x-0 top-12 text-center text-xs text-slate-500 dark:text-slate-400">
              No movements logged in this window
            </div>
          )}
          {hovered && (
            <div
              className="pointer-events-none absolute top-0 z-10 w-40 -translate-x-1/2 rounded-lg bg-white px-3 py-2 text-xs shadow-lg ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700"
              style={{ left: tipLeft }}
              role="tooltip"
            >
              <div className="mb-1 font-medium text-slate-500 dark:text-slate-400">{fmtRange(hovered.start)}</div>
              {SERIES.map((s) => (
                <div key={s.key} className="flex items-center gap-2">
                  <span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} aria-hidden />
                  <span className="font-semibold tabular-nums text-slate-900 dark:text-white">{hovered[s.key]}</span>
                  <span className="text-slate-500 dark:text-slate-400">{s.label.toLowerCase()}</span>
                </div>
              ))}
              <div className="mt-1 flex items-center gap-2 border-t border-slate-100 pt-1 dark:border-slate-700">
                <span className="w-3" aria-hidden />
                <span className="font-semibold tabular-nums text-slate-900 dark:text-white">{hovered.observations}</span>
                <span className="text-slate-500 dark:text-slate-400">sightings</span>
              </div>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
