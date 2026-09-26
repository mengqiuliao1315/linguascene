"use client";

import { useState } from "react";

import { HEAT_COLORS, type HeatCell } from "@/lib/social";

const WEEKDAYS = ["一", "", "三", "", "五", "", "日"];
const WEEKDAY_FULL = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const MONTHS = [
  "1月", "2月", "3月", "4月", "5月", "6月",
  "7月", "8月", "9月", "10月", "11月", "12月",
];

const CELL = 16;
const GAP = 3;
const STEP = CELL + GAP;

function formatDate(date: Date): string {
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function toKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function Heatmap({
  cells,
  weeks = 18,
  currentStreak,
  longestStreak,
  activeDays,
}: {
  cells: HeatCell[];
  weeks?: number;
  currentStreak?: number;
  longestStreak?: number;
  activeDays?: number;
}) {
  const byDate = new Map(cells.map((cell) => [cell.date, cell]));

  const [tip, setTip] = useState<{
    weekday: string;
    label: string;
    x: number;
    y: number;
  } | null>(null);

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const isoWeekday = (today.getDay() + 6) % 7;
  const lastMonday = new Date(today);
  lastMonday.setDate(today.getDate() - isoWeekday);

  const start = new Date(lastMonday);
  start.setDate(lastMonday.getDate() - (weeks - 1) * 7);

  const columns: { date: Date; key: string; cell?: HeatCell }[][] = [];
  const monthLabels: { index: number; label: string }[] = [];

  for (let col = 0; col < weeks; col += 1) {
    const column: { date: Date; key: string; cell?: HeatCell }[] = [];
    for (let row = 0; row < 7; row += 1) {
      const date = new Date(start);
      date.setDate(start.getDate() + col * 7 + row);
      const key = toKey(date);
      column.push({ date, key, cell: byDate.get(key) });
    }

    const first = column[0].date;
    const previous = col > 0 ? columns[col - 1][0].date : null;
    if (!previous || previous.getMonth() !== first.getMonth()) {
      monthLabels.push({ index: col, label: MONTHS[first.getMonth()] });
    }

    columns.push(column);
  }

  const total = cells.reduce((sum, cell) => sum + cell.count, 0);
  const todayKey = toKey(today);

  const stats: { label: string; value: number; icon: string }[] = [];
  if (currentStreak != null) {
    stats.push({ label: "当前连续打卡", value: currentStreak, icon: "🔥" });
  }
  if (longestStreak != null) {
    stats.push({ label: "最长连续打卡", value: longestStreak, icon: "🏅" });
  }
  if (activeDays != null) {
    stats.push({ label: "活跃天数", value: activeDays, icon: "📅" });
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto pb-1">
        <div className="flex gap-2">
          <div className="flex shrink-0 flex-col" style={{ gap: GAP }}>
            <div style={{ height: CELL }} />
            {WEEKDAYS.map((day, index) => (
              <span
                key={index}
                className="flex items-center justify-end text-[10px] leading-none text-slate-300"
                style={{ height: CELL }}
              >
                {day}
              </span>
            ))}
          </div>

          <div className="flex min-w-0 flex-col" style={{ gap: GAP }}>
            <div className="relative" style={{ height: CELL }}>
              {monthLabels.map((item) => (
                <span
                  key={item.index}
                  className="absolute top-0 whitespace-nowrap text-[10px] font-medium leading-none text-slate-400"
                  style={{ left: item.index * STEP }}
                >
                  {item.label}
                </span>
              ))}
            </div>

            <div className="flex" style={{ gap: GAP }}>
              {columns.map((column, colIndex) => (
                <div
                  key={colIndex}
                  className="flex shrink-0 flex-col"
                  style={{ gap: GAP }}
                >
                  {column.map(({ date, key, cell }) => {
                    const future = date.getTime() > today.getTime();
                    const level = future ? -1 : (cell?.level ?? 0);

                    return (
                      <span
                        key={key}
                        style={{ width: CELL, height: CELL }}
                        onMouseEnter={
                          future
                            ? undefined
                            : (event) => {
                                const rect =
                                  event.currentTarget.getBoundingClientRect();
                                setTip({
                                  weekday: WEEKDAY_FULL[date.getDay()],
                                  label: formatDate(date),
                                  x: rect.left + rect.width / 2,
                                  y: rect.top,
                                });
                              }
                        }
                        onMouseLeave={future ? undefined : () => setTip(null)}
                        className={`rounded-[4px] transition ${
                          level < 0
                            ? "bg-transparent"
                            : HEAT_COLORS[Math.min(level, HEAT_COLORS.length - 1)]
                        } ${
                          key === todayKey
                            ? "ring-2 ring-inset ring-brand-600"
                            : "hover:ring-1 hover:ring-brand-300"
                        }`}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {stats.length > 0 ? (
        <div className="flex flex-wrap gap-3">
          {stats.map((item) => (
            <div
              key={item.label}
              className="flex min-w-[104px] flex-1 items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2.5"
            >
              <span className="text-lg leading-none">{item.icon}</span>
              <div className="leading-tight">
                <p className="text-sm font-semibold text-slate-900">
                  {item.value}
                  <span className="ml-0.5 text-[11px] font-normal text-slate-400">
                    天
                  </span>
                </p>
                <p className="text-[11px] text-slate-400">{item.label}</p>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
        <span>
          近 {weeks} 周共 {total} 次学习
        </span>
        <span className="flex items-center gap-1">
          少
          {HEAT_COLORS.map((color) => (
            <span
              key={color}
              className={`rounded-[4px] ${color}`}
              style={{ width: CELL, height: CELL }}
            />
          ))}
          多
        </span>
      </div>

      {tip ? (
        <div
          className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full"
          style={{ left: tip.x, top: tip.y - 8 }}
        >
          <div className="heat-tip relative">
            <div className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-slate-200/70 bg-white/95 py-[3px] pl-[3px] pr-2.5 shadow-[0_8px_22px_-10px_rgba(37,99,235,0.5)]">
              <span className="grid h-[18px] w-[18px] place-items-center rounded-full bg-brand-500 text-[9px] font-semibold leading-none text-white">
                {tip.weekday.slice(1)}
              </span>
              <span className="text-[11px] font-medium tracking-tight text-slate-600">
                {tip.label}
              </span>
            </div>
            <span className="absolute left-1/2 top-full -ml-1 h-0 w-0 border-4 border-transparent border-t-white" />
          </div>
        </div>
      ) : null}
    </div>
  );
}
