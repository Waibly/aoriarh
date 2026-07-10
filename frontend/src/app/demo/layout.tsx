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
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4 sm:px-6">
          <img
            src="/logo-aoria.svg"
            alt="AORIA RH"
            width={140}
            height={30}
            className="block h-6 w-auto shrink-0 sm:h-7"
          />
          <div className="flex items-center gap-2 text-sm sm:gap-3">
            <Link
              href="/login"
              className="font-medium text-foreground hover:text-primary"
            >
              Se connecter
            </Link>
            <Link
              href="/register"
              className="whitespace-nowrap rounded-md bg-primary px-3 py-1.5 font-semibold text-primary-foreground hover:bg-primary/90 sm:px-4 sm:py-2"
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
