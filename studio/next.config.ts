import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Production Studio is fronted by Caddy; API lives under /backend.
  // Local `next dev` talks to NEXT_PUBLIC_API_URL (usually http://127.0.0.1:8000).
};

export default nextConfig;
