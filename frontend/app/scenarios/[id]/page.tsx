"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, Modal, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { staticOpeningUrl } from "@/lib/openingAudio";
import { prefetchSpeech, warmSpeechBackend } from "@/lib/speech";
import type { ConversationSummary, Scenario } from "@/lib/types";

function ScenarioDetail() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [scenario, setScenario] = useState<Scenario | null>(null);

  const [existing, setExisting] = useState<ConversationSummary | null>(null);
  const [choiceOpen, setChoiceOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .scenario(Number(params.id))
      .then(setScenario)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, [params.id]);

  useEffect(() => {
    api
      .conversations()
      .then((list) =>
        setExisting(
          list.find((item) => item.scenario_id === Number(params.id)) ?? null
        )
      )
      .catch(() => setExisting(null));
  }, [params.id]);

  useEffect(() => {
    if (!scenario?.opening_line) return;
    warmSpeechBackend();
    prefetchSpeech(scenario.opening_line, {
      url: staticOpeningUrl(scenario.slug, scenario.opening_line),
      urgent: true,
    });
  }, [scenario?.opening_line, scenario?.slug]);

  async function handleStart() {
    if (!scenario) return;

    if (existing) {
      setChoiceOpen(true);
      return;
    }
    await begin(false);
  }

  async function begin(restart: boolean) {
    if (!scenario) return;
    setChoiceOpen(false);
    setStarting(true);
    setError("");
    try {
      const conversation = await api.startScenario(scenario.id, restart);
      router.push(`/chat/${conversation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法开始对话");
      setStarting(false);
    }
  }

  if (error) return <EmptyState text={error} />;
  if (!scenario) return <Spinner />;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="card space-y-5 p-7">
        <div className="flex items-start gap-5">
          <span className="text-5xl">{scenario.icon}</span>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold text-slate-900">
              {scenario.title}
            </h1>
            <p className="text-sm text-slate-400">{scenario.title_zh}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="chip-brand">{scenario.level}</span>
              <span className="chip-slate">
                {scenario.estimated_minutes} min
              </span>
              <span className="chip-slate">AI: {scenario.ai_role}</span>
            </div>
          </div>
        </div>

        <p className="text-sm leading-relaxed text-slate-600">
          {scenario.goal}
        </p>

        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-xs font-medium text-slate-500">Tasks</p>
          <ol className="mt-2 space-y-2">
            {scenario.tasks.map((task, index) => (
              <li key={task.id} className="flex items-center gap-3 text-sm">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white text-[11px] font-medium text-slate-500">
                  {index + 1}
                </span>
                <span className="text-slate-700">{task.description}</span>
              </li>
            ))}
          </ol>
        </div>

        {scenario.key_phrases.length > 0 ? (
          <div>
            <p className="text-xs font-medium text-slate-500">Key Expressions</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {scenario.key_phrases.map((phrase) => (
                <span key={phrase} className="chip-brand">
                  {phrase}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        <button
          onClick={handleStart}
          disabled={starting}
          className="btn-primary w-full"
        >
          {starting ? "准备中…" : "Start Conversation"}
        </button>
      </div>

      <Modal
        open={choiceOpen}
        onClose={() => setChoiceOpen(false)}
        title="这个场景你之前聊过"
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
                existing && router.push(`/chat/${existing.id}`)
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
          重新开始会用这次的新对话覆盖之前的记录，历史里同一个场景只保留一条。
        </p>
      </Modal>
    </div>
  );
}

export default function ScenarioDetailPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ScenarioDetail />
      </AppShell>
    </RequireAuth>
  );
}
