/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // API requests رو proxy کن به backend
  async rewrites() {
    return [
      { source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' },
    ];
  },
};
module.exports = nextConfig;
