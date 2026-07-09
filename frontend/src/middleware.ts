import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const session = req.auth;
  const isLoggedIn = !!session?.user?.email;
  const isAuthPage =
    req.nextUrl.pathname.startsWith("/login") ||
    req.nextUrl.pathname.startsWith("/register");
  const isInvitePage = req.nextUrl.pathname.startsWith("/invite");
  const isPromoPage = req.nextUrl.pathname.startsWith("/promo");
  // Démo publique (hero du site → réponse dans l'app) : accessible sans compte.
  const isDemoPage = req.nextUrl.pathname.startsWith("/demo");

  // Root "/" is not a landing page on app.aoriarh.fr: redirect to /chat if
  // logged in, otherwise to /login. The marketing site handles the rest.
  if (req.nextUrl.pathname === "/") {
    return NextResponse.redirect(
      new URL(isLoggedIn ? "/chat" : "/login", req.nextUrl.origin)
    );
  }

  if (isInvitePage || isPromoPage || isDemoPage) {
    return NextResponse.next();
  }

  if (isAuthPage) {
    if (isLoggedIn) {
      return NextResponse.redirect(new URL("/chat", req.nextUrl.origin));
    }
    return NextResponse.next();
  }

  if (!isLoggedIn) {
    return NextResponse.redirect(new URL("/login", req.nextUrl.origin));
  }

  if (req.nextUrl.pathname.startsWith("/admin")) {
    const role = session?.user?.role;
    if (role !== "admin") {
      return NextResponse.redirect(new URL("/chat", req.nextUrl.origin));
    }
    // Bare /admin lands on the cockpit matching the staff profile:
    // tech staff → technical console, everyone else → business cockpit.
    if (
      req.nextUrl.pathname === "/admin" ||
      req.nextUrl.pathname === "/admin/"
    ) {
      const dest =
        session?.user?.staff_role === "tech"
          ? "/admin/home"
          : "/admin/pilotage";
      return NextResponse.redirect(new URL(dest, req.nextUrl.origin));
    }
  }

  return NextResponse.next();
});

export const config = {
  // Skip API, Next internals, and any file with a static-asset extension
  // (svg, png, jpg, jpeg, gif, webp, ico, woff, woff2, ttf, eot, txt).
  matcher: [
    "/((?!api|_next/static|_next/image|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf|eot|txt)$).*)",
  ],
};
