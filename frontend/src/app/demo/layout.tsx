import Link from "next/link";

export default function DemoLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-svh flex-col bg-[#f4f4f7]">
      {/* Header seul en pleine largeur (max-w-6xl), comme le site aoriarh.fr. */}
      <header className="sticky top-0 z-50 border-b border-border bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6">
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
      {/* Le contenu vit dans une carte blanche posée sur le fond gris (comme l'app). */}
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6 sm:px-6 sm:py-10">
        {children}
      </main>
    </div>
  );
}
