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

function isThemeCode(value: unknown): value is ThemeCode {
  return (
    typeof value === "string" && (THEME_CODES as readonly string[]).includes(value)
  );
}

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

  }
}

export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  STORAGE_KEY
)});if(t&&t!=="${DEFAULT_THEME}"){document.documentElement.dataset.theme=t}}catch(e){}})();`;
