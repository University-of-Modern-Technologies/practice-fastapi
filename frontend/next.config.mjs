// Where the dev server forwards `/api`. In the Docker stack nginx answers `/api`
// before a request ever reaches this server, so only local runs depend on it.
const apiOrigin = process.env.API_ORIGIN ?? 'http://127.0.0.1:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits a self-contained server bundle so the runtime image carries neither the
  // sources nor node_modules.
  output: 'standalone',
  reactStrictMode: true,
  // The client is a pure API consumer: it must not be judged by a build-time
  // snapshot of data, so nothing is statically cached across requests.
  poweredByHeader: false,
  // The repository carries its own contributor notes; next dev must not write more.
  agentRules: false,
  // `/api/docs/` needs its trailing slash; the default redirect strips it, and the
  // API adds it back, so neither side may rewrite the other's URL.
  skipTrailingSlashRedirect: true,
  // The client always calls its own origin, so it needs no address of the API.
  async rewrites() {
    return [
      // `:path*` drops a trailing slash, so a path that carries one keeps it here.
      { source: '/api/:path*/', destination: `${apiOrigin}/api/:path*/` },
      { source: '/api/:path*', destination: `${apiOrigin}/api/:path*` },
    ];
  },
};

export default nextConfig;
