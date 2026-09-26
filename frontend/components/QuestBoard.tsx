/**
 * 每日计划面板。
 *
 * 列表里的每一条都归用户自己：对号由用户自己打（计划做什么系统猜不到），
 * 计划名、目标、图标可以改，也能删。新用户第一次打开会拿到四条默认计划，
 * 播种逻辑在后端 social_service.ensure_default_quests。
 */

"use client";

import { useEffect, useState } from "react";

import { ProgressBar } from "@/components/ui";
import { socialApi, type Quest, type QuestMetric } from "@/lib/social";

const ICONS = ["🎯", "📚", "📖", "🎭", "💬", "✍️", "🔥", "⭐", "🗣️", "🧠"];

export function QuestBoard({ compact = false }: { compact?: boolean }) {
  const [quests, setQuests] = useState<Quest[]>([]);
  const [metrics, setMetrics] = useState<QuestMetric[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // 正在提交打勾的条目，避免连点重复请求
  const [pending, setPending] = useState<string[]>([]);

  const [label, setLabel] = useState("");
  const [metric, setMetric] = useState("words");
  const [target, setTarget] = useState(10);
  const [icon, setIcon] = useState("🎯");

  async function load() {
    try {
      const [qs, ms] = await Promise.all([socialApi.quests(), socialApi.questMetrics()]);
      setQuests(qs);
      setMetrics(ms);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleCreate() {
    if (!label.trim()) return;
    setBusy(true);
    setError("");
    try {
      // 计划的 XP 不再由系统代发，固定传 0。
      await socialApi.createQuest({ label: label.trim(), metric, target, xp: 0, icon });
      setLabel("");
      setTarget(10);
      setIcon("🎯");
      setEditing(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id: number) {
    setBusy(true);
    try {
      await socialApi.deleteQuest(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleTarget(quest: Quest, next: number) {
    if (!quest.id) return;
    setBusy(true);
    try {
      await socialApi.updateQuest(quest.id, { target: Math.max(1, next) });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleRename(quest: Quest, value: string) {
    const next = value.trim();
    if (!quest.id || !next || next === quest.label) return;
    setBusy(true);
    try {
      await socialApi.updateQuest(quest.id, { label: next });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败");
      await load();
    } finally {
      setBusy(false);
    }
  }

  /** 打勾 / 取消打勾：先本地翻，让点击立刻有反馈，失败再翻回来。 */
  async function handleToggle(quest: Quest) {
    if (!quest.id || pending.includes(quest.key)) return;
    const next = !quest.completed;

    setError("");
    setPending((list) => [...list, quest.key]);
    setQuests((list) =>
      list.map((q) => (q.key === quest.key ? { ...q, completed: next } : q))
    );

    try {
      const updated = await socialApi.checkQuest(quest.id, next);
      setQuests((list) => list.map((q) => (q.key === quest.key ? updated : q)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
      setQuests((list) =>
        list.map((q) => (q.key === quest.key ? { ...q, completed: !next } : q))
      );
    } finally {
      setPending((list) => list.filter((key) => key !== quest.key));
    }
  }

  const done = quests.filter((q) => q.completed).length;
  const percent = quests.length ? Math.round((done / quests.length) * 100) : 0;

  return (
    <div className="card space-y-4 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Daily Quest</h2>
        <button
          onClick={() => setEditing((v) => !v)}
          className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-600 transition hover:border-brand-300"
        >
          {editing ? "完成" : "编辑"}
        </button>
      </div>

      <div className="space-y-1.5">
        <ProgressBar value={percent} />
        <p className="text-right text-[11px] text-slate-400">
          {done}/{quests.length} 已完成
        </p>
      </div>

      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
      ) : null}

      <ul className="space-y-3">
        {quests.map((quest) => {
          const isPending = pending.includes(quest.key);
          return (
            <li key={quest.key} className="flex items-center gap-3 text-sm">
              <button
                type="button"
                onClick={() => handleToggle(quest)}
                disabled={isPending}
                aria-pressed={quest.completed}
                aria-label={quest.completed ? `取消完成：${quest.label}` : `标记完成：${quest.label}`}
                title={quest.completed ? "取消打勾" : "标记为今天已完成"}
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-[11px] transition ${
                  quest.completed
                    ? "border-brand-600 bg-brand-600 text-white"
                    : "border-slate-300 text-transparent hover:border-brand-400 hover:text-slate-300"
                } ${isPending ? "opacity-50" : ""}`}
              >
                ✓
              </button>
              <span className="text-base">{quest.icon}</span>

              {editing ? (
                <input
                  key={quest.label}
                  defaultValue={quest.label}
                  maxLength={64}
                  disabled={busy}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                  }}
                  onBlur={(e) => handleRename(quest, e.target.value)}
                  className="input min-w-0 flex-1 !py-1 text-sm"
                />
              ) : (
                <span
                  className={
                    quest.completed ? "text-slate-400 line-through" : "text-slate-700"
                  }
                >
                  {quest.label}
                </span>
              )}

              {quest.target > 1 ? (
                <span className="shrink-0 text-[11px] text-slate-400">
                  {quest.progress}/{quest.target}
                </span>
              ) : null}

              <span className="ml-auto flex shrink-0 items-center gap-2">
                {editing ? (
                  <>
                    <button
                      onClick={() => handleTarget(quest, quest.target + 5)}
                      disabled={busy}
                      title="提高目标"
                      className="h-5 w-5 rounded border border-slate-200 text-[11px] text-slate-500 hover:border-brand-300"
                    >
                      +
                    </button>
                    <button
                      onClick={() => handleTarget(quest, quest.target - 5)}
                      disabled={busy}
                      title="降低目标"
                      className="h-5 w-5 rounded border border-slate-200 text-[11px] text-slate-500 hover:border-brand-300"
                    >
                      −
                    </button>
                    <button
                      onClick={() => quest.id && handleDelete(quest.id)}
                      disabled={busy}
                      className="text-[11px] text-rose-400 hover:text-rose-600"
                    >
                      删除
                    </button>
                  </>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>

      {editing ? (
        <div className="space-y-3 rounded-xl bg-slate-50 p-3">
          <p className="text-xs font-medium text-slate-600">添加自己的计划</p>

          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="例如：每天背 20 个单词"
            className="input !py-2 text-sm"
          />

          <div className="flex flex-wrap gap-1.5">
            {ICONS.map((item) => (
              <button
                key={item}
                onClick={() => setIcon(item)}
                className={`h-7 w-7 rounded-lg text-sm transition ${
                  icon === item ? "bg-brand-600" : "bg-white hover:bg-slate-100"
                }`}
              >
                {item}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="input !py-2 text-sm"
            >
              {metrics.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={500}
                value={target}
                onChange={(e) => setTarget(Number(e.target.value))}
                className="input !py-2 text-sm"
              />
              <span className="shrink-0 text-xs text-slate-400">
                {metrics.find((m) => m.key === metric)?.unit ?? ""}
              </span>
            </div>
          </div>

          <button
            onClick={handleCreate}
            disabled={busy || !label.trim()}
            className="btn-primary w-full !py-2 text-sm"
          >
            添加
          </button>
        </div>
      ) : null}

      {!compact && quests.length === 0 ? (
        <p className="text-xs text-slate-400">还没有计划，点「编辑」加一条</p>
      ) : null}
    </div>
  );
}
