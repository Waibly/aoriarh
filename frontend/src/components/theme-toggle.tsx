"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const isDark = document.documentElement.classList.contains("dark");
    setDark(isDark);
  }, []);

  const toggle = () => {
    document.documentElement.classList.toggle("dark");
    setDark(!dark);
  };

  return (
    <Button variant="outline" size="sm" onClick={toggle} className="w-full">
      {dark ? "Mode clair" : "Mode sombre"}
    </Button>
  );
}
