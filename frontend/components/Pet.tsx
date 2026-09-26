/**
 * 萌宠本体：一只抱着苹果的小刺猬「墩墩」。
 *
 * 形象是位图（`/pet/hedgehog.png`）。眨眼叠两张闭眼贴片；开心和委屈
 * 再各叠一对眼睛贴片，盖住瞳孔的一半。贴片由 `scripts/make_pet_faces.py`
 * 从底图上裁，外圈与底图像素一致，所以不会有接缝。
 *
 * 心情、进场、呼吸、打招呼、啃苹果各占一层 class，互不覆盖 transform。
 */

"use client";

import { useEffect, useState } from "react";

import type { PetMood } from "@/lib/pet";

/** 底图原始尺寸：贴片坐标都按这个比例换算成百分比 */
const ART_W = 400;
const ART_H = 521;

/**
 * 两张闭眼贴片的位置与大小（像素，按 ART_W×ART_H 量出）。
 * 换眨眼素材后同步这里。
 */
const BLINK_PATCHES = [
  { left: 75, top: 186, width: 97, height: 86, src: "/pet/eye-left.png" },
  { left: 234, top: 172, width: 93, height: 83, src: "/pet/eye-right.png" },
];

/**
 * 开心 / 委屈的眼睛贴片。框必须和 make_pet_faces.py 里的 EYES 一致，
 * 容器宽高比一变就会对不齐。
 */
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

/** 心情决定晃动方式。hungry 跟 sad 一样轻轻发抖，只是眼睛贴片不同。 */
const MOOD_ANIM: Record<PetMood, string> = {
  excited: "pet-hop",
  delighted: "pet-hop",
  happy: "pet-mood-happy",
  waiting: "pet-float",
  sad: "pet-mood-sad",
  hungry: "pet-mood-sad",
};

const MOOD_EMOJI: Record<PetMood, string[]> = {
  excited: ["💖", "✨", "🎵", "⭐"],
  delighted: ["💗", "✨"],
  happy: ["✨"],
  waiting: [],
  sad: [],
  hungry: [],
};

/** 百分比定位：贴片与特效都按底图比例摆，缩放时不会错位 */
const pct = (value: number, total: number) => `${(value / total) * 100}%`;

type FacePatch = { left: number; top: number; width: number; height: number; src: string };

function Patches({ patches }: { patches: FacePatch[] }) {
  return (
    <>
      {patches.map((patch) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={patch.src}
          src={patch.src}
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
  munching = false,
}: {
  mood: PetMood;
  className?: string;
  /** 久别重逢那一刻：多撒一圈爱心 */
  celebrate?: boolean;
  /** 进页面打招呼：笑眼再加一点上下点头 */
  greeting?: boolean;
  /** 刚喂下去的那几秒：啃苹果 */
  munching?: boolean;
}) {
  const [blink, setBlink] = useState(false);

  // 随机眨眼：闭眼 130ms，间隔 2.2~5s。笑眼 / 委屈眼盖着时不眨，避免两层贴片叠在一起。
  useEffect(() => {
    if (mood === "hungry" || mood === "sad" || greeting || munching) return;
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
  }, [mood, greeting, munching]);

  const face =
    munching || greeting
      ? "happy"
      : mood === "hungry"
        ? "sad"
        : mood === "sad"
          ? "sad"
          : null;

  return (
    <div className={`relative flex items-center justify-center ${className}`}>
      {/* 进场：从卡片外蹦到你面前，只播一次。
          高度撑满、宽度按底图比例算出来：贴片按底图百分比定位，
          容器比例一旦和底图不一致，贴片就会跑偏。 */}
      <div
        className="pet-enter relative h-full"
        style={{ aspectRatio: `${ART_W} / ${ART_H}` }}
      >
        {/* 打招呼的点头包在心情层外面，两层 transform 不抢 */}
        <div className={greeting ? "pet-greet h-full w-full" : "h-full w-full"}>
          {/* 心情动画只作用在这一层，特效层保持不动 */}
          <div className={`h-full w-full ${MOOD_ANIM[mood]}`}>
            {/* 呼吸只做极轻微的缩放，幅度大了会像在拉伸图片 */}
            <div className="pet-breathe relative h-full w-full">
              <div className={munching ? "pet-munch h-full w-full" : "h-full w-full"}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/pet/hedgehog.png"
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

        {/* 心情特效：百分比定位对齐底图上的眼睛与头顶 */}
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

          {mood === "sad" || mood === "hungry"
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

          {munching ? (
            <span
              className="absolute text-base"
              style={{
                left: "58%",
                top: "62%",
                animation: "pet-nibble 0.7s ease-in-out infinite",
              }}
            >
              🍎
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
