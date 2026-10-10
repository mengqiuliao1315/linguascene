"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { prefetchSpeech, speak } from "@/lib/speech";
import type { WordExplanation } from "@/lib/types";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 在例句里把查的词高亮出来，方便对照（图一的插件也是这么做的）。 */
function highlightExample(text: string, ...forms: (string | undefined)[]): ReactNode {
  const targets = Array.from(
    new Set(
      forms.filter(
        (item): item is string => !!item && item.trim().length > 1
      )
    )
  );
  if (targets.length === 0) return text;
  const pattern = new RegExp(`(${targets.map(escapeRegExp).join("|")})`, "gi");
  return text.split(pattern).map((part, index) =>
    targets.some((target) => target.toLowerCase() === part.toLowerCase()) ? (
      <span key={index} className="font-medium text-brand-600">
        {part}
      </span>
    ) : (
      part
    )
  );
}

export function WordPopover({
  word,
  raw,
  context,
  position,
  notedMeaning,
  onAddNote,
  onClose,
}: {

  word: string;

  raw?: string;
  context: string;
  position: { x: number; y: number };

  notedMeaning?: string;
  onAddNote?: (payload: { text: string; meaning: string }) => Promise<void> | void;
  onClose: () => void;
}) {
  const [data, setData] = useState<WordExplanation | null>(null);
  const [preview, setPreview] = useState<WordExplanation | null>(null);
  const [saved, setSaved] = useState(false);
  const [noting, setNoting] = useState(false);
  const [slowPending, setSlowPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const lookupRef = useRef<Promise<WordExplanation | null> | null>(null);
  const spokenFor = useRef("");

  const display = raw || word;

  // 先展示词典结果，等模型分析完再整体替换。
  const shown = data ?? preview;
  const senses = shown?.senses ?? [];

  const canAnnotate = notedMeaning === undefined || !notedMeaning.trim();

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setPreview(null);
    setSaved(false);
    setFailed(false);

    void api
      .translate(word, context, true)
      .then((result) => {
        if (!cancelled && result.core_meanings.length > 0) setPreview(result);
        return null;
      })
      .catch(() => null);

    const task = api
      .translate(word, context)
      .then((result) => {
        if (!cancelled) setData(result);
        return result;
      })
      .catch(() => {
        if (!cancelled) {
          setData(null);
          setFailed(true);
        }
        return null;
      });
    lookupRef.current = task;

    if (spokenFor.current !== word) {
      spokenFor.current = word;
      prefetchSpeech(word, { lang: "en-US" });
    }
    return () => {
      cancelled = true;
    };
  }, [word, context]);

  // 词典预览出现后模型还没回来的话，过一会儿提示一句，避免让人以为就不更新了。
  useEffect(() => {
    if (!preview || data) {
      setSlowPending(false);
      return;
    }
    const timer = window.setTimeout(() => setSlowPending(true), 900);
    return () => window.clearTimeout(timer);
  }, [preview, data]);

  function handleSpeak() {

    void speak(shown?.word || display);
  }

  async function handleSave() {
    if (!shown) return;
    await api.saveWord({
      word: shown.word,
      meaning:
        shown.core_meanings[0] ?? senses[0]?.meaning ?? shown.meaning_in_context,
      phonetic: shown.pronunciation,
      example: shown.example_sentences[0] ?? context,
      level: shown.cefr_level,
      source: "reading",
    });
    setSaved(true);
  }

  async function handleAnnotate() {
    if (!onAddNote || !canAnnotate) return;
    setNoting(true);
    try {

      const result = shown ?? (await lookupRef.current) ?? null;
      const meaning =
        result?.core_meanings.join("；") ||
        result?.senses.map((sense) => sense.meaning).filter(Boolean).join("；") ||
        result?.meaning_in_context ||
        "";
      await onAddNote({ text: display, meaning });
    } finally {
      setNoting(false);
    }
  }

  return (
    <div
      className="fixed z-40 max-h-[70vh] w-72 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-4 shadow-xl"
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
          {shown?.pronunciation ? (
            <p className="text-xs text-slate-400">{shown.pronunciation}</p>
          ) : null}
        </div>
        <button
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          ✕
        </button>
      </div>

      {!shown && !failed ? (
        <p className="mt-3 text-xs text-slate-400">查询中…</p>
      ) : !shown ? (
        <p className="mt-3 text-xs text-slate-400">暂无释义</p>
      ) : (
        <div className="mt-3 space-y-2 text-xs">
          {shown.word && shown.word.toLowerCase() !== display.toLowerCase() ? (
            <p className="text-[11px] text-slate-400">
              原形：<span className="text-slate-500">{shown.word}</span>
            </p>
          ) : null}

          {senses.length > 0 ? (
            <ul className="space-y-2">
              {senses.map((sense, index) => (
                <li key={`${sense.part_of_speech}-${index}`} className="space-y-1">
                  <div className="flex items-baseline gap-1.5">
                    {sense.part_of_speech ? (
                      <span className="chip-slate shrink-0">
                        {sense.part_of_speech}
                      </span>
                    ) : null}
                    <span className="text-slate-700">{sense.meaning}</span>
                  </div>
                  {sense.example ? (
                    <p className="rounded-lg bg-slate-50 p-2 leading-relaxed text-slate-600">
                      {highlightExample(sense.example, display, shown.word)}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <>
              {shown.part_of_speech ? (
                <span className="chip-slate">{shown.part_of_speech}</span>
              ) : null}
              <p className="text-slate-700">{shown.core_meanings.join("；")}</p>
              {shown.example_sentences[0] ? (
                <p className="rounded-lg bg-slate-50 p-2 leading-relaxed text-slate-600">
                  {highlightExample(shown.example_sentences[0], display, shown.word)}
                </p>
              ) : null}
            </>
          )}

          {shown.meaning_in_context ? (
            <p className="rounded-lg bg-brand-50 p-2 leading-relaxed text-slate-600">
              <span className="font-medium text-brand-700">语境 </span>
              {shown.meaning_in_context}
            </p>
          ) : null}

          {shown.collocations.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {shown.collocations.map((item) => (
                <span key={item} className="chip-brand">
                  {item}
                </span>
              ))}
            </div>
          ) : null}

          {slowPending ? (
            <p className="text-[11px] text-slate-400">
              AI 正在补充本句用法…
            </p>
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
          disabled={saved || !shown || (shown.core_meanings.length === 0 && senses.length === 0)}
          className="btn-primary flex-1 !py-2 text-xs"
        >
          {saved ? "已加入词库" : "⭐ 加入词库"}
        </button>
      </div>
    </div>
  );
}
