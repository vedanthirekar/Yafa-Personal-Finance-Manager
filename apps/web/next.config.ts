import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle for the Docker runtime stage.
  output: "standalone",
  // The repo root is the monorepo root, not apps/web; without this Next warns
  // about an inferred workspace root and can trace the wrong files.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
