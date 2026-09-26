/**
 * Next.js 配置。
 *
 * /api/* 由 Next 服务端代理到后端，浏览器始终同源访问，
 * 因此本地换端口（3000/3001）不会触发 CORS 问题，
 * 同时保证 AI Key 等敏感配置只留在后端。
 */

const backendBase = process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 允许用独立目录构建，避免和正在运行的 dev server 抢 .next
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    // dev 代理默认 30 秒就断连，而首次逐句分析（要逐句调模型）常超过它，
    // 浏览器于是收到代理层的连接中断而不是后端的 JSON。放宽到 10 分钟。
    proxyTimeout: 600_000,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
