import type { Metadata, Viewport } from "next";

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

// 移动端/刘海屏适配：viewport-fit=cover 让安全区变量生效，
// 底部标签栏再用 pb-safe 垫开 home 指示条；maximumScale 不限制，保留无障碍缩放。
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (

    <html lang="zh-CN" suppressHydrationWarning>
      <body>
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
