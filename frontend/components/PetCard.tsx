/**
 * 首页萌宠卡片：展示刺猬「墩墩」，支持改名和每天喂一次。
 *
 * 名字默认是墩墩：后端 pet_name 为空时回落到 DEFAULT_PET_NAME，
 * 用户点一下名字（旁边有个灰色小铅笔提示可点）就能改，改完写回后端。
 *
 * 进页面先打招呼：站定后笑一下，气泡说一句英文。今天还没喂时，
 * 招呼说完就回到 hungry——眼睛耷下来，按钮可以喂。喂过之后按钮变灰，
 * 同一天再点不会再吃一次。
 *
 * 心情过渡：/api/pet 会返回「见面前」的旧心情。久别重逢时先播难过，
 * 再切到今天的心情并撒一圈爱心。卡片上不写心情标签。
 */

"use client";

import { useEffect, useRef, useState } from "react";

import { Pet } from "@/components/Pet";
import { ErrorText } from "@/components/ui";
import {
  DEFAULT_PET_NAME,
  petApi,
  type PetMood,
  type PetState,
} from "@/lib/pet";

/** 旧心情停留时长：太短看不见，太长显得迟钝 */
const MOOD_SWITCH_MS = 900;
/** 进场蹦跳约 0.95s，等它站定了再开口打招呼 */
const GREET_DELAY_MS = 620;
/** 气泡停留时长，与 pet-bubble 动画时长一致 */
const BUBBLE_MS = 3600;
/** 喂下去之后啃苹果的时长 */
const MUNCH_MS = 1600;

/** 见面第一句话（英文）：饿着优先，久别重逢其次，其余按心情说。 */
function greetingFor(mood: PetMood, pet: PetState): string {
  if (!pet.fed_today) {
    return "Hi! I saved you a spot... and my tummy is empty.";
  }
  if (pet.previous_mood === "sad" && pet.days_away > 0) {
    return `You're back! I waited ${pet.days_away} day${pet.days_away > 1 ? "s" : ""} for you.`;
  }
  switch (mood) {
    case "excited":
      return "You're here! I'm so happy I could spin!";
    case "delighted":
      return "Hi again! My quills are all perked up!";
    case "waiting":
      return "There you are! Let's start together!";
    case "sad":
      return "You're back... I've been waiting for you.";
    case "hungry":
      return "Hi! I saved you a spot... and my tummy is empty.";
    default:
      return "Hi! Ready to learn something new today?";
  }
}

function fedLine(pet: PetState): string {
  if (pet.feed_streak > 1) {
    return `今天喂过了 · 连续 ${pet.feed_streak} 天`;
  }
  return "今天喂过了，明天再来";
}

export function PetCard() {
  const [pet, setPet] = useState<PetState | null>(null);
  const [mood, setMood] = useState<PetMood>("happy");
  const [celebrate, setCelebrate] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [greeting, setGreeting] = useState("");
  const [waving, setWaving] = useState(false);
  const [munching, setMunching] = useState(false);
  const [feeding, setFeeding] = useState(false);
  // 严格模式下 effect 会跑两次；只让第一次真正发起请求和记录到访。
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    petApi
      .get()
      .then((state) => {
        setPet(state);
        setDraftName(state.name);
        // 先播见面前的心情。今天还没喂时，见面之后落到 hungry，而不是陪伴天数的开心档。
        const before = state.previous_mood;
        setMood(before ?? state.mood);
        setLoaded(true);

        void petApi.visit().catch(() => {
          // 记录失败不影响展示，下次打开首页会补上
        });

        if (before && before !== state.mood) {
          window.setTimeout(() => {
            setMood(state.mood);
            if (before === "sad") setCelebrate(true);
          }, MOOD_SWITCH_MS);
        }

        window.setTimeout(() => {
          setGreeting(greetingFor(state.mood, state));
          setWaving(true);
          window.setTimeout(() => {
            setGreeting("");
            setWaving(false);
          }, BUBBLE_MS);
        }, GREET_DELAY_MS);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "宠物走丢了");
        setLoaded(true);
      });
  }, []);

  useEffect(() => {
    if (!celebrate) return;
    const timer = setTimeout(() => setCelebrate(false), 1400);
    return () => clearTimeout(timer);
  }, [celebrate]);

  const saveName = async () => {
    if (!pet) return;
    setEditingName(false);
    const next = draftName.trim();
    // 没改过名时后端存的是空串，此时输入默认名不必写库
    const unchanged = pet.name ? next === pet.name : next === "" || next === DEFAULT_PET_NAME;
    if (unchanged) return;
    setError("");
    try {
      setPet(await petApi.update({ name: next }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "改名失败");
      setDraftName(pet.name);
    }
  };

  const feed = async () => {
    if (!pet || pet.fed_today || feeding) return;
    setFeeding(true);
    setError("");
    try {
      const next = await petApi.feed();
      setPet(next);
      setMood(next.mood);
      setMunching(true);
      setCelebrate(true);
      setGreeting("Yum! That's my apple for today.");
      setWaving(true);
      window.setTimeout(() => setMunching(false), MUNCH_MS);
      window.setTimeout(() => {
        setGreeting("");
        setWaving(false);
      }, BUBBLE_MS);
    } catch (err) {
      setError(err instanceof Error ? err.message : "喂食失败");
    } finally {
      setFeeding(false);
    }
  };

  if (!loaded) {
    return (
      <section className="card flex h-full flex-col justify-center space-y-4 p-5">
        <div className="flex h-40 items-center justify-center text-xs text-slate-300">
          正在叫它过来…
        </div>
      </section>
    );
  }

  if (!pet) {
    return (
      <section className="card space-y-3 p-5">
        <ErrorText>{error || "宠物暂时联系不上"}</ErrorText>
      </section>
    );
  }

  const displayName = pet.name || DEFAULT_PET_NAME;

  return (
    // 它和热力图同排，会被拉伸到一样高；纵向居中，别让内容顶在上面
    <section className="card flex h-full flex-col justify-center space-y-4 p-5">
      <div className="flex flex-col items-center gap-3">
        <div className="relative">
          {greeting ? (
            <div className="pointer-events-none absolute -top-9 left-1/2 z-10 -translate-x-1/2">
              <div className="pet-bubble relative whitespace-nowrap rounded-2xl bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-md">
                {greeting}
                <span className="absolute left-1/2 top-full h-2 w-2 -translate-x-1/2 -translate-y-1 rotate-45 bg-white" />
              </div>
            </div>
          ) : null}
          <button
            type="button"
            onClick={() => setCelebrate(true)}
            className="block transition hover:scale-105"
            title="摸摸它"
          >
            <Pet
              mood={mood}
              celebrate={celebrate}
              greeting={waving}
              munching={munching}
              className="h-32 w-32"
            />
          </button>
        </div>

        <div className="flex items-center gap-2">
          {editingName ? (
            <input
              autoFocus
              value={draftName}
              maxLength={12}
              onChange={(event) => setDraftName(event.target.value)}
              onBlur={saveName}
              onKeyDown={(event) => {
                if (event.key === "Enter") void saveName();
                if (event.key === "Escape") {
                  setDraftName(pet.name);
                  setEditingName(false);
                }
              }}
              placeholder={DEFAULT_PET_NAME}
              className="input w-32 px-2 py-1 text-center text-sm"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingName(true)}
              className="group inline-flex items-center gap-1.5 text-base font-semibold text-slate-900 hover:text-brand-700"
              title="点一下改名"
            >
              {displayName}
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-3.5 w-3.5 text-slate-400 transition group-hover:text-brand-500"
              >
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={() => void feed()}
          disabled={pet.fed_today || feeding}
          className={
            pet.fed_today
              ? "btn-ghost cursor-default px-3 py-1.5 text-xs text-slate-400"
              : "btn-primary px-3 py-1.5 text-xs"
          }
        >
          {pet.fed_today ? fedLine(pet) : feeding ? "正在喂…" : "🍎 喂一个苹果"}
        </button>

        <div className="flex w-full flex-wrap justify-center gap-2 text-[11px]">
          <span className="chip-slate">🗓️ 连续陪伴 {pet.login_streak} 天</span>
          <span className="chip-slate">🔥 学习打卡 {pet.study_streak} 天</span>
          {pet.best_login_streak > 0 ? (
            <span className="chip-slate">🏆 最长陪伴 {pet.best_login_streak} 天</span>
          ) : null}
        </div>
      </div>

      <ErrorText>{error}</ErrorText>
    </section>
  );
}
