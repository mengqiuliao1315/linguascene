"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, Modal, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import type { ConversationSummary } from "@/lib/types";

function parseServerTime(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`);
}

function formatLastSeen(value: string): string {
  const at = parseServerTime(value);
  if (Number.isNaN(at.getTime())) return "";
  const time = at.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

  const now = new Date();
  if (sameDay(at, now)) return `今天 ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (sameDay(at, yesterday)) return `昨天 ${time}`;
  if (at.getFullYear() === now.getFullYear()) {
    return `${at.getMonth() + 1}月${at.getDate()}日 ${time}`;
  }
  return `${at.getFullYear()}年${at.getMonth() + 1}月${at.getDate()}日`;
}

function FreeTalkHome() {
  const router = useRouter();
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  const [choiceOpen, setChoiceOpen] = useState(false);

  const [pendingDelete, setPendingDelete] =
    useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    api
      .conversations()
      .then(setHistory)
      .catch(() => setHistory([]))
      .finally(() => setLoading(false));
  }, []);

  const existingFreeTalk =
    history.find((item) => item.mode === "free_talk") ?? null;

  async function handleStart() {
    if (existingFreeTalk) {
      setChoiceOpen(true);
      return;
    }
    await begin(false);
  }

  async function begin(restart: boolean) {
    setChoiceOpen(false);
    setStarting(true);
    setError("");
    try {
      const conversation = await api.startFreeTalk(restart);
      router.push(`/chat/${conversation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法开始对话");
      setStarting(false);
    }
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setDeleting(true);
    setError("");
    try {
      await api.deleteConversation(id);
      setHistory((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="card space-y-4 p-7">
        <div className="flex items-center gap-4">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-2xl">
            🤖
          </span>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">AI Tutor</h1>
            <p className="text-sm text-slate-400">
              自由对话，AI 会按你的等级调整语言并纠正表达
            </p>
          </div>
        </div>

        {error ? (
          <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">
            {error}
          </p>
        ) : null}

        <button
          onClick={handleStart}
          disabled={starting}
          className="btn-primary w-full"
        >
          {starting ? "准备中…" : "开始自由对话"}
        </button>
      </div>

      <section className="space-y-3">
        <p className="section-title">历史对话</p>
        {loading ? (
          <Spinner />
        ) : history.length === 0 ? (
          <EmptyState text="还没有对话记录" />
        ) : (
          <div className="space-y-2">
            {history.map((item) => (
              <div
                key={item.id}
                className="card flex items-center gap-2 p-4 transition hover:border-brand-300"
              >
                <button
                  onClick={() => router.push(`/chat/${item.id}`)}
                  className="flex min-w-0 flex-1 items-center gap-4 text-left"
                >
                  <span className="shrink-0 text-xl">{item.scenario_icon}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-900">
                      {item.scenario_title}
                    </p>
                    {item.mode === "free_talk" && item.preview ? (
                      <p className="truncate text-xs text-slate-500">
                        {item.preview}
                      </p>
                    ) : null}
                    <p className="text-xs text-slate-400">
                      最后对话 · {formatLastSeen(item.last_message_at)}
                    </p>
                  </div>
                  {item.is_completed ? (
                    <span className="chip-slate shrink-0">已完成</span>
                  ) : null}
                  {item.xp_earned > 0 ? (
                    <span className="chip-brand shrink-0">
                      +{item.xp_earned} XP
                    </span>
                  ) : null}
                </button>
                <button
                  type="button"
                  onClick={() => setPendingDelete(item)}
                  aria-label={`删除「${item.scenario_title}」这条对话记录`}
                  title="删除这条对话记录"
                  className="shrink-0 rounded-lg px-2 py-1.5 text-sm text-slate-300 transition hover:bg-rose-50 hover:text-rose-500"
                >
                  🗑
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <Modal
        open={choiceOpen}
        onClose={() => setChoiceOpen(false)}
        title="你已经聊过一次自由对话"
        footer={
          <>
            <button
              type="button"
              onClick={() => begin(true)}
              className="btn-ghost flex-1"
            >
              重新开始
            </button>
            <button
              type="button"
              onClick={() =>
                existingFreeTalk && router.push(`/chat/${existingFreeTalk.id}`)
              }
              className="btn-primary flex-1"
            >
              继续之前的会话
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-slate-600">
          接着上次继续，还是清掉旧记录重新开始？
        </p>
        <p className="text-xs leading-relaxed text-slate-400">
          重新开始会用这次的新对话覆盖之前的记录，历史里自由对话只保留一条。
        </p>
      </Modal>

      <Modal
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title="删除这次对话？"
        footer={
          <>
            <button
              type="button"
              onClick={() => setPendingDelete(null)}
              className="btn-ghost flex-1"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="btn-primary flex-1"
            >
              {deleting ? "删除中…" : "删除"}
            </button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-slate-600">
          {pendingDelete
            ? `「${pendingDelete.scenario_title}」的对话内容与纠错记录会一起删除。`
            : ""}
        </p>
        <p className="text-xs leading-relaxed text-slate-400">删除后无法恢复。</p>
      </Modal>
    </div>
  );
}

export default function ChatHomePage() {
  return (
    <RequireAuth>
      <AppShell>
        <FreeTalkHome />
      </AppShell>
    </RequireAuth>
  );
}
