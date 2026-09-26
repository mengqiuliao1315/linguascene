/**
 * 皮肤（主题）应用层。
 *
 * 后端只负责存用户的偏好（users.theme）并返回预览用的两款色块；
 * 真正让界面变色的机制是：把 code 写到 <html data-theme="code">，
 * 由 app/globals.css 里对应的色阶覆盖 --brand-50 ~ --brand-900。
 *
 * 新增皮肤要同时改三处：
 *   1. backend/app/services/levels.py 的 THEMES（code / name / 预览色块）
 *   2. frontend/app/globals.css 的 [data-theme="code"] 色阶
 *   3. 本文件的 THEME_CODES
 */

/** 默认皮肤，也是 :root 里那套色阶。 */
export const DEFAULT_THEME = "ocean";

export const THEME_CODES = [
  "ocean",
  "sky",
  "night",
  "coffee",
  "forest",
  "sakura",
] as const;

export type ThemeCode = (typeof THEME_CODES)[number];

const STORAGE_KEY = "linguascene:theme";

export function isThemeCode(value: unknown): value is ThemeCode {
  return (
    typeof value === "string" && (THEME_CODES as readonly string[]).includes(value)
  );
}

/**
 * 把皮肤贴到 <html data-theme="...">，CSS 变量随之切换。
 * 默认皮肤就是 :root 本身，所以不写 data-theme（而不是写 data-theme="ocean"）。
 * 同时往 localStorage 存一份，供首屏脚本在 React 挂载前抢先上色。
 */
export function applyTheme(code: string | null | undefined): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const active = isThemeCode(code) && code !== DEFAULT_THEME ? code : null;

  if (active) {
    root.dataset.theme = active;
  } else {
    delete root.dataset.theme;
  }

  try {
    if (active) {
      window.localStorage.setItem(STORAGE_KEY, active);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // 隐私模式 / 禁用存储时 localStorage 会抛错，换肤本身不该因此失败
  }
}

/**
 * 首屏防闪脚本：在 React 接管之前先把上次用过的皮肤贴到 <html> 上，
 * 否则刷新页面会先闪一下默认的 Ocean 再跳到用户选的皮肤。
 */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  STORAGE_KEY
)});if(t&&t!=="${DEFAULT_THEME}"){document.documentElement.dataset.theme=t}}catch(e){}})();`;
