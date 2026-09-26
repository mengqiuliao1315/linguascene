"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import type { UserContent } from "@/lib/types";

function ContentLibrary() {
  const [items, setItems] = useState<UserContent[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [mode, setMode] = useState<"file" | "text">("file");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  function reload() {
    api
      .contents()
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);

  async function handleUpload(event: React.FormEvent) {
    event.preventDefault();
    const file = mode === "file" ? fileRef.current?.files?.[0] ?? null : null;
    if (mode === "file" && !file) {
      setError("请选择文件，或切换到「粘贴文本」");
      return;
    }
    if (mode === "text" && !text.trim()) {
      setError("请输入文本内容");
      return;
    }

    setUploading(true);
    setError("");
    try {
      await api.uploadContent(file, titleRef.current?.value ?? "", text);
      if (fileRef.current) fileRef.current.value = "";
      if (titleRef.current) titleRef.current.value = "";
      setText("");
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <form onSubmit={handleUpload} className="card space-y-4 p-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">我的文章</h1>
          <p className="text-xs text-slate-400">
            {mode === "file"
              ? "支持 TXT / MD / PDF / DOCX / SRT，上传后自动生成学习材料"
              : "直接粘贴或输入正文，保存后自动生成学习材料"}
          </p>
        </div>

        <div className="flex gap-1 rounded-xl bg-slate-100 p-1 text-xs">
          {(
            [
              ["file", "上传文件"],
              ["text", "粘贴文本"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => {
                setMode(key);
                setError("");
              }}
              className={`flex-1 rounded-lg px-3 py-1.5 transition ${
                mode === key
                  ? "bg-white font-medium text-brand-700 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <input
          ref={titleRef}
          placeholder="标题（可选）"
          className="input"
        />

        {mode === "file" ? (
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.pdf,.docx,.srt,.vtt,.json"
            className="w-full rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-xs file:text-white"
          />
        ) : (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            placeholder="在此粘贴或输入英文材料，支持多段落…"
            className="input resize-y font-[inherit] leading-relaxed"
          />
        )}

        {error ? (
          <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">
            {error}
          </p>
        ) : null}

        <button type="submit" disabled={uploading} className="btn-primary w-full">
          {uploading ? "上传中…" : "上传"}
        </button>
      </form>

      {loading ? (
        <Spinner />
      ) : items.length === 0 ? (
        <EmptyState text="还没有上传内容" />
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <Link
              key={item.id}
              href={`/content/${item.id}`}
              className="card flex items-center gap-4 p-4 transition hover:border-brand-300"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-xs font-medium uppercase text-slate-500">
                {item.content_type}
              </span>
              <div className="flex-1">
                <p className="text-sm font-medium text-slate-900">
                  {item.title}
                </p>
                <p className="line-clamp-1 text-xs text-slate-400">
                  {item.preview}
                </p>
              </div>
              <span className="chip-slate">{item.word_count} words</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ContentPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ContentLibrary />
      </AppShell>
    </RequireAuth>
  );
}
