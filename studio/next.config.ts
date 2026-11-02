import type { NextConfig } from "next";

const isGitHubPages = process.env.GITHUB_PAGES === "true";
const basePath = isGitHubPages ? "/universal-ai-backend" : "";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  output: isGitHubPages ? "export" : "standalone",
  ...(isGitHubPages ? { basePath, trailingSlash: true } : {}),
};

export default nextConfig;
