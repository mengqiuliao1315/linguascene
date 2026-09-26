"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { playWord } from "@/components/WordFlashcard";
import { EmptyState, Spinner } from "@/components/ui";
import { RequireAuth } from "@/lib/auth";
import {
  wordbookApi,
  type QuizAnswerResult,
  type QuizSession,
  type WordCard,
} from "@/lib/wordbook";

/** 开始测验的设置面板：有未完成的测验时先问「继续」还是「重新抽题」。 */
function QuizPanel({
  total,
  session,
  onStart,
  onResume,
  onDiscard,
  onClose,
}: {
  total: number;
  session: QuizSession | null;
  onStart: (count: number) => void;
  onResume: () => void;
  onDiscard: () => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(String(Math.min(10, Math.max(1, total))));
  const parsed = Number.parseInt(value, 10);
  const valid = Number.isFinite(parsed) && parsed >= 1 && parsed <= total;

  const unfinished = session?.active ? session : null;

  return (
    <div className="card space-y-3 p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-900">随机测验</p>
          <p className="mt-0.5 text-xs text-slate-500">
            从我的单词本随机抽词，生成中文释义选择题。共 {total} 个单词。
          </p>
        </div>
        <button
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          ✕
        </button>
      </div>

      {unfinished ? (
        <div className="space-y-3 rounded-xl bg-brand-50/60 p-4">
          <p className="text-sm text-slate-700">
            上次的测验还没做完，还剩 {unfinished.remaining} / {unfinished.total} 个单词。
          </p>
          <div className="flex flex-wrap gap-2">
            <button onClick={onResume} className="btn-primary px-3 py-2 text-sm">
              继续上次
            </button>
            <button
              onClick={onDiscard}
              className="btn-ghost px-3 py-2 text-sm text-slate-500"
            >
              放弃并重新抽题
            </button>
          </div>
        </div>
      ) : null}

      <div className="flex items-center gap-3">
        <label className="text-xs text-slate-500">测试单词数</label>
        <input
          type="number"
          min={1}
          max={total}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          className="w-24 rounded-xl border border-slate-200 px-3 py-1.5 text-sm outline-none focus:border-brand-400"
        />
        <span className="text-xs text-slate-400">最多 {total} 个</span>
      </div>
      {!valid ? (
        <p className="text-xs text-rose-500">
          请输入 1 到 {total} 之间的数量
        </p>
      ) : null}

      <button
        onClick={() => onStart(parsed)}
        disabled={!valid}
        className="btn-primary w-full !py-2 text-sm disabled:opacity-40"
      >
        {unfinished ? "重新抽题开始" : "开始测验"}
      </button>
    </div>
  );
}

/** 一道选择题：单词 + 4 个中文释义选项。选错的标红、正确的标绿，之后这题还会重新出现。 */
function QuizQuestionCard({
  session,
  chosen,
  result,
  onAnswer,
}: {
  session: QuizSession;
  /** 用户在这道题选了哪一项，null 表示还没作答。 */
  chosen: string | null;
  /** 接口返回的作答结果，与 chosen 一起决定配色。 */
  result: QuizAnswerResult | null;
  onAnswer: (choice: string) => void;
}) {
  const question = session.question;
  if (!question) return null;

  const word = question.word;
  const locked = chosen !== null;
  const correct = result?.correct ?? null;
  const answerText = result?.answer ?? "";

  return (
    <div className="card space-y-4 p-6">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>
          还剩 {session.remaining} / {session.total} 题
        </span>
        <span>答对 {session.correct_count} · 答错 {session.wrong_count}</span>
      </div>

      <div className="text-center">
        <p className="text-3xl font-semibold text-slate-900">{word.word}</p>
        <div className="mt-2 flex items-center justify-center gap-2 text-xs text-slate-400">
          <button
            onClick={() => playWord(word.word, "us")}
            className="hover:text-brand-600"
            title="美式发音"
          >
            🔊 {word.phonetic_us || "美"}
          </button>
          <button
            onClick={() => playWord(word.word, "uk")}
            className="hover:text-brand-600"
            title="英式发音"
          >
            🔊 {word.phonetic_uk || "英"}
          </button>
        </div>
      </div>

      <div className="space-y-2 border-t border-slate-100 pt-4">
        <p className="text-xs text-slate-400">选择正确的中文释义</p>
        {question.options.map((option, index) => {
          const isChosen = chosen === option;
          // 答错时选中项标红、正确答案同时标绿；答对时只有选中项标绿。
          const isWrongPick = locked && isChosen && !correct;
          const isRightAnswer = locked && (correct ? isChosen : option === answerText);
          let style =
            "border-slate-200 bg-white text-slate-700 hover:border-brand-300 hover:bg-brand-50/50";
          if (isWrongPick) {
            style = "border-rose-300 bg-rose-50 text-rose-700";
          } else if (isRightAnswer) {
            style = "border-emerald-300 bg-emerald-50 text-emerald-700";
          } else if (locked) {
            style = "border-slate-100 bg-white text-slate-400";
          }
          return (
            <button
              key={index}
              onClick={() => !locked && onAnswer(option)}
              disabled={locked}
              className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition ${style}`}
            >
              <span className="shrink-0 text-xs font-semibold text-slate-400">
                {"ABCD"[index] ?? index + 1}
              </span>
              <span className="min-w-0 flex-1">{option}</span>
              {isRightAnswer ? <span>✓</span> : null}
              {isWrongPick ? <span>✕</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function QuizRunner({
  initial,
  onExit,
}: {
  initial: QuizSession;
  onExit: () => void;
}) {
  const [session, setSession] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<QuizAnswerResult | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  // 换到下一题时清掉上一题的作答反馈
  useEffect(() => {
    setChosen(null);
    setOutcome(null);
  }, [session.question?.word.id]);

  async function handleAnswer(choice: string) {
    if (busy || !session.question) return;
    const wordId = session.question.word.id;
    setBusy(true);
    // 先记住选了哪项，接口回来后连同 result 一起决定配色
    setChosen(choice);
    try {
      const res = await wordbookApi.quizAnswer(wordId, choice);
      setOutcome(res);
      setFlash(res.correct ? "答对了" : `正确答案：${res.answer}`);
      // 留一点时间让用户看到对错，再切到下一题
      timer.current = setTimeout(
        () => {
          setSession(res.session);
          // 答错的词被排到队尾，队列只剩它时下一题还是同一个单词 id，
          // effect 不会触发，必须在这里显式清掉本题的作答反馈。
          setChosen(null);
          setOutcome(null);
          setFlash("");
          setBusy(false);
        },
        res.correct ? 700 : 1600
      );
    } catch {
      setFlash("提交失败，请重试");
      // 提交失败要解锁选项，否则这题点不动了
      setChosen(null);
      setOutcome(null);
      setBusy(false);
    }
  }

  if (session.finished || !session.question) {
    return (
      <div className="card space-y-3 p-6 text-center">
        <p className="text-lg font-semibold text-slate-900">测验完成 🎉</p>
        <p className="text-sm text-slate-500">
          共 {session.total} 个单词，全部答对。答错 {session.wrong_count} 次。
        </p>
        <button onClick={onExit} className="btn-primary px-4 py-2 text-sm">
          返回单词本
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button
          onClick={onExit}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          ← 退出测验
        </button>
        <span className="text-xs text-brand-600">{flash}</span>
      </div>
      <QuizQuestionCard
        session={session}
        chosen={chosen}
        result={outcome}
        onAnswer={handleAnswer}
      />
    </div>
  );
}

function VocabularyBook() {
  const [words, setWords] = useState<WordCard[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);
  const [quizSetup, setQuizSetup] = useState(false);
  const [session, setSession] = useState<QuizSession | null>(null);
  const [running, setRunning] = useState(false);
  const [quizError, setQuizError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    wordbookApi
      .myWords(0, 100)
      .then((page) => {
        setWords(page.items);
        setTotal(page.total);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const refreshQuizState = useCallback(() => {
    wordbookApi
      .quizState()
      .then((state) => setSession(state.active ? state : null))
      .catch(() => undefined);
  }, []);

  useEffect(refreshQuizState, [refreshQuizState]);

  async function handleDelete(id: number) {
    setPendingDelete(null);
    await wordbookApi.remove(id);
    load();
  }

  async function startQuiz(count: number) {
    setQuizError("");
    try {
      const result = await wordbookApi.quizStart(count, "fresh");
      if (!result.question) {
        setQuizError("单词本还是空的，先去词书里加几个单词吧");
        return;
      }
      setSession(result);
      setQuizSetup(false);
      setRunning(true);
    } catch (err) {
      setQuizError(err instanceof Error ? err.message : "生成测验失败");
    }
  }

  function resumeQuiz() {
    if (!session) return;
    setQuizSetup(false);
    setRunning(true);
  }

  async function discardQuiz() {
    await wordbookApi.quizReset();
    setSession(null);
  }

  const canQuiz = total > 0;

  if (running && session) {
    return (
      <QuizRunner
        initial={session}
        onExit={() => {
          setRunning(false);
          setSession(null);
          refreshQuizState();
        }}
      />
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">My Vocabulary</h1>
        <Link href="/wordbook" className="btn-ghost !py-1.5 text-sm">
          词书
        </Link>
      </div>

      {quizSetup ? (
        <QuizPanel
          total={total}
          session={session}
          onStart={startQuiz}
          onResume={resumeQuiz}
          onDiscard={discardQuiz}
          onClose={() => setQuizSetup(false)}
        />
      ) : (
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-400">共 {total} 个单词</p>
          <button
            onClick={() => setQuizSetup(true)}
            disabled={!canQuiz}
            className="btn-primary !py-1.5 text-sm disabled:opacity-40"
          >
            随机测验
          </button>
        </div>
      )}

      {session?.active && !quizSetup ? (
        <div className="card flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="text-sm text-slate-600">
            上次的测验还没做完，还剩 {session.remaining} / {session.total} 个单词。
          </p>
          <button onClick={resumeQuiz} className="btn-primary !py-1.5 text-sm">
            继续测验
          </button>
        </div>
      ) : null}

      {quizError ? <p className="text-xs text-rose-500">{quizError}</p> : null}

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState text={error} />
      ) : words.length === 0 ? (
        <EmptyState text="单词本还是空的，去词书或精读里加几个单词吧" />
      ) : (
        <div className="space-y-3">
          {words.map((word) => (
            <div key={word.id} className="card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-base font-semibold text-slate-900">
                      {word.word}
                    </p>
                    {word.phonetic_us || word.phonetic_uk ? (
                      <span className="text-xs text-slate-400">
                        {word.phonetic_us || word.phonetic_uk}
                      </span>
                    ) : null}
                    <button
                      onClick={() => playWord(word.word, "us")}
                      className="text-slate-300 transition hover:text-brand-600"
                      aria-label="朗读"
                    >
                      🔊
                    </button>
                    {word.level ? (
                      <span className="chip-slate">{word.level}</span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm text-slate-600">
                    {word.meaning_zh || word.meaning || "暂无释义"}
                  </p>
                  {word.example ? (
                    <p className="mt-1 text-xs text-slate-400">{word.example}</p>
                  ) : null}
                </div>

                {pendingDelete === word.id ? (
                  <div className="flex shrink-0 items-center gap-2 text-xs">
                    <button
                      onClick={() => handleDelete(word.id)}
                      className="rounded-lg bg-rose-500 px-2.5 py-1 text-white"
                    >
                      确认删除
                    </button>
                    <button
                      onClick={() => setPendingDelete(null)}
                      className="text-slate-400 hover:text-slate-600"
                    >
                      取消
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setPendingDelete(word.id)}
                    className="shrink-0 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-500 transition hover:border-rose-200 hover:text-rose-500"
                  >
                    删除
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function VocabularyPage() {
  return (
    <RequireAuth>
      <AppShell>
        <VocabularyBook />
      </AppShell>
    </RequireAuth>
  );
}
