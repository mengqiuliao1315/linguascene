import { request } from "./api";

export type PetMood = "excited" | "delighted" | "happy" | "waiting" | "sad";

export interface PetSpecies {
  id: string;
  label: string;
  emoji: string;
  tagline: string;
}

export const PET_SPECIES: PetSpecies[] = [
  { id: "hedgehog", label: "墩墩", emoji: "🦔", tagline: "圆滚滚一团软刺，等你回来" },
];

export const DEFAULT_PET_NAME = "墩墩";

export interface PetState {
  species: string;
  name: string;
  mood: PetMood;

  previous_mood: PetMood | null;
  days_away: number;
  login_streak: number;
  best_login_streak: number;
  study_streak: number;
  last_login_date: string | null;
}

export const petApi = {

  get: () => request<PetState>("/api/pet"),

  visit: () => request<PetState>("/api/pet/visit", { method: "POST" }),
  update: (payload: { species?: string; name?: string }) =>
    request<PetState>("/api/pet", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};
