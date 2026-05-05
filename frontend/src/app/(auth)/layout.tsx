export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="container relative grid min-h-svh flex-col items-center justify-center bg-white dark:bg-background lg:max-w-none lg:grid-cols-2 lg:px-0">
      <div className="bg-primary text-primary-foreground relative hidden h-full flex-col overflow-hidden p-10 lg:flex">
        {/* Filigrane icône blanche, sans fond */}
        <img
          src="/icon-aoria-white.svg"
          alt=""
          aria-hidden
          className="pointer-events-none select-none absolute -right-[8%] top-1/2 -translate-y-1/2 h-[55%] w-auto opacity-[0.15] mix-blend-screen"
        />

        {/* Logo */}
        <div className="relative z-20 flex items-center">
          <img
            src="/logo-aoria-white.svg"
            alt="AORIA RH"
            width={160}
            height={34}
            className="block"
          />
        </div>

        {/* Pitch */}
        <div className="relative z-20 mt-auto max-w-xl">
          <p className="text-4xl xl:text-5xl font-semibold leading-[1.1] tracking-tight">
            L&apos;humain au cœur des décisions.
          </p>
          <p className="mt-5 text-xl xl:text-2xl font-medium text-primary-foreground/80 leading-snug">
            AORIA RH, l&apos;outil pour les sécuriser.
          </p>
        </div>
      </div>
      <div className="lg:p-8">
        <div className="mx-auto flex w-full flex-col justify-center space-y-6 sm:w-[350px]">
          <img
            src="/icon-aoria-dark.svg"
            alt="AORIA RH"
            className="mx-auto h-14 w-14 lg:hidden"
          />
          {children}
        </div>
      </div>
    </div>
  );
}
