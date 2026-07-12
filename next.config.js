/** @type {import('next').NextConfig} */
const nextConfig = {
  rewrites: async () => {
    return process.env.NODE_ENV === 'development'
      ? [{ source: '/api/py/:path*', destination: 'http://127.0.0.1:8000/api/py/:path*' }]
      : [];
  },
};

module.exports = nextConfig;
