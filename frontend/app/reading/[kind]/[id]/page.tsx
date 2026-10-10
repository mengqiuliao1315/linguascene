"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  SelectionToolbar,
  type SelectionInfo,
} from "@/components/SelectionToolbar";
import { WordPopover } from "@/components/WordPopover";
import { EmptyState, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import {
  COLOR_DOTS,
  COLOR_LABELS,
  COLOR_MASK,
  COLOR_ORDER,
  COLOR_STYLES,
  readingApi,
  type MaterialDetail,
  type MaterialKind,
  type NoteColor,
  type ReadingNote,
  type ReadingSentence,
  type SentenceSkeleton,
  type SuggestedSpan,
} from "@/lib/reading";
import {
  cancelPrefetchSpeech,
  prefetchSpeech,
  speak,
  stopSpeaking,
  useSpeechSettings,
} from "@/lib/speech";

type LiveSentence = ReadingSentence & { pending?: boolean };

function placeholderSentence(skeleton: SentenceSkeleton): LiveSentence {
  return {
    index: skeleton.index,
    paragraph: skeleton.paragraph,
    text: skeleton.text,
    translation: "",
    main_clause: "",
    words: [],
    phrases: [],
    grammar: [],
    explanation: "",
    notes: [],
    pending: true,
  };
}

const COLOR_SUGGESTION_BORDER: Record<NoteColor, string> = {
  blue: "border-blue-400",
  green: "border-green-400",
  amber: "border-amber-400",
  rose: "border-rose-400",
  violet: "border-violet-400",
};

type Piece = {
  text: string;
  note?: ReadingNote;

  suggestion?: SuggestedSpan;
};

function buildPieces(
  text: string,
  notes: ReadingNote[],
  suggestions: SuggestedSpan[] = []
): Piece[] {
  const ranged = notes
    .map((note) => ({
      note,
      start: Math.max(0, Math.min(note.start_offset, text.length)),
      end: Math.max(0, Math.min(note.end_offset, text.length)),
    }))
    .filter((item) => item.end > item.start);

  const suggested = suggestions
    .map((suggestion) => ({
      suggestion,
      start: Math.max(0, Math.min(suggestion.start_offset, text.length)),
      end: Math.max(0, Math.min(suggestion.end_offset, text.length)),
    }))
    .filter((item) => item.end > item.start);

  const boundaries = new Set<number>([0, text.length]);
  for (const item of [...ranged, ...suggested]) {
    boundaries.add(item.start);
    boundaries.add(item.end);
  }
  const sorted = [...boundaries].sort((a, b) => a - b);

  let pieces: Piece[] = [];
  for (let i = 0; i < sorted.length - 1; i += 1) {
    const start = sorted[i];
    const end = sorted[i + 1];
    if (end <= start) continue;

    const covering = ranged
      .filter((item) => item.start <= start && item.end >= end)
      .sort((a, b) => b.start - a.start || b.note.id - a.note.id);
    const note = covering[0]?.note;

    const suggestion = note
      ? undefined
      : suggested
          .filter((item) => item.start <= start && item.end >= end)
          .sort((a, b) => b.start - a.start)[0]?.suggestion;
    pieces.push({ text: text.slice(start, end), note, suggestion });
  }

  const legacy = notes
    .filter(
      (note) =>
        !(note.end_offset > note.start_offset) &&
        (note.kind === "word" || note.kind === "phrase") &&
        note.text.trim()
    )
    .map((note) => ({ text: note.text, note }))
    .sort((a, b) => b.text.length - a.text.length);

  for (const mark of legacy) {
    const next: Piece[] = [];
    for (const piece of pieces) {
      if (piece.note) {
        next.push(piece);
        continue;
      }
      const lower = piece.text.toLowerCase();
      const target = mark.text.toLowerCase();
      let cursor = 0;
      let found = lower.indexOf(target);
      if (found === -1) {
        next.push(piece);
        continue;
      }
      while (found !== -1) {
        if (found > cursor) next.push({ text: piece.text.slice(cursor, found) });
        next.push({
          text: piece.text.slice(found, found + mark.text.length),
          note: mark.note,
        });
        cursor = found + mark.text.length;
        found = lower.indexOf(target, cursor);
      }
      if (cursor < piece.text.length) {
        next.push({ text: piece.text.slice(cursor) });
      }
    }
    pieces = next;
  }

  if (pieces.length === 0) return [{ text }];
  return pieces;
}

function selectionOffsets(
  root: HTMLElement
): { text: string; start: number; end: number; x: number; y: number } | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }
  const range = selection.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return null;

  const pre = range.cloneRange();
  pre.selectNodeContents(root);
  pre.setEnd(range.startContainer, range.startOffset);
  const rawStart = pre.toString().length;

  const raw = selection.toString();
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const start = rawStart + (raw.length - raw.trimStart().length);
  const rect = range.getBoundingClientRect();

  return {
    text: trimmed,
    start,
    end: start + trimmed.length,
    x: rect.left + rect.width / 2,
    y: rect.top,
  };
}

function HighlightedSentence({
  sentence,
  recallMode,
  revealed,
  onReveal,
  hoveredNoteId,
  onHoverNote,
  onSelect,
  suggestions,
  onAcceptSuggestion,
  onAcceptAll,
  onDismissSuggestions,
}: {
  sentence: ReadingSentence;
  recallMode: boolean;
  revealed: Set<number>;
  onReveal: (noteId: number) => void;
  hoveredNoteId: number | null;
  onHoverNote: (noteId: number | null) => void;
  onSelect: (selection: SelectionInfo) => void;
  suggestions: SuggestedSpan[];
  onAcceptSuggestion: (span: SuggestedSpan) => void;
  onAcceptAll: (spans: SuggestedSpan[]) => void;
  onDismissSuggestions: () => void;
}) {
  const ref = useRef<HTMLParagraphElement>(null);

  const pieces = useMemo(
    () => buildPieces(sentence.text, sentence.notes, suggestions),
    [sentence.text, sentence.notes, suggestions]
  );

  function handleMouseUp() {
    const root = ref.current;
    if (!root) return;
    const found = selectionOffsets(root);
    if (!found) return;
    onSelect({ ...found, sentenceIndex: sentence.index });
  }

  return (
    <p
      ref={ref}
      onMouseUp={handleMouseUp}
      className="text-[15px] leading-8 text-slate-800"
    >
      {pieces.map((piece, index) => {
        if (piece.note) {
          const note = piece.note;
          const hidden = recallMode && !revealed.has(note.id);
          return (
            <mark
              key={index}
              title={`${COLOR_LABELS[note.color]}${
                note.meaning ? `：${note.meaning}` : ""
              }${note.note ? ` · ${note.note}` : ""}`}
              onClick={hidden ? () => onReveal(note.id) : undefined}
              onMouseEnter={() => onHoverNote(note.id)}
              onMouseLeave={() => onHoverNote(null)}
              className={`rounded px-0.5 transition ${
                hidden
                  ? `${COLOR_MASK[note.color]} cursor-pointer text-transparent select-none`
                  : `${COLOR_STYLES[note.color]} cursor-pointer`
              } ${
                hoveredNoteId === note.id && !hidden
                  ? "ring-2 ring-slate-400 ring-offset-1"
                  : ""
              }`}
            >
              {piece.text}
            </mark>
          );
        }
        if (piece.suggestion) {
          const span = piece.suggestion;
          return (
            <button
              key={index}
              type="button"
              title={`${span.reason || COLOR_LABELS[span.color]}（点击采纳）`}
              onClick={() => onAcceptSuggestion(span)}
              className={`rounded border-b-2 border-dashed px-0.5 text-left transition hover:bg-slate-100 ${COLOR_SUGGESTION_BORDER[span.color]}`}
            >
              {piece.text}
            </button>
          );
        }
        return <span key={index}>{piece.text}</span>;
      })}
    </p>
  );
}

function AddButton({
  active,
  onClick,
  title,
}: {
  active?: boolean;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      title={active ? "已加入本页笔记" : title}
      onClick={active ? undefined : onClick}
      aria-pressed={active}
      className={`ml-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[11px] leading-none transition ${
        active
          ? "cursor-default bg-brand-600 text-white"
          : "border border-slate-300 text-slate-400 hover:border-brand-500 hover:text-brand-600"
      }`}
    >
      {active ? "✓" : "+"}
    </button>
  );
}

function Workspace() {
  const params = useParams<{ kind: string; id: string }>();
  const kind = params.kind as MaterialKind;
  const materialId = Number(params.id);

  const [material, setMaterial] = useState<MaterialDetail | null>(null);
  const [sentences, setSentences] = useState<LiveSentence[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [popover, setPopover] = useState<{

    word: string;

    raw: string;
    x: number;
    y: number;
    context: string;

    sentenceIndex: number;
    start: number;
    end: number;
  } | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [draftSentence, setDraftSentence] = useState(0);
  const [selection, setSelection] = useState<SelectionInfo | null>(null);
  const [recallMode, setRecallMode] = useState(false);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<NoteColor | "all">("all");
  const [hoveredNoteId, setHoveredNoteId] = useState<number | null>(null);

  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const [editMeaning, setEditMeaning] = useState("");
  const [editBody, setEditBody] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [suggesting, setSuggesting] = useState(false);

  const [suggestProgress, setSuggestProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [suggestions, setSuggestions] = useState<Record<number, SuggestedSpan[]>>(
    {}
  );

  const [speakingIndex, setSpeakingIndex] = useState<number | null>(null);

  // 只在本次停留本页期间可撤销：刷新或重新进入页面后清空，无法恢复上次删除的句子。
  const [recentlyDeleted, setRecentlyDeleted] = useState<LiveSentence[]>([]);

  const streamRef = useRef<AbortController | null>(null);

  const autoStartedRef = useRef(false);
  const {
    muted,
    supported: ttsSupported,

    ready: speechReady,
    setMuted,
  } = useSpeechSettings();

  useEffect(
    () => () => {
      stopSpeaking();
      cancelPrefetchSpeech();
    },
    []
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const detail = await readingApi.material(kind, materialId);
      setMaterial(detail);
      setSentences(detail.sentences);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [kind, materialId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (loading || autoStartedRef.current) return;
    if (!material || material.sentences.length > 0) return;
    autoStartedRef.current = true;
    void handleAnalyze(false);

  }, [loading, material]);

  const mergeSentences = useCallback((incoming: LiveSentence[]) => {
    setSentences((prev) => {
      const byIndex = new Map(prev.map((item) => [item.index, item]));
      for (const item of incoming) {
        const existing = byIndex.get(item.index);
        byIndex.set(item.index, {
          ...item,
          notes: item.notes.length > 0 ? item.notes : existing?.notes ?? [],
        });
      }
      return [...byIndex.values()].sort((a, b) => a.index - b.index);
    });
  }, []);

  useEffect(() => {
    if (!speechReady || muted) return;
    for (const sentence of sentences) prefetchSpeech(sentence.text);
  }, [sentences, muted, speechReady]);

  useEffect(() => {
    if (!speechReady || muted || !selection) return;
    const text = selection.text.trim();
    if (text.split(/\s+/).length !== 1) return;
    prefetchSpeech(text);
  }, [selection, muted, speechReady]);

  const allNotes = useMemo(
    () => sentences.flatMap((s) => s.notes).sort((a, b) => a.id - b.id),
    [sentences]
  );

  function notedNoteFor(
    sentenceIndex: number,
    text: string
  ): ReadingNote | undefined {
    const target = text.toLowerCase();
    return allNotes.find(
      (n) => n.sentence_index === sentenceIndex && n.text.toLowerCase() === target
    );
  }

  function alreadyNoted(sentenceIndex: number, text: string): boolean {
    return notedNoteFor(sentenceIndex, text) !== undefined;
  }

  function meaningFor(sentenceIndex: number, text: string): string {
    const sentence = sentences.find((s) => s.index === sentenceIndex);
    if (!sentence) return "";
    const target = text.toLowerCase();
    const word = sentence.words.find(
      (w) => w.word.toLowerCase() === target || w.lemma.toLowerCase() === target
    );
    if (word) return word.meaning;
    const phrase = sentence.phrases.find((p) => p.phrase.toLowerCase() === target);
    return phrase?.meaning ?? "";
  }

  function mergeNote(note: ReadingNote) {
    setSentences((prev) =>
      prev.map((s) =>
        s.index === note.sentence_index
          ? {
              ...s,
              notes: s.notes.some((n) => n.id === note.id)
                ? s.notes.map((n) => (n.id === note.id ? note : n))
                : [...s.notes, note],
            }
          : s
      )
    );
  }

  async function addNote(
    sentenceIndex: number,
    noteKind: "word" | "phrase" | "note",
    text: string,
    options: {
      meaning?: string;
      note?: string;
      color?: NoteColor;
      start?: number;
      end?: number;
    } = {}
  ) {
    const clean = text.trim();
    if (!clean) return;

    const hasSpan = (options.start ?? 0) > 0 || (options.end ?? 0) > 0;
    if (!hasSpan && noteKind !== "note" && alreadyNoted(sentenceIndex, clean)) {
      return;
    }

    try {
      const created = await readingApi.createNote(kind, materialId, {
        sentence_index: sentenceIndex,
        kind: noteKind,
        text: clean,
        meaning: options.meaning ?? "",
        note: options.note ?? "",
        color: options.color ?? "blue",
        start_offset: options.start ?? 0,
        end_offset: options.end ?? 0,
      });
      mergeNote(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加失败");
    }
  }

  async function handlePickColor(color: NoteColor) {
    if (!selection) return;
    const single = selection.text.split(/\s+/).length === 1;
    const noteKind = single ? "word" : "phrase";
    const payload = {
      meaning: meaningFor(selection.sentenceIndex, selection.text),
      color,
      start: selection.start,
      end: selection.end,
    };
    setSelection(null);
    window.getSelection()?.removeAllRanges();
    await addNote(selection.sentenceIndex, noteKind, selection.text, payload);
  }

  async function handleAnnotate(body: string, color: NoteColor) {
    if (!selection) return;
    const payload = {
      note: body.trim(),
      color,
      start: selection.start,
      end: selection.end,
    };
    const target = selection;
    setSelection(null);
    window.getSelection()?.removeAllRanges();
    await addNote(target.sentenceIndex, "note", target.text, payload);
  }

  function handleLookup() {
    if (!selection) return;
    const sentence = sentences.find((s) => s.index === selection.sentenceIndex);
    setPopover({
      word: selection.text.toLowerCase(),
      raw: selection.text,
      x: selection.x,
      y: selection.y,
      context: sentence?.text ?? material?.title ?? "",
      sentenceIndex: selection.sentenceIndex,
      start: selection.start,
      end: selection.end,
    });
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  }

  async function handleAnnotateFromPopover(payload: {
    text: string;
    meaning: string;
  }) {
    if (!popover) return;
    const existing = notedNoteFor(popover.sentenceIndex, payload.text);
    if (existing) {
      const meaning = payload.meaning.trim();
      if (!existing.meaning.trim() && meaning) {
        try {
          const updated = await readingApi.updateNote(existing.id, { meaning });
          mergeNote(updated);
        } catch (err) {
          setError(err instanceof Error ? err.message : "补翻译失败");
        }
      }
      return;
    }
    const single = payload.text.split(/\s+/).length === 1;
    await addNote(popover.sentenceIndex, single ? "word" : "phrase", payload.text, {
      meaning: payload.meaning,
      color: "blue",
      start: popover.start,
      end: popover.end,
    });
  }

  async function handleChangeColor(note: ReadingNote, color: NoteColor) {
    if (note.color === color) return;
    try {
      const updated = await readingApi.updateNote(note.id, { color });
      mergeNote(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "改色失败");
    }
  }

  function startEditNote(note: ReadingNote) {
    setEditingNoteId(note.id);
    setEditMeaning(note.meaning);
    setEditBody(note.note);
  }

  function cancelEditNote() {
    setEditingNoteId(null);
    setEditMeaning("");
    setEditBody("");
  }

  async function saveEditNote(note: ReadingNote) {
    if (savingNote) return;
    setSavingNote(true);
    try {
      const updated = await readingApi.updateNote(note.id, {
        meaning: editMeaning.trim(),
        note: editBody.trim(),
      });
      mergeNote(updated);
      cancelEditNote();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSavingNote(false);
    }
  }

  async function handleSuggest() {
    if (suggesting) return;
    setSuggesting(true);
    setError("");
    setSuggestProgress(null);

    setSuggestions({});

    let received = 0;
    let hits = 0;
    try {
      await readingApi.suggestStream(kind, materialId, {
        onStart: (total) => setSuggestProgress({ done: 0, total }),
        onSentence: (index, spans) => {
          received += 1;
          hits += spans.length ? 1 : 0;
          setSuggestProgress((prev) => (prev ? { ...prev, done: received } : prev));
          if (spans.length) {
            setSuggestions((prev) => ({ ...prev, [index]: spans }));
          }
        },
        onDone: (summary) => {
          reportSuggestOutcome(hits, summary.fallbackCount, summary.sentenceCount);
        },
      });
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {

        await suggestInOneShot();
      } else {
        setError(err instanceof Error ? err.message : "生成建议失败");
      }
    } finally {
      setSuggesting(false);
      setSuggestProgress(null);
    }
  }

  async function suggestInOneShot() {
    try {
      const result = await readingApi.suggest(kind, materialId);
      const mapped: Record<number, SuggestedSpan[]> = {};
      for (const [index, spans] of Object.entries(result.by_sentence)) {
        mapped[Number(index)] = spans;
      }
      setSuggestions(mapped);
      reportSuggestOutcome(
        Object.keys(mapped).length,
        result.fallback_count,
        result.sentence_count
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成建议失败");
    }
  }

  function reportSuggestOutcome(
    hits: number,
    fallbackCount: number,
    sentenceCount: number
  ) {
    if (!hits) {
      setError("这篇没有找到值得标注的地方，试试自己划词标注。");
    } else if (fallbackCount > 0) {

      setError(
        fallbackCount >= sentenceCount
          ? "模型暂时没调通，下面是按分级词表挑的超纲词，仅供参考。"
          : `有 ${fallbackCount} 句模型没调通、用了词表兜底，其余是 AI 挑的。`
      );
    }
  }

  async function acceptSuggestion(span: SuggestedSpan, sentenceIndex: number) {
    const single = span.text.split(/\s+/).length === 1;
    setSuggestions((prev) => ({
      ...prev,
      [sentenceIndex]: (prev[sentenceIndex] ?? []).filter(
        (item) => item.start_offset !== span.start_offset
      ),
    }));

    await addNote(sentenceIndex, single ? "word" : "phrase", span.text, {
      meaning: meaningFor(sentenceIndex, span.text),
      color: span.color,
      start: span.start_offset,
      end: span.end_offset,
    });
  }

  async function acceptAllSuggestions(spans: SuggestedSpan[], sentenceIndex: number) {
    for (const span of spans) {
      await acceptSuggestion(span, sentenceIndex);
    }
  }

  function dismissSuggestions(sentenceIndex: number) {
    setSuggestions((prev) => ({ ...prev, [sentenceIndex]: [] }));
  }

  function handleReveal(noteId: number) {
    setRevealed((prev) => new Set(prev).add(noteId));
  }

  function handleRevealAll() {
    setRevealed(new Set(allNotes.map((n) => n.id)));
  }

  function scrollToSentence(index: number) {
    document
      .getElementById(`sentence-${index}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function speakSentence(index: number, text: string) {
    if (muted) return;
    setSpeakingIndex(index);

    const next = sentences.find((item) => item.index === index + 1);
    if (next) prefetchSpeech(next.text, { urgent: true });
    try {
      await speak(text);
    } finally {

      setSpeakingIndex((current) => (current === index ? null : current));
    }
  }

  async function handleAnalyze(force = false) {
    if (analyzing) return;
    const useForce = force;

    streamRef.current?.abort();
    const controller = new AbortController();
    streamRef.current = controller;

    setAnalyzing(true);
    setError("");

    try {
      await readingApi.analyzeStream(kind, materialId, {
        force: useForce,
        signal: controller.signal,
        onStart: (skeleton) => {

          mergeSentences(skeleton.map(placeholderSentence));
        },
        onSentence: (sentence) => {
          mergeSentences([{ ...sentence, pending: false }]);
        },
        onDone: (generated) => {

          if (!generated) {
            setError(
              "模型暂时没调通，下面是离线分析结果；稍后点「重新分析」再试一次。"
            );
          }
        },
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {

        await analyzeInOneShot(useForce);
      } else {
        setError(err instanceof Error ? err.message : "生成失败");
      }
    } finally {

      if (streamRef.current === controller) {
        streamRef.current = null;
        setAnalyzing(false);
      }
    }
  }

  async function analyzeInOneShot(force: boolean) {
    try {
      const result = await readingApi.analyze(kind, materialId, force);
      mergeSentences(result.sentences.map((item) => ({ ...item, pending: false })));
      if (!result.generated) {
        setError("模型暂时没调通，下面是离线分析结果；稍后点「重新分析」再试一次。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    }
  }

  async function handleExport() {
    if (!material) return;
    setExporting(true);
    setError("");
    try {
      await readingApi.exportPdf(kind, materialId, `${material.title}.pdf`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  async function handlePublish() {
    if (!material) return;
    try {
      const updated = await readingApi.publish(material.id, !material.is_public);
      setMaterial({ ...material, is_public: updated.is_public });
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleToggleVocabulary(note: ReadingNote) {
    try {
      const updated = await readingApi.noteToVocabulary(note.id);
      mergeNote(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加入词库失败");
    }
  }

  async function handleDeleteNote(note: ReadingNote) {
    try {
      await readingApi.deleteNote(note.id);
      setSentences((prev) =>
        prev.map((s) => ({
          ...s,
          notes: s.notes.filter((n) => n.id !== note.id),
        }))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handleHideSentence(index: number) {
    if (
      !window.confirm(
        "删除后这句话不再显示，导出 PDF 也不包含它。确定删除吗？"
      )
    ) {
      return;
    }
    const removed = sentences.find((s) => s.index === index);
    try {
      await readingApi.hideSentence(kind, materialId, index);
      setSentences((prev) => prev.filter((s) => s.index !== index));
      if (removed) {
        setRecentlyDeleted((prev) => [...prev, removed]);
      }
      setSuggestions((prev) => {
        if (!(index in prev)) return prev;
        const next = { ...prev };
        delete next[index];
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handleRestoreSentence(index: number) {
    const target = recentlyDeleted.find((s) => s.index === index);
    if (!target) return;
    try {
      await readingApi.unhideSentence(kind, materialId, index);
      setSentences((prev) =>
        [...prev, target].sort((a, b) => a.index - b.index)
      );
      setRecentlyDeleted((prev) => prev.filter((s) => s.index !== index));
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复失败");
    }
  }

  if (loading) return <Spinner />;
  if (error && !material) return <EmptyState text={error} />;
  if (!material) return <EmptyState text="材料不存在" />;

  const canManage = material.is_mine && kind === "content";
  const colorCounts = COLOR_ORDER.map((color) => ({
    color,
    count: allNotes.filter((n) => n.color === color).length,
  }));
  const visibleNotes =
    filter === "all" ? allNotes : allNotes.filter((n) => n.color === filter);

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-[12rem] flex-1">
          <h1 className="text-base font-semibold text-slate-900">{material.title}</h1>
          <p className="text-xs text-slate-400">
            {material.author_name} · {material.level} · {material.word_count} words
            {material.source === "shared" ? " · 他人分享" : ""}
          </p>
        </div>

        {sentences.length === 0 ? (
          <button
            onClick={() => void handleAnalyze()}
            disabled={analyzing}
            className="btn-primary !py-2 text-sm"
          >
            {analyzing ? "分析中…" : "生成逐句讲解"}
          </button>
        ) : (
          <>
            <button
              onClick={() => {
                setRecallMode((prev) => !prev);
                setRevealed(new Set());
              }}
              className={`!py-2 text-sm ${recallMode ? "btn-primary" : "btn-ghost"}`}
            >
              {recallMode ? "退出复习" : "遮罩复习"}
            </button>
            {recallMode ? (
              <button onClick={handleRevealAll} className="btn-ghost !py-2 text-sm">
                全部揭示
              </button>
            ) : null}
            <button
              onClick={handleSuggest}
              disabled={suggesting}
              className="btn-ghost !py-2 text-sm"
            >
              {suggesting
                ? suggestProgress
                  ? `挑选中 ${suggestProgress.done}/${suggestProgress.total}`
                  : "挑选中…"
                : "AI 建议标注"}
            </button>
            <button
              onClick={() => void handleAnalyze(true)}
              disabled={analyzing}
              className="btn-ghost !py-2 text-sm"
            >
              {analyzing ? "重新分析中…" : "重新分析"}
            </button>
            <button
              onClick={handleExport}
              disabled={exporting}
              className="btn-primary !py-2 text-sm"
            >
              {exporting ? "导出中…" : "导出 PDF"}
            </button>
            {ttsSupported ? (
              <button
                onClick={() => setMuted(!muted)}
                title={muted ? "开启朗读声音" : "关闭朗读声音"}
                aria-label={muted ? "开启朗读声音" : "关闭朗读声音"}
                className={`btn-ghost !py-2 text-sm ${muted ? "!text-slate-400" : ""}`}
              >
                {muted ? "🔇" : "🔊"}
              </button>
            ) : null}
          </>
        )}

        {canManage ? (
          <button onClick={handlePublish} className="btn-ghost !py-2 text-sm">
            {material.is_public ? "取消公布" : "公布给大家"}
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
      ) : null}

      {recentlyDeleted.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
          <span className="text-xs text-slate-500">
            本次已删除 {recentlyDeleted.length} 句（离开本页后不可恢复）：
          </span>
          {recentlyDeleted.map((sentence) => (
            <button
              key={sentence.index}
              type="button"
              onClick={() => void handleRestoreSentence(sentence.index)}
              title={sentence.text}
              className="max-w-[240px] truncate rounded-lg border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-600 transition hover:border-brand-400 hover:text-brand-600"
            >
              恢复「{sentence.text}」
            </button>
          ))}
        </div>
      ) : null}

      {sentences.length === 0 ? (
        <EmptyState
          text={
            analyzing
              ? "正在切句、逐句解析，第一句马上就到…"
              : "还没有逐句讲解，点上面的按钮生成"
          }
        />
      ) : (
        <div className="grid gap-5 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            {sentences.map((sentence) => (
              <section
                key={sentence.index}
                id={`sentence-${sentence.index}`}
                data-sentence-index={sentence.index}

                onMouseEnter={() => {
                  if (!muted) prefetchSpeech(sentence.text, { urgent: true });
                }}
                className="card space-y-3 p-5"
              >
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <HighlightedSentence
                      sentence={sentence}
                      recallMode={recallMode}
                      revealed={revealed}
                      onReveal={handleReveal}
                      hoveredNoteId={hoveredNoteId}
                      onHoverNote={setHoveredNoteId}
                      onSelect={setSelection}
                      suggestions={suggestions[sentence.index] ?? []}
                      onAcceptSuggestion={(span) =>
                        void acceptSuggestion(span, sentence.index)
                      }
                      onAcceptAll={(spans) =>
                        void acceptAllSuggestions(spans, sentence.index)
                      }
                      onDismissSuggestions={() => dismissSuggestions(sentence.index)}
                    />
                  </div>
                  {ttsSupported ? (
                    <button
                      type="button"
                      onClick={() => void speakSentence(sentence.index, sentence.text)}
                      disabled={muted || speakingIndex === sentence.index}
                      aria-label={
                        speakingIndex === sentence.index
                          ? "正在合成语音"
                          : "朗读这句话"
                      }
                      title={
                        muted
                          ? "朗读声音已关闭，点上面的 🔊 打开"
                          : speakingIndex === sentence.index
                            ? "正在合成语音…"
                            : "朗读这句话"
                      }
                      className={`mt-1 shrink-0 transition disabled:opacity-40 ${
                        speakingIndex === sentence.index
                          ? "text-brand-600"
                          : "text-slate-300 hover:text-brand-600"
                      }`}
                    >
                      {speakingIndex === sentence.index ? (
                        <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600 align-middle" />
                      ) : (
                        "🔊"
                      )}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void handleHideSentence(sentence.index)}
                    title="删除这句：不再显示，导出 PDF 也不包含"
                    className="mt-1 shrink-0 rounded-lg px-2 py-1 text-[11px] text-slate-400 transition hover:bg-rose-50 hover:text-rose-500"
                  >
                    删除
                  </button>
                </div>

                {sentence.pending ? (
                  <p className="flex items-center gap-2 text-xs text-slate-400">
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-200 border-t-brand-500" />
                    正在解析这一句…
                  </p>
                ) : null}

                {(suggestions[sentence.index]?.length ?? 0) > 0 ? (
                  <div className="flex items-center gap-2 rounded-xl border border-dashed border-slate-300 px-3 py-2">
                    <span className="text-xs text-slate-500">
                      AI 建议了 {suggestions[sentence.index].length} 处，点虚线的词可直接采纳
                    </span>
                    <button
                      onClick={() =>
                        void acceptAllSuggestions(
                          suggestions[sentence.index],
                          sentence.index
                        )
                      }
                      className="ml-auto rounded-lg bg-brand-50 px-2 py-1 text-[11px] text-brand-700 transition hover:bg-brand-100"
                    >
                      全部采纳
                    </button>
                    <button
                      onClick={() => dismissSuggestions(sentence.index)}
                      className="rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:text-slate-600"
                    >
                      忽略
                    </button>
                  </div>
                ) : null}

                {sentence.translation ? (
                  <p className="text-xs text-slate-500">{sentence.translation}</p>
                ) : null}

                {sentence.words.length > 0 ? (
                  <div className="space-y-1.5">
                    <p className="section-title">重点单词</p>
                    <div className="flex flex-wrap gap-2">
                      {sentence.words.map((word) => (
                        <span
                          key={word.word}
                          className="inline-flex items-center rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs"
                        >
                          <span className="font-medium text-slate-800">
                            {word.lemma || word.word}
                          </span>
                          {word.lemma && word.lemma !== word.word ? (
                            <span className="ml-1 text-slate-400">({word.word})</span>
                          ) : null}
                          {word.meaning ? (
                            <span className="ml-1.5 text-slate-500">{word.meaning}</span>
                          ) : null}
                          <AddButton
                            title="加入本页笔记"
                            active={alreadyNoted(sentence.index, word.lemma || word.word)}
                            onClick={() =>
                              void addNote(
                                sentence.index,
                                "word",
                                word.lemma || word.word,
                                { meaning: word.meaning, color: "blue" }
                              )
                            }
                          />
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {sentence.phrases.length > 0 ? (
                  <div className="space-y-1.5">
                    <p className="section-title">固定搭配</p>
                    <div className="flex flex-wrap gap-2">
                      {sentence.phrases.map((phrase) => (
                        <span
                          key={phrase.phrase}
                          className="inline-flex items-center rounded-lg bg-brand-50 px-2.5 py-1.5 text-xs"
                        >
                          <span className="font-medium text-brand-800">
                            {phrase.phrase}
                          </span>
                          {phrase.meaning ? (
                            <span className="ml-1.5 text-brand-600">
                              {phrase.meaning}
                            </span>
                          ) : null}
                          <AddButton
                            title="加入本页笔记"
                            active={alreadyNoted(sentence.index, phrase.phrase)}
                            onClick={() =>
                              void addNote(sentence.index, "phrase", phrase.phrase, {
                                meaning: phrase.meaning,
                                color: "green",
                              })
                            }
                          />
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {sentence.grammar.length > 0 ? (
                  <div className="space-y-1.5">
                    <p className="section-title">语法</p>
                    {sentence.grammar.map((item) => (
                      <p key={item.point} className="text-xs text-slate-600">
                        <span className="font-medium text-slate-800">{item.point}</span>
                        {item.explanation ? ` · ${item.explanation}` : ""}
                      </p>
                    ))}
                  </div>
                ) : null}

                {sentence.pending ? null : (
                  <div className="flex items-center gap-2 pt-1">
                    <input
                      value={draftSentence === sentence.index ? noteDraft : ""}
                      onFocus={() => setDraftSentence(sentence.index)}
                      onChange={(event) => {
                        setDraftSentence(sentence.index);
                        setNoteDraft(event.target.value);
                      }}
                      placeholder="给这句加笔记…"
                      className="input !py-1.5 text-xs"
                    />
                    <button
                      onClick={() => {
                        if (draftSentence !== sentence.index) return;
                        void addNote(sentence.index, "note", noteDraft, {
                          color: "violet",
                        });
                        setNoteDraft("");
                      }}
                      className="btn-ghost shrink-0 !py-1.5 text-xs"
                    >
                      添加
                    </button>
                  </div>
                )}
              </section>
            ))}
          </div>

          <aside className="space-y-3 lg:sticky lg:top-20 lg:self-start">
            <div className="card space-y-3 p-5">
              <div className="flex items-center justify-between">
                <p className="section-title">本页批注</p>
                <span className="text-xs text-slate-400">{allNotes.length} 条</span>
              </div>

              {allNotes.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  <button
                    onClick={() => setFilter("all")}
                    className={`rounded-full px-2.5 py-1 text-[11px] transition ${
                      filter === "all"
                        ? "bg-slate-800 text-white"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    全部 {allNotes.length}
                  </button>
                  {colorCounts
                    .filter((item) => item.count > 0)
                    .map((item) => (
                      <button
                        key={item.color}
                        onClick={() => setFilter(item.color)}
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition ${
                          filter === item.color
                            ? "bg-slate-800 text-white"
                            : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        }`}
                      >
                        <span
                          className={`h-2 w-2 rounded-full ${COLOR_DOTS[item.color]}`}
                        />
                        {COLOR_LABELS[item.color]} {item.count}
                      </button>
                    ))}
                </div>
              ) : null}

              {allNotes.length === 0 ? (
                <p className="text-xs text-slate-400">
                  选中原文，点浮层里的颜色就能标注；也可以点句子里的 + 收重点词。
                </p>
              ) : (
                <ul className="space-y-2.5">
                  {visibleNotes.map((note) => (
                    <li
                      key={note.id}
                      onMouseEnter={() => setHoveredNoteId(note.id)}
                      onMouseLeave={() => setHoveredNoteId(null)}
                      className={`rounded-xl p-3 transition ${
                        hoveredNoteId === note.id ? "bg-brand-50" : "bg-slate-50"
                      }`}
                    >
                      {editingNoteId === note.id ? (

                        <div className="space-y-1.5">
                          <div className="flex items-start gap-2">
                            <span
                              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${COLOR_DOTS[note.color]}`}
                            />
                            <span className="min-w-0 flex-1 text-sm font-medium text-slate-800">
                              {note.text}
                              <span className="ml-1 text-[11px] font-normal text-slate-400">
                                第 {note.sentence_index + 1} 句
                              </span>
                            </span>
                          </div>
                          <label className="block text-[11px] text-slate-400">
                            翻译 / 释义
                          </label>
                          <textarea
                            autoFocus
                            rows={2}
                            value={editMeaning}
                            onChange={(event) => setEditMeaning(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Escape") cancelEditNote();
                              if (
                                event.key === "Enter" &&
                                (event.metaKey || event.ctrlKey)
                              ) {
                                void saveEditNote(note);
                              }
                            }}
                            placeholder="这个说法在这里的意思…"
                            className="input resize-none !py-1.5 text-xs"
                          />
                          <label className="block text-[11px] text-slate-400">备注</label>
                          <textarea
                            rows={2}
                            value={editBody}
                            onChange={(event) => setEditBody(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Escape") cancelEditNote();
                              if (
                                event.key === "Enter" &&
                                (event.metaKey || event.ctrlKey)
                              ) {
                                void saveEditNote(note);
                              }
                            }}
                            placeholder="自己的笔记…"
                            className="input resize-none !py-1.5 text-xs"
                          />
                          <div className="flex items-center gap-2 pt-0.5">
                            <button
                              type="button"
                              onClick={() => void saveEditNote(note)}
                              disabled={savingNote}
                              className="btn-primary !py-1 text-[11px]"
                            >
                              {savingNote ? "保存中…" : "保存"}
                            </button>
                            <button
                              type="button"
                              onClick={cancelEditNote}
                              className="btn-ghost !py-1 text-[11px]"
                            >
                              取消
                            </button>
                            <span className="ml-auto text-[11px] text-slate-400">
                              Ctrl+Enter 保存
                            </span>
                          </div>
                        </div>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => scrollToSentence(note.sentence_index)}
                            className="flex w-full items-start gap-2 text-left"
                          >
                            <span
                              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${COLOR_DOTS[note.color]}`}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block text-sm font-medium text-slate-800">
                                {note.text}
                                <span className="ml-1 text-[11px] font-normal text-slate-400">
                                  第 {note.sentence_index + 1} 句
                                </span>
                              </span>
                              {note.meaning ? (
                                <span className="block text-xs text-slate-500">
                                  {note.meaning}
                                </span>
                              ) : null}
                              {note.note ? (
                                <span className="mt-0.5 block text-xs text-slate-500">
                                  {note.note}
                                </span>
                              ) : null}
                            </span>
                          </button>

                          <div className="mt-2 flex items-center gap-2">
                            {COLOR_ORDER.map((color) => (
                              <button
                                key={color}
                                type="button"
                                title={`改为${COLOR_LABELS[color]}`}
                                onClick={() => handleChangeColor(note, color)}
                                className={`h-3.5 w-3.5 rounded-full transition hover:scale-125 ${COLOR_DOTS[color]} ${
                                  note.color === color
                                    ? "ring-2 ring-slate-400"
                                    : "ring-1 ring-slate-200"
                                }`}
                              />
                            ))}
                            <button
                              onClick={() => handleToggleVocabulary(note)}
                              disabled={note.in_vocabulary}
                              className={`ml-auto rounded-lg px-2 py-1 text-[11px] transition ${
                                note.in_vocabulary
                                  ? "bg-brand-50 text-brand-600"
                                  : "border border-slate-200 text-slate-600 hover:border-brand-300"
                              }`}
                            >
                              {note.in_vocabulary ? "已在词库" : "加入词库"}
                            </button>
                            <button
                              type="button"
                              title="修改释义和备注"
                              onClick={() => startEditNote(note)}
                              className="rounded-lg px-2 py-1 text-[11px] text-slate-500 transition hover:bg-slate-100 hover:text-brand-600"
                            >
                              编辑
                            </button>
                            <button
                              onClick={() => handleDeleteNote(note)}
                              className="rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:text-rose-500"
                            >
                              删除
                            </button>
                          </div>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>
      )}

      {selection ? (
        <SelectionToolbar
          selection={selection}
          onPickColor={handlePickColor}
          onAnnotate={handleAnnotate}
          onLookup={handleLookup}
          onClose={() => setSelection(null)}
        />
      ) : null}

      {popover ? (
        <WordPopover
          word={popover.word}
          raw={popover.raw}
          context={popover.context}
          position={{ x: popover.x, y: popover.y }}
          notedMeaning={notedNoteFor(popover.sentenceIndex, popover.raw)?.meaning}
          onAddNote={handleAnnotateFromPopover}
          onClose={() => setPopover(null)}
        />
      ) : null}
    </div>
  );
}

export default function ReadingWorkspacePage() {
  return (
    <RequireAuth>
      <AppShell>
        <Workspace />
      </AppShell>
    </RequireAuth>
  );
}
