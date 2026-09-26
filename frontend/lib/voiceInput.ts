"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, type VoiceEngine } from "./api";

export type VoiceMode = VoiceEngine | "none";

const SILENCE_CUT_MS = 700;

const MIN_SPEECH_MS = 500;

const MAX_SEGMENT_MS = 12000;

const IDLE_SEGMENT_MS = 15000;

const TICK_MS = 80;

const CALIBRATION_MS = 320;

const NOISE_PATTERN =
  /^\s*(?:\[.*?\]|\(.*?\)|\*.*?\*|♪+|嗯+|呃+|啊+|hmm+|uh+|um+)\s*[.?!]?\s*$/i;

const ENGINE_KEY = "linguascene_voice_engine";

const DEFAULT_ENGINE: VoiceEngine = "local";

function savedEngine(): VoiceEngine | null {
  if (typeof window === "undefined") return null;
  const saved = window.localStorage.getItem(ENGINE_KEY);
  return saved === "model" || saved === "local" ? saved : null;
}

const PROMPT_SEEN_KEY = "linguascene_voice_channel_prompted";

function channelPromptSeen(): boolean {
  if (typeof window === "undefined") return true;
  return window.localStorage.getItem(PROMPT_SEEN_KEY) === "1";
}

function markChannelPromptSeen(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(PROMPT_SEEN_KEY, "1");
}

export const ENGINE_LABELS: Record<VoiceEngine, { label: string; detail: string }> = {
  model: { label: "模型转写", detail: "用你自己接的模型，最准、带标点" },
  local: { label: "本地识别", detail: "在这台服务器上识别，免费、不需要 Key" },
};

const SLOW_TRANSCRIBE_MS = 8000;

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  return candidates.find(
    (type) => MediaRecorder.isTypeSupported?.(type) ?? false
  );
}

function extensionFor(mimeType: string): string {
  if (mimeType.includes("mp4")) return "m4a";
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("wav")) return "wav";
  return "webm";
}

function polishTranscript(raw: string, startsSentence: boolean): string {
  let text = raw.replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (NOISE_PATTERN.test(text)) return "";

  text = text
    .replace(/[，、]/g, ", ")
    .replace(/。/g, ". ")
    .replace(/？/g, "? ")
    .replace(/！/g, "! ")
    .replace(/\s+/g, " ")
    .trim();

  text = text
    .replace(/\bi'(m|ve|ll|d)\b/gi, (_match, tail: string) => `I'${tail.toLowerCase()}`)
    .replace(/\bi\b/g, "I");

  if (startsSentence) {
    text = text[0].toUpperCase() + text.slice(1);
  }
  if (!/[.!?…"')\]]$/.test(text)) {
    text = `${text}.`;
  }
  return text;
}

function joinText(left: string, right: string): string {
  const a = left.trim();
  const b = right.trim();
  if (!a) return b;
  if (!b) return a;
  return `${a} ${b}`;
}

type VoiceOptions = {

  value: string;
  onText: (text: string) => void;
  lang?: string;
  disabled?: boolean;
};

export function useVoiceInput({
  value,
  onText,
  lang = "en-US",
  disabled = false,
}: VoiceOptions) {
  const [mode, setMode] = useState<VoiceMode>("none");
  const [recording, setRecording] = useState(false);

  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState("");

  const [notice, setNotice] = useState("");

  const [modelReady, setModelReady] = useState(false);

  const [engines, setEngines] = useState<VoiceEngine[]>([]);

  const [channelPrompt, setChannelPrompt] = useState<{
    reason: string;
    options: VoiceEngine[];
  } | null>(null);

  const [modelSlow, setModelSlow] = useState(false);

  const valueRef = useRef(value);
  valueRef.current = value;

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const pendingUploadsRef = useRef(0);

  const uploadChainRef = useRef<Promise<void>>(Promise.resolve());
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const tickTimerRef = useRef<number | null>(null);
  const wantListenRef = useRef(false);
  const recordingRef = useRef(false);

  const segmentMsRef = useRef(0);
  const segmentSpeechMsRef = useRef(0);
  const sinceSpeechMsRef = useRef(0);
  const noiseFloorRef = useRef(0);
  const calibrationRef = useRef(0);

  const lastSegmentRef = useRef("");

  const stopRef = useRef<() => void>(() => {});

  const modeRef = useRef<VoiceMode>("none");
  modeRef.current = mode;

  const enginesRef = useRef<VoiceEngine[]>([]);
  enginesRef.current = engines;

  const appendText = useCallback(
    (raw: string): boolean => {
      const current = valueRef.current;
      const formatted = polishTranscript(
        raw,

        !current.trim() || /[.!?…]["')\]]?$/.test(current.trim())
      );
      if (!formatted) return false;

      if (formatted === lastSegmentRef.current) return false;
      lastSegmentRef.current = formatted;
      valueRef.current = joinText(current, formatted);
      setNotice("");
      onText(valueRef.current);
      return true;
    },
    [onText]
  );

  useEffect(() => {
    let cancelled = false;
    const canRecord =
      typeof navigator !== "undefined" &&
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      typeof MediaRecorder !== "undefined";

    if (!canRecord) {

      setMode("none");
      return () => {
        cancelled = true;
      };
    }

    api
      .audioStt()
      .then((status) => {
        if (cancelled) return;

        const available = new Set<VoiceEngine>(
          (status.engines ?? []).map((item) => item.id)
        );

        if (status.available && !status.reason) available.add("model");

        const usable = ([DEFAULT_ENGINE, "model"] as VoiceEngine[]).filter((id) =>
          available.has(id)
        );
        setEngines(usable);
        setModelReady(available.has("model"));

        const saved = savedEngine();
        const preferred = saved ?? DEFAULT_ENGINE;
        const modelRejected = saved === "model" && !available.has("model");
        if (!modelRejected && usable.includes(preferred)) {
          setMode(preferred);
        } else if (!saved && usable.length > 0) {
          setMode(usable[0]);
        } else {
          setMode("none");

          if (usable.length > 0 && !channelPromptSeen()) {
            setChannelPrompt({
              reason: status.reason || "",
              options: modelRejected ? usable.filter((id) => id !== "model") : usable,
            });
          }
        }
      })
      .catch(() => {

        if (!cancelled) {
          setModelReady(true);
          setMode(savedEngine() ?? DEFAULT_ENGINE);
        }
      });

    return () => {
      cancelled = true;
    };

  }, []);

  const setEngine = useCallback(
    (next: VoiceEngine) => {
      if (next === "model" && !modelReady) return;
      if (next === "local" && !engines.includes("local")) return;
      window.localStorage.setItem(ENGINE_KEY, next);
      if (recordingRef.current) stopRef.current();
      setMode(next);
    },
    [modelReady, engines]
  );

  const stopTicker = useCallback(() => {
    if (tickTimerRef.current !== null) {
      window.clearInterval(tickTimerRef.current);
      tickTimerRef.current = null;
    }
  }, []);

  const teardownAudio = useCallback(() => {
    stopTicker();
    analyserRef.current = null;
    const ctx = audioCtxRef.current;
    audioCtxRef.current = null;
    if (ctx) void ctx.close().catch(() => {});
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, [stopTicker]);

  const clearError = useCallback(() => setError(""), []);

  const cutSegment = useCallback(() => {
    const recorder = recorderRef.current;
    segmentMsRef.current = 0;
    segmentSpeechMsRef.current = 0;
    sinceSpeechMsRef.current = 0;
    if (!recorder || recorder.state === "inactive") return;
    try {
      recorder.stop();
    } catch {

    }
  }, []);

  const stopModelCapture = useCallback(() => {
    wantListenRef.current = false;
    recordingRef.current = false;
    setRecording(false);
    stopTicker();
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (recorder && recorder.state !== "inactive") {

      segmentMsRef.current = 0;
      segmentSpeechMsRef.current = 0;
      try {
        recorder.stop();
      } catch {
        teardownAudio();
      }
    } else {
      teardownAudio();
    }
  }, [stopTicker, teardownAudio]);

  const uploadSegment = useCallback(
    (blob: Blob, mimeType: string) => {

      const wanted: VoiceEngine = modeRef.current === "local" ? "local" : "model";
      pendingUploadsRef.current += 1;
      setTranscribing(true);
      const task = uploadChainRef.current.then(async () => {
        const startedAt = Date.now();
        try {
          const result = await api.transcribe(
            blob,
            `speech.${extensionFor(mimeType)}`,
            "en",
            wanted
          );
          const applied = appendText(result.text ?? "");
          if (!applied) {

            setNotice("这句没听清，再说一遍试试");
          } else if (Date.now() - startedAt > SLOW_TRANSCRIBE_MS) {
            setModelSlow(true);
          }
        } catch (err) {
          if (err instanceof ApiError && err.status === 503) {

            setChannelPrompt({
              reason: err.message,
              options: enginesRef.current.filter((id) => id !== "model"),
            });
          } else if (err instanceof ApiError && err.status === 401) {
            setError("登录已过期，请重新登录后再用语音输入");
          } else {
            setError(err instanceof ApiError ? err.message : "这段没识别成功，请再说一遍");
          }
        } finally {
          pendingUploadsRef.current -= 1;
          if (pendingUploadsRef.current <= 0) {
            pendingUploadsRef.current = 0;
            setTranscribing(false);
          }
        }
      });
      uploadChainRef.current = task.catch(() => {});
    },
    [appendText]
  );

  const startSegment = useCallback(() => {
    const stream = streamRef.current;
    if (!stream || !wantListenRef.current) return;
    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = mimeType
        ? new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 })
        : new MediaRecorder(stream);
    } catch {
      wantListenRef.current = false;
      setRecording(false);
      setError("无法开始录音，请检查麦克风权限");
      return;
    }

    chunksRef.current = [];
    const startedAt = Date.now();
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];

      if (blob.size > 2000 && Date.now() - startedAt > MIN_SPEECH_MS) {
        uploadSegment(blob, type);
      }
      if (wantListenRef.current) {
        startSegment();
      } else if (recorderRef.current === null) {

        teardownAudio();
      }
    };

    recorderRef.current = recorder;
    segmentMsRef.current = 0;
    segmentSpeechMsRef.current = 0;
    sinceSpeechMsRef.current = 0;
    recorder.start();
  }, [teardownAudio, uploadSegment]);

  const startTicker = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const buffer = new Uint8Array(analyser.fftSize);
    stopTicker();
    let lastTick = Date.now();
    tickTimerRef.current = window.setInterval(() => {
      const node = analyserRef.current;
      if (!node) return;
      const now = Date.now();
      const elapsed = Math.min(now - lastTick, 2000);
      lastTick = now;

      node.getByteTimeDomainData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i += 1) {
        const value = (buffer[i] - 128) / 128;
        sum += value * value;
      }
      const rms = Math.sqrt(sum / buffer.length);

      if (calibrationRef.current < CALIBRATION_MS) {

        calibrationRef.current += elapsed;
        noiseFloorRef.current = noiseFloorRef.current
          ? Math.min(noiseFloorRef.current, rms || noiseFloorRef.current)
          : rms;
        return;
      }

      const threshold = Math.min(
        Math.max(noiseFloorRef.current * 2.4, 0.012),
        0.08
      );
      const speaking = rms > threshold;
      segmentMsRef.current += elapsed;
      if (speaking) {
        segmentSpeechMsRef.current += elapsed;
        sinceSpeechMsRef.current = 0;
      } else {
        sinceSpeechMsRef.current += elapsed;
      }

      const quietEnough =
        sinceSpeechMsRef.current >= SILENCE_CUT_MS &&
        segmentSpeechMsRef.current >= MIN_SPEECH_MS;
      const tooLong = segmentMsRef.current >= MAX_SEGMENT_MS;
      const wastedAir =
        segmentMsRef.current >= IDLE_SEGMENT_MS &&
        segmentSpeechMsRef.current < MIN_SPEECH_MS;
      if (quietEnough || tooLong || wastedAir) {
        cutSegment();
      }
    }, TICK_MS);
  }, [cutSegment, stopTicker]);

  const stop = useCallback(() => {
    stopModelCapture();
  }, [stopModelCapture]);

  const start = useCallback(async () => {
    if (disabled) return;
    setError("");
    noiseFloorRef.current = 0;
    calibrationRef.current = 0;

    if (mode === "none") {
      setError("当前环境不支持语音输入，请改用键盘输入");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      const Ctor: typeof AudioContext =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new Ctor();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();

      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;
    } catch {
      setError("没有拿到麦克风权限，请在浏览器设置里允许后重试");
      return;
    }

    wantListenRef.current = true;
    recordingRef.current = true;
    setRecording(true);
    startSegment();
    startTicker();
  }, [disabled, mode, startSegment, startTicker]);

  const toggle = useCallback(() => {
    if (recordingRef.current) {
      stop();
    } else {
      void start();
    }
  }, [start, stop]);

  useEffect(() => stop, [stop]);
  useEffect(() => {
    if (disabled && recordingRef.current) stop();
  }, [disabled, stop]);

  stopRef.current = stop;

  const listening = recording || transcribing;

  return {
    supported: mode !== "none",

    mode,

    listening,
    recording,
    transcribing,
    error,
    clearError,

    notice,
    clearNotice: useCallback(() => setNotice(""), []),
    toggle,
    stop,
    setEngine,

    engines,

    channelPrompt,

    chooseChannel: useCallback((next: VoiceEngine) => {
      markChannelPromptSeen();
      window.localStorage.setItem(ENGINE_KEY, next);
      setMode(next);
      setChannelPrompt(null);
      setError("");
    }, []),

    dismissChannelPrompt: useCallback(() => {
      markChannelPromptSeen();
      setChannelPrompt(null);
    }, []),

    modelSlow,
  };
}
