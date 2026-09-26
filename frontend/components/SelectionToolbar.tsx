"use client";

import { useEffect, useRef, useState } from "react";

import {
  COLOR_DOTS,
  COLOR_LABELS,
  COLOR_ORDER,
  type NoteColor,
} from "@/lib/reading";

export interface SelectionInfo {
  text: string;
  start: number;
  end: number;
  sentenceIndex: number;
  x: number;
  y: number;
}

export function SelectionToolbar({
  selection,
  onPickColor,
  onAnnotate,
  onLookup,
  onClose,
}: {
  selection: SelectionInfo;
  onPickColor: (color: NoteColor) => void;
  onAnnotate: (note: string, color: NoteColor) => void;
  onLookup: () => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"menu" | "note">("menu");
  const [draft, setDraft] = useState("");
  const [color, setColor] = useState<NoteColor>("blue");
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        onClose();
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  const above = selection.y > 140;
  const viewportWidth =
    typeof window === "undefined" ? 1024 : window.innerWidth;
  const left = Math.min(
    Math.max(selection.x, 130),
    Math.max(viewportWidth - 130, 130)
  );

  return (
    <div
      ref={boxRef}
      className="fixed z-40 rounded-2xl border border-slate-200 bg-white/95 p-2 shadow-lg backdrop-blur"
      style={{
        left,
        top: above ? selection.y - 10 : selection.y + 24,
        transform: above ? "translate(-50%, -100%)" : "translate(-50%, 0)",
      }}
    >
      {mode === "menu" ? (
        <div className="flex items-center gap-1.5">
          {COLOR_ORDER.map((item) => (
            <button
              key={item}
              type="button"
              title={`标为${COLOR_LABELS[item]}`}
              onClick={() => onPickColor(item)}
              className={`h-6 w-6 rounded-full ring-1 ring-slate-200 transition hover:scale-110 ${COLOR_DOTS[item]}`}
            />
          ))}
          <span className="mx-1 h-5 w-px bg-slate-200" />
          <button
            type="button"
            onClick={onLookup}
            className="rounded-lg px-2 py-1 text-xs text-slate-600 transition hover:bg-slate-100"
          >
            查词
          </button>
          <button
            type="button"
            onClick={() => setMode("note")}
            className="rounded-lg px-2 py-1 text-xs text-slate-600 transition hover:bg-slate-100"
          >
            写笔记
          </button>
        </div>
      ) : (
        <div className="w-72 space-y-2">
          <p className="truncate text-xs font-medium text-slate-700">
            {selection.text}
          </p>
          <input
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onAnnotate(draft, color);
            }}
            placeholder="写点什么…"
            className="input !py-1.5 text-xs"
          />
          <div className="flex items-center gap-1.5">
            {COLOR_ORDER.map((item) => (
              <button
                key={item}
                type="button"
                title={COLOR_LABELS[item]}
                onClick={() => setColor(item)}
                className={`h-5 w-5 rounded-full transition hover:scale-110 ${COLOR_DOTS[item]} ${
                  item === color ? "ring-2 ring-slate-400" : "ring-1 ring-slate-200"
                }`}
              />
            ))}
            <button
              type="button"
              onClick={() => onAnnotate(draft, color)}
              className="btn-primary ml-auto !px-3 !py-1 text-xs"
            >
              保存
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
