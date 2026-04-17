import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const session = req.auth;
  const isLoggedIn = !!session?.user?.email;
  const isAuthPage =
    req.nextUrl.pathname.startsWith("/login") ||
    req.nextUrl.pathname.startsWith("/register");
  const isInvitePage = req.nextUrl.pathname.startsWith("/invite");

  // Invite pages are accessible whether logged in or not
  if (isInvitePage) {
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

  // Redirect authenticated users from "/" to "/chat"
  if (req.nextUrl.pathname === "/") {
    return NextResponse.redirect(new URL("/chat", req.nextUrl.origin));
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
  matcher: ["/((?!api|_next/static|_next/image|favicon\\.ico|icon\\.png|apple-icon\\.png|logo-aoria\\.png|icon-aoria\\.png|robots\\.txt).*)"],
};
