"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import type { ArticleAnalysis, UserContent } from "@/lib/types";

function ContentDetail() {
  const params = useParams<{ id: string }>();
  const [content, setContent] = useState<(UserContent & { content: string }) | null>(
    null
  );
  const [analysis, setAnalysis] = useState<ArticleAnalysis | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .content(Number(params.id))
      .then(setContent)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, [params.id]);

  async function handleGenerate() {
    if (!content) return;
    setGenerating(true);
    try {
      setAnalysis(await api.generateMaterial(content.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  }

  if (error && !content) return <EmptyState text={error} />;
  if (!content) return <Spinner />;

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <div className="card space-y-4 p-7">
          <div className="flex items-center gap-2">
            <span className="chip-slate uppercase">{content.content_type}</span>
            <span className="text-xs text-slate-400">
              {content.word_count} words
            </span>
          </div>
          <h1 className="text-xl font-semibold text-slate-900">{content.title}</h1>
          <div className="whitespace-pre-wrap text-[15px] leading-8 text-slate-700">
            {content.content}
          </div>
        </div>
      </div>

      <aside className="space-y-4">
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="btn-primary w-full"
        >
          {generating ? "生成中…" : "生成学习材料"}
        </button>

        {analysis ? (
          <>
            <div className="card space-y-2 p-5">
              <p className="section-title">难度</p>
              <span className="chip-brand">{analysis.level}</span>
              <p className="mt-2 text-xs text-slate-500">{analysis.summary}</p>
            </div>

            <div className="card space-y-3 p-5">
              <p className="section-title">核心词汇</p>
              {analysis.keywords.length === 0 ? (
                <p className="text-xs text-slate-400">暂无</p>
              ) : (
                analysis.keywords.map((item) => (
                  <div key={item.word}>
                    <p className="text-sm font-medium text-slate-800">
                      {item.word}
                    </p>
                    <p className="text-xs text-slate-500">{item.meaning}</p>
                  </div>
                ))
              )}
            </div>

            {analysis.reading_questions.length > 0 ? (
              <div className="card space-y-2 p-5">
                <p className="section-title">阅读问题</p>
                <ul className="space-y-2 text-xs text-slate-600">
                  {analysis.reading_questions.map((item) => (
                    <li key={item}>· {item}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {analysis.speaking_questions.length > 0 ? (
              <div className="card space-y-2 p-5">
                <p className="section-title">口语任务</p>
                <ul className="space-y-2 text-xs text-slate-600">
                  {analysis.speaking_questions.map((item) => (
                    <li key={item}>· {item}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {analysis.writing_task ? (
              <div className="card space-y-2 p-5">
                <p className="section-title">写作任务</p>
                <p className="text-xs text-slate-600">{analysis.writing_task}</p>
              </div>
            ) : null}
          </>
        ) : null}
      </aside>
    </div>
  );
}

export default function ContentDetailPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ContentDetail />
      </AppShell>
    </RequireAuth>
  );
}
