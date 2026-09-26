"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, ProgressBar, Spinner, Stars } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import type { Report } from "@/lib/types";

const SCORE_LABELS: { key: keyof Report["scores"]; label: string }[] = [
  { key: "grammar", label: "Grammar" },
  { key: "vocabulary", label: "Vocabulary" },
  { key: "naturalness", label: "Naturalness" },
  { key: "communication", label: "Communication" },
];

function ReportView() {
  const params = useParams<{ id: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .finishConversation(Number(params.id))
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, [params.id]);

  if (error) return <EmptyState text={error} />;
  if (!report) return <Spinner />;

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="card space-y-5 p-7 text-center">
        <div>
          <p className="text-3xl">🎉</p>
          <h1 className="mt-2 text-xl font-semibold text-slate-900">
            Scenario Complete
          </h1>
          <p className="text-sm text-slate-400">{report.scenario_title}</p>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>任务完成度</span>
            <span>{report.task_progress}%</span>
          </div>
          <ProgressBar value={report.task_progress} />
        </div>

        <p className="text-sm text-slate-600">{report.summary}</p>
      </div>

      <div className="card space-y-4 p-6">
        <p className="section-title">英语表现</p>
        <div className="space-y-3">
          {SCORE_LABELS.map((item) => (
            <div key={item.key} className="flex items-center justify-between">
              <span className="text-sm text-slate-600">{item.label}</span>
              <Stars value={report.scores[item.key]} />
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="card space-y-3 p-5">
          <p className="section-title">本次学到</p>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-brand-600">
              {report.new_words.length}
            </span>
            <span className="text-xs text-slate-500">个新单词</span>
          </div>
          {report.new_words.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {report.new_words.map((word) => (
                <span key={word} className="chip-slate">
                  {word}
                </span>
              ))}
            </div>
          ) : null}
          <p className="text-xs text-slate-400">
            记录 {report.corrections_count} 处表达优化
          </p>
        </div>

        <div className="card space-y-3 p-5">
          <p className="section-title">重点表达</p>
          <div className="space-y-2">
            {report.key_phrases.map((phrase) => (
              <p key={phrase} className="text-sm font-medium text-slate-800">
                {phrase}
              </p>
            ))}
          </div>
        </div>
      </div>

      <div className="card flex items-center justify-between p-5">
        <span className="chip-brand">XP +{report.xp_earned}</span>
        <span className="chip-brand">🔥 连续打卡 {report.streak} 天</span>
      </div>

      <div className="flex gap-3">
        <Link href="/dashboard" className="btn-ghost flex-1">
          返回首页
        </Link>
        <Link href="/scenarios" className="btn-primary flex-1">
          继续练习
        </Link>
      </div>
    </div>
  );
}

export default function ResultPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ReportView />
      </AppShell>
    </RequireAuth>
  );
}
