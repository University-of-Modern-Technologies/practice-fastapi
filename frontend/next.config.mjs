/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits a self-contained server bundle so the runtime image carries neither the
  // sources nor node_modules.
  output: 'standalone',
  reactStrictMode: true,
  // The client is a pure API consumer: it must not be judged by a build-time
  // snapshot of data, so nothing is statically cached across requests.
  poweredByHeader: false,
};

export default nextConfig;
