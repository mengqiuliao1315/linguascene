import type { Metadata } from "next";

import { AchievementUnlockToast } from "@/components/AchievementUnlockToast";
import { AiSharePromptDialog } from "@/components/AiSharePromptDialog";
import { CuteCursor } from "@/components/CuteCursor";
import { AuthProvider } from "@/lib/auth";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "LinguaScene",
  description: "Learn English by living it.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning：下面的脚本会在 React 接管前给 <html> 挂
    // data-theme，属性对不上会被当成水合不一致，这里明确放行。
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        {/* 先上色再渲染，避免刷新时闪一下默认皮肤 */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
        <AuthProvider>
          {children}
          <AchievementUnlockToast />
          <AiSharePromptDialog />
          <CuteCursor />
        </AuthProvider>
      </body>
    </html>
  );
}
