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

const MOOD_SWITCH_MS = 900;

const GREET_DELAY_MS = 620;

const BUBBLE_MS = 3600;

function greetingFor(mood: PetMood, pet: PetState): string {
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
    default:
      return "Hi! Ready to learn something new today?";
  }
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

  const started = useRef(false);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const later = (fn: () => void, delay: number) => {
      timers.current.push(window.setTimeout(fn, delay));
    };

    if (!started.current) {
      started.current = true;

      petApi
        .get()
        .then((state) => {
          setPet(state);
          setDraftName(state.name);
          const before = state.previous_mood;
          setMood(before ?? state.mood);
          setLoaded(true);

          void petApi.visit().catch(() => {

          });

          if (before && before !== state.mood) {
            later(() => {
              setMood(state.mood);
              if (before === "sad") setCelebrate(true);
            }, MOOD_SWITCH_MS);
          }

          later(() => {
            setGreeting(greetingFor(state.mood, state));
            setWaving(true);
            later(() => {
              setGreeting("");
              setWaving(false);
            }, BUBBLE_MS);
          }, GREET_DELAY_MS);
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : "宠物走丢了");
          setLoaded(true);
        });
    }

    return () => {
      timers.current.forEach((timer) => window.clearTimeout(timer));
      timers.current = [];
    };
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
