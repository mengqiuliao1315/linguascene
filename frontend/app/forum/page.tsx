/**
 * 论坛：经验帖列表 + 发帖。
 */

"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Markdown } from "@/components/Markdown";
import { Avatar, EmptyState, Spinner } from "@/components/ui";
import { RequireAuth } from "@/lib/auth";
import {
  socialApi,
  type ForumPost,
  type ForumSort,
  type PopularTag,
} from "@/lib/social";

const PAGE_SIZE = 10;

const SORTS: { key: ForumSort; label: string }[] = [
  { key: "new", label: "最新" },
  { key: "hot", label: "最热" },
  { key: "active", label: "讨论最多" },
];

function Forum() {
  const [posts, setPosts] = useState<ForumPost[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ForumSort>("new");
  const [tag, setTag] = useState("");
  const [popularTags, setPopularTags] = useState<PopularTag[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const [composing, setComposing] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [busy, setBusy] = useState(false);

  // 列表卡片只拿得到摘要，展开时才按需拉全文
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [fullContent, setFullContent] = useState<Record<number, string>>({});
  const [expandingId, setExpandingId] = useState<number | null>(null);

  const load = useCallback(
    async (offset: number) => {
      if (offset === 0) setLoading(true);
      else setLoadingMore(true);
      setError("");
      try {
        const page = await socialApi.posts({
          q: search || undefined,
          tag: tag || undefined,
          sort,
          offset,
          limit: PAGE_SIZE,
        });
        setPosts((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
        setHasMore(page.has_more);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [search, sort, tag],
  );

  const loadTags = useCallback(() => {
    socialApi
      .popularTags()
      .then(setPopularTags)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    void load(0);
  }, [load]);

  useEffect(() => {
    loadTags();
  }, [loadTags]);

  const contentRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkLabel, setLinkLabel] = useState("");

  /** 在光标处插入 Markdown 片段，插完把光标移到末尾，方便接着写。 */
  function insertAtCursor(snippet: string) {
    const el = contentRef.current;
    if (!el) {
      setContent((prev) => prev + snippet);
      return;
    }
    const start = el.selectionStart ?? content.length;
    const end = el.selectionEnd ?? content.length;
    setContent(content.slice(0, start) + snippet + content.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + snippet.length;
      el.setSelectionRange(pos, pos);
    });
  }

  async function handlePickImage(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // 清空后才能再次选中同一张图
    if (!file) return;

    setUploading(true);
    setError("");
    try {
      const { url } = await socialApi.uploadImage(file);
      const alt = file.name.replace(/\.[^.]+$/, "") || "图片";
      insertAtCursor(`\n![${alt}](${url})\n`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "图片上传失败");
    } finally {
      setUploading(false);
    }
  }

  function handleInsertLink() {
    const raw = linkUrl.trim();
    if (!raw) return;
    // 直接粘 example.com 的人不少，补上协议，否则渲染时会被当成非法链接丢掉
    const url = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
    insertAtCursor(`[${linkLabel.trim() || url}](${url})`);
    setLinkOpen(false);
    setLinkUrl("");
    setLinkLabel("");
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !content.trim()) return;

    setBusy(true);
    setError("");
    try {
      await socialApi.createPost({
        title: title.trim(),
        content,
        tags: tagsInput
          .split(/[,，\s]+/)
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setTitle("");
      setContent("");
      setTagsInput("");
      setComposing(false);
      setSort("new");
      setTag("");
      setSearch("");
      setKeyword("");
      await load(0);
      loadTags();
    } catch (err) {
      setError(err instanceof Error ? err.message : "发布失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleLike(post: ForumPost) {
    try {
      const result = await socialApi.likePost(post.id);
      setPosts((prev) =>
        prev.map((item) =>
          item.id === post.id
            ? { ...item, liked: result.liked, like_count: result.like_count }
            : item,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleDelete(post: ForumPost) {
    if (!window.confirm(`删除《${post.title}》？`)) return;
    try {
      await socialApi.deletePost(post.id);
      setPosts((prev) => prev.filter((item) => item.id !== post.id));
      setTotal((prev) => Math.max(0, prev - 1));
      if (expandedId === post.id) setExpandedId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  // 卡片主体可点开：标题仍跳详情，按钮各自处理，其余区域切换展开
  function handleCardClick(event: React.MouseEvent, post: ForumPost) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button")) return;
    if (!post.truncated && expandedId !== post.id) return;
    void toggleExpand(post);
  }

  async function toggleExpand(post: ForumPost) {
    if (expandedId === post.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(post.id);
    if (fullContent[post.id] !== undefined) return;

    setExpandingId(post.id);
    try {
      // count_view=false：就地展开不算一次阅读
      const full = await socialApi.post(post.id, false);
      setFullContent((prev) => ({ ...prev, [post.id]: full.content ?? "" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载全文失败");
      setExpandedId(null);
    } finally {
      setExpandingId(null);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-900">
          学习经验
          {total > 0 ? (
            <span className="ml-2 text-xs font-normal text-slate-400">{total} 篇</span>
          ) : null}
        </h1>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
          {SORTS.map((option) => (
            <button
              key={option.key}
              onClick={() => setSort(option.key)}
              className={`rounded-lg px-3 py-1.5 text-xs transition ${
                sort === option.key
                  ? "bg-white font-medium text-brand-700 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(keyword.trim());
          }}
          className="ml-auto flex gap-2"
        >
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索帖子…"
            className="input !py-1.5 w-40 text-sm"
          />
          <button type="submit" className="btn-ghost !py-1.5 text-sm">
            搜索
          </button>
        </form>
      </div>

      {popularTags.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setTag("")}
            className={tag === "" ? "chip-brand" : "chip-slate"}
          >
            全部
          </button>
          {popularTags.map((item) => (
            <button
              key={item.tag}
              onClick={() => setTag(tag === item.tag ? "" : item.tag)}
              className={tag === item.tag ? "chip-brand" : "chip-slate"}
            >
              {item.tag} · {item.count}
            </button>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
      ) : null}

      {composing ? (
        <form onSubmit={handleCreate} className="card space-y-3 p-5">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="标题"
            className="input"
          />
          <div>
            <textarea
              ref={contentRef}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={8}
              placeholder={"正文支持 Markdown：# 标题、**加粗**、- 列表。也可以点下面的按钮插入图片或链接。"}
              className="input resize-y font-mono text-sm"
            />
            {/* 编辑工具条：图片先传到服务器换回 URL，再以 Markdown 图片语法插到光标处 */}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                onChange={handlePickImage}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="btn-ghost !py-1.5 text-xs"
              >
                {uploading ? "上传中…" : "🖼 插入图片"}
              </button>
              <button
                type="button"
                onClick={() => setLinkOpen(true)}
                className="btn-ghost !py-1.5 text-xs"
              >
                🔗 插入链接
              </button>
              <span className="text-[11px] text-slate-400">
                图片不超过 5MB，支持 png / jpg / webp / gif
              </span>
            </div>
          </div>
          <input
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="标签，用逗号分隔，例如：经验, 口语"
            className="input !py-2 text-sm"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setComposing(false)}
              className="btn-ghost !py-2 text-sm"
            >
              取消
            </button>
            <button type="submit" disabled={busy} className="btn-primary !py-2 text-sm">
              {busy ? "发布中…" : "发布"}
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <Spinner />
      ) : posts.length === 0 ? (
        <EmptyState text={search || tag ? "没有匹配的帖子" : "还没有帖子，来发第一篇"} />
      ) : (
        <div className="space-y-3">
          {posts.map((post) => {
            const expanded = expandedId === post.id;
            const full = fullContent[post.id];
            return (
              <article
                key={post.id}
                onClick={(e) => handleCardClick(e, post)}
                className="card space-y-2.5 p-5 transition hover:border-brand-300 hover:shadow-lg"
              >
                <div className="flex items-center gap-2">
                  {post.is_pinned ? <span className="chip-brand">置顶</span> : null}
                  {post.tags.map((t) => (
                    <span key={t} className="chip-slate">
                      {t}
                    </span>
                  ))}
                  {post.is_mine ? (
                    <button
                      onClick={() => handleDelete(post)}
                      className="ml-auto rounded-lg px-2 py-1 text-[11px] text-slate-400 transition hover:bg-rose-50 hover:text-rose-500"
                    >
                      删除
                    </button>
                  ) : null}
                </div>

                <Link
                  href={`/forum/${post.id}`}
                  className="block font-semibold text-slate-900 hover:text-brand-700"
                >
                  {post.title}
                </Link>

                {expanded ? (
                  <div>
                    {expandingId === post.id ? (
                      <p className="text-sm text-slate-400">加载中…</p>
                    ) : (
                      <Markdown content={full ?? post.summary} />
                    )}
                    <button
                      onClick={() => toggleExpand(post)}
                      className="mt-1 text-xs text-brand-600 hover:text-brand-700"
                    >
                      收起
                    </button>
                  </div>
                ) : (
                  <div>
                    <p className="line-clamp-2 text-sm text-slate-500">
                      {post.summary}
                      {post.truncated ? "…" : ""}
                    </p>
                    {post.truncated ? (
                      <button
                        onClick={() => toggleExpand(post)}
                        className="mt-1 text-xs text-brand-600 hover:text-brand-700"
                      >
                        展开全文
                      </button>
                    ) : null}
                  </div>
                )}

                <div className="flex items-center gap-3 pt-0.5 text-[11px] text-slate-400">
                  <span className="flex items-center gap-1.5">
                    <Avatar
                      username={post.author.username}
                      avatar={post.author.avatar}
                      className="h-5 w-5 text-[10px]"
                    />
                    {post.author.username}
                  </span>
                  <span className="chip-slate !px-1.5 !py-0">
                    Lv.{post.author.level}
                  </span>
                  <span>·</span>
                  <span>{new Date(post.created_at).toLocaleDateString("zh-CN")}</span>
                  <span className="ml-auto flex items-center gap-3">
                    <Link
                      href={`/forum/${post.id}`}
                      title="打开帖子"
                      className="transition hover:text-brand-600"
                    >
                      👁 {post.view_count}
                    </Link>
                    <button
                      onClick={() => handleLike(post)}
                      className={`transition hover:text-rose-500 ${
                        post.liked ? "text-rose-500" : ""
                      }`}
                    >
                      ♥ {post.like_count}
                    </button>
                    <Link
                      href={`/forum/${post.id}#comments`}
                      title="查看评论"
                      className="transition hover:text-brand-600"
                    >
                      💬 {post.comment_count}
                    </Link>
                  </span>
                </div>
              </article>
            );
          })}

          {hasMore ? (
            <button
              onClick={() => load(posts.length)}
              disabled={loadingMore}
              className="btn-ghost w-full !py-2.5 text-sm"
            >
              {loadingMore ? "加载中…" : "加载更多"}
            </button>
          ) : (
            <p className="py-2 text-center text-xs text-slate-300">没有更多了</p>
          )}
        </div>
      )}

      {/* 发布入口：蓝色圆形悬浮按钮 */}
      <button
        onClick={() => setComposing((v) => !v)}
        aria-label={composing ? "取消发布" : "发布帖子"}
        title={composing ? "取消发布" : "发布帖子"}
        className="fixed bottom-6 right-6 z-30 flex h-14 w-14 items-center justify-center rounded-full bg-brand-600 text-3xl leading-none text-white shadow-lg shadow-brand-600/30 transition hover:bg-brand-700 active:scale-95"
      >
        <span className={composing ? "rotate-45 transition-transform" : "transition-transform"}>
          +
        </span>
      </button>

      {/* 链接弹窗：确认后把 [文字](网址) 插进正文，渲染成可点的新标签页链接 */}
      {linkOpen ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/30 p-4"
          onClick={() => setLinkOpen(false)}
        >
          <div
            className="card w-full max-w-md space-y-3 p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold text-slate-900">插入链接</h3>
            <input
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
              autoFocus
              placeholder="网址，例如 https://example.com"
              className="input !py-2 text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleInsertLink();
                }
              }}
            />
            <input
              value={linkLabel}
              onChange={(e) => setLinkLabel(e.target.value)}
              placeholder="显示文字（可留空，默认显示网址）"
              className="input !py-2 text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleInsertLink();
                }
              }}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setLinkOpen(false)}
                className="btn-ghost !py-2 text-sm"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleInsertLink}
                disabled={!linkUrl.trim()}
                className="btn-primary !py-2 text-sm"
              >
                插入
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function ForumPage() {
  return (
    <RequireAuth>
      <AppShell>
        <Forum />
      </AppShell>
    </RequireAuth>
  );
}
