"use client";

import { useState } from "react";

import type { ScenarioHint } from "@/lib/types";

export function ScenarioHintCard({
  hint,
  onFill,
}: {
  hint: ScenarioHint | null;
  onFill: (text: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [showEnglish, setShowEnglish] = useState(false);

  if (!hint) return null;

  return (
    <div className="rounded-xl border border-brand-100 bg-brand-50/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-brand-700">
          💡 提示
          {hint.task_description ? (
            <span className="ml-2 font-normal text-slate-500">
              当前任务：{hint.task_description}
            </span>
          ) : null}
        </p>
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          {open ? "收起" : "展开"}
        </button>
      </div>

      {open ? (
        <div className="mt-2 space-y-2 text-xs">
          {hint.idea_zh ? (
            <p className="text-slate-600">
              <span className="text-slate-400">中文思路：</span>
              {hint.idea_zh}
            </p>
          ) : null}

          {hint.suggested_zh ? (
            <p className="text-slate-800">
              <span className="text-slate-400">你可以说：</span>
              {hint.suggested_zh}
            </p>
          ) : null}

          {hint.suggested_en ? (
            <p className="flex items-start gap-1.5 text-slate-500">
              <span className="shrink-0 text-slate-400">英文参考：</span>
              {showEnglish ? (
                <span className="flex-1">{hint.suggested_en}</span>
              ) : (
                <span className="flex-1 select-none text-slate-300">
                  ••••••
                </span>
              )}
              <button
                type="button"
                onClick={() => setShowEnglish((prev) => !prev)}
                aria-label={showEnglish ? "隐藏英文参考" : "显示英文参考"}
                title={showEnglish ? "隐藏英文参考" : "显示英文参考"}
                className={`shrink-0 leading-none transition ${
                  showEnglish
                    ? "text-brand-600"
                    : "text-slate-400 hover:text-slate-600"
                }`}
              >
                👁
              </button>
            </p>
          ) : null}

          {hint.suggested_en ? (
            <div className="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                onClick={() => onFill(hint.suggested_en)}
                className="btn-ghost !py-1.5 text-xs"
              >
                填入输入框
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
