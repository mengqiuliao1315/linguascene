import type { Config } from "tailwindcss";

const config: Config = {
  // lib 里也有类名（热力图配色、宠物心情配色），漏掉会生成不出对应样式
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 品牌色阶不写死色值，改为引用 CSS 变量：切 <html data-theme="...">
        // 就能让全站 brand-* 一起换肤。色阶本身定义在 app/globals.css，
        // 与 backend/app/services/levels.py 的 THEMES 一一对应（改一处要改两处）。
        brand: {
          50: "rgb(var(--brand-50) / <alpha-value>)",
          100: "rgb(var(--brand-100) / <alpha-value>)",
          200: "rgb(var(--brand-200) / <alpha-value>)",
          300: "rgb(var(--brand-300) / <alpha-value>)",
          400: "rgb(var(--brand-400) / <alpha-value>)",
          500: "rgb(var(--brand-500) / <alpha-value>)",
          600: "rgb(var(--brand-600) / <alpha-value>)",
          700: "rgb(var(--brand-700) / <alpha-value>)",
          800: "rgb(var(--brand-800) / <alpha-value>)",
          900: "rgb(var(--brand-900) / <alpha-value>)",
        },
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        // 卡片投影里的那抹光晕也跟品牌色走，否则换肤后卡片还是蓝色。
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -12px rgb(var(--brand-600) / 0.16)",
      },
    },
  },
  plugins: [],
};

export default config;
