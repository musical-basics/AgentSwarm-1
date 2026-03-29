/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  transpilePackages: ["@agentswarm/shared-swarm"],
  images: {
    unoptimized: true,
  },
}

export default nextConfig
