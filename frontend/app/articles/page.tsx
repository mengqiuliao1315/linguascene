"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import type { ArticleCard } from "@/lib/types";

const CATEGORIES = [
  "全部",
  "Technology",
  "Business",
  "Science",
  "World",
  "Culture",
  "Lifestyle",
];

function ArticleList() {
  const [articles, setArticles] = useState<ArticleCard[]>([]);
  const [category, setCategory] = useState("全部");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    api
      .articles(category === "全部" ? undefined : { category })
      .then(setArticles)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [category]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {CATEGORIES.map((item) => (
            <button
              key={item}
              onClick={() => setCategory(item)}
              className={`rounded-xl px-4 py-2 text-sm transition ${
                category === item
                  ? "bg-brand-600 text-white"
                  : "border border-slate-200 bg-white text-slate-600 hover:border-brand-300"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
        <Link href="/content" className="btn-ghost !py-2 text-sm">
          我的文章
        </Link>
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState text={error} />
      ) : articles.length === 0 ? (
        <EmptyState text="暂无文章" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {articles.map((article) => (
            <Link
              key={article.id}
              href={`/articles/${article.id}`}
              className="card group space-y-3 p-5 transition hover:border-brand-300 hover:shadow-lg"
            >
              <div className="flex items-center justify-between">
                <span className="chip-slate">{article.category}</span>
                <span className="chip-brand">{article.level}</span>
              </div>
              <p className="font-semibold text-slate-900 group-hover:text-brand-700">
                {article.title}
              </p>
              <p className="line-clamp-2 text-sm text-slate-500">
                {article.summary}
              </p>
              <div className="flex items-center gap-3 text-xs text-slate-400">
                <span>{article.read_minutes} min read</span>
                <span>·</span>
                <span>{article.word_count} words</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ArticlesPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ArticleList />
      </AppShell>
    </RequireAuth>
  );
}
