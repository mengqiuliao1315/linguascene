/**
 * 今日学习任务：显示目标/完成度，支持调整目标，超额完成有额外经验。
 *
 * 背单词一项按「新学 / 复习」两个目标分别设置，总进度取两者之和。
 */
"use client";

import { useCallback, useEffect, useState } from "react";

import { wordbookApi, type DailyTask } from "@/lib/wordbook";

const ROWS: {
  key: "scenarios" | "articles";
  label: string;
  unit: string;
  max: number;
}[] = [
  { key: "scenarios", label: "场景对话", unit: "个", max: 20 },
  { key: "articles", label: "读文章", unit: "篇", max: 20 },
];

const DEFAULT_TARGETS: DailyTask["targets"] = {
  words: 45,
  new_words: 15,
  review_words: 30,
  scenarios: 1,
  articles: 1,
  minutes: 15,
};

export function DailyTaskCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const [task, setTask] = useState<DailyTask | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DailyTask["targets"]>(DEFAULT_TARGETS);

  const load = useCallback(() => {
    wordbookApi.dailyTask().then(setTask).catch(() => undefined);
  }, []);

  useEffect(load, [load, refreshKey]);

  if (!task) return null;

  const percent = Math.round(Math.min(1, task.progress) * 100);
  const over = Math.round(task.overachievement * 100);

  const startEdit = () => {
    setDraft(task.targets);
    setEditing(true);
  };

  const save = async () => {
    // 只提交新学/复习两个目标，后端会把「背单词」总目标算成两者之和
    const next = await wordbookApi.saveDailyTask({
      target_new_words: draft.new_words,
      target_review_words: draft.review_words,
      target_scenarios: draft.scenarios,
      target_articles: draft.articles,
    });
    setTask(next);
    setEditing(false);
  };

  return (
    <div className="card space-y-3 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">今日任务</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">{task.date}</span>
          {!editing ? (
            <button
              onClick={startEdit}
              className="text-xs text-brand-600 hover:underline"
            >
              编辑
            </button>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="h-2 flex-1 rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full transition-all ${
              task.is_complete ? "bg-emerald-500" : "bg-brand-500"
            }`}
            style={{ width: `${percent}%` }}
          />
        </div>
        <span className="w-10 text-right text-xs font-medium text-slate-500">
          {percent}%
        </span>
      </div>

      <ul className="space-y-1.5">
        <li className="text-sm">
          <div className="flex items-center justify-between">
            <span className="text-slate-600">背单词</span>
            {editing ? (
              <span className="flex items-center gap-1.5">
                <span className="text-[11px] text-slate-400">新</span>
                <input
                  type="number"
                  min={0}
                  max={200}
                  value={draft.new_words}
                  onChange={(event) =>
                    setDraft((prev) => ({
                      ...prev,
                      new_words: Number(event.target.value),
                    }))
                  }
                  className="input w-16 py-1 text-right text-sm"
                />
                <span className="text-[11px] text-slate-400">复习</span>
                <input
                  type="number"
                  min={0}
                  max={300}
                  value={draft.review_words}
                  onChange={(event) =>
                    setDraft((prev) => ({
                      ...prev,
                      review_words: Number(event.target.value),
                    }))
                  }
                  className="input w-16 py-1 text-right text-sm"
                />
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <span className="text-slate-400">
                  {task.done.words} / {task.targets.words} 个
                </span>
                <XpBadge awarded={task.awarded.words} />
              </span>
            )}
          </div>
          {!editing ? (
            <p className="mt-0.5 text-[11px] text-slate-400">
              新学 {task.done.new_words}/{task.targets.new_words} · 复习{" "}
              {task.done.review_words}/{task.targets.review_words}
            </p>
          ) : null}
        </li>

        {ROWS.map((row) => (
          <li key={row.key} className="flex items-center justify-between text-sm">
            <span className="text-slate-600">{row.label}</span>
            {editing ? (
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={row.max}
                  value={draft[row.key]}
                  onChange={(event) =>
                    setDraft((prev) => ({
                      ...prev,
                      [row.key]: Number(event.target.value),
                    }))
                  }
                  className="input w-20 py-1 text-right text-sm"
                />
                <span className="w-6 text-xs text-slate-400">{row.unit}</span>
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <span className="text-slate-400">
                  {task.done[row.key]} / {task.targets[row.key]} {row.unit}
                </span>
                <XpBadge awarded={task.awarded[row.key]} />
              </span>
            )}
          </li>
        ))}
      </ul>

      {task.is_complete ? (
        <p className="rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          ✅ 已完成，获得 {task.xp_earned} XP
          {task.bonus_xp > 0 ? `，超额奖励 +${task.bonus_xp} XP` : ""}
        </p>
      ) : over > 0 ? (
        <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">
          已超额 {over}%，继续完成其他目标可解锁额外经验
        </p>
      ) : null}

      {editing ? (
        <div className="flex items-center gap-2 pt-1">
          <button onClick={save} className="btn-primary px-3 py-1.5 text-xs">
            保存
          </button>
          <button
            onClick={() => setEditing(false)}
            className="btn-ghost px-3 py-1.5 text-xs"
          >
            取消
          </button>
        </div>
      ) : null}
    </div>
  );
}

function XpBadge({ awarded }: { awarded: boolean }) {
  return awarded ? (
    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
      ✓ +10 XP
    </span>
  ) : (
    <span className="rounded-full bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-400">
      +10 XP
    </span>
  );
}
