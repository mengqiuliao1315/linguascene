"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { BASE_PATH } from "./api";

const TTS_MUTED_KEY = "linguascene_tts_muted";
const TTS_AUTO_KEY = "linguascene_tts_auto";
const TTS_VOLUME_KEY = "linguascene_tts_volume";

const SPEECH_RATE = 0.9;

const START_TIMEOUT_MS = 12000;

function playbackTimeoutMs(text: string): number {
  return START_TIMEOUT_MS + text.length * 120;
}

function ttsUrl(text: string, lang: string): string {
  return `${BASE_PATH}/api/audio/tts?text=${encodeURIComponent(text)}&lang=${encodeURIComponent(lang)}`;
}

function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

let currentAudio: HTMLAudioElement | null = null;

let currentAudioKey: string | null = null;

let currentVolume = 1;

let speakToken = 0;

export function setSpeechVolume(next: number): void {
  currentVolume = Math.min(1, Math.max(0, next));
  if (currentAudio) currentAudio.volume = currentVolume;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TTS_VOLUME_KEY, String(currentVolume));
  }
}

export function currentSpeechVolume(): number {
  return currentVolume;
}

export function stopSpeaking(): void {
  speakToken += 1;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  currentAudioKey = null;
  if (canSpeak()) window.speechSynthesis.cancel();
}

function pickVoice(lang: string): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;
  const normalized = (value: string) => value.replace("_", "-").toLowerCase();
  const target = normalized(lang);
  const exact = voices.find((voice) => normalized(voice.lang) === target);
  if (exact) return exact;
  const prefix = target.split("-")[0];
  return (
    voices.find((voice) => normalized(voice.lang).startsWith(prefix)) ?? null
  );
}

function speakWithBrowser(
  text: string,
  lang: string,
  waitUntilEnd = false
): Promise<boolean> {
  if (!canSpeak()) return Promise.resolve(false);
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = SPEECH_RATE;
  utterance.volume = currentVolume;
  const voice = pickVoice(lang);
  if (voice) utterance.voice = voice;
  window.speechSynthesis.cancel();

  if (!waitUntilEnd) {
    window.speechSynthesis.speak(utterance);
    return Promise.resolve(false);
  }

  if (!voice) return Promise.resolve(false);

  return new Promise<boolean>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(false);
    };
    const timer = setTimeout(finish, playbackTimeoutMs(text));
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  });
}

const audioCache = new Map<string, Promise<string>>();

const AUDIO_CACHE_LIMIT = 120;
const AUDIO_FETCH_TIMEOUT_MS = 12000;

function trimAudioCache(): void {
  while (audioCache.size > AUDIO_CACHE_LIMIT) {
    const oldest = audioCache.keys().next().value;
    if (oldest === undefined) return;
    const stale = audioCache.get(oldest);
    audioCache.delete(oldest);
    if (oldest === currentAudioKey) continue;
    stale?.then((objectUrl) => URL.revokeObjectURL(objectUrl)).catch(() => {});
  }
}

function loadSpeechAudio(url: string): Promise<string> {
  const hit = audioCache.get(url);
  if (hit) return hit;

  const task = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), AUDIO_FETCH_TIMEOUT_MS);
    try {
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw new Error(`tts ${res.status}`);
      const blob = await res.blob();
      if (!blob.size) throw new Error("tts empty");
      return URL.createObjectURL(blob);
    } finally {
      clearTimeout(timer);
    }
  })();
  audioCache.set(url, task);

  task.catch(() => audioCache.delete(url));

  trimAudioCache();
  return task;
}

const PREFETCH_CONCURRENCY = 6;

type PrefetchTask = { url: string; urgent: boolean };

const prefetchQueue: PrefetchTask[] = [];

const prefetchQueued = new Set<string>();
let prefetchRunning = 0;

function pumpPrefetchQueue(): void {
  while (prefetchRunning < PREFETCH_CONCURRENCY && prefetchQueue.length > 0) {

    prefetchQueue.sort((a, b) => Number(b.urgent) - Number(a.urgent));
    const task = prefetchQueue.shift();
    if (!task) return;
    prefetchQueued.delete(task.url);
    prefetchRunning += 1;
    void loadSpeechAudio(task.url)
      .catch(() => {})
      .finally(() => {
        prefetchRunning -= 1;
        pumpPrefetchQueue();
      });
  }
}

function enqueuePrefetch(url: string, urgent: boolean): void {

  if (prefetchQueued.has(url) || audioCache.has(url)) return;
  prefetchQueued.add(url);
  prefetchQueue.push({ url, urgent });
  pumpPrefetchQueue();
}

let backendTts: boolean | null = null;

function setBackendTtsAvailable(next: boolean): void {
  backendTts = next;
}

let backendProbe: Promise<boolean> | null = null;

export function warmSpeechBackend(
  options: { force?: boolean } = {}
): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if (options.force) backendProbe = null;
  if (!backendProbe) {
    backendProbe = fetch(`${BASE_PATH}/api/audio/capability`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const available = Boolean(data?.tts);
        setBackendTtsAvailable(available);
        return available;
      })
      .catch(() => {

        return false;
      });
  }
  return backendProbe;
}

export function prefetchSpeech(
  text: string,
  options: { lang?: string; urgent?: boolean; url?: string | null } = {}
): void {
  const content = text.trim();
  if (!content || typeof window === "undefined") return;
  if (backendTts === false && !options.url) return;
  enqueuePrefetch(
    options.url ?? ttsUrl(content, options.lang ?? "en-US"),
    options.urgent ?? false
  );
}

export function cancelPrefetchSpeech(): void {
  prefetchQueue.length = 0;
  prefetchQueued.clear();
}

function takeCompleteSentences(pending: string): [string[], string] {
  const sentences: string[] = [];
  const boundary = /[.!?…]+["')\]”’]*(?=\s|$)|\n+/g;
  let start = 0;
  let match: RegExpExecArray | null;
  while ((match = boundary.exec(pending)) !== null) {
    const end = match.index + match[0].length;
    const candidate = pending.slice(start, end).trim();
    start = end;
    if (candidate) sentences.push(candidate);
  }
  return [sentences, pending.slice(start)];
}

type SpeechStream = {
  id: number;

  seen: number;

  buffer: string;

  queue: string[];

  active: boolean;
};

let speechStream: SpeechStream | null = null;
let speechStreamSeq = 0;

function pumpSpeechStream(): void {
  const stream = speechStream;
  if (!stream || stream.active) return;
  const sentence = stream.queue.shift();
  if (!sentence) return;
  stream.active = true;

  const next = stream.queue[0];
  if (next) prefetchSpeech(next, { urgent: true });
  void speak(sentence, "en-US", { waitUntilEnd: true }).finally(() => {

    if (speechStream !== stream) return;
    stream.active = false;
    pumpSpeechStream();
  });
}

export function startSpeechStream(): number {
  cancelSpeechStream();
  const id = ++speechStreamSeq;
  speechStream = { id, seen: 0, buffer: "", queue: [], active: false };
  return id;
}

export function feedSpeechStream(id: number, fullText: string): void {
  const stream = speechStream;
  if (!stream || stream.id !== id) return;
  if (fullText.length <= stream.seen) return;
  const delta = fullText.slice(stream.seen);
  stream.seen = fullText.length;
  stream.buffer += delta;
  const [sentences, rest] = takeCompleteSentences(stream.buffer);
  if (!sentences.length) return;
  stream.buffer = rest;
  stream.queue.push(...sentences);
  pumpSpeechStream();
}

export function endSpeechStream(id: number): void {
  const stream = speechStream;
  if (!stream || stream.id !== id) return;
  const tail = stream.buffer.trim();
  stream.buffer = "";
  if (tail) stream.queue.push(tail);
  pumpSpeechStream();
}

export function cancelSpeechStream(): void {
  const stream = speechStream;
  speechStream = null;
  if (stream) stream.queue.length = 0;
  stopSpeaking();
}

const TRACE_KEY = "linguascene_tts_trace";

function traceSpeak(entry: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(TRACE_KEY);
    const list = raw ? (JSON.parse(raw) as unknown[]) : [];
    list.push({ at: new Date().toISOString(), ...entry });
    window.localStorage.setItem(TRACE_KEY, JSON.stringify(list.slice(-20)));
  } catch {

  }
}

const PLAY_CUT = "play-cut";

function playUrl(
  src: string,
  cacheKey: string,
  text: string,
  waitUntilEnd = false
): Promise<void> {
  const audio = new Audio(src);
  audio.preload = "auto";
  audio.volume = currentVolume;
  currentAudio = audio;
  currentAudioKey = cacheKey;

  return new Promise<void>((resolve, reject) => {
    let settled = false;

    let playing = false;
    const release = () => {
      if (currentAudio === audio) {
        currentAudio = null;
        currentAudioKey = null;
      }
    };
    const timer = setTimeout(() => {

      fail(new Error(playing ? PLAY_CUT : "audio unavailable"));
    }, waitUntilEnd ? playbackTimeoutMs(text) : START_TIMEOUT_MS);

    const fail = (err: unknown) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      release();
      if (playing) audio.pause();
      reject(err);
    };
    const done = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      release();
      resolve();
    };

    audio.onerror = () => fail(new Error(playing ? PLAY_CUT : "audio unavailable"));

    audio.onpause = () => {
      if (!playing || audio.ended) return;
      fail(new Error(PLAY_CUT));
    };

    audio.onended = () => {
      release();
      done();
    };
    audio
      .play()
      .then(() => {
        playing = true;
        if (!waitUntilEnd) done();
      })
      .catch(() => fail(new Error(playing ? PLAY_CUT : "audio unavailable")));
  });
}

export async function speak(
  text: string,
  lang = "en-US",
  options: { url?: string | null; waitUntilEnd?: boolean } = {}
): Promise<boolean> {
  const content = text.trim();
  if (!content) return false;
  const waitUntilEnd = options.waitUntilEnd ?? false;
  stopSpeaking();

  const started = performance.now();
  const marks: string[] = [];
  const label = content.slice(0, 32);

  if (typeof window !== "undefined" && typeof Audio !== "undefined") {
    const token = ++speakToken;
    const candidates = [
      ...(options.url ? [options.url] : []),
      ttsUrl(content, lang),
    ];
    for (const url of candidates) {

      try {
        await playUrl(url, url, content, waitUntilEnd);
        if (token !== speakToken) {
          traceSpeak({ text: label, url, stopped: true, marks });
          return false;
        }
        marks.push(`direct=${Math.round(performance.now() - started)}ms`);
        traceSpeak({
          text: label,
          url,
          played: true,
          totalMs: Math.round(performance.now() - started),
          marks,
        });
        return true;
      } catch (err) {
        marks.push(
          `direct-fail=${Math.round(performance.now() - started)}ms${
            err instanceof Error ? `(${err.name})` : ""
          }`
        );
        currentAudio = null;
        currentAudioKey = null;
        if (token !== speakToken) {
          traceSpeak({ text: label, url, stopped: true, marks });
          return false;
        }

        if (waitUntilEnd && err instanceof Error && err.message === PLAY_CUT) {
          traceSpeak({ text: label, url, cut: true, marks });
          return false;
        }
      }

      try {
        const objectUrl = await loadSpeechAudio(url);
        marks.push(`blob=${Math.round(performance.now() - started)}ms`);
        if (token !== speakToken) {
          traceSpeak({ text: label, url, stopped: true, marks });
          return false;
        }
        await playUrl(objectUrl, url, content, waitUntilEnd);
        traceSpeak({
          text: label,
          url,
          played: true,
          viaBlob: true,
          totalMs: Math.round(performance.now() - started),
          marks,
        });
        return true;
      } catch (err) {
        marks.push(
          `blob-fail=${Math.round(performance.now() - started)}ms${
            err instanceof Error ? `(${err.name})` : ""
          }`
        );
        currentAudio = null;
        currentAudioKey = null;
        if (token !== speakToken) {
          traceSpeak({ text: label, url, stopped: true, marks });
          return false;
        }
        if (waitUntilEnd && err instanceof Error && err.message === PLAY_CUT) {
          traceSpeak({ text: label, url, cut: true, marks });
          return false;
        }
      }
    }
  }
  await speakWithBrowser(content, lang, waitUntilEnd);
  traceSpeak({
    text: label,
    browser: true,
    totalMs: Math.round(performance.now() - started),
    marks,
  });
  return false;
}

export function useSpeechSettings() {
  const [muted, setMutedState] = useState(false);
  const [autoSpeak, setAutoSpeakState] = useState(true);
  const [volume, setVolumeState] = useState(1);
  const [supported, setSupported] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {

    setSupported(canSpeak());
    setMutedState(window.localStorage.getItem(TTS_MUTED_KEY) === "1");

    setAutoSpeakState(window.localStorage.getItem(TTS_AUTO_KEY) !== "0");

    const rawVolume = window.localStorage.getItem(TTS_VOLUME_KEY);
    const initialVolume =
      rawVolume === null ? 1 : Math.min(1, Math.max(0, Number(rawVolume) || 0));
    setSpeechVolume(initialVolume);
    setVolumeState(initialVolume);
    setReady(true);

    let cancelled = false;

    void warmSpeechBackend().then((available) => {
      if (!cancelled && available) setSupported(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const setMuted = useCallback((next: boolean) => {
    setMutedState(next);
    window.localStorage.setItem(TTS_MUTED_KEY, next ? "1" : "0");

    if (next) cancelSpeechStream();
  }, []);

  const setAutoSpeak = useCallback((next: boolean) => {
    setAutoSpeakState(next);
    window.localStorage.setItem(TTS_AUTO_KEY, next ? "1" : "0");
    if (!next) cancelSpeechStream();
  }, []);

  const setVolume = useCallback((next: number) => {
    const clamped = Math.min(1, Math.max(0, next));
    setSpeechVolume(clamped);
    setVolumeState(clamped);
  }, []);

  return {
    muted,
    autoSpeak,
    volume,
    supported,
    ready,
    setMuted,
    setAutoSpeak,
    setVolume,
  };
}
