/**
 * 登录后的模型分享弹窗。
 *
 * 别的用户分享了模型时，登录后弹一次：可以直接采纳来用，也可以关掉。
 * 关掉的分享服务端会记住，不再对当前用户推送。同一浏览器会话内不重复弹。
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Modal } from "@/components/ui";
import { api } from "@/lib/api";
import { formatLabel } from "@/lib/aiFormats";
import { useAuth } from "@/lib/auth";
import type { AiShare } from "@/lib/types";

const SESSION_KEY = "linguascene_share_prompt_seen";

export function AiSharePromptDialog() {
  const { user } = useAuth();
  const router = useRouter();
  const [share, setShare] = useState<AiShare | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    if (typeof window === "undefined") return;
    if (window.sessionStorage.getItem(SESSION_KEY)) return;

    let cancelled = false;
    api
      .aiSharePrompt()
      .then((result) => {
        if (cancelled) return;
        window.sessionStorage.setItem(SESSION_KEY, "1");
        if (result.available && result.share) setShare(result.share);
      })
      .catch(() => {
        // 弹窗是锦上添花，取不到就静默跳过
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  const close = useCallback(() => setShare(null), []);

  async function handleDismiss() {
    if (!share) return;
    setBusy(true);
    try {
      await api.dismissAiShare(share.id);
    } catch {
      // 关掉失败也无妨，本地收起即可
    } finally {
      setBusy(false);
      close();
    }
  }

  async function handleAdopt() {
    if (!share) return;
    setError("");
    setBusy(true);
    try {
      await api.adoptAiShare(share.id);
      close();
      router.push("/settings/ai");
    } catch (err) {
      setError(err instanceof Error ? err.message : "采纳失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={share !== null}
      onClose={handleDismiss}
      title="有人分享了 AI 模型给你"
      footer={
        <>
          <button
            type="button"
            onClick={handleAdopt}
            disabled={busy}
            className="btn-primary flex-1"
          >
            {busy ? "处理中…" : "采纳并使用"}
          </button>
          <button
            type="button"
            onClick={handleDismiss}
            disabled={busy}
            className="btn-ghost"
          >
            关闭
          </button>
        </>
      }
    >
      {share ? (
        <>
          <div className="rounded-xl border border-brand-200 bg-brand-50/50 p-4">
            <p className="text-sm font-medium text-slate-900">{share.title}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              来自 {share.owner_name} · {share.active_model}（
              {formatLabel(share.api_format)}）
            </p>
          </div>
          {share.note ? (
            <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
              {share.note}
            </p>
          ) : null}
          <p className="text-xs text-slate-400">
            采纳后你的对话、纠错、精读等 AI 功能都会调用这个模型；随时可以在「AI
            模型」页切回自己的。
          </p>
          {error ? (
            <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">
              {error}
            </p>
          ) : null}
        </>
      ) : null}
    </Modal>
  );
}
