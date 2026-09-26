/**
 * 单词卡：音标 + 发音 + 例句，可加入我的词库。
 */
"use client";

import { useState } from "react";

import { currentSpeechVolume } from "@/lib/speech";
import { wordbookApi, type WordCard } from "@/lib/wordbook";

const SPEECH_LANG = { us: "en-US", uk: "en-GB" } as const;

// 同一时刻只放一条发音：连点或翻卡时几条音频叠在一起会听不清。
let currentAudio: HTMLAudioElement | null = null;
// 预取过的音频要留住引用，元素被回收会把已缓冲的数据一起丢掉。
const preloadedAudio = new Map<string, HTMLAudioElement>();
const PRELOAD_LIMIT = 12;

function speakFallback(word: string, accent: "us" | "uk") {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  const utterance = new SpeechSynthesisUtterance(word);
  utterance.lang = SPEECH_LANG[accent];
  utterance.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

/**
 * 提前把音频拉进浏览器缓存。后端遇到没缓存的词要联网合成，翻到那张卡
 * 才请求就得干等，所以下一张还在看的时候就先取回来。
 */
export function preloadWord(word: string, accent: "us" | "uk" = "us") {
  if (typeof window === "undefined") return;
  const url = wordbookApi.audioUrl(word, accent);
  if (preloadedAudio.has(url)) return;
  const audio = new Audio();
  audio.preload = "auto";
  audio.src = url;
  audio.load();
  preloadedAudio.set(url, audio);
  if (preloadedAudio.size > PRELOAD_LIMIT) {
    const oldest = preloadedAudio.keys().next().value;
    if (oldest) preloadedAudio.delete(oldest);
  }
}

/**
 * 播放发音：优先用后端缓存/合成的音频，拿不到就回退到浏览器朗读。
 * 这样没装 edge-tts 或没有外网时也不会「点了没反应」。
 */
export function playWord(word: string, accent: "us" | "uk" = "us") {
  if (typeof window === "undefined") return;
  currentAudio?.pause();
  currentAudio = null;
  const audio = new Audio(wordbookApi.audioUrl(word, accent));
  // 单词发音和整句朗读共用同一个音量偏好
  audio.volume = currentSpeechVolume();
  currentAudio = audio;
  let fellBack = false;
  const fallback = () => {
    if (fellBack) return;
    fellBack = true;
    speakFallback(word, accent);
  };
  audio.onerror = fallback;
  audio.play().catch(fallback);
}

export function WordFlashcard({
  word,
  onChange,
  revealed = true,
  onReveal,
}: {
  word: WordCard;
  onChange?: (next: WordCard) => void;
  revealed?: boolean;
  onReveal?: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const collect = async () => {
    setBusy(true);
    try {
      const updated = await wordbookApi.collect(word.id);
      onChange?.(updated);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card overflow-hidden p-0">
      <div className="flex items-start justify-between gap-3 bg-gradient-to-br from-brand-50 to-white px-5 pb-4 pt-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="chip-brand">{word.level || "—"}</span>
            {word.unit ? <span className="chip-slate">{word.unit}</span> : null}
            {word.in_vocabulary ? (
              <span className="chip bg-emerald-50 text-emerald-700">已在我的词库</span>
            ) : null}
          </div>
          <h3 className="mt-2 truncate text-2xl font-semibold text-slate-900">
            {word.word}
          </h3>
          {word.part_of_speech ? (
            <p className="mt-0.5 text-xs italic text-slate-400">
              {word.part_of_speech}
            </p>
          ) : null}
        </div>
      </div>

      <div className="space-y-4 px-5 pb-5">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => playWord(word.word, "us")}
            className="btn-ghost gap-1.5 px-3 py-1.5 text-xs"
            title="美式发音"
          >
            🔊 <span className="font-mono">{word.phonetic_us || "—"}</span>
            <span className="text-slate-400">美</span>
          </button>
          <button
            onClick={() => playWord(word.word, "uk")}
            className="btn-ghost gap-1.5 px-3 py-1.5 text-xs"
            title="英式发音"
          >
            🔊 <span className="font-mono">{word.phonetic_uk || "—"}</span>
            <span className="text-slate-400">英</span>
          </button>
        </div>

        {revealed ? (
          <>
            <p className="text-lg font-medium text-slate-900">{word.meaning_zh}</p>
            {word.meaning ? (
              <p className="text-sm leading-relaxed text-slate-500">{word.meaning}</p>
            ) : null}

            {word.examples.length > 0 ? (
              <ul className="space-y-2.5 border-t border-slate-100 pt-4">
                {word.examples.map((example, index) => (
                  <li key={index} className="text-sm">
                    <div className="flex items-start gap-2">
                      <button
                        onClick={() => playWord(example.en, "us")}
                        className="mt-0.5 shrink-0 text-slate-300 transition hover:text-brand-600"
                        aria-label="朗读例句"
                      >
                        🔊
                      </button>
                      <div>
                        <p className="text-slate-700">{example.en}</p>
                        {example.zh ? (
                          <p className="text-xs text-slate-400">{example.zh}</p>
                        ) : null}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="flex items-center gap-3 border-t border-slate-100 pt-4">
              <div className="flex-1">
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>掌握度</span>
                  <span>{Math.round(word.mastery * 100)}%</span>
                </div>
                <div className="mt-1 h-1.5 w-full rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-brand-500 transition-all"
                    style={{ width: `${Math.round(word.mastery * 100)}%` }}
                  />
                </div>
              </div>
              {!word.in_vocabulary ? (
                <button onClick={collect} disabled={busy} className="btn-primary px-3 py-1.5 text-xs">
                  加入词库
                </button>
              ) : null}
            </div>
          </>
        ) : (
          <button onClick={onReveal} className="btn-ghost w-full py-2 text-sm">
            点击显示释义
          </button>
        )}
      </div>
    </div>
  );
}
