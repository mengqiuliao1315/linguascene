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
