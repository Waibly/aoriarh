import Link from "next/link";

export default function DemoLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-svh flex-col bg-white">
      <header className="border-b border-border">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 py-3 sm:px-6">
          <img
            src="/logo-aoria.svg"
            alt="AORIA RH"
            width={140}
            height={30}
            className="block h-7 w-auto"
          />
          <div className="flex items-center gap-3 text-sm">
            <Link
              href="/login"
              className="font-medium text-foreground hover:text-primary"
            >
              Se connecter
            </Link>
            <Link
              href="/register"
              className="rounded-md bg-primary px-4 py-2 font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Créer un compte
            </Link>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 sm:px-6">
        {children}
      </main>
    </div>
  );
}
