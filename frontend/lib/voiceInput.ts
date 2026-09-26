/**
 * 输入框的语音输入。
 *
 * 两条通道，默认走第二条：
 *
 * 1. **模型转写**：浏览器录音 → 检测到停顿就切一段 → 上传后端（后端转发给用户
 *    在「AI 模型」页配的那家 whisper / Qwen3-ASR / SenseVoice）→ 把带标点、
 *    首字母大写的文本实时填进输入框。
 * 2. **本地识别**（默认）：同一段音频交给服务器上的开源 whisper（见
 *    backend/app/services/local_asr.py），不需要任何 Key、不花用户的模型额度。
 *
 * 原来还有第三条「浏览器识别」（Web Speech API），已按产品要求删除：它依赖
 * 浏览器厂商的在线识别服务，内嵌 webview 里常常连不上（表现为「有时候识别
 * 不到」），而且没有标点和大小写。
 *
 * 和「按一次说一句」的老做法相比，这里解决的是三个具体毛病：
 *
 * * **说一半就被截断**：录音全程不停，只在检测到停顿（默认 1 秒静音）时切段；
 *   切段只是为了分批上传，用户没按停止就一直听着。
 * * **没有标点、没有大写**：模型转写天然带；万一返回的也是裸词串，
 *   polishTranscript 会补上大小写与句读。
 * * **识别不准**：走的是模型而不是浏览器内置识别。
 *
 * 向后端转发而不是前端直连模型服务，是为了不把 Key 暴露给浏览器，也让
 * 「用哪个转写模型」这件事只在后端处理一次。
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, type VoiceEngine } from "./api";

/**
 * 两条通道 + 「一条都没有」：都在服务端识别（见文件头的说明）。
 */
export type VoiceMode = VoiceEngine | "none";

/** 停顿多久算「这句说完了」。太短会把句子切碎，太长会让文字迟迟不出现。 */
const SILENCE_CUT_MS = 700;
/** 一段里至少说了这么久才值得上传，避免把咳嗽、翻页声送去识别。 */
const MIN_SPEECH_MS = 500;
/** 最长一段：一口气说太久就切一刀，免得单次上传过大、结果等太久。 */
const MAX_SEGMENT_MS = 12000;
/** 一直没人说话就把这段丢掉重开，避免录出一条无声的十几秒音频。 */
const IDLE_SEGMENT_MS = 15000;
/** 音量采样的间隔。用定时器而不是 rAF：内嵌 webview 里 rAF 会被节流。 */
const TICK_MS = 80;
/** 起录后先用这么久的采样估一下环境噪声，据此定说话的门槛。 */
const CALIBRATION_MS = 320;

/** 识别结果里的噪声标记：模型把静音/杂音转成这些占位文本时要丢掉。 */
const NOISE_PATTERN =
  /^\s*(?:\[.*?\]|\(.*?\)|\*.*?\*|♪+|嗯+|呃+|啊+|hmm+|uh+|um+)\s*[.?!]?\s*$/i;

/** 用户选过的识别通道，记在本地，下次进对话页还用同一条。 */
const ENGINE_KEY = "linguascene_voice_engine";

/** 没选过时默认本地识别：不花用户的模型额度，也不用配任何 Key。 */
const DEFAULT_ENGINE: VoiceEngine = "local";

/** 返回用户**显式选过**的通道，没选过返回 null（好和「默认」区分开）。 */
function savedEngine(): VoiceEngine | null {
  if (typeof window === "undefined") return null;
  const saved = window.localStorage.getItem(ENGINE_KEY);
  return saved === "model" || saved === "local" ? saved : null;
}

/** 弹窗问过一次就别再反复问（换通道这事用户知道入口在哪了）。 */
const PROMPT_SEEN_KEY = "linguascene_voice_channel_prompted";

function channelPromptSeen(): boolean {
  if (typeof window === "undefined") return true;
  return window.localStorage.getItem(PROMPT_SEEN_KEY) === "1";
}

function markChannelPromptSeen(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(PROMPT_SEEN_KEY, "1");
}

/** 三条通道的说明：探测结果里只带 id，文案在前端定，方便随时改口径。 */
export const ENGINE_LABELS: Record<VoiceEngine, { label: string; detail: string }> = {
  model: { label: "模型转写", detail: "用你自己接的模型，最准、带标点" },
  local: { label: "本地识别", detail: "在这台服务器上识别，免费、不需要 Key" },
};

/** 单段转写超过这个时间就提示用户模型转写在排队（免费额度的服务商常有）。 */
const SLOW_TRANSCRIBE_MS = 8000;

/** 选一个浏览器支持、后端也认的录音格式。 */
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

/**
 * 把一段识别文本整成能直接发出去的英文。
 *
 * 模型基本都自带标点与大小写，这里只补它可能漏掉的：独立的 i、句首字母、
 * 句末句读。是对**每段新文本**做的，不是对整句重做，所以不会越叠越多。
 */
export function polishTranscript(raw: string, startsSentence: boolean): string {
  let text = raw.replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (NOISE_PATTERN.test(text)) return "";

  // 中文标点偶尔会混进来（模型说中文时），换成英文的
  text = text
    .replace(/[，、]/g, ", ")
    .replace(/。/g, ". ")
    .replace(/？/g, "? ")
    .replace(/！/g, "! ")
    .replace(/\s+/g, " ")
    .trim();

  // 单词 i 与 i'm / i've / i'll / i'd
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

/** 两段文本相接，空段跳过。 */
function joinText(left: string, right: string): string {
  const a = left.trim();
  const b = right.trim();
  if (!a) return b;
  if (!b) return a;
  return `${a} ${b}`;
}

type VoiceOptions = {
  /** 输入框当前内容。用户中途手打时以它为准，识别结果往后接。 */
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
  /** 有音频正在转写：录音继续，但输入框那边看得出还在等文字。 */
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState("");
  /** 软提示：没听清、正在排队之类，不打断录音，只在状态行里说一句。 */
  const [notice, setNotice] = useState("");
  /** 模型转写这条通道能不能用（能用才谈得上「切换引擎」）。 */
  const [modelReady, setModelReady] = useState(false);
  /** 服务端当前可用的通道：至少两条时界面才给切换入口。 */
  const [engines, setEngines] = useState<VoiceEngine[]>([]);
  /**
   * 需要用户拿主意时弹的窗：他配的模型不支持语音输入（探测出来、或录到一半
   * 才发现），旁边还有哪些通道可选。绝不替他换通道——换通道是他自己的事。
   */
  const [channelPrompt, setChannelPrompt] = useState<{
    reason: string;
    options: VoiceEngine[];
  } | null>(null);
  /** 模型转写慢到需要提醒用户：免费额度的服务商会排队，一次要几十秒。 */
  const [modelSlow, setModelSlow] = useState(false);

  const valueRef = useRef(value);
  valueRef.current = value;

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const pendingUploadsRef = useRef(0);
  /** 上传排队：串行发送，保证文字顺序与说话顺序一致。 */
  const uploadChainRef = useRef<Promise<void>>(Promise.resolve());
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const tickTimerRef = useRef<number | null>(null);
  const wantListenRef = useRef(false);
  const recordingRef = useRef(false);

  // 分段状态（每次切段都重置）
  const segmentMsRef = useRef(0);
  const segmentSpeechMsRef = useRef(0);
  const sinceSpeechMsRef = useRef(0);
  const noiseFloorRef = useRef(0);
  const calibrationRef = useRef(0);
  /** 上一段定稿的文本：用来挡掉模型在静音上重复吐同一句的幻觉。 */
  const lastSegmentRef = useRef("");

  /** stop 的引用：切换通道那一步要用，但 stop 定义在后面。 */
  const stopRef = useRef<() => void>(() => {});
  /** 当前引擎的引用：上传那一步要按它决定请求参数，但它比回调变更频繁。 */
  const modeRef = useRef<VoiceMode>("none");
  modeRef.current = mode;
  /** 可用通道的引用：出错时要在回调里读最新的，不能吃闭包里的旧值。 */
  const enginesRef = useRef<VoiceEngine[]>([]);
  enginesRef.current = engines;

  /**
   * 把一段刚识别出的文字接到输入框末尾。
   *
   * 只做「追加」：每次都用输入框**当前**的内容往后接，所以用户边录边改、
   * 或者转写结果比打字晚到，都不会把已经写好的文字覆盖掉。
   *
   * 返回这次到底有没有接上：没接上通常是「这段没听清」（模型返回空、或者
   * 后端把听成中文的结果丢掉了），调用方据此提示用户重说，而不是毫无反应。
   */
  const appendText = useCallback(
    (raw: string): boolean => {
      const current = valueRef.current;
      const formatted = polishTranscript(
        raw,
        // 前面还没说过话，或者上一句已经以句末点号收尾 → 这句重新起头大写
        !current.trim() || /[.!?…]["')\]]?$/.test(current.trim())
      );
      if (!formatted) return false;
      // 静音段上模型偶尔会把上一句再说一遍（whisper 系的经典幻觉），别照抄
      if (formatted === lastSegmentRef.current) return false;
      lastSegmentRef.current = formatted;
      valueRef.current = joinText(current, formatted);
      setNotice("");
      onText(valueRef.current);
      return true;
    },
    [onText]
  );

  /** 探测有哪些识别通道可用，顺带让后端把转写模型试出来。 */
  useEffect(() => {
    let cancelled = false;
    const canRecord =
      typeof navigator !== "undefined" &&
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      typeof MediaRecorder !== "undefined";

    if (!canRecord) {
      // 浏览器不给录音权限/不支持 MediaRecorder：没有通道可用
      setMode("none");
      return () => {
        cancelled = true;
      };
    }

    api
      .audioStt()
      .then((status) => {
        if (cancelled) return;
        // 服务端能给哪几条通道：本地识别（默认）与用户的模型（备选）
        const available = new Set<VoiceEngine>(
          (status.engines ?? []).map((item) => item.id)
        );
        // 后端报了具体原因（格式不支持、模型不认转写）时不把模型通道算作可用，
        // 否则用户选了模型转写才在录音中途撞上 503。
        if (status.available && !status.reason) available.add("model");
        // 展示顺序即按钮顺序：默认那条（本地识别）排前面
        const usable = ([DEFAULT_ENGINE, "model"] as VoiceEngine[]).filter((id) =>
          available.has(id)
        );
        setEngines(usable);
        setModelReady(available.has("model"));

        // 用户自己选过、且这条通道还能用 → 继续用它。没选过就用默认的本地识别；
        // 服务器没开本地识别时才回落到他自己配的模型。用户显式选过的那条不能用了，
        // 也不替他挑别的——弹窗问过他再说。
        const saved = savedEngine();
        const preferred = saved ?? DEFAULT_ENGINE;
        const modelRejected = saved === "model" && !available.has("model");
        if (!modelRejected && usable.includes(preferred)) {
          setMode(preferred);
        } else if (!saved && usable.length > 0) {
          setMode(usable[0]);
        } else {
          setMode("none");
          // 他选的通道用不了，而旁边还有别的通道：问一次。
          // 模型通道被明确拒绝（格式不支持、或探测过不认转写）时也走这里，
          // 进页面就说清，不必等录完一段才弹窗。
          if (usable.length > 0 && !channelPromptSeen()) {
            setChannelPrompt({
              reason: status.reason || "",
              options: modelRejected ? usable.filter((id) => id !== "model") : usable,
            });
          }
        }
      })
      .catch(() => {
        // 探测失败不代表不能用：真实请求会再试，失败时再提示用户换通道
        if (!cancelled) {
          setModelReady(true);
          setMode(savedEngine() ?? DEFAULT_ENGINE);
        }
      });

    return () => {
      cancelled = true;
    };
    // 只在挂载时探测一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * 换一条识别通道。
   *
   * 两条路各有取舍，选哪个用户说了算：模型转写用他自己配的那家（最准），
   * 本地识别用服务器上的开源 whisper（不花他的 API 额度）。选过之后记在本地，
   * 下次进来还用这条。
   */
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

  /** 收下当前这一段，交给转写队列。 */
  const cutSegment = useCallback(() => {
    const recorder = recorderRef.current;
    segmentMsRef.current = 0;
    segmentSpeechMsRef.current = 0;
    sinceSpeechMsRef.current = 0;
    if (!recorder || recorder.state === "inactive") return;
    try {
      recorder.stop();
    } catch {
      // 已经停了，忽略
    }
  }, []);

  /** 停掉模型这条通道的录音与采集（用户已说出的文字不受影响）。 */
  const stopModelCapture = useCallback(() => {
    wantListenRef.current = false;
    recordingRef.current = false;
    setRecording(false);
    stopTicker();
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (recorder && recorder.state !== "inactive") {
      // 最后一段先交给 onstop 收走，收完再由它关掉采集：直接关流会把刚说的
      // 那半句连同音频一起丢掉，「我还没说完就被截断」正是这么来的。
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

  /** 上传一段录音并把它接进输入框。 */
  const uploadSegment = useCallback(
    (blob: Blob, mimeType: string) => {
      // 用哪条通道由用户选定的引擎决定：后端只负责执行，不会替他换
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
            // 没听出英文（静音、杂音，或者听成了中文被后端丢掉）
            setNotice("这句没听清，再说一遍试试");
          } else if (Date.now() - startedAt > SLOW_TRANSCRIBE_MS) {
            setModelSlow(true);
          }
        } catch (err) {
          if (err instanceof ApiError && err.status === 503) {
            // 他配的模型不支持语音输入：停下来问他，不替他换通道
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

  /** 起一段新的录音（切段之后接着录）。 */
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
      // 太短的段多半是杂音，不值得花一次转写
      if (blob.size > 2000 && Date.now() - startedAt > MIN_SPEECH_MS) {
        uploadSegment(blob, type);
      }
      if (wantListenRef.current) {
        startSegment();
      } else if (recorderRef.current === null) {
        // 用户已经按了停止：最后一段收完了，这时候才关麦克风
        teardownAudio();
      }
    };

    recorderRef.current = recorder;
    segmentMsRef.current = 0;
    segmentSpeechMsRef.current = 0;
    sinceSpeechMsRef.current = 0;
    recorder.start();
  }, [teardownAudio, uploadSegment]);

  /** 音量采样：判断在说话还是在停顿。
   *
   * 时间一律用真实时钟差累加，而不是「tick 次数 × 间隔」：标签页切到后台时
   * 定时器会被浏览器节流到 1 秒甚至更久一次，按次数算的话分段时长会缩水十几
   * 倍，用户说半天也切不出一段。
   */
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
        // 取最低音量当环境噪声：用户可能一点下麦克风就开口，用最高值会把
        // 门槛抬到说话都过不去（那就永远切不出句子）。
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
      // 小窗口：VAD 只需要粗略音量，大窗口要攒更久才出一帧
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

  // 离开页面 / 输入框被禁用时别再录
  useEffect(() => stop, [stop]);
  useEffect(() => {
    if (disabled && recordingRef.current) stop();
  }, [disabled, stop]);

  stopRef.current = stop;

  const listening = recording || transcribing;

  return {
    supported: mode !== "none",
    /** 当前用的识别通道 */
    mode,
    /** 正在听（含还在等文字回来） */
    listening,
    recording,
    transcribing,
    error,
    clearError,
    /** 软提示：没听清 / 模型在排队，不打断录音 */
    notice,
    clearNotice: useCallback(() => setNotice(""), []),
    toggle,
    stop,
    setEngine,
    /** 服务端 + 浏览器当前可用的通道，界面据此决定给不给切换入口 */
    engines,
    /** 需要用户拿主意的弹窗（模型不支持语音输入时） */
    channelPrompt,
    /** 用户在弹窗里选了某条通道：记住它，并把弹窗收起来 */
    chooseChannel: useCallback((next: VoiceEngine) => {
      markChannelPromptSeen();
      window.localStorage.setItem(ENGINE_KEY, next);
      setMode(next);
      setChannelPrompt(null);
      setError("");
    }, []),
    /** 用户不想换：收窗并记住别再问 */
    dismissChannelPrompt: useCallback(() => {
      markChannelPromptSeen();
      setChannelPrompt(null);
    }, []),
    /** 模型转写慢到值得提醒（免费额度的服务商在排队） */
    modelSlow,
  };
}
