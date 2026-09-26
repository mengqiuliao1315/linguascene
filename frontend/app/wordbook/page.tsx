"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { WordFlashcard, playWord, preloadWord } from "@/components/WordFlashcard";
import { EmptyState, ProgressBar, Spinner } from "@/components/ui";
import { RequireAuth } from "@/lib/auth";
import {
  wordbookApi,
  type StudyAction,
  type StudySummary,
  type WordCard,
  type Wordbook,
} from "@/lib/wordbook";

const BATCH = 20;

function StudyScreen() {
  const [books, setBooks] = useState<Wordbook[]>([]);
  const [book, setBook] = useState("");
  const [summary, setSummary] = useState<StudySummary | null>(null);
  const [queue, setQueue] = useState<WordCard[]>([]);
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [editingGoals, setEditingGoals] = useState(false);
  const [draft, setDraft] = useState(30);

  const refresh = useCallback(async (nextBook: string) => {
    setLoading(true);
    setError("");
    try {
      const [nextSummary, page] = await Promise.all([
        wordbookApi.studySummary(nextBook || undefined),
        wordbookApi.studyQueue({ book: nextBook || undefined, limit: BATCH }),
      ]);
      setSummary(nextSummary);
      setQueue(page.items);
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
        void refresh(first);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "加载失败");
        setLoading(false);
      });
  }, [refresh]);

  const switchBook = (next: string) => {
    if (next === book) return;
    setBook(next);
    void refresh(next);
  };

  const word = queue[0];

  useEffect(() => {
    if (loading || !word) return;
    playWord(word.word);
    queue.slice(1, 3).forEach((item) => preloadWord(item.word));
  }, [word?.id, loading]);

  const answer = async (action: StudyAction) => {
    if (!word || busy) return;
    setBusy(true);
    try {
      const result = await wordbookApi.answer(word.id, action, book || undefined);
      setFlash(
        result.status === "mastered"
          ? `已掌握 · +${result.xp_gained} XP`
          : `+${result.xp_gained} XP`
      );
      window.setTimeout(() => setFlash(""), 1600);

      wordbookApi
        .studySummary(book || undefined)
        .then(setSummary)
        .catch(() => undefined);

      // 没背出去的词放回队列的随机位置，之后还会再碰到
      const rest = queue.slice(1);
      if (result.status !== "mastered") {
        const at = Math.floor(Math.random() * (rest.length + 1));
        rest.splice(at, 0, result);
      }
      setQueue(rest);
      setRevealed(false);
      if (rest.length === 0) void refresh(book);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setBusy(false);
    }
  };

  const openGoals = () => {
    if (!summary) return;
    setDraft(summary.target);
    setEditingGoals(true);
  };

  const saveGoals = async () => {
    await wordbookApi.saveDailyTask({ target_words: Math.max(1, draft) });
    setEditingGoals(false);
    await refresh(book);
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

      <div className="card space-y-3 p-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-700">今日背词</span>
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
              <span className="text-slate-600">每天背单词</span>
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  max={300}
                  value={draft}
                  onChange={(e) => setDraft(Number(e.target.value))}
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
        ) : summary ? (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span>
                进度 {summary.done}/{summary.target}
              </span>
              <span>词书剩余 {summary.available}</span>
            </div>
            <ProgressBar
              value={summary.target ? (summary.done / summary.target) * 100 : 100}
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
            <span>本轮剩余 {queue.length} 张</span>
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
          <p className="text-sm text-slate-600">这本词书都背完了 🎉</p>
          <div className="flex flex-wrap justify-center gap-2">
            <button
              onClick={() => refresh(book)}
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
