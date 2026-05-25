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

  // Root "/" is not a landing page on app.aoriarh.fr: redirect to /chat if
  // logged in, otherwise to /login. The marketing site handles the rest.
  if (req.nextUrl.pathname === "/") {
    return NextResponse.redirect(
      new URL(isLoggedIn ? "/chat" : "/login", req.nextUrl.origin),
    );
  }

  if (isInvitePage || isPromoPage) {
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
