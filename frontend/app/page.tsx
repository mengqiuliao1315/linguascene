import { redirect } from "next/navigation";

/**
 * 根路径没有独立内容，统一进入仪表盘。
 * 未登录时 RequireAuth 会再把人送到 /login。
 */
export default function RootPage() {
  redirect("/dashboard");
}
