export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="container relative grid min-h-svh flex-col items-center justify-center bg-white dark:bg-background lg:max-w-none lg:grid-cols-2 lg:px-0">
      <div className="bg-primary text-primary-foreground relative hidden h-full flex-col overflow-hidden p-10 lg:flex">
        {/* Filigrane icône */}
        <img
          src="/icon-aoria.png"
          alt=""
          aria-hidden
          className="pointer-events-none select-none absolute -right-[20%] top-1/2 -translate-y-1/2 w-[85%] max-w-[720px] opacity-[0.08] mix-blend-screen"
        />

        {/* Logo */}
        <div className="relative z-20 flex items-center">
          <img
            src="/logo-aoria-white.svg"
            alt="AORIA RH"
            className="h-9 w-auto"
          />
        </div>

        {/* Pitch */}
        <div className="relative z-20 mt-auto max-w-md space-y-6">
          <p className="text-3xl font-semibold leading-tight">
            Le Code du travail, votre CCN
            <br />
            et vos accords — au même endroit.
          </p>
          <ul className="space-y-2 text-base text-primary-foreground/85">
            <li className="flex items-start gap-2">
              <span aria-hidden className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-primary-foreground/70" />
              <span>Posez vos questions RH en langage naturel</span>
            </li>
            <li className="flex items-start gap-2">
              <span aria-hidden className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-primary-foreground/70" />
              <span>Recevez des réponses sourcées, articles à l&apos;appui</span>
            </li>
            <li className="flex items-start gap-2">
              <span aria-hidden className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-primary-foreground/70" />
              <span>Convention collective &amp; jurisprudence à jour</span>
            </li>
          </ul>
        </div>
      </div>
      <div className="lg:p-8">
        <div className="mx-auto flex w-full flex-col justify-center space-y-6 sm:w-[350px]">
          <img
            src="/icon-aoria.png"
            alt="AORIA RH"
            className="mx-auto h-14 w-14 lg:hidden"
          />
          {children}
        </div>
      </div>
    </div>
  );
}
