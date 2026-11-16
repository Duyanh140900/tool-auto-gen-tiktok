/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    typedRoutes: false,
  },
  // The frontend expects to talk to the FastAPI backend exposed on the same
  // machine (port 8000). We forward `/api/*` to it during `next dev` /
  // `next start` so the React app can keep using relative URLs.
  async rewrites() {
    const target = process.env.NEXT_PUBLIC_API_TARGET ?? "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${target}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;