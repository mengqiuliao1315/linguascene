"use client";

import { useState } from "react";

import { WordPopover } from "@/components/WordPopover";
import { loadTranslation } from "@/lib/chat";

const TOKEN_PATTERN = /([A-Za-z][A-Za-z'-]*)/g;

function tokenize(text: string): { value: string; isWord: boolean }[] {
  const parts: { value: string; isWord: boolean }[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(TOKEN_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      parts.push({ value: text.slice(lastIndex, index), isWord: false });
    }
    parts.push({ value: match[0], isWord: true });
    lastIndex = index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push({ value: text.slice(lastIndex), isWord: false });
  }
  return parts;
}

export function MessageTranslation({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const [translation, setTranslation] = useState("");
  const [loading, setLoading] = useState(false);
  const [popover, setPopover] = useState<{
    word: string;
    x: number;
    y: number;
  } | null>(null);

  async function handleToggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (translation || loading) return;

    setLoading(true);
    try {
      setTranslation(await loadTranslation(content));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={handleToggle}
        className="text-[11px] text-slate-400 hover:text-slate-600"
      >
        {open ? "收起翻译" : "翻译"}
      </button>

      {open ? (
        <div className="mt-1 rounded-xl border border-slate-200 bg-white p-3 text-xs">
          {loading ? (
            <p className="text-slate-400">查询中…</p>
          ) : (
            <>
              {translation ? (
                <p className="text-slate-800">{translation}</p>
              ) : (
                <p className="text-slate-400">
                  离线模式暂不支持整句翻译，可点击句中单词查词，或在设置中配置 AI 模型。
                </p>
              )}

              <p className="mt-2 leading-relaxed text-slate-500">
                {tokenize(content).map((token, index) =>
                  token.isWord ? (
                    <button
                      key={index}
                      type="button"
                      className="hover:text-brand-600 hover:underline"
                      onClick={(event) => {
                        const rect =
                          event.currentTarget.getBoundingClientRect();
                        setPopover({
                          word: token.value.toLowerCase(),
                          x: rect.left,
                          y: rect.bottom,
                        });
                      }}
                    >
                      {token.value}
                    </button>
                  ) : (
                    <span key={index}>{token.value}</span>
                  )
                )}
              </p>
            </>
          )}
        </div>
      ) : null}

      {popover ? (
        <WordPopover
          word={popover.word}
          context={content}
          position={{ x: popover.x, y: popover.y }}
          onClose={() => setPopover(null)}
        />
      ) : null}
    </div>
  );
}
