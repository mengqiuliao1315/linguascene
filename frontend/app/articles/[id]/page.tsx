"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { WordPopover } from "@/components/WordPopover";
import { EmptyState, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import type {
  ArticleAnalysis,
  ArticleDetail,
  SentenceAnalysis,
} from "@/lib/types";

function ArticleReader() {
  const params = useParams<{ id: string }>();
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [analysis, setAnalysis] = useState<ArticleAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [sentence, setSentence] = useState<SentenceAnalysis | null>(null);
  const [selection, setSelection] = useState<{
    word: string;
    x: number;
    y: number;
  } | null>(null);
  const [error, setError] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .article(Number(params.id))
      .then(setArticle)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, [params.id]);

  const handleMouseUp = useCallback(() => {
    const selected = window.getSelection();
    const text = selected?.toString().trim() ?? "";
    if (!text || text.split(/\s+/).length > 30) return;

    const range = selected?.getRangeAt(0);
    if (!range) return;
    const rect = range.getBoundingClientRect();

    if (text.split(/\s+/).length === 1 && /^[A-Za-z][A-Za-z'-]*$/.test(text)) {
      setSelection({ word: text.toLowerCase(), x: rect.left, y: rect.bottom });
      setSentence(null);
    } else {
      setSelection(null);
      api
        .analyzeSentence(text, article?.title ?? "")
        .then(setSentence)
        .catch(() => setSentence(null));
    }
  }, [article?.title]);

  async function handleAnalyze() {
    if (!article) return;
    setAnalyzing(true);
    try {
      setAnalysis(await api.analyzeArticle(article.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "分析失败");
    } finally {
      setAnalyzing(false);
    }
  }

  if (error && !article) return <EmptyState text={error} />;
  if (!article) return <Spinner />;

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <article className="lg:col-span-2">
        <div className="card space-y-4 p-7">
          <div className="flex items-center gap-2">
            <span className="chip-slate">{article.category}</span>
            <span className="chip-brand">{article.level}</span>
            <span className="text-xs text-slate-400">
              {article.read_minutes} min read
            </span>
          </div>

          <h1 className="text-2xl font-semibold text-slate-900">
            {article.title}
          </h1>
          <p className="text-sm text-slate-500">{article.summary}</p>

          <div
            ref={bodyRef}
            onMouseUp={handleMouseUp}
            className="space-y-4 text-[15px] leading-8 text-slate-700"
          >
            {article.content.split(/\n+/).map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
          </div>
        </div>
      </article>

      <aside className="space-y-4">
        <button
          onClick={handleAnalyze}
          disabled={analyzing}
          className="btn-primary w-full"
        >
          {analyzing ? "分析中…" : "AI Analysis"}
        </button>

        {analysis ? (
          <>
            <div className="card space-y-3 p-5">
              <p className="section-title">📌 Key Words</p>
              <div className="space-y-2">
                {analysis.keywords.map((item) => (
                  <div key={item.word}>
                    <p className="text-sm font-medium text-slate-800">
                      {item.word}
                    </p>
                    <p className="text-xs text-slate-500">{item.meaning}</p>
                  </div>
                ))}
                {analysis.keywords.length === 0 ? (
                  <p className="text-xs text-slate-400">暂无</p>
                ) : null}
              </div>
            </div>

            {analysis.phrases.length > 0 ? (
              <div className="card space-y-3 p-5">
                <p className="section-title">固定搭配</p>
                {analysis.phrases.map((item) => (
                  <div key={item.phrase}>
                    <p className="text-sm font-medium text-slate-800">
                      {item.phrase}
                    </p>
                    <p className="text-xs text-slate-500">{item.meaning}</p>
                  </div>
                ))}
              </div>
            ) : null}

            {analysis.grammar_points.length > 0 ? (
              <div className="card space-y-3 p-5">
                <p className="section-title">语法重点</p>
                {analysis.grammar_points.map((item) => (
                  <div key={item.point}>
                    <p className="text-sm font-medium text-slate-800">
                      {item.point}
                    </p>
                    <p className="text-xs text-slate-500">
                      {item.explanation}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}

            {analysis.reading_questions.length > 0 ? (
              <div className="card space-y-2 p-5">
                <p className="section-title">阅读理解</p>
                <ul className="space-y-2 text-xs text-slate-600">
                  {analysis.reading_questions.map((item) => (
                    <li key={item}>· {item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : null}

        {sentence ? (
          <div className="card space-y-3 p-5">
            <p className="section-title">Sentence Analysis</p>
            <p className="text-xs text-slate-500">{sentence.sentence}</p>
            {sentence.main_clause ? (
              <div>
                <p className="text-[11px] text-slate-400">主干</p>
                <p className="text-sm text-slate-800">{sentence.main_clause}</p>
              </div>
            ) : null}
            {sentence.vocabulary.length > 0 ? (
              <div>
                <p className="text-[11px] text-slate-400">重点单词</p>
                {sentence.vocabulary.map((item) => (
                  <p key={item.word} className="text-xs text-slate-700">
                    {item.word} · {item.meaning}
                  </p>
                ))}
              </div>
            ) : null}
            {sentence.collocations.length > 0 ? (
              <div>
                <p className="text-[11px] text-slate-400">固定搭配</p>
                {sentence.collocations.map((item) => (
                  <p key={item.phrase} className="text-xs text-slate-700">
                    {item.phrase} · {item.meaning}
                  </p>
                ))}
              </div>
            ) : null}
            {sentence.grammar_points.length > 0 ? (
              <div>
                <p className="text-[11px] text-slate-400">语法</p>
                {sentence.grammar_points.map((item) => (
                  <p key={item.point} className="text-xs text-slate-700">
                    {item.point} · {item.explanation}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </aside>

      {selection ? (
        <WordPopover
          word={selection.word}
          context={article.title}
          position={{ x: selection.x, y: selection.y }}
          onClose={() => setSelection(null)}
        />
      ) : null}
    </div>
  );
}

export default function ArticleDetailPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ArticleReader />
      </AppShell>
    </RequireAuth>
  );
}
