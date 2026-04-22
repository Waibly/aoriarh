import Image from "next/image";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="container relative grid min-h-svh flex-col items-center justify-center bg-white dark:bg-background lg:max-w-none lg:grid-cols-2 lg:px-0">
      <div className="bg-primary text-primary-foreground relative hidden h-full flex-col p-10 lg:flex">
        <div className="relative z-20 flex items-center text-lg font-medium">
          <Image src="/logo-aoria.png" alt="AORIA RH" width={140} height={40} priority />
        </div>
        <div className="relative z-20 mt-auto">
          <p className="text-2xl font-semibold leading-snug">
            Des réponses adaptées à votre réalité.
          </p>
          <p className="text-2xl font-semibold leading-snug text-primary-foreground/80 mt-1">
            Décidez en toute sécurité.
          </p>
        </div>
      </div>
      <div className="lg:p-8">
        <div className="mx-auto flex w-full flex-col justify-center space-y-6 sm:w-[350px]">
          {children}
        </div>
      </div>
    </div>
  );
}
