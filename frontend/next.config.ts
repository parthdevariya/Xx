import type { NextConfig } from "next";

const backend = process.env.X_BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    // Same-origin proxy so the session cookie is first-party. The browser never sees backend secrets.
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
