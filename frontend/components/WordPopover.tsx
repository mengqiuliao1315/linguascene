/**
 * 划词翻译弹窗：查词、发音、加批注、加词库。
 *
 * 查完词就地就能「加入批注」——批注里落的是这个词和它的释义，
 * 这样不用先关掉卡片、再重新划一次词去点颜色。
 */
"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { prefetchSpeech, speak } from "@/lib/speech";
import type { WordExplanation } from "@/lib/types";

export function WordPopover({
  word,
  raw,
  context,
  position,
  notedMeaning,
  onAddNote,
  onClose,
}: {
  /** 用于查词的小写形式 */
  word: string;
  /** 用户实际选中的原文：批注锚点与展示都用它，保留大小写 */
  raw?: string;
  context: string;
  position: { x: number; y: number };
  /**
   * 这个词在所属句子里已有批注的释义，由页面按笔记列表判断。
   * undefined = 还没有批注；空串 = 有批注但没翻译（这时按钮负责把翻译补上）。
   */
  notedMeaning?: string;
  onAddNote?: (payload: { text: string; meaning: string }) => Promise<void> | void;
  onClose: () => void;
}) {
  const [data, setData] = useState<WordExplanation | null>(null);
  const [saved, setSaved] = useState(false);
  const [noting, setNoting] = useState(false);
  const [loading, setLoading] = useState(true);
  /** 在途的查词请求：点「加入批注」比接口快时要靠它拿到释义 */
  const lookupRef = useRef<Promise<WordExplanation | null> | null>(null);
  const spokenFor = useRef("");

  const display = raw || word;
  /** 还有事可做：没批注，或批注里缺翻译（补翻译也是这条按钮的活） */
  const canAnnotate = notedMeaning === undefined || !notedMeaning.trim();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSaved(false);
    const task = api
      .translate(word)
      .then((result) => {
        if (!cancelled) setData(result);
        return result;
      })
      .catch(() => {
        if (!cancelled) setData(null);
        return null;
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    lookupRef.current = task;
    // 释义在路上时就把发音先取回来：点喇叭时音频多半已经在浏览器里
    if (spokenFor.current !== word) {
      spokenFor.current = word;
      prefetchSpeech(word, { lang: "en-US" });
    }
    return () => {
      cancelled = true;
    };
  }, [word]);

  /** 读音：词典形和后端给的音标是一套，优先读它，没查到再读选中原文。 */
  function handleSpeak() {
    // 走整句朗读那条已经预取过的通道，不再单独打一次单词合成
    void speak(data?.word || display);
  }

  async function handleSave() {
    if (!data) return;
    await api.saveWord({
      word: data.word,
      meaning: data.core_meanings[0] ?? data.meaning_in_context,
      phonetic: data.pronunciation,
      example: data.example_sentences[0] ?? context,
      level: data.cefr_level,
      source: "reading",
    });
    setSaved(true);
  }

  async function handleAnnotate() {
    if (!onAddNote || !canAnnotate) return;
    setNoting(true);
    try {
      // 查词要调模型，几秒起步。用户点得比接口快时得等它回来再落库，
      // 否则批注里只有词、没有翻译 —— 这条批注要的就是「词 + 翻译」。
      // 查词失败时 meaning 为空，仍然允许记一笔，不拦着用户。
      const result = data ?? (await lookupRef.current) ?? null;
      const meaning =
        result?.core_meanings.join("；") || result?.meaning_in_context || "";
      await onAddNote({ text: display, meaning });
    } finally {
      setNoting(false);
    }
  }

  return (
    <div
      className="fixed z-40 w-72 rounded-2xl border border-slate-200 bg-white p-4 shadow-xl"
      style={{
        left: Math.max(12, Math.min(position.x, window.innerWidth - 300)),
        top: Math.max(12, Math.min(position.y + 12, window.innerHeight - 280)),
      }}
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 font-semibold text-slate-900">
            <span className="truncate">{display}</span>
            <button
              type="button"
              onClick={handleSpeak}
              title="朗读这个词"
              aria-label="朗读这个词"
              className="shrink-0 text-sm text-slate-300 transition hover:text-brand-600"
            >
              🔊
            </button>
          </p>
          {data?.pronunciation ? (
            <p className="text-xs text-slate-400">{data.pronunciation}</p>
          ) : null}
        </div>
        <button
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          ✕
        </button>
      </div>

      {loading ? (
        <p className="mt-3 text-xs text-slate-400">查询中…</p>
      ) : !data || data.core_meanings.length === 0 ? (
        <p className="mt-3 text-xs text-slate-400">暂无释义</p>
      ) : (
        <div className="mt-3 space-y-2 text-xs">
          {data.part_of_speech ? (
            <span className="chip-slate">{data.part_of_speech}</span>
          ) : null}
          <p className="text-slate-700">{data.core_meanings.join("；")}</p>
          {data.meaning_in_context ? (
            <p className="text-slate-500">语境：{data.meaning_in_context}</p>
          ) : null}
          {data.example_sentences[0] ? (
            <p className="rounded-lg bg-slate-50 p-2 text-slate-600">
              {data.example_sentences[0]}
            </p>
          ) : null}
          {data.collocations.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {data.collocations.map((item) => (
                <span key={item} className="chip-brand">
                  {item}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={handleAnnotate}
          disabled={!canAnnotate || noting || !onAddNote}
          title="把这个词和它的释义记到本页批注"
          className={`flex-1 rounded-xl px-3 py-2 text-xs transition ${
            canAnnotate
              ? "border border-slate-200 text-slate-600 hover:border-brand-300 hover:text-brand-700"
              : "bg-slate-100 text-slate-400"
          }`}
        >
          {!canAnnotate ? "已加入批注" : noting ? "加入中…" : "✏️ 加入批注"}
        </button>
        <button
          onClick={handleSave}
          disabled={saved || !data || data.core_meanings.length === 0}
          className="btn-primary flex-1 !py-2 text-xs"
        >
          {saved ? "已加入词库" : "⭐ 加入词库"}
        </button>
      </div>
    </div>
  );
}
