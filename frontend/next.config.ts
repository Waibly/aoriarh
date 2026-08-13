import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    reactCompiler: true,
  },
  headers: async () => [
    {
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        {
          key: "Content-Security-Policy",
          value: [
            "default-src 'self'",
            // challenges.cloudflare.com : widget Turnstile de la démo publique (/demo).
            // googletagmanager.com : gtag.js (GA4 + Google Ads), chargé uniquement
            // après consentement (bandeau du site vitrine, cookie .aoriarh.fr).
            "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://www.googletagmanager.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "img-src 'self' data:",
            "font-src 'self' data: https://fonts.gstatic.com",
            "connect-src 'self' " + new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").origin + " https://api.stripe.com https://challenges.cloudflare.com https://www.googletagmanager.com https://*.google-analytics.com https://*.analytics.google.com https://stats.g.doubleclick.net https://www.google.com https://www.google.fr https://googleads.g.doubleclick.net",
            "frame-src https://js.stripe.com https://challenges.cloudflare.com https://td.doubleclick.net https://www.googletagmanager.com",
          ].join("; "),
        },
        {
          key: "Permissions-Policy",
          value: "camera=(), microphone=(), geolocation=()",
        },
      ],
    },
  ],
};

export default nextConfig;
