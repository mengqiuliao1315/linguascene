import type { AiPreset } from "@/lib/aiFormats";

export function AiProviderIcon({
  preset,
  size = "md",
}: {
  preset: AiPreset;
  size?: "sm" | "md";
}) {
  const box =
    size === "sm"
      ? "h-6 w-6 rounded-md text-[11px]"
      : "h-9 w-9 rounded-lg text-sm";
  return (
    <span
      aria-hidden
      className={`flex shrink-0 items-center justify-center font-semibold ${box} ${preset.accent}`}
    >
      {preset.initial}
    </span>
  );
}
