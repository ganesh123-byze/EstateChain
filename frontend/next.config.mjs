/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/favicon.ico", destination: "/icon.svg" }];
  },
  async redirects() {
    return [
      { source: "/admin", destination: "/property_owner", permanent: true },
      { source: "/admin/:path*", destination: "/property_owner/:path*", permanent: true },
      { source: "/investor/yield", destination: "/investor", permanent: false },
    ];
  },
};

export default nextConfig;
