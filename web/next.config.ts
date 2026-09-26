import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Playwright runs its own dev server beside `make web`; Next allows one dev server per build directory.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // A stray package-lock.json above the repo made Next guess the wrong root.
  turbopack: { root: path.resolve(".") },
};

export default nextConfig;
