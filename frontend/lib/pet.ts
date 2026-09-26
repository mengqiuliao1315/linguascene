/**
 * 萌宠：形象目录、心情文案与接口。
 *
 * 形象只剩一个：刺猬「墩墩」。形象 id 必须与后端 pet_service.PET_SPECIES 一致。
 * 名字默认叫墩墩，用户可以随时点着改名；后端 pet_name 为空时前端回落到
 * DEFAULT_PET_NAME，不要直接拿 species.label 兜底（改形象名会连带改掉默认名）。
 *
 * 每天可以喂一次。fed_today 为 false 时 mood 是 hungry，卡片用委屈的眼睛
 * 表现「还没吃到」。喂过之后 mood 才回到陪伴天数对应的开心档。
 * 卡片上不展示心情标签/文案，心情只用来驱动动画、表情和问候语。
 */

import { request } from "./api";

export type PetMood = "excited" | "delighted" | "happy" | "waiting" | "sad" | "hungry";

export interface PetSpecies {
  id: string;
  label: string;
  emoji: string;
  tagline: string;
}

export const PET_SPECIES: PetSpecies[] = [
  { id: "hedgehog", label: "墩墩", emoji: "🦔", tagline: "圆滚滚一团软刺，抱着苹果等你回来" },
];

export const DEFAULT_SPECIES = "hedgehog";

/** 用户没改过名时的默认称呼；后端 pet_name 为空就用它 */
export const DEFAULT_PET_NAME = "墩墩";

export function speciesById(id: string): PetSpecies {
  return PET_SPECIES.find((item) => item.id === id) ?? PET_SPECIES[0];
}

export interface PetState {
  species: string;
  name: string;
  mood: PetMood;
  /** 见面前的心情：先播它再切到 mood，形成「难过 -> 开心」的过渡 */
  previous_mood: PetMood | null;
  days_away: number;
  login_streak: number;
  best_login_streak: number;
  study_streak: number;
  last_login_date: string | null;
  fed_today: boolean;
  feed_streak: number;
  last_fed_date: string | null;
}

/** 心情对应的晃动方式与问候语档位由组件决定；卡片上不再展示心情标签。 */

export const petApi = {
  /** 只读，可安全重复调用 */
  get: () => request<PetState>("/api/pet"),
  /** 记录今天来看过它；幂等，重复调用只算一次 */
  visit: () => request<PetState>("/api/pet/visit", { method: "POST" }),
  /** 每天喂一次；同一天再喂后端不涨连续天数，返回的仍是喂过的状态 */
  feed: () => request<PetState>("/api/pet/feed", { method: "POST" }),
  update: (payload: { species?: string; name?: string }) =>
    request<PetState>("/api/pet", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};
