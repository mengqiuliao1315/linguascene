/**
 * 萌宠本体：一只抱着苹果的小刺猬「墩墩」。
 *
 * 形象改用位图（`/pet/hedgehog.png`），不再手写 SVG。眨眼是唯一的细节动作，
 * 做法是两张预先算好的「闭眼贴片」：`scripts/make_blink_patches2.py` 从**已缩放的底图**
 * 上把眼睛那片裁下来，只把眼球像素换成周围肤色、再压一条睫毛弧。贴片外圈与底图
 * 逐像素一致，叠上去不会有接缝，所以不必给眼睛建矢量模型。
 *
 * 心情、进场、呼吸仍是 CSS 动画，各占一层 class，互不覆盖 transform。
 */

"use client";

import { useEffect, useState } from "react";

import type { PetMood } from "@/lib/pet";

/** 底图原始尺寸：贴片坐标都按这个比例换算成百分比 */
const ART_W = 400;
const ART_H = 521;

/**
 * 两张闭眼贴片的位置与大小（像素，按 ART_W×ART_H 量出）。
 * `scripts/make_blink_patches.py` 会打印这组数字，换素材后同步这里。
 */
const BLINK_PATCHES = [
  { left: 75, top: 186, width: 97, height: 86 },
  { left: 234, top: 172, width: 93, height: 83 },
];

/** 心情决定晃动方式。 */
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

/** 百分比定位：贴片与特效都按底图比例摆，缩放时不会错位 */
const pct = (value: number, total: number) => `${(value / total) * 100}%`;

export function Pet({
  mood,
  className = "h-32 w-32",
  celebrate = false,
}: {
  mood: PetMood;
  className?: string;
  /** 久别重逢那一刻：多撒一圈爱心 */
  celebrate?: boolean;
}) {
  const [blink, setBlink] = useState(false);

  // 随机眨眼：闭眼 130ms，间隔 2.2~5s，看起来才像活物
  useEffect(() => {
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
  }, []);

  return (
    <div className={`relative flex items-center justify-center ${className}`}>
      {/* 进场：从卡片外蹦到你面前，只播一次。
          高度撑满、宽度按底图比例算出来：贴片按底图百分比定位，
          容器比例一旦和底图不一致，贴片就会跑偏。 */}
      <div
        className="pet-enter relative h-full"
        style={{ aspectRatio: `${ART_W} / ${ART_H}` }}
      >
        {/* 心情动画只作用在这一层，特效层保持不动 */}
        <div className={`h-full w-full ${MOOD_ANIM[mood]}`}>
          {/* 呼吸只做极轻微的缩放，幅度大了会像在拉伸图片 */}
          <div className="pet-breathe relative h-full w-full">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/pet/hedgehog.png"
              alt=""
              draggable={false}
              className="h-full w-full select-none object-contain"
            />

            {/* 闭眼贴片：只在眨眼那一瞬叠上去 */}
            {blink
              ? BLINK_PATCHES.map((patch, index) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={index}
                    src={`/pet/eye-${index === 0 ? "left" : "right"}.png`}
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
                ))
              : null}
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
