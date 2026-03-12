import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

const API_BASE_URL =
  process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

declare module "next-auth" {
  interface User {
    access_token: string;
    refresh_token: string;
    expires_at: number;
    role: string;
    full_name: string;
  }

  interface Session {
    access_token: string;
    error?: string;
    user: {
      id: string;
      email: string;
      full_name: string;
      role: string;
    };
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    access_token: string;
    refresh_token: string;
    expires_at: number;
    id: string;
    role: string;
    full_name: string;
    error?: string;
  }
}

async function refreshAccessToken(token: {
  refresh_token: string;
  [key: string]: unknown;
}) {
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token.refresh_token }),
    });

    if (!res.ok) throw new Error("Refresh failed");

    const data = await res.json();

    return {
      ...token,
      access_token: data.access_token as string,
      refresh_token: data.refresh_token as string,
      expires_at: Math.floor(Date.now() / 1000) + (data.expires_in as number),
    };
  } catch {
    return { ...token, error: "RefreshTokenExpired" };
  }
}

async function getBackendTokensForGoogle(profile: {
  email: string;
  name: string;
  sub: string;
}) {
  const res = await fetch(`${API_BASE_URL}/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: profile.email,
      full_name: profile.name,
      google_sub: profile.sub,
    }),
  });

  if (!res.ok) return null;
  return res.json();
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Credentials({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Mot de passe", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          return null;
        }

        try {
          const loginRes = await fetch(`${API_BASE_URL}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          });

          if (!loginRes.ok) return null;

          const { access_token, refresh_token, expires_in } =
            await loginRes.json();

          const userRes = await fetch(`${API_BASE_URL}/users/me`, {
            headers: { Authorization: `Bearer ${access_token}` },
          });

          if (!userRes.ok) return null;

          const user = await userRes.json();

          return {
            id: user.id,
            email: user.email,
            name: user.full_name,
            full_name: user.full_name,
            role: user.role,
            access_token,
            refresh_token,
            expires_at: Math.floor(Date.now() / 1000) + expires_in,
          };
        } catch {
          return null;
        }
      },
    }),
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
  ],
  callbacks: {
    authorized({ auth, request }) {
      const isLoggedIn = !!auth?.user?.email;
      const isAuthPage =
        request.nextUrl.pathname.startsWith("/login") ||
        request.nextUrl.pathname.startsWith("/register");
      const isInvitePage = request.nextUrl.pathname.startsWith("/invite");
      if (isInvitePage || isAuthPage) return true;
      return isLoggedIn;
    },
    async jwt({ token, user, account, profile }) {
      // Initial sign-in via Credentials
      if (user && account?.provider === "credentials") {
        token.access_token = user.access_token;
        token.refresh_token = user.refresh_token;
        token.expires_at = user.expires_at;
        token.id = user.id as string;
        token.role = user.role;
        token.full_name = user.full_name;
        return token;
      }

      // Initial sign-in via Google
      if (account?.provider === "google" && profile) {
        const googleProfile = profile as { email: string; name: string; sub: string };
        const backendTokens = await getBackendTokensForGoogle({
          email: googleProfile.email ?? "",
          name: googleProfile.name ?? "",
          sub: googleProfile.sub ?? "",
        });

        if (!backendTokens) {
          return { ...token, error: "GoogleAuthFailed" };
        }

        // Fetch user profile from backend
        const userRes = await fetch(`${API_BASE_URL}/users/me`, {
          headers: { Authorization: `Bearer ${backendTokens.access_token}` },
        });

        if (!userRes.ok) {
          return { ...token, error: "GoogleAuthFailed" };
        }

        const backendUser = await userRes.json();

        token.access_token = backendTokens.access_token;
        token.refresh_token = backendTokens.refresh_token;
        token.expires_at = Math.floor(Date.now() / 1000) + backendTokens.expires_in;
        token.id = backendUser.id;
        token.role = backendUser.role;
        token.full_name = backendUser.full_name;
        return token;
      }

      // Token still valid — return as-is
      if (Date.now() / 1000 < token.expires_at) {
        return token;
      }

      // Token expired — refresh it
      return refreshAccessToken(token) as unknown as typeof token;
    },
    async session({ session, token }) {
      session.access_token = token.access_token;
      session.user.id = token.id;
      session.user.email = token.email as string;
      session.user.full_name = token.full_name;
      session.user.role = token.role;
      if (token.error) {
        session.error = token.error;
      }
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 7 * 24 * 60 * 60, // 7 days — matches refresh token expiry
  },
});
