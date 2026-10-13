"use client";

import { useEffect, useState } from "react";

import { ErrorText, Modal } from "@/components/ui";
import { BASE_PATH } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const APK_PATH = `${BASE_PATH}/download/linguascene.apk`;

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);
  const [siteUrl, setSiteUrl] = useState("");

  // 手机上没法扫自己屏幕上的二维码，弹窗改为直接显示网址。
  // 地址取运行时真实访问地址，换域名/IP 访问也不会写错。
  useEffect(() => {
    setSiteUrl(`${window.location.origin}${BASE_PATH}`);
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh">
      <div className="hidden flex-1 flex-col justify-between bg-brand-600 p-12 text-white lg:flex">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/20">
            L
          </span>
          LinguaScene
        </div>
        <div className="space-y-6">
          <h1 className="text-4xl font-bold leading-tight">
            Learn English
            <br />
            by living it.
          </h1>
          <div className="flex flex-wrap gap-2 text-sm">
            {["☕ Ordering Coffee", "✈️ Airport Check-in", "💼 Job Interview"].map(
              (item) => (
                <span
                  key={item}
                  className="rounded-full bg-white/15 px-3 py-1.5"
                >
                  {item}
                </span>
              )
            )}
          </div>
        </div>
        <p className="text-sm text-white/60">场景 · 对话 · 纠错 · 成长</p>
      </div>

      <div className="flex flex-1 items-center justify-center px-6">
        <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-5">
          <div className="lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 font-bold text-white">
              L
            </span>
          </div>

          <h2 className="text-2xl font-semibold text-slate-900">登录</h2>

          <div className="space-y-3">
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="邮箱"
              className="input"
            />
            <input
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="密码"
              className="input"
            />
          </div>

          <ErrorText>{error}</ErrorText>

          <button
            type="submit"
            disabled={submitting}
            className="btn-primary w-full"
          >
            {submitting ? "登录中…" : "登录"}
          </button>

          <div className="flex flex-col items-center gap-2 pt-1">
            <p className="text-center text-xs text-slate-400">
              账号由管理员统一开通
            </p>
            {/* 桌面端：给出 Android 客户端下载入口（点开扫码） */}
            <button
              type="button"
              onClick={() => setQrOpen(true)}
              className="hidden text-xs text-slate-400 underline decoration-slate-200 underline-offset-2 transition hover:text-brand-600 md:inline"
            >
              📱 下载 Android 客户端
            </button>
            {/* 移动端：已经在手机上，直接展示网页地址，不再引导装包 */}
            <div className="space-y-1 md:hidden">
              <p className="text-center text-xs text-slate-400">
                网页版地址，用手机浏览器打开
              </p>
              <p className="break-all text-center font-mono text-xs text-slate-500">
                {siteUrl || "https://forddream.icu/linguascene"}
              </p>
            </div>
          </div>
        </form>
      </div>

      <Modal
        open={qrOpen}
        onClose={() => setQrOpen(false)}
        title="下载 Android 客户端"
        maxWidth="max-w-xs"
      >
        <div className="flex flex-col items-center gap-3">
          {/* 桌面端入口，扫码指向 APK，用手机扫码装客户端 */}
          {/* 二维码为构建期生成的静态资源 */}
          <img
            src={`${BASE_PATH}/download/qr-apk.svg`}
            alt="扫码下载 LinguaScene Android 安装包"
            className="h-44 w-44 rounded-xl border border-slate-200 bg-white p-2"
          />
          <p className="text-center text-xs leading-relaxed text-slate-500">
            用手机扫码下载安装包。若系统提示「未知来源」，请允许本次安装。
          </p>

          <a href={APK_PATH} download className="btn-primary w-full">
            直接下载安装包
          </a>
        </div>
      </Modal>
    </div>
  );
}