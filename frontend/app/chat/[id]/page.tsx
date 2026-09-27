"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { MessageTranslation } from "@/components/MessageTranslation";
import { ScenarioHintCard } from "@/components/ScenarioHintCard";
import { WordPopover } from "@/components/WordPopover";
import { Spinner } from "@/components/ui";
import { api, ApiError, type VoiceEngine } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import {
  prefetchTranslation,
  sendMessageOnce,
  streamTurn,
} from "@/lib/chat";
import { staticOpeningUrl } from "@/lib/openingAudio";
import {
  cancelSpeechStream,
  endSpeechStream,
  feedSpeechStream,
  prefetchSpeech,
  speak,
  startSpeechStream,
  warmSpeechBackend,
  useSpeechSettings,
} from "@/lib/speech";
import { useVoiceInput, ENGINE_LABELS } from "@/lib/voiceInput";
import type {
  ChatFeedbackEvent,
  ChatReplyEvent,
  Conversation,
  CoachNote,
  Message,
  MessageFeedback,
  SentenceAnalysis,
} from "@/lib/types";

const COACH_STYLES: Record<
  CoachNote["verdict"],
  { label: string; wrap: string; labelColor: string }
> = {
  good: {
    label: "不错",
    wrap: "border-emerald-100 bg-emerald-50/60",
    labelColor: "text-emerald-600",
  },
  fix: {
    label: "需要修改",
    wrap: "border-amber-100 bg-amber-50/60",
    labelColor: "text-amber-600",
  },
  try: {
    label: "可以更好",
    wrap: "border-brand-100 bg-brand-50/50",
    labelColor: "text-brand-600",
  },
};

function VoiceChannelDialog({
  reason,
  options,
  onChoose,
  onDismiss,
}: {
  reason: string;
  options: VoiceEngine[];
  onChoose: (engine: VoiceEngine) => void;
  onDismiss: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-4">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-5 shadow-xl">
        <p className="text-sm font-medium text-slate-900">
          你配置的模型不支持语音输入
        </p>
        <p className="mt-2 text-xs leading-relaxed text-slate-500">
          {reason ||
            "语音识别需要模型服务商提供转写接口（如 whisper）。可以在「AI 模型」里换一个支持转写的模型，或者先用下面的通道。"}
        </p>

        <div className="mt-4 space-y-2">
          {options.map((engine) => (
            <button
              key={engine}
              type="button"
              onClick={() => onChoose(engine)}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-left transition hover:border-brand-300 hover:bg-brand-50/40"
            >
              <span className="text-sm text-slate-800">
                {ENGINE_LABELS[engine].label}
              </span>
              <span className="mt-0.5 block text-[11px] text-slate-400">
                {ENGINE_LABELS[engine].detail}
              </span>
            </button>
          ))}
        </div>

        <div className="mt-4 flex items-center justify-between text-xs">
          <Link
            href="/settings/ai"
            className="text-brand-600 hover:text-brand-700"
          >
            去 AI 模型设置
          </Link>
          <button
            type="button"
            onClick={onDismiss}
            className="text-slate-400 hover:text-slate-600"
          >
            先不用语音输入
          </button>
        </div>
      </div>
    </div>
  );
}

function CoachPanel({ note }: { note: CoachNote }) {
  const style = COACH_STYLES[note.verdict] ?? COACH_STYLES.good;
  return (
    <div className={`mt-2 rounded-xl border p-3 text-xs ${style.wrap}`}>
      <p className={`font-medium ${style.labelColor}`}>
        AI 点评 · {style.label}
      </p>
      <p className="mt-1 text-slate-700">{note.message_zh}</p>
      {note.tip_en ? (
        <p className="mt-1 text-slate-500">参考说法：{note.tip_en}</p>
      ) : null}
    </div>
  );
}

function FeedbackPanel({ feedback }: { feedback: MessageFeedback }) {
  const hasContent =
    feedback.correction ||
    feedback.natural_expression ||
    feedback.new_vocabulary.length > 0 ||
    feedback.coach_note;
  if (!hasContent) return null;

  return (
    <div className="mt-2 space-y-2">
      {feedback.coach_note ? <CoachPanel note={feedback.coach_note} /> : null}

      {feedback.correction ? (
        <div className="rounded-xl border border-rose-100 bg-rose-50/60 p-3 text-xs">
          <p className="font-medium text-rose-500">
            {feedback.correction.severity === 1 ? "Grammar" : "More natural"}
          </p>
          <p className="mt-1 text-slate-400 line-through">
            {feedback.correction.original}
          </p>
          <p className="text-slate-800">{feedback.correction.corrected}</p>
          <p className="mt-1 text-slate-500">{feedback.correction.explanation}</p>
        </div>
      ) : null}

      {feedback.natural_expression ? (
        <div className="rounded-xl border border-brand-100 bg-brand-50/60 p-3 text-xs">
          <p className="font-medium text-brand-600">Useful expression</p>
          <p className="mt-1 font-medium text-slate-800">
            {feedback.natural_expression.expression}
          </p>
          <p className="text-slate-500">{feedback.natural_expression.meaning}</p>
          {feedback.natural_expression.example ? (
            <p className="mt-1 text-slate-400">
              {feedback.natural_expression.example}
            </p>
          ) : null}
        </div>
      ) : null}

      {feedback.new_vocabulary.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {feedback.new_vocabulary.map((item) => (
            <span key={item.word} className="chip-slate">
              {item.word}
              {item.meaning ? ` · ${item.meaning}` : ""}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SentenceCard({
  analysis,
  position,
  onClose,
}: {
  analysis: SentenceAnalysis;
  position: { x: number; y: number } | null;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed z-40 w-80 max-h-[70vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-4 shadow-xl"
      style={{
        left: Math.max(
          12,
          Math.min(position?.x ?? 12, window.innerWidth - 340)
        ),
        top: Math.max(
          12,
          Math.min((position?.y ?? 12) + 12, window.innerHeight - 320)
        ),
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-slate-400">句子分析</p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          ✕
        </button>
      </div>

      <p className="mt-2 text-sm leading-relaxed text-slate-800">
        {analysis.chinese_meaning || "暂无整句翻译"}
      </p>

      {analysis.main_clause ? (
        <div className="mt-3">
          <p className="text-[11px] text-slate-400">主干</p>
          <p className="text-xs text-slate-700">{analysis.main_clause}</p>
        </div>
      ) : null}

      {analysis.vocabulary.length > 0 ? (
        <div className="mt-3 space-y-1">
          <p className="text-[11px] text-slate-400">重点单词</p>
          {analysis.vocabulary.map((item) => (
            <p key={item.word} className="text-xs text-slate-700">
              <span className="font-medium">{item.word}</span>
              {item.meaning ? ` · ${item.meaning}` : ""}
            </p>
          ))}
        </div>
      ) : null}

      {analysis.collocations.length > 0 ? (
        <div className="mt-3 space-y-1">
          <p className="text-[11px] text-slate-400">固定搭配</p>
          {analysis.collocations.map((item) => (
            <p key={item.phrase} className="text-xs text-slate-700">
              <span className="font-medium">{item.phrase}</span>
              {item.meaning ? ` · ${item.meaning}` : ""}
            </p>
          ))}
        </div>
      ) : null}

      {analysis.grammar_points.length > 0 ? (
        <div className="mt-3 space-y-1">
          <p className="text-[11px] text-slate-400">语法</p>
          {analysis.grammar_points.map((item) => (
            <p key={item.point} className="text-xs text-slate-700">
              <span className="font-medium">{item.point}</span>
              {item.explanation ? ` · ${item.explanation}` : ""}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ChatRoom() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const [feedbackPending, setFeedbackPending] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState("");
  const [popover, setPopover] = useState<{
    word: string;
    context: string;
    x: number;
    y: number;
  } | null>(null);
  const [sentence, setSentence] = useState<SentenceAnalysis | null>(null);
  const [sentencePos, setSentencePos] = useState<{
    x: number;
    y: number;
  } | null>(null);

  const [speakingId, setSpeakingId] = useState<number | null>(null);

  const speechStreamRef = useRef<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const {
    muted,
    autoSpeak,
    volume,
    supported: ttsSupported,
    ready: settingsReady,
    setMuted,
    setAutoSpeak,
    setVolume,
  } = useSpeechSettings();

  const voice = useVoiceInput({
    value: input,
    onText: setInput,
    disabled: Boolean(conversation?.is_completed),
  });

  useEffect(() => {
    api
      .conversation(Number(params.id))
      .then(setConversation)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, [params.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation?.messages.length]);

  useEffect(() => {
    if (!conversation) return;
    const assistants = conversation.messages.filter(
      (message) => message.role === "assistant" && message.content
    );
    const opening = assistants[0];
    const latest = assistants[assistants.length - 1];
    for (const message of [opening, latest]) {
      if (message) prefetchTranslation(message.content);
    }
  }, [conversation?.id]);

  useEffect(() => {
    if (!settingsReady || !conversation) return;

    const opening = conversation.messages.find(
      (message) => message.role === "assistant" && message.content
    );
    if (!opening) return;

    const url = staticOpeningUrl(conversation.scenario?.slug, opening.content);

    prefetchSpeech(opening.content, { url, urgent: true });

    const hasHistory = conversation.messages.some(
      (message) => message.role === "user"
    );
    if (!autoSpeak || muted || hasHistory) return;

    const playedKey = `linguascene_opening_played_${conversation.id}`;
    if (window.sessionStorage.getItem(playedKey) === "1") return;

    let started = false;
    const playOpening = () => {
      if (started) return;
      if (window.sessionStorage.getItem(playedKey) === "1") return;
      started = true;
      void speakText(opening.content, opening.id, url).then((played) => {
        if (played) window.sessionStorage.setItem(playedKey, "1");

        else started = false;
      });
    };

    playOpening();

    const retry = () => playOpening();
    window.addEventListener("pointerdown", retry, { once: true });
    window.addEventListener("keydown", retry, { once: true });
    return () => {
      window.removeEventListener("pointerdown", retry);
      window.removeEventListener("keydown", retry);
    };
  }, [settingsReady, conversation, autoSpeak, muted]);

  useEffect(() => cancelSpeechStream, []);

  async function speakText(
    text: string,
    messageId?: number,
    url?: string | null
  ): Promise<boolean> {
    if (muted) return false;

    speechStreamRef.current = null;
    cancelSpeechStream();
    setSpeakingId(messageId ?? null);
    try {
      return await speak(text, "en-US", { url });
    } finally {

      setSpeakingId((current) =>
        current === (messageId ?? null) ? null : current
      );
    }
  }

  function handleSelectText() {
    const selected = window.getSelection();
    const text = selected?.toString().trim() ?? "";
    if (!text || text.split(/\s+/).length > 30) return;

    const range = selected?.getRangeAt(0);
    if (!range) return;
    const rect = range.getBoundingClientRect();

    const node = selected?.anchorNode ?? null;
    const element = node instanceof Element ? node : node?.parentElement;
    const bubble = element?.closest("[data-message-content]");
    if (!bubble) return;
    const context =
      bubble.getAttribute("data-message-content") ||
      conversation?.scenario?.title ||
      "";

    if (text.split(/\s+/).length === 1 && /^[A-Za-z][A-Za-z'-]*$/.test(text)) {
      setSentence(null);
      setSentencePos(null);
      setPopover({
        word: text.toLowerCase(),
        context,
        x: rect.left,
        y: rect.bottom,
      });
    } else {
      setPopover(null);
      setSentencePos({ x: rect.left, y: rect.bottom });
      api
        .analyzeSentence(text, context)
        .then(setSentence)
        .catch(() => {
          setSentence(null);
          setSentencePos(null);
        });
    }
  }

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || !conversation || sending) return;

    voice.stop();
    cancelSpeechStream();
    speechStreamRef.current = null;

    if (autoSpeak && !muted) void warmSpeechBackend({ force: true });
    setSending(true);
    setError("");
    voice.clearError();
    const optimistic: Message = {
      id: Date.now(),
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
      feedback: null,
    };

    const streamingId = optimistic.id - 1;
    setConversation((prev) =>
      prev ? { ...prev, messages: [...prev.messages, optimistic] } : prev
    );
    setInput("");

    let userMessageId: number | null = null;

    let serverAccepted = false;

    let replyText = "";

    function applyReplyChunk(chunk: string) {
      serverAccepted = true;
      replyText += chunk;

      if (autoSpeak && !muted) {
        if (speechStreamRef.current === null) {
          speechStreamRef.current = startSpeechStream();
        }
        feedSpeechStream(speechStreamRef.current, replyText);
      }
      setConversation((prev) => {
        if (!prev) return prev;
        const existing = prev.messages.find((m) => m.id === streamingId);
        if (existing) {
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === streamingId
                ? { ...m, content: existing.content + chunk }
                : m
            ),
          };
        }
        const streaming: Message = {
          id: streamingId,
          role: "assistant",
          content: chunk,
          created_at: new Date().toISOString(),
          feedback: null,
        };
        return {
          ...prev,
          messages: [
            ...prev.messages.filter((m) => m.id !== optimistic.id),
            streaming,
          ],
        };
      });
    }

    const spokenReplies = new Set<number>();

    function applyReply(payload: ChatReplyEvent): number {
      setConversation((prev) =>
        prev
          ? {
              ...prev,
              task_progress: payload.task_progress,
              is_completed: payload.task_completed,
              hint: payload.hint,
              messages: [
                ...prev.messages.filter(
                  (m) => m.id !== optimistic.id && m.id !== streamingId
                ),
                payload.user_message,
                payload.ai_message,
              ],
            }
          : prev
      );

      if (payload.ai_message.content) {
        if (!autoSpeak && !muted) prefetchSpeech(payload.ai_message.content);
        prefetchTranslation(payload.ai_message.content);
      }

      const replyId = payload.ai_message.id;
      if (autoSpeak && !muted && !spokenReplies.has(replyId)) {
        spokenReplies.add(replyId);
        const content = payload.ai_message.content;
        const streamId = speechStreamRef.current ?? startSpeechStream();
        speechStreamRef.current = null;

        feedSpeechStream(streamId, content);
        endSpeechStream(streamId);
      }
      return payload.user_message.id;
    }

    function applyFeedback(payload: ChatFeedbackEvent) {
      if (userMessageId === null) return;
      const feedback: MessageFeedback = {
        correction: payload.correction,
        natural_expression: payload.natural_expression,
        new_vocabulary: payload.new_vocabulary,
        coach_note: payload.coach_note,
      };
      setConversation((prev) =>
        prev
          ? {
              ...prev,
              task_progress: payload.task_progress,
              is_completed: payload.task_completed,
              hint: payload.hint,
              messages: prev.messages.map((m) =>
                m.id === userMessageId ? { ...m, feedback } : m
              ),
            }
          : prev
      );
    }

    function restoreAfterFailure(err: unknown) {
      cancelSpeechStream();
      speechStreamRef.current = null;
      setError(err instanceof Error ? err.message : "发送失败");
      if (serverAccepted) {

        // 后端已经落库这条消息，保留它，避免重发产生重复消息
        return;
      }
      setConversation((prev) =>
        prev
          ? {
              ...prev,
              messages: prev.messages.filter(
                (m) => m.id !== optimistic.id && m.id !== streamingId
              ),
            }
          : prev
      );
      setInput(text);
    }

    try {
      await streamTurn(conversation.id, text, {
        onReplyChunk: (chunk) => {
          applyReplyChunk(chunk);
          setFeedbackPending(true);
        },
        onReply: (payload) => {
          serverAccepted = true;
          userMessageId = applyReply(payload);
          setFeedbackPending(true);
        },
        onFeedback: (payload) => {
          applyFeedback(payload);
          setFeedbackPending(false);
        },
        onDone: () => setFeedbackPending(false),
      });
    } catch (err) {

      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
        try {
          const response = await sendMessageOnce(conversation.id, text);
          userMessageId = applyReply(response);
          applyFeedback(response);
        } catch (fallbackError) {
          restoreAfterFailure(fallbackError);
        }
      } else {
        restoreAfterFailure(err);
      }
    } finally {
      setSending(false);
      setFeedbackPending(false);
    }
  }

  async function handleFinish() {
    if (!conversation) return;
    setFinishing(true);
    speechStreamRef.current = null;
    cancelSpeechStream();
    try {
      await api.finishConversation(conversation.id);
      router.push(`/result/${conversation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "结算失败");
      setFinishing(false);
    }
  }

  if (error && !conversation) {
    return <div className="card p-8 text-center text-sm text-slate-400">{error}</div>;
  }
  if (!conversation) return <Spinner />;

  const scenario = conversation.scenario;

  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] max-w-3xl flex-col">
      <header className="card flex items-center gap-4 rounded-b-none border-b-0 p-4">
        <span className="text-2xl">{scenario?.icon ?? "💬"}</span>
        <div className="flex-1">
          <p className="font-medium text-slate-900">
            {scenario?.title ?? "Free Talk"}
          </p>
          <p className="text-xs text-slate-400">
            {scenario ? `AI: ${scenario.ai_role}` : "AI Tutor"}
          </p>
        </div>
        {ttsSupported ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setAutoSpeak(!autoSpeak)}
              disabled={muted}
              title={autoSpeak ? "关闭 AI 回复自动朗读" : "开启 AI 回复自动朗读"}
              className={`rounded-full px-2.5 py-1.5 text-xs transition disabled:opacity-40 ${
                autoSpeak && !muted
                  ? "bg-brand-50 text-brand-600"
                  : "text-slate-400 hover:text-slate-600"
              }`}
            >
              自动朗读
            </button>
            <button
              type="button"
              onClick={() => setMuted(!muted)}
              title={muted ? "开启声音" : "关闭声音"}
              aria-label={muted ? "开启声音" : "关闭声音"}
              className="rounded-full px-2 py-1.5 text-base transition hover:bg-slate-100"
            >
              {muted ? "🔇" : "🔊"}
            </button>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={Math.round(volume * 100)}
              onChange={(event) => setVolume(Number(event.target.value) / 100)}
              disabled={muted}
              aria-label="朗读音量"
              title={`朗读音量 ${Math.round(volume * 100)}%`}
              className="range-brand w-20"
            />
            <span className="w-7 text-right text-[11px] tabular-nums text-slate-400">
              {Math.round(volume * 100)}%
            </span>
          </div>
        ) : null}
      </header>

      <div
        onMouseUp={handleSelectText}
        className="card flex-1 space-y-4 overflow-y-auto rounded-none border-y-0 p-5"
      >
        {conversation.messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${
              message.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`flex max-w-[80%] flex-col ${
                message.role === "user" ? "items-end" : "items-start"
              }`}
            >
              <div className="flex items-start gap-1.5">
                <div
                  data-message-content={message.content}
                  className={`rounded-2xl px-4 py-2.5 text-sm ${
                    message.role === "user"
                      ? "bg-brand-600 text-white"
                      : "bg-slate-100 text-slate-800"
                  }`}
                >
                  {message.content}
                </div>
                {message.role === "assistant" &&
                message.content &&
                ttsSupported ? (
                  <button
                    type="button"
                    onClick={() => speakText(message.content, message.id)}
                    disabled={muted || speakingId === message.id}
                    aria-label={
                      speakingId === message.id ? "正在合成语音" : "朗读这条回复"
                    }
                    title={
                      speakingId === message.id
                        ? "正在合成语音…"
                        : "朗读这条回复"
                    }
                    className={`mt-1 shrink-0 transition disabled:opacity-40 ${
                      speakingId === message.id
                        ? "text-brand-600"
                        : "text-slate-300 hover:text-brand-600"
                    }`}
                  >
                    {speakingId === message.id ? (
                      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600 align-middle" />
                    ) : (
                      "🔊"
                    )}
                  </button>
                ) : null}
              </div>
              {message.feedback ? (
                <FeedbackPanel feedback={message.feedback} />
              ) : null}
              {message.role === "assistant" && message.content ? (
                <MessageTranslation content={message.content} />
              ) : null}
            </div>
          </div>
        ))}
        {sending || feedbackPending ? (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl bg-slate-100 px-4 py-2.5 text-xs text-slate-400">
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
              {feedbackPending ? "AI 正在点评这句话…" : "AI 正在回复…"}
            </div>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      {voice.channelPrompt ? (
        <VoiceChannelDialog
          reason={voice.channelPrompt.reason}
          options={voice.channelPrompt.options}
          onChoose={voice.chooseChannel}
          onDismiss={voice.dismissChannelPrompt}
        />
      ) : null}

      {sentence ? (
        <SentenceCard
          analysis={sentence}
          position={sentencePos}
          onClose={() => {
            setSentence(null);
            setSentencePos(null);
          }}
        />
      ) : null}

      {popover ? (
        <WordPopover
          word={popover.word}
          context={popover.context}
          position={{ x: popover.x, y: popover.y }}
          onClose={() => setPopover(null)}
        />
      ) : null}

      <div className="card space-y-3 rounded-t-none border-t-0 p-4">
        {error || voice.error ? (
          <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-600">
            {error || voice.error}
            {voice.error ? (
              <button
                type="button"
                onClick={voice.clearError}
                className="ml-2 text-rose-400 hover:text-rose-600"
              >
                知道了
              </button>
            ) : null}
          </p>
        ) : null}

        {voice.recording || voice.transcribing ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-brand-50/70 px-3 py-2 text-xs text-brand-700">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" />
            </span>
            {voice.transcribing
              ? "正在把你刚才说的转成文字…"
              : "正在听你说… 说完了点一下麦克风"}
            {voice.notice ? (
              <span className="text-amber-600">{voice.notice}</span>
            ) : null}
            {voice.modelSlow && voice.mode === "model" ? (
              <span className="text-amber-600">
                （这家模型转写在排队，比较慢）
              </span>
            ) : null}
          </div>
        ) : null}

        {voice.engines.length > 0 ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-400">
            <span>语音识别：</span>
            {voice.engines.map((engine) => (
              <button
                key={engine}
                type="button"
                onClick={() => voice.setEngine(engine)}
                className={`rounded-full px-2 py-0.5 transition ${
                  voice.mode === engine
                    ? "bg-brand-50 text-brand-600"
                    : "hover:text-slate-600"
                }`}
              >
                {ENGINE_LABELS[engine].label}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-amber-600">
            语音输入不可用：
            {voice.unavailableDetail ||
              "你在 AI 模型里配置的模型不支持转写，服务器也没有启用本地识别。"}
          </p>
        )}

        <ScenarioHintCard hint={conversation.hint} onFill={setInput} />

        <form onSubmit={handleSend} className="flex gap-2">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={voice.recording ? "正在听你说…" : "Type in English…"}
            className="input flex-1"
            disabled={conversation.is_completed}
          />
          {voice.supported ? (
            <button
              type="button"
              onClick={voice.toggle}
              disabled={conversation.is_completed}
              aria-label={
                voice.recording ? "结束语音输入" : "用语音输入（英文）"
              }
              title={
                voice.recording
                  ? "结束语音输入"
                  : "语音输入：按一下开始说，再按一下结束"
              }
              className={`shrink-0 rounded-xl px-3 text-lg transition disabled:opacity-40 ${
                voice.recording
                  ? "bg-rose-50 text-rose-500 ring-1 ring-rose-200"
                  : "text-slate-400 hover:bg-slate-50 hover:text-brand-600"
              }`}
            >
              {voice.transcribing && !voice.recording ? (
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600 align-middle" />
              ) : (
                "🎙️"
              )}
            </button>
          ) : null}
          <button
            type="submit"
            disabled={sending || !input.trim() || conversation.is_completed}
            className="btn-primary"
          >
            {sending ? "…" : "发送"}
          </button>
        </form>

        <div className="flex items-center justify-between">
          <Link
            href={scenario ? `/scenarios/${scenario.id}` : "/chat"}
            className="text-xs text-slate-400 hover:text-slate-600"
          >
            返回
          </Link>
          {conversation.is_completed ? (
            <button onClick={handleFinish} className="btn-primary">
              查看学习报告
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ChatRoom />
      </AppShell>
    </RequireAuth>
  );
}
