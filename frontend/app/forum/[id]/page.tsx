"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Markdown } from "@/components/Markdown";
import { Avatar, EmptyState, Spinner } from "@/components/ui";
import { RequireAuth, useAuth } from "@/lib/auth";
import { socialApi, type ForumComment, type ForumPost } from "@/lib/social";

function wasEdited(post: ForumPost) {
  if (!post.updated_at) return false;

  return (
    new Date(post.updated_at).getTime() - new Date(post.created_at).getTime() > 1000
  );
}

function PostDetail() {
  const params = useParams<{ id: string }>();
  const postId = Number(params.id);
  const router = useRouter();
  const { user } = useAuth();

  const [post, setPost] = useState<ForumPost | null>(null);
  const [comments, setComments] = useState<ForumComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editTags, setEditTags] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([socialApi.post(postId), socialApi.comments(postId)])
      .then(([p, c]) => {
        setPost(p);
        setComments(c);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [postId]);

  useEffect(() => {
    if (loading) return;
    if (window.location.hash !== "#comments") return;
    document
      .getElementById("comments")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [loading]);

  async function handleLike() {
    if (!post) return;
    try {
      const r = await socialApi.likePost(post.id);
      setPost({ ...post, liked: r.liked, like_count: r.like_count });
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  function startEdit() {
    if (!post) return;
    setEditTitle(post.title);
    setEditContent(post.content ?? "");
    setEditTags(post.tags.join(", "));
    setEditing(true);
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    if (!post || !editTitle.trim() || !editContent.trim()) return;

    setSaving(true);
    setError("");
    try {
      const updated = await socialApi.updatePost(post.id, {
        title: editTitle.trim(),
        content: editContent,
        tags: editTags
          .split(/[,，\s]+/)
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setPost(updated);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handlePin() {
    if (!post) return;
    try {
      const updated = await socialApi.pinPost(post.id, !post.is_pinned);
      setPost(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleComment(event: React.SyntheticEvent) {
    event.preventDefault();
    if (!draft.trim() || !post) return;

    setBusy(true);
    try {
      const created = await socialApi.addComment(post.id, draft.trim());
      setComments((prev) => [...prev, created]);
      setPost({ ...post, comment_count: post.comment_count + 1 });
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "评论失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!post || !window.confirm("删除这篇帖子？")) return;
    try {
      await socialApi.deletePost(post.id);
      router.push("/forum");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handleDeleteComment(comment: ForumComment) {
    if (!post) return;
    try {
      await socialApi.deleteComment(comment.id);
      setComments((prev) => prev.filter((c) => c.id !== comment.id));
      setPost({ ...post, comment_count: Math.max(0, post.comment_count - 1) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  if (loading) return <Spinner />;
  if (error && !post) return <EmptyState text={error} />;
  if (!post) return <EmptyState text="帖子不存在" />;

  const canManage = post.is_mine || user?.role === "ADMIN";
  const isAdmin = user?.role === "ADMIN";

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link href="/forum" className="inline-block text-xs text-slate-400 hover:text-brand-600">
        ← 返回论坛
      </Link>

      <article className="card space-y-5 p-7">
        {editing ? (
          <form onSubmit={handleSave} className="space-y-3">
            <input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              className="input"
              placeholder="标题"
            />
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              rows={12}
              className="input resize-y font-mono text-sm"
              placeholder="正文支持 Markdown"
            />
            <input
              value={editTags}
              onChange={(e) => setEditTags(e.target.value)}
              className="input !py-2 text-sm"
              placeholder="标签，用逗号分隔"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="btn-ghost !py-2 text-sm"
              >
                取消
              </button>
              <button type="submit" disabled={saving} className="btn-primary !py-2 text-sm">
                {saving ? "保存中…" : "保存"}
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {post.is_pinned ? <span className="chip-brand">置顶</span> : null}
              {post.tags.map((tag) => (
                <span key={tag} className="chip-slate">
                  {tag}
                </span>
              ))}
            </div>

            <h1 className="text-xl font-semibold leading-snug text-slate-900">
              {post.title}
            </h1>

            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
              <Link
                href={`/u/${post.author.user_id}`}
                className="flex items-center gap-1.5 hover:text-brand-600"
              >
                <Avatar
                  username={post.author.username}
                  avatar={post.author.avatar}
                  className="h-6 w-6 text-[11px]"
                />
                {post.author.username}
              </Link>
              <span className="chip-slate !px-1.5 !py-0">
                Lv.{post.author.level} {post.author.level_name}
              </span>
              <span>·</span>
              <span>{new Date(post.created_at).toLocaleString("zh-CN")}</span>
              {wasEdited(post) ? (
                <span className="text-slate-300">已编辑</span>
              ) : null}
              <span>·</span>
              <span>👁 {post.view_count}</span>
            </div>

            <Markdown content={post.content ?? ""} />
          </>
        )}

        {!editing ? (
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
            <button
              onClick={handleLike}
              className={`rounded-xl px-3.5 py-2 text-sm transition ${
                post.liked
                  ? "bg-rose-50 text-rose-600"
                  : "border border-slate-200 text-slate-600 hover:border-rose-300"
              }`}
            >
              ♥ {post.like_count}
            </button>
            <span className="text-sm text-slate-400">💬 {post.comment_count}</span>

            <div className="ml-auto flex items-center gap-3 text-xs">
              {post.is_mine ? (
                <button
                  onClick={startEdit}
                  className="text-slate-400 hover:text-brand-600"
                >
                  编辑
                </button>
              ) : null}
              {isAdmin ? (
                <button
                  onClick={handlePin}
                  className="text-slate-400 hover:text-brand-600"
                >
                  {post.is_pinned ? "取消置顶" : "置顶"}
                </button>
              ) : null}
              {canManage ? (
                <button
                  onClick={handleDelete}
                  className="text-slate-400 hover:text-rose-500"
                >
                  删除帖子
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </article>

      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
      ) : null}

      <section id="comments" className="card scroll-mt-20 space-y-4 p-6">
        <h2 className="text-sm font-semibold text-slate-900">
          评论 {comments.length > 0 ? `(${comments.length})` : ""}
        </h2>

        {comments.length === 0 ? (
          <p className="text-xs text-slate-400">还没有评论</p>
        ) : (
          <ul className="space-y-3">
            {comments.map((comment) => (
              <li key={comment.id} className="flex gap-3">
                <Link href={`/u/${comment.author.user_id}`} className="shrink-0">
                  <Avatar
                    username={comment.author.username}
                    avatar={comment.author.avatar}
                    className="h-8 w-8 text-xs"
                  />
                </Link>
                <div className="min-w-0 flex-1 rounded-xl bg-slate-50 p-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-700">
                      {comment.author.username}
                    </span>
                    <span className="chip-slate !px-1.5 !py-0 !text-[10px]">
                      Lv.{comment.author.level}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      {new Date(comment.created_at).toLocaleString("zh-CN")}
                    </span>
                    {comment.is_mine || isAdmin ? (
                      <button
                        onClick={() => handleDeleteComment(comment)}
                        className="ml-auto text-[10px] text-slate-400 hover:text-rose-500"
                      >
                        删除
                      </button>
                    ) : null}
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">
                    {comment.content}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={handleComment} className="space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            placeholder="写点评论…（Ctrl/Cmd + Enter 发送）"
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                void handleComment(e);
              }
            }}
            className="input resize-y text-sm"
          />
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="btn-primary !py-2 text-sm"
            >
              {busy ? "发送中…" : "评论"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function ForumPostPage() {
  return (
    <RequireAuth>
      <AppShell>
        <PostDetail />
      </AppShell>
    </RequireAuth>
  );
}
