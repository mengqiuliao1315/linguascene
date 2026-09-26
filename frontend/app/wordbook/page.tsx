/**
 * 背单词：选词书 → 一次一张卡片 → 自己判断记住没记住。
 *
 * 三种作答：没记住（今天再来）/ 记住了（排进复习）/ 已掌握（不再出现）。
 * 新学和复习是两条独立队列，每天各自有目标，可以在页面上直接改。
 */
"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { WordFlashcard, playWord, preloadWord } from "@/components/WordFlashcard";
import { EmptyState, ProgressBar, Spinner } from "@/components/ui";
import { RequireAuth } from "@/lib/auth";
import {
  wordbookApi,
  type StudyAction,
  type StudyMode,
  type StudySummary,
  type WordCard,
  type Wordbook,
} from "@/lib/wordbook";

const BATCH = 20;
const MODES: { key: StudyMode; label: string }[] = [
  { key: "new", label: "新学" },
  { key: "review", label: "复习" },
];

function StudyScreen() {
  const [books, setBooks] = useState<Wordbook[]>([]);
  const [book, setBook] = useState("");
  const [mode, setMode] = useState<StudyMode>("new");
  const [summary, setSummary] = useState<StudySummary | null>(null);
  const [queue, setQueue] = useState<WordCard[]>([]);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [editingGoals, setEditingGoals] = useState(false);
  const [draft, setDraft] = useState({ new_words: 15, review_words: 30 });

  // 本轮已经答过的词，重新拉队列时不再出现（「没记住」当天可重学，但不在一轮里连刷）
  const sessionSeen = useRef<Set<number>>(new Set());

  const refresh = useCallback(async (nextMode: StudyMode, nextBook: string) => {
    setLoading(true);
    setError("");
    try {
      const [nextSummary, page] = await Promise.all([
        wordbookApi.studySummary(nextBook || undefined),
        wordbookApi.studyQueue({
          mode: nextMode,
          book: nextBook || undefined,
          limit: BATCH,
        }),
      ]);
      setSummary(nextSummary);
      setQueue(page.items.filter((word) => !sessionSeen.current.has(word.id)));
      setIndex(0);
      setRevealed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    wordbookApi
      .books()
      .then((res) => {
        setBooks(res.items);
        const first = res.items[0]?.code ?? "";
        setBook(first);
        void refresh("new", first);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "加载失败");
        setLoading(false);
      });
  }, [refresh]);

  const switchMode = (next: StudyMode) => {
    if (next === mode) return;
    sessionSeen.current = new Set();
    setMode(next);
    void refresh(next, book);
  };

  const switchBook = (next: string) => {
    if (next === book) return;
    sessionSeen.current = new Set();
    setBook(next);
    void refresh(mode, next);
  };

  const word = queue[index];
  const progress = summary ? summary[mode] : null;

  // 朗读跟着「当前显示的这张卡」走：进页面读第一张，翻到新卡读新词。
  // 以前是在作答回调里读刚答完的那张，耳朵听到的才是上一个词。
  // 顺手把后面两张的音频提前拉回来，后端冷合成的那几秒就不会卡在翻卡时。
  useEffect(() => {
    if (loading || !word) return;
    playWord(word.word);
    queue.slice(index + 1, index + 3).forEach((item) => preloadWord(item.word));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [word?.id, loading]);

  const answer = async (action: StudyAction) => {
    if (!word || busy) return;
    setBusy(true);
    try {
      const result = await wordbookApi.answer(word.id, action, mode, book || undefined);
      sessionSeen.current.add(word.id);
      setFlash(
        action === "mastered"
          ? `已标记掌握 · +${result.xp_gained} XP`
          : `+${result.xp_gained} XP`
      );
      window.setTimeout(() => setFlash(""), 1600);

      // 进度条用的是服务端统计，后台刷新即可，不阻塞翻到下一张
      wordbookApi
        .studySummary(book || undefined)
        .then(setSummary)
        .catch(() => undefined);

      if (index + 1 < queue.length) {
        setIndex(index + 1);
        setRevealed(false);
      } else {
        await refresh(mode, book);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setBusy(false);
    }
  };

  const openGoals = () => {
    if (!summary) return;
    setDraft({
      new_words: summary.new.target,
      review_words: summary.review.target,
    });
    setEditingGoals(true);
  };

  const saveGoals = async () => {
    await wordbookApi.saveDailyTask({
      target_new_words: draft.new_words,
      target_review_words: draft.review_words,
    });
    setEditingGoals(false);
    sessionSeen.current = new Set();
    await refresh(mode, book);
  };

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-900">背单词</h1>
        <div className="flex items-center gap-3 text-sm">
          {summary ? (
            <span className="text-xs text-slate-400">
              已掌握 {summary.mastered}
            </span>
          ) : null}
          <Link href="/vocabulary" className="text-brand-600 hover:underline">
            我的词库 →
          </Link>
        </div>
      </div>

      {/* 词书 */}
      <div className="flex flex-wrap gap-2">
        {books.map((item) => (
          <button
            key={item.code}
            onClick={() => switchBook(item.code)}
            className={`rounded-xl px-3.5 py-2 text-sm transition ${
              book === item.code
                ? "bg-brand-600 text-white"
                : "border border-slate-200 bg-white text-slate-600 hover:border-brand-300"
            }`}
          >
            <span className="mr-1">{item.icon}</span>
            {item.name_zh}
          </button>
        ))}
      </div>

      {/* 新学 / 复习 + 今日目标 */}
      <div className="card space-y-3 p-4">
        <div className="flex items-center gap-2">
          {MODES.map((item) => (
            <button
              key={item.key}
              onClick={() => switchMode(item.key)}
              className={`rounded-xl px-3.5 py-1.5 text-sm transition ${
                mode === item.key
                  ? "bg-slate-900 text-white"
                  : "border border-slate-200 bg-white text-slate-600"
              }`}
            >
              {item.label}
              {summary ? (
                <span className="ml-1.5 text-[11px] opacity-70">
                  {summary[item.key].done}/{summary[item.key].target}
                </span>
              ) : null}
            </button>
          ))}
          <button
            onClick={editingGoals ? () => setEditingGoals(false) : openGoals}
            className="ml-auto text-xs text-brand-600 hover:underline"
          >
            {editingGoals ? "收起" : "设定每日目标"}
          </button>
        </div>

        {editingGoals ? (
          <div className="space-y-2 rounded-xl bg-slate-50 p-3">
            <label className="flex items-center justify-between text-sm">
              <span className="text-slate-600">每天新学</span>
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={200}
                  value={draft.new_words}
                  onChange={(e) =>
                    setDraft((prev) => ({ ...prev, new_words: Number(e.target.value) }))
                  }
                  className="input w-20 py-1 text-right text-sm"
                />
                <span className="text-xs text-slate-400">词</span>
              </span>
            </label>
            <label className="flex items-center justify-between text-sm">
              <span className="text-slate-600">每天复习</span>
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={300}
                  value={draft.review_words}
                  onChange={(e) =>
                    setDraft((prev) => ({ ...prev, review_words: Number(e.target.value) }))
                  }
                  className="input w-20 py-1 text-right text-sm"
                />
                <span className="text-xs text-slate-400">词</span>
              </span>
            </label>
            <div className="flex gap-2 pt-1">
              <button onClick={saveGoals} className="btn-primary px-3 py-1.5 text-xs">
                保存
              </button>
              <button
                onClick={() => setEditingGoals(false)}
                className="btn-ghost px-3 py-1.5 text-xs"
              >
                取消
              </button>
            </div>
          </div>
        ) : progress ? (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span>
                {mode === "new" ? "新学" : "复习"}进度 {progress.done}/
                {progress.target}
              </span>
              <span>
                {mode === "new"
                  ? `未学 ${summary?.new.available ?? 0}`
                  : `到期 ${summary?.review.due ?? 0}`}
              </span>
            </div>
            <ProgressBar
              value={
                progress.target ? (progress.done / progress.target) * 100 : 100
              }
            />
          </div>
        ) : null}
      </div>

      {error ? <EmptyState text={error} /> : null}

      {loading ? (
        <Spinner />
      ) : word ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>
              {mode === "new" ? "新学" : "复习"} · 第 {index + 1} / {queue.length} 张
            </span>
            <span className="h-4 text-brand-600">{flash}</span>
          </div>

          <WordFlashcard
            word={word}
            revealed={revealed}
            onReveal={() => setRevealed(true)}
            onChange={(next) =>
              setQueue((prev) => prev.map((w) => (w.id === next.id ? next : w)))
            }
          />

          <div className="space-y-2">
            <button
              onClick={() => answer("forget")}
              disabled={busy}
              className="btn-ghost w-full py-3 text-sm text-rose-600"
            >
              没记住
            </button>
            <div className="flex gap-2">
              <button
                onClick={() => answer("remember")}
                disabled={busy}
                className="btn-primary flex-1 py-3 text-sm"
              >
                记住了
              </button>
              <button
                onClick={() => answer("mastered")}
                disabled={busy}
                className="btn-ghost flex-1 py-3 text-sm text-emerald-700"
                title="已掌握，之后不再出现"
              >
                已掌握
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="card space-y-3 p-6 text-center">
          <p className="text-sm text-slate-600">
            {mode === "new"
              ? progress && progress.target > 0
                ? "今天的新学目标完成了 🎉"
                : "这本词书的新词都学完了 🎉"
              : "今天的复习目标完成了 🎉"}
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {mode === "new" ? (
              <button
                onClick={() => switchMode("review")}
                className="btn-primary px-4 py-2 text-sm"
              >
                去复习
              </button>
            ) : (
              <button
                onClick={() => switchMode("new")}
                className="btn-primary px-4 py-2 text-sm"
              >
                去新学
              </button>
            )}
            <button
              onClick={() => {
                sessionSeen.current = new Set();
                void refresh(mode, book);
              }}
              className="btn-ghost px-4 py-2 text-sm"
            >
              继续
            </button>
            <button onClick={openGoals} className="btn-ghost px-4 py-2 text-sm">
              调整目标
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function WordbookPage() {
  return (
    <RequireAuth>
      <AppShell>
        <StudyScreen />
      </AppShell>
    </RequireAuth>
  );
}
