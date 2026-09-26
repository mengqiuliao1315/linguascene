"use client";

import { useEffect, useRef } from "react";

const PALETTE = ["#60a5fa", "#3b82f6", "#f472b6", "#fbbf24", "#a78bfa"];

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  size: number;
  rot: number;
  vrot: number;
  color: string;
  kind: "star" | "heart" | "dot";
};

function starPath(ctx: CanvasRenderingContext2D, r: number) {
  const tips = 4;
  ctx.beginPath();
  for (let i = 0; i < tips; i++) {
    const a0 = (i * Math.PI * 2) / tips - Math.PI / 2;
    const a1 = ((i + 1) * Math.PI * 2) / tips - Math.PI / 2;
    if (i === 0) ctx.moveTo(Math.cos(a0) * r, Math.sin(a0) * r);
    ctx.quadraticCurveTo(0, 0, Math.cos(a1) * r, Math.sin(a1) * r);
  }
  ctx.closePath();
}

function heartPath(ctx: CanvasRenderingContext2D, s: number) {
  ctx.beginPath();
  ctx.moveTo(0, s * 0.34);
  ctx.bezierCurveTo(-s * 1.05, -s * 0.36, -s * 0.44, -s * 1.0, 0, -s * 0.34);
  ctx.bezierCurveTo(s * 0.44, -s * 1.0, s * 1.05, -s * 0.36, 0, s * 0.34);
  ctx.closePath();
}

type BubbleSound = {
  play: (x: number) => void;
  dispose: () => void;
};

function createBubbleSound(): BubbleSound | null {

  try {
    if (localStorage.getItem("cuteCursorSound") === "off") return null;
  } catch {

  }

  const w = window as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  const Ctor = w.AudioContext ?? w.webkitAudioContext;
  if (!Ctor) return null;

  let ctx: AudioContext | null = null;

  const unlock = () => {
    if (!ctx) ctx = new Ctor();
    if (ctx.state === "suspended") void ctx.resume();
  };
  window.addEventListener("pointerdown", unlock, { passive: true });
  window.addEventListener("keydown", unlock, { passive: true });

  const play = (x: number) => {
    if (!ctx) return;
    if (ctx.state === "suspended") void ctx.resume();
    const t = ctx.currentTime;
    const base =
      300 + (x / Math.max(1, window.innerWidth)) * 360 + Math.random() * 70;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(base, t);
    osc.frequency.exponentialRampToValueAtTime(base * 2.8, t + 0.045);
    osc.frequency.exponentialRampToValueAtTime(base * 1.5, t + 0.13);

    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.11, t + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.17);

    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.2);
  };

  return {
    play,
    dispose: () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
      void ctx?.close();
      ctx = null;
    },
  };
}

export function CuteCursor() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    if (
      !window.matchMedia("(any-hover: hover) and (any-pointer: fine)").matches
    ) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const root = document.documentElement;
    root.classList.add("cute-cursor-active");

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const sound = createBubbleSound();

    let width = window.innerWidth;
    let height = window.innerHeight;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const target = { x: width / 2, y: height / 2 };
    const aura = { x: target.x, y: target.y, vx: 0, vy: 0, pop: 0 };
    let lastSpawn = { x: target.x, y: target.y };
    let seen = false;

    const particles: Particle[] = [];
    const MAX_PARTICLES = 150;

    let raf = 0;
    let running = false;
    let blinkTimer = 0;
    let blinkCountdown = 90 + Math.random() * 150;

    const spawn = (
      x: number,
      y: number,
      vx: number,
      vy: number,
      burst: boolean,
    ) => {
      if (particles.length >= MAX_PARTICLES) return;
      const kind: Particle["kind"] = burst
        ? Math.random() < 0.5
          ? "heart"
          : "star"
        : Math.random() < 0.75
          ? "star"
          : "dot";
      const maxLife = burst ? 46 + Math.random() * 26 : 34 + Math.random() * 22;
      particles.push({
        x,
        y,
        vx,
        vy,
        life: maxLife,
        maxLife,
        size: burst ? 5 + Math.random() * 6 : 2.6 + Math.random() * 5,
        rot: Math.random() * Math.PI * 2,
        vrot: (Math.random() - 0.5) * 0.14,
        color: PALETTE[Math.floor(Math.random() * PALETTE.length)],
        kind,
      });
    };

    const drawParticles = () => {
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        const k = p.life / p.maxLife;
        ctx.save();
        ctx.globalAlpha = k < 0.35 ? k / 0.35 : 1;
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = p.color;

        if (p.kind === "star") {
          starPath(ctx, p.size * (0.4 + k * 0.6));
          ctx.fill();
        } else if (p.kind === "heart") {
          heartPath(ctx, p.size * (0.5 + k * 0.6));
          ctx.fill();
        } else {
          ctx.globalAlpha *= 0.85;
          ctx.beginPath();
          ctx.arc(0, 0, p.size * 0.32 * (0.4 + k * 0.6), 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }
    };

    const drawAura = () => {
      const speed = Math.hypot(aura.vx, aura.vy);
      const dirX = Math.max(-1, Math.min(1, aura.vx / 6));
      const dirY = Math.max(-1, Math.min(1, aura.vy / 6));
      const pop = aura.pop;
      const r = 14 * (1 + pop * 0.4);
      const tilt = reduceMotion
        ? 0
        : Math.max(-0.35, Math.min(0.35, aura.vx * 0.02));

      ctx.save();
      ctx.translate(aura.x, aura.y);
      ctx.rotate(tilt);
      ctx.scale(1 + pop * 0.18, 1 - pop * 0.1);

      const grad = ctx.createRadialGradient(0, 0, 1, 0, 0, r);
      grad.addColorStop(0, "rgba(147, 197, 253, 0.34)");
      grad.addColorStop(1, "rgba(59, 130, 246, 0.05)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 1.4;
      ctx.strokeStyle = `rgba(59, 130, 246, ${0.42 - pop * 0.2})`;
      ctx.stroke();

      const blinking = blinkTimer > 0;
      const ex = dirX * 2.4;
      const ey = dirY * 2.4;
      ctx.fillStyle = "rgba(30, 58, 138, 0.85)";
      ctx.strokeStyle = "rgba(30, 58, 138, 0.85)";
      ctx.lineWidth = 1.5;
      ctx.lineCap = "round";
      for (const side of [-1, 1]) {
        const px = side * 4.2;
        if (blinking) {
          ctx.beginPath();
          ctx.moveTo(px - 1.7, ey * 0.4);
          ctx.lineTo(px + 1.7, ey * 0.4);
          ctx.stroke();
        } else {
          ctx.beginPath();
          ctx.arc(px + ex * 0.5, ey * 0.5 - 0.6, 1.7, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.fillStyle = "rgba(244, 114, 182, 0.32)";
      for (const side of [-1, 1]) {
        ctx.beginPath();
        ctx.arc(side * 7.4, 1.6, 2.1, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.strokeStyle = "rgba(30, 58, 138, 0.75)";
      ctx.beginPath();
      ctx.arc(ex * 0.4, 2.4, 2.6, 0.25 * Math.PI, 0.75 * Math.PI);
      ctx.stroke();

      ctx.restore();

      if (speed > 1.5) {
        ctx.save();
        ctx.globalAlpha = Math.min(0.5, speed / 26);
        ctx.fillStyle = "#93c5fd";
        ctx.beginPath();
        ctx.arc(-aura.vx * 1.6, -aura.vy * 1.6, r * 0.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    };

    const step = () => {
      if (reduceMotion) {

        aura.x = target.x;
        aura.y = target.y;
        aura.vx = 0;
        aura.vy = 0;
        aura.pop = 0;
        return;
      }

      aura.vx += (target.x - aura.x) * 0.24;
      aura.vy += (target.y - aura.y) * 0.24;
      aura.vx *= 0.68;
      aura.vy *= 0.68;
      aura.x += aura.vx;
      aura.y += aura.vy;
      aura.pop *= 0.9;
      if (aura.pop < 0.01) aura.pop = 0;

      if (blinkTimer > 0) {
        blinkTimer--;
      } else if (--blinkCountdown <= 0) {
        blinkTimer = 7;
        blinkCountdown = 90 + Math.random() * 170;
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.vx *= 0.96;
        p.vy = p.vy * 0.96 + 0.035;
        p.rot += p.vrot;
        p.life--;
        if (p.life <= 0 || p.y > height + 40) particles.splice(i, 1);
      }
    };

    const render = () => {
      if (width === 0 || height === 0) return;
      ctx.clearRect(0, 0, width, height);
      drawParticles();
      drawAura();
    };

    const settled = () =>
      reduceMotion ||
      (Math.abs(target.x - aura.x) < 0.5 &&
        Math.abs(target.y - aura.y) < 0.5 &&
        Math.hypot(aura.vx, aura.vy) < 0.5 &&
        aura.pop === 0 &&
        particles.length === 0);

    const loop = () => {
      step();
      render();
      if (settled()) {
        running = false;
        return;
      }
      raf = requestAnimationFrame(loop);
    };

    const tick = () => {
      step();
      render();
      if (!running && !settled()) {
        running = true;
        raf = requestAnimationFrame(loop);
      }
    };

    const onMove = (e: PointerEvent) => {
      target.x = e.clientX;
      target.y = e.clientY;
      if (!seen) {
        seen = true;
        aura.x = target.x;
        aura.y = target.y;
        lastSpawn = { x: target.x, y: target.y };
        tick();
        return;
      }
      const dx = target.x - lastSpawn.x;
      const dy = target.y - lastSpawn.y;
      const dist = Math.hypot(dx, dy);
      if (dist > 9) {
        lastSpawn = { x: target.x, y: target.y };
        if (!reduceMotion) {

          const nx = dx / dist;
          const ny = dy / dist;
          const spread = 0.9;
          spawn(
            target.x + (Math.random() - 0.5) * 6,
            target.y + (Math.random() - 0.5) * 6,
            -nx * (0.5 + Math.random()) + (Math.random() - 0.5) * spread,
            -ny * (0.5 + Math.random()) + (Math.random() - 0.5) * spread - 0.35,
            false,
          );
        }
      }
      tick();
    };

    const onDown = (e: MouseEvent) => {
      target.x = e.clientX;
      target.y = e.clientY;
      sound?.play(e.clientX);
      if (!reduceMotion) {
        aura.pop = 1;
        const count = 12;
        for (let i = 0; i < count; i++) {
          const a = (i / count) * Math.PI * 2 + Math.random() * 0.3;
          const speed = 1.6 + Math.random() * 2.4;
          spawn(
            e.clientX,
            e.clientY,
            Math.cos(a) * speed,
            Math.sin(a) * speed - 0.6,
            true,
          );
        }
      }
      tick();
    };

    const onVisibility = () => {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else {
        tick();
      }
    };

    const onResize = () => {
      resize();
      render();
    };

    resize();
    render();
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerdown", onDown, { passive: true });
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      root.classList.remove("cute-cursor-active");
      sound?.dispose();
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[100]"
    />
  );
}
