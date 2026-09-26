"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, Spinner } from "@/components/ui";
import { RequireAuth } from "@/lib/auth";
import { readingApi, type Material, type MaterialSource } from "@/lib/reading";

const TABS: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "platform", label: "平台材料" },
  { key: "mine", label: "我的上传" },
  { key: "shared", label: "他人分享" },
];

const SOURCE_LABEL: Record<MaterialSource, string> = {
  platform: "平台",
  mine: "我的",
  shared: "分享",
};

function Library() {
  const router = useRouter();
  const [tab, setTab] = useState("all");
  const [items, setItems] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [mode, setMode] = useState<"file" | "text">("file");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async (source: string) => {
    setLoading(true);
    try {
      setItems(await readingApi.materials(source));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(tab);
  }, [tab, load]);

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
      const created = await readingApi.upload(
        file,
        titleRef.current?.value ?? "",
        text
      );
      if (fileRef.current) fileRef.current.value = "";
      if (titleRef.current) titleRef.current.value = "";
      setText("");

      router.push(`/reading/content/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function handlePublish(item: Material) {
    try {
      const updated = await readingApi.publish(item.id, !item.is_public);
      setItems((prev) =>
        prev.map((m) => (m.id === item.id ? { ...m, is_public: updated.is_public } : m))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleDelete(item: Material) {
    if (!window.confirm(`删除《${item.title}》？相关笔记也会一并删除。`)) return;
    try {
      await readingApi.remove(item.id);
      setItems((prev) => prev.filter((m) => m.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <form onSubmit={handleUpload} className="card space-y-3 p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="section-title">上传阅读材料</p>
          <span className="text-[11px] text-slate-400">
            {mode === "file"
              ? "支持 TXT / MD / PDF / DOCX / SRT"
              : "直接粘贴或输入正文"}
          </span>
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

        <input ref={titleRef} placeholder="标题（可选）" className="input" />

        {mode === "file" ? (
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.pdf,.docx,.srt,.vtt,.json"
            className="w-full rounded-xl border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-xs file:text-white"
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

      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className={`rounded-xl px-4 py-2 text-sm transition ${
              tab === item.key
                ? "bg-brand-600 text-white"
                : "border border-slate-200 bg-white text-slate-600 hover:border-brand-300"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {loading ? (
        <Spinner />
      ) : items.length === 0 ? (
        <EmptyState text="这里还没有材料" />
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const kind = item.source === "platform" ? "article" : "content";
            return (
              <div key={`${kind}-${item.id}`} className="card p-4">
                <div className="flex items-start gap-4">
                  <Link
                    href={`/reading/${kind}/${item.id}`}
                    className="min-w-0 flex-1"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="chip-slate">{SOURCE_LABEL[item.source]}</span>
                      <span className="chip-brand">{item.level}</span>
                      {item.is_public && item.source === "mine" ? (
                        <span className="chip-slate">已公布</span>
                      ) : null}
                    </div>
                    <p className="mt-1.5 font-medium text-slate-900 hover:text-brand-700">
                      {item.title}
                    </p>
                    <p className="text-xs text-slate-400">
                      {item.author_name} · {item.word_count} words · {item.read_minutes} min
                      {item.note_count > 0 ? ` · ${item.note_count} 条笔记` : ""}
                    </p>
                  </Link>

                  {item.is_mine ? (
                    <div className="flex shrink-0 gap-2">
                      <button
                        onClick={() => handlePublish(item)}
                        className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-brand-300"
                      >
                        {item.is_public ? "取消公布" : "公布"}
                      </button>
                      <button
                        onClick={() => handleDelete(item)}
                        className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-rose-500 transition hover:border-rose-300"
                      >
                        删除
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ReadingPage() {
  return (
    <RequireAuth>
      <AppShell>
        <Library />
      </AppShell>
    </RequireAuth>
  );
}
