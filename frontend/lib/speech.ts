/**
 * 朗读（TTS）封装。
 *
 * 优先走后端 edge-tts（GET /api/audio/tts），因为内嵌 webview 的
 * speechSynthesis 常常只装了中文语音，读英文会「点了没声音」；后端拿不到
 * 音频时再回退到浏览器朗读。
 *
 * 后端维持着一小组常驻的合成连接（backend/app/services/audio_service.py），
 * 连接热着时一句约 0.3~0.5s，命中磁盘缓存只要几毫秒；只有池子冷启动（后端
 * 刚起 / 空闲太久被服务端断连）才要付一次 1s 上下的建连。所以真正的优化方向
 * 不是把合成做快，而是让用户点下去之前音频就已经在路上。
 *
 * 注意：这 2 秒是「后端已绕开系统代理」时的数字。后端的 aiohttp 会读系统
 * 代理，本机装了本地代理时握手会被拖到 6 秒以上——那部分修在
 * `backend/app/services/audio_service.py`，前端这边看不到，别在这里找原因。
 *
 * 这里补了五件事：
 * 1. 前端把合成结果按 URL 缓存成 blob，重播不再走网络，也避免并发重复合成；
 * 2. 暴露 prefetchSpeech，让页面在 AI 回复到达、句子滚进视野、鼠标悬停、
 *    上一句播完时就提前合成——点击时通常已经命中缓存，感知上就是「瞬间出声」；
 * 3. 预取走一个带优先级的限流队列：悬停/下一句这类明确意图插队，背景批量预取
 *    让路；同时最多跑 PREFETCH_CONCURRENCY 个，避免几十条连接互相拖慢。
 * 4. AI 回复**边流边念**（startSpeechStream / feedSpeechStream / endSpeechStream）：
 *    回复还在逐字生成时，已经写完的句子就先送去合成、按下句串行念出来。以前是等
 *    `reply` 帧（整段回复）到了才开始合成，长回复要「文字全部到齐 + 一次冷合成」
 *    才出声，用户感知就是慢、而且时有时无。
 * 5. 每次朗读都有等待上限（START_TIMEOUT_MS / playbackTimeoutMs）：后端卡住时
 *    play() 会一直悬着，转圈永远停不下来——边界一到就当这次失败，退回 blob 或
 *    浏览器朗读，宁可音质差一点也不要「点了没反应」。
 *
 * 曾经还有一个「本地语音」开关（改用浏览器自带语音换取零延迟），已按产品要求
 * 下线：朗读一律走后端合成，只有在拿不到音频时才回退浏览器朗读。
 *
 * 语音输入（STT）在 `lib/voiceInput.ts`：走用户自己的模型或服务端本地识别，
 * 原来那条浏览器 Web Speech 通道已按产品要求删除（内嵌 webview 里连不上
 * 浏览器厂商的识别服务，识别质量也差）。
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const TTS_MUTED_KEY = "linguascene_tts_muted";
const TTS_AUTO_KEY = "linguascene_tts_auto";
const TTS_VOLUME_KEY = "linguascene_tts_volume";

/** 学习场景下语速略慢一些，和单词卡的朗读保持一致。 */
const SPEECH_RATE = 0.9;

/**
 * 等音频真正出声的上限。
 *
 * 后端合成一句要 0.5~2s（连接池冷、或走系统代理时实测 6.5s 上下），超过这个
 * 时间就判定这次直连没戏、退到下一步。没有上限时 play() 可能一直悬着：按钮上的
 * 转圈永远停不下来、流式朗读也卡在这一句，用户看到的就是「点了没反应」。
 */
const START_TIMEOUT_MS = 12000;

/** 逐句流式朗读时一整句（含合成 + 播完）的等待上限，按字数据估算并留足余量。 */
function playbackTimeoutMs(text: string): number {
  return START_TIMEOUT_MS + text.length * 120;
}

/** 后端整句合成地址。同源 /api 由 next.config.mjs 代理到后端。 */
function ttsUrl(text: string, lang: string): string {
  return `/api/audio/tts?text=${encodeURIComponent(text)}&lang=${encodeURIComponent(lang)}`;
}

// ---------------------------------------------------------------- 朗读（TTS）

export function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** 当前正在播放的后端语音，用于再次朗读前打断。 */
let currentAudio: HTMLAudioElement | null = null;

/**
 * 正在播放的音频对应的**缓存 key**（audioCache 里的那个 URL）。
 *
 * 播 blob 时 <audio> 的 src 是 objectURL、缓存 key 是 ttsUrl，两者不等，
 * 所以淘汰缓存时必须拿这个 key 比对，否则会把正在播的 blob 吊销掉——
 * 表现就是「念到一半突然没声了」。
 */
let currentAudioKey: string | null = null;

/** 音量对所有朗读通道生效（后端 mp3 与浏览器朗读），取值 0~1。 */
let currentVolume = 1;

/** 每次朗读/打断都会自增；异步加载音频回来后据此丢弃过期请求。 */
let speakToken = 0;

export function setSpeechVolume(next: number): void {
  currentVolume = Math.min(1, Math.max(0, next));
  if (currentAudio) currentAudio.volume = currentVolume;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TTS_VOLUME_KEY, String(currentVolume));
  }
}

/** 当前音量，供单词发音等自建 Audio 的通道复用。 */
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

/** 浏览器朗读兜底：优先挑一个和 lang 完全匹配的语音，挑不到退到同语系。 */
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

  // 没有和语言匹配的语音时，内嵌 webview 里 speak() 是无声的，而且 end/error
  // 都不一定触发——逐句朗读不能在这种句子上各等一次超时，直接当没出声。
  if (!voice) return Promise.resolve(false);

  // 逐句流式朗读必须等这句念完再念下一句：否则下一次 speak() 开头的 cancel()
  // 会把上句掐掉，一整段回复只剩最后半句有声音。内嵌 webview 里没有英文语音时
  // `end` 永远不会触发，这里的超时是唯一的出口。
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

/**
 * 已合成音频的 blob 缓存，key 是 ttsUrl。
 *
 * 后端同一句话第二次是毫秒级命中，但浏览器仍要再发一次请求；缓存成 blob 后
 * 重播、自动朗读与手动点读之间不再重复走网络，也顺手挡住并发重复合成。
 */
const audioCache = new Map<string, Promise<string>>();
/** 一篇文章几十句都会被预取，上限留够，否则读到后面会把开头的挤掉。 */
const AUDIO_CACHE_LIMIT = 120;
const AUDIO_FETCH_TIMEOUT_MS = 12000;

/**
 * 超出上限时淘汰最旧的一条。
 *
 * 正在播的那条只从表里摘掉、不吊销 URL：浏览器可能还要按 range 回读同一个
 * blob，提前 revoke 会让播放中途断掉。让它随页面一起释放即可。
 *
 * 比的是 `currentAudioKey` 而不是 `currentAudio.src`——播 blob 时 src 是
 * objectURL、表里的 key 是 ttsUrl，拿 src 比对永远不相等，等于没拦。
 */
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
  // 失败不留在缓存里，否则一次网络抖动会被钉死。
  task.catch(() => audioCache.delete(url));

  trimAudioCache();
  return task;
}

/**
 * 预取队列。
 *
 * 一次页面里可能有几十句话要朗读，全部并发丢给 edge-tts 会互相拖慢甚至被限流，
 * 所以排成队列限流跑。队列的意义在于「排优先级」：用户鼠标悬停、刚播完一句要
 * 听下一句，这些是明确的意图，插到队首；句子滚进视野触发的背景预取排在后面。
 *
 * 并发度定得比较高的原因是合成的开销几乎全是**每条连接自己的握手**（实测首块
 * 音频 1.5~2s、剩下的音频一共才 0.3s），彼此不争带宽：8 路并发各自跑完仍是
 * 7s 上下，而 2 路并发跑 8 句要 4 个来回、接近 26s。所以这里提并发几乎不要钱，
 * 却直接决定了整篇文章「多久之后全部可秒播」。
 *
 * 但不能贴着后端连接池的容量跑（POOL_SIZE=8）：点击喇叭的请求不走这个队列、
 * 直接打进后端，池子必须常有空槽接着，否则点的那句要排在整篇背景预取后面
 * 干等。留 6 路给背景预取、剩下留给悬停/点击/「听下一句」这些 urgent 请求——
 * 背景慢半拍没关系，反正用户真正想听的那句永远插队。
 */
const PREFETCH_CONCURRENCY = 6;

type PrefetchTask = { url: string; urgent: boolean };

const prefetchQueue: PrefetchTask[] = [];
/** 已在队列里的 url，避免滚进视野 + 悬停把同一句排两次。 */
const prefetchQueued = new Set<string>();
let prefetchRunning = 0;

function pumpPrefetchQueue(): void {
  while (prefetchRunning < PREFETCH_CONCURRENCY && prefetchQueue.length > 0) {
    // 队列很短（一篇文章的量级），每次取队首前重排一次的代价可以忽略
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
  // 已经在缓存里（含正在取）就不必再排队
  if (prefetchQueued.has(url) || audioCache.has(url)) return;
  prefetchQueued.add(url);
  prefetchQueue.push({ url, urgent });
  pumpPrefetchQueue();
}

/**
 * 后端能不能合成语音：null 表示还没探测出来。
 *
 * 后端没装 edge-tts 时 /api/audio/tts 一律 404，预取就成了每次滚动、悬停都白发
 * 一串请求。探测到不能合成后直接关掉预取，朗读仍走浏览器语音兜底。
 */
let backendTts: boolean | null = null;

function setBackendTtsAvailable(next: boolean): void {
  backendTts = next;
}

/** 能力探测只打一次：多个页面（场景详情、对话页）都会调。 */
let backendProbe: Promise<boolean> | null = null;

/**
 * 提前把后端朗读准备好：探查能力（顺带让后端预热合成连接池）。
 *
 * 场景详情页会在用户读说明时就调用——等真正进对话页听到第一句时，连接已经
 * 热着、音频也多半已经在路上，而不是现场付一次建连 + 合成的钱。
 *
 * 返回「后端能不能合成语音」，调用方可以据此决定要不要显示朗读控件。
 *
 * options.force 用于「用户刚开口、AI 马上要回话」这种时刻：能力本身没变，但
 * 后端的合成连接闲置 20~40s 就会被服务端断掉，重探一次等于让后端把连接池重新
 * 热起来，第一句 AI 回复就不用现场付握手钱。不传就是全程只探一次（页面加载）。
 */
export function warmSpeechBackend(
  options: { force?: boolean } = {}
): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if (options.force) backendProbe = null;
  if (!backendProbe) {
    backendProbe = fetch("/api/audio/capability")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const available = Boolean(data?.tts);
        setBackendTtsAvailable(available);
        return available;
      })
      .catch(() => {
        // 探测失败就沿用浏览器能力判断，也别把预取关掉
        return false;
      });
  }
  return backendProbe;
}

/**
 * 提前把音频取回来，用户点朗读时就能立刻出声。
 *
 * urgent 用于「用户马上就会点」的场景（悬停、播放下一句），会插到背景预取前面。
 * url 用于内置开场白这类有静态文件的句子：直接取文件，连后端都不用惊动。
 */
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

/**
 * 清空尚未开始的预取。
 *
 * 离开精读页面时调用：否则用户在别的页面里还要替一篇已经关掉的文章合成几十句。
 * 已经开始的那一两个请求拦不住，让它们跑完即可。
 */
export function cancelPrefetchSpeech(): void {
  prefetchQueue.length = 0;
  prefetchQueued.clear();
}

// ------------------------------------------------------- 流式逐句朗读（AI 回复）

/**
 * 从流式文本里切出「已经写完的句子」，返回 [完整句子, 剩下的尾巴]。
 *
 * 边界是句末标点（后面跟空白或正好在末尾）与换行。末尾也算边界很关键：AI 写出
 * "Hi there!" 的时候这一句就已经可以念了，不用等它把整段回复写完——那样又退回
 * 「等整段到齐」的老路。
 *
 * 不留「太短就攒着」的规则：攒着等于把「开口的第一声」往后推，而短句（"Oh!"）
 * 走 edge-tts 单独合成照样是正常的一句。
 */
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
  /** 到目前为止喂进来的全文长度，用来只取增量（见 feedSpeechStream）。 */
  seen: number;
  /** 还没成句的尾巴（AI 正在写的那半句）。 */
  buffer: string;
  /** 已切好、等着念的句子。 */
  queue: string[];
  /** 有一句正在念。 */
  active: boolean;
};

let speechStream: SpeechStream | null = null;
let speechStreamSeq = 0;

/** 取下一句念；念完（或这一句失败）再取一句。失败不中断整段。 */
function pumpSpeechStream(): void {
  const stream = speechStream;
  if (!stream || stream.active) return;
  const sentence = stream.queue.shift();
  if (!sentence) return;
  stream.active = true;
  // 念这一句的同时只把**下一句**合成好：既接得顺，又不和「正在念的这句」重复
  // 请求同一个 URL（speak 是直连播放，本身就带一次合成）。
  const next = stream.queue[0];
  if (next) prefetchSpeech(next, { urgent: true });
  void speak(sentence, "en-US", { waitUntilEnd: true }).finally(() => {
    // 期间换了新回复（或被取消）时，这个 finally 属于上一段，别再往下推进
    if (speechStream !== stream) return;
    stream.active = false;
    pumpSpeechStream();
  });
}

/**
 * 开始一次「边流边念」的自动朗读，返回这一次的 id。
 *
 * 调用方（对话页）在 AI 回复开始流式生成时调用，之后每个文本块都喂给
 * feedSpeechStream：句子一写完就立刻送去合成并排队念，不用等整段回复结束。
 * 这就是「自动朗读慢」的主因——以前要等 `reply` 帧（整段回复）到齐才开始合成，
 * 长回复会白等几秒到十几秒，用户看着字都打完了却没声音。
 *
 * 重复调用会打断上一次：用户又发了一句时，旧回复不该继续念。
 */
export function startSpeechStream(): number {
  cancelSpeechStream();
  const id = ++speechStreamSeq;
  speechStream = { id, seen: 0, buffer: "", queue: [], active: false };
  return id;
}

/**
 * 喂进「到目前为止的 AI 回复全文」，只取比上次多出来的增量。
 *
 * 传全文而不是块：后端偶尔会重发某一帧，那样一句会被排队念两遍；按长度取增量
 * 天然去重，也让调用方不必自己维护一份拼接结果。
 */
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

/**
 * 流结束（AI 回复收尾）：把尾巴上没标点的那半句也念掉。
 *
 * 长回复的最后一句往往不带结尾标点，不补这一步就会「最后半句没声音」。
 */
export function endSpeechStream(id: number): void {
  const stream = speechStream;
  if (!stream || stream.id !== id) return;
  const tail = stream.buffer.trim();
  stream.buffer = "";
  if (tail) stream.queue.push(tail);
  pumpSpeechStream();
}

/**
 * 放弃当前流式朗读并静音。
 *
 * 用户手动点了别的喇叭、关掉自动朗读、离开页面时调用——不然那一串句子还会
 * 继续往下念，盖住用户真正想听的那句。
 */
export function cancelSpeechStream(): void {
  const stream = speechStream;
  speechStream = null;
  if (stream) stream.queue.length = 0;
  stopSpeaking();
}

/**
 * 最近几次朗读的耗时打点（localStorage 留 20 条）。
 *
 * 「这次怎么半天没出声」在这条链路上有好几种可能：取静态文件慢、后端合成慢、
 * 自动播放被浏览器拦、回退到浏览器朗读（内嵌 webview 没有英文语音时它是无声的）。
 * 现场看不出来是哪一种，所以每次朗读都把关键时间点留下，事后直接读
 * `localStorage.linguascene_tts_trace` 就知道卡在哪一段。
 */
const TRACE_KEY = "linguascene_tts_trace";

function traceSpeak(entry: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(TRACE_KEY);
    const list = raw ? (JSON.parse(raw) as unknown[]) : [];
    list.push({ at: new Date().toISOString(), ...entry });
    window.localStorage.setItem(TRACE_KEY, JSON.stringify(list.slice(-20)));
  } catch {
    // 打点失败不影响朗读
  }
}

/**
 * 音频「已出声、中途才断」的标记。
 *
 * 这种失败不该再退回下一档重播——用户会听到同一句从头念两遍。要么是这次朗读
 * 被打断（打断时 token 会变，调用方先判断 token），要么是真的播到一半断了。
 */
const PLAY_CUT = "play-cut";

/**
 * 播一段音频，resolve 表示成功。
 *
 * 和单词书同一套做法：把 URL 直接交给 <audio>，由浏览器自己流式加载，
 * 不先 fetch 成 blob。currentAudio 先登记好，stopSpeaking() 才打断得到它。
 *
 * waitUntilEnd 为 true 时等到整段**播完**才 resolve（逐句流式朗读要按顺序念，
 * 上一句没念完不能开下一句）；为 false 时一出声就 resolve（点读单句只要即时
 * 反馈）。两条路都带超时：后端卡住时 play() 可能永远不 resolve。
 */
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
    /** 是否真的出声了——决定失败时该不该退到下一档重播。 */
    let playing = false;
    const release = () => {
      if (currentAudio === audio) {
        currentAudio = null;
        currentAudioKey = null;
      }
    };
    const timer = setTimeout(() => {
      // 出声前卡住 = 这一档拿不到音频，交给调用方退到 blob / 浏览器朗读；
      // 出声后超时 = 当成这一句已经念完，别从头再来。
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
    // 被打断时 stopSpeaking() 会 pause()：立刻结束等待，别让调用方白等到超时。
    audio.onpause = () => {
      if (!playing || audio.ended) return;
      fail(new Error(PLAY_CUT));
    };
    // 播完就把登记摘掉（好让缓存能淘汰这一条）。注意「一出声就 resolve」的那种
    // 调用**不**摘：currentAudio 得留着，页面卸载时 stopSpeaking() 才停得掉它。
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

/**
 * 朗读一段英文，返回「是否真的用音频文件出了声」。
 *
 * 返回 false 表示退回了浏览器朗读（内嵌 webview 里往往没有英文语音，等于没出声）
 * 或中途被打断——调用方据此决定要不要重试。
 *
 * Promise 在「声音真正开始播放」时才 resolve，页面据此显示合成中状态——
 * 冷启动要等好几秒，没有反馈会让人以为功能坏了。
 * options.waitUntilEnd 改成「整段播完才 resolve」，逐句流式朗读按这个顺序串起来。
 *
 * options.url 指定一段现成的音频（内置开场白的静态文件）：优先用它，取不到
 * 再退回后端合成，最后才用浏览器朗读。
 */
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
      // 先按单词书的做法直接给 <audio> 一个 URL 播放，不经过 fetch+blob。
      // 之前是 fetch 成 blob 再播（为了重播少走一次网络），但在内嵌 webview 里
      // 出现过「play() 已经 resolve、用户却听不到声音」的情况，而单词书那种
      // 直连播放一直正常。以能出声为准，blob 只留作直连失败时的兜底。
      try {
        await playUrl(url, url, content, waitUntilEnd);
        if (token !== speakToken) {
          traceSpeak({ text: label, url, stopped: true, marks });
          return false; // 期间被新的朗读或静音打断
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
          return false; // 期间被新的朗读或静音打断
        }
        // 已经出声、中途才断：别退回下一档从头重播，这一句就当作念过。
        if (waitUntilEnd && err instanceof Error && err.message === PLAY_CUT) {
          traceSpeak({ text: label, url, cut: true, marks });
          return false;
        }
      }

      // 直连也不行时，退回已经预取好的 blob（预取缓存的音频别浪费）。
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

/**
 * 朗读偏好：静音、自动朗读、音量。
 * 存在 localStorage，刷新后保留。首次渲染后再读，避免 SSR 水合不一致。
 *
 * 自动朗读**默认开着**（AI Tutor 进去就该先听见 AI 说话），只有用户显式关过
 * 才是关：localStorage 里存的是 "0"/"1"，没存过按开处理。
 */
export function useSpeechSettings() {
  const [muted, setMutedState] = useState(false);
  const [autoSpeak, setAutoSpeakState] = useState(true);
  const [volume, setVolumeState] = useState(1);
  const [supported, setSupported] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // 浏览器没有英文语音也没关系：后端 edge-tts 能合成，控件同样要显示。
    setSupported(canSpeak());
    setMutedState(window.localStorage.getItem(TTS_MUTED_KEY) === "1");
    // 没存过 = 用户没关过 = 默认开
    setAutoSpeakState(window.localStorage.getItem(TTS_AUTO_KEY) !== "0");

    // 注意区分「没存过」和「存了 0」：前者默认满音量。
    const rawVolume = window.localStorage.getItem(TTS_VOLUME_KEY);
    const initialVolume =
      rawVolume === null ? 1 : Math.min(1, Math.max(0, Number(rawVolume) || 0));
    setSpeechVolume(initialVolume);
    setVolumeState(initialVolume);
    setReady(true);

    let cancelled = false;
    // 能力探测顺便让后端预热合成连接池（探测只打一次，多个页面共用）
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
    // 必须整段取消，不能只 stopSpeaking：流式朗读被打断后还会接着念下一句
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
