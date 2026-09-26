"use client";

import { useEffect, useState } from "react";

import type { PetMood } from "@/lib/pet";
import { BASE_PATH } from "@/lib/api";

const ART_W = 400;
const ART_H = 521;

const BLINK_PATCHES = [
  { left: 75, top: 186, width: 97, height: 86, src: "/pet/eye-left.png" },
  { left: 234, top: 172, width: 93, height: 83, src: "/pet/eye-right.png" },
];

const FACE_PATCHES = {
  happy: [
    { left: 108, top: 206, width: 40, height: 34, src: "/pet/happy-left.png" },
    { left: 260, top: 192, width: 40, height: 34, src: "/pet/happy-right.png" },
  ],
  sad: [
    { left: 108, top: 206, width: 40, height: 34, src: "/pet/sad-left.png" },
    { left: 260, top: 192, width: 40, height: 34, src: "/pet/sad-right.png" },
  ],
};

const MOOD_ANIM: Record<PetMood, string> = {
  excited: "pet-hop",
  delighted: "pet-hop",
  happy: "pet-mood-happy",
  waiting: "pet-float",
  sad: "pet-mood-sad",
};

const MOOD_EMOJI: Record<PetMood, string[]> = {
  excited: ["💖", "✨", "🎵", "⭐"],
  delighted: ["💗", "✨"],
  happy: ["✨"],
  waiting: [],
  sad: [],
};

const pct = (value: number, total: number) => `${(value / total) * 100}%`;

type FacePatch = { left: number; top: number; width: number; height: number; src: string };

function Patches({ patches }: { patches: FacePatch[] }) {
  return (
    <>
      {patches.map((patch) => (

        <img
          key={patch.src}
          src={`${BASE_PATH}${patch.src}`}
          alt=""
          draggable={false}
          className="pointer-events-none absolute select-none"
          style={{
            left: pct(patch.left, ART_W),
            top: pct(patch.top, ART_H),
            width: pct(patch.width, ART_W),
            height: pct(patch.height, ART_H),
          }}
        />
      ))}
    </>
  );
}

export function Pet({
  mood,
  className = "h-32 w-32",
  celebrate = false,
  greeting = false,
}: {
  mood: PetMood;
  className?: string;

  celebrate?: boolean;

  greeting?: boolean;
}) {
  const [blink, setBlink] = useState(false);

  useEffect(() => {
    if (mood === "sad" || greeting) return;
    let cancelled = false;
    let timer = 0;

    const loop = () => {
      timer = window.setTimeout(
        () => {
          if (cancelled) return;
          setBlink(true);
          timer = window.setTimeout(() => {
            if (cancelled) return;
            setBlink(false);
            loop();
          }, 130);
        },
        2200 + Math.random() * 2800,
      );
    };

    loop();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mood, greeting]);

  const face = greeting ? "happy" : mood === "sad" ? "sad" : null;

  return (
    <div className={`relative flex items-center justify-center ${className}`}>
      <div
        className="pet-enter relative h-full"
        style={{ aspectRatio: `${ART_W} / ${ART_H}` }}
      >
        <div className={greeting ? "pet-greet h-full w-full" : "h-full w-full"}>
          <div className={`h-full w-full ${MOOD_ANIM[mood]}`}>
            <div className="pet-breathe relative h-full w-full">
              <div className="h-full w-full">
                <img
                  src={`${BASE_PATH}/pet/hedgehog.png`}
                  alt=""
                  draggable={false}
                  className="h-full w-full select-none object-contain"
                />

                {blink && !face ? <Patches patches={BLINK_PATCHES} /> : null}
                {face ? <Patches patches={FACE_PATCHES[face]} /> : null}
              </div>
            </div>
          </div>
        </div>

        <div className="pointer-events-none absolute inset-0">
          {MOOD_EMOJI[mood].map((emoji, index) => (
            <span
              key={`${emoji}-${index}`}
              className="absolute text-sm"
              style={{
                left: `${[18, 62, 34, 70][index % 4]}%`,
                top: `${[6, 2, 20, 14][index % 4]}%`,
                animation: `pet-pop 1.8s ease-out ${index * 0.28}s infinite`,
              }}
            >
              {emoji}
            </span>
          ))}

          {mood === "sad"
            ? [28, 34].map((left, index) => (
                <span
                  key={left}
                  className="absolute text-[11px]"
                  style={{
                    left: `${left}%`,
                    top: "60%",
                    animation: `pet-tear 1.6s ease-in ${index * 0.5}s infinite`,
                  }}
                >
                  💧
                </span>
              ))
            : null}

          {celebrate
            ? [0, 1, 2, 3, 4].map((index) => (
                <span
                  key={index}
                  className="absolute text-base"
                  style={{
                    left: `${[14, 44, 66, 30, 58][index]}%`,
                    top: `${[44, 28, 38, 60, 54][index]}%`,
                    animation: `pet-burst 1.1s ease-out ${index * 0.12}s 1`,
                  }}
                >
                  {["💖", "✨", "💗", "⭐", "💕"][index]}
                </span>
              ))
            : null}
        </div>
      </div>
    </div>
  );
}
