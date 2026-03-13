"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import type { CcnReference } from "@/types/api";

interface CcnSelectorProps {
  token: string;
  selected: CcnReference[];
  onChange: (selected: CcnReference[]) => void;
  disabled?: boolean;
}

export function CcnSelector({
  token,
  selected,
  onChange,
  disabled,
}: CcnSelectorProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CcnReference[]>([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(
    async (q: string) => {
      setLoading(true);
      try {
        const data = await apiFetch<{ results: CcnReference[]; total: number }>(
          `/conventions/search?q=${encodeURIComponent(q)}&limit=30`,
          { token }
        );
        setResults(data.results);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [token]
  );

  useEffect(() => {
    if (!open) return;
    search("");
  }, [open, search]);

  const handleSearch = (value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(value), 300);
  };

  const toggleItem = (ccn: CcnReference) => {
    const exists = selected.find((s) => s.idcc === ccn.idcc);
    if (exists) {
      onChange(selected.filter((s) => s.idcc !== ccn.idcc));
    } else {
      onChange([...selected, ccn]);
    }
  };

  const removeItem = (idcc: string) => {
    onChange(selected.filter((s) => s.idcc !== idcc));
  };

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-full justify-between font-normal"
            disabled={disabled}
          >
            {selected.length > 0
              ? `${selected.length} convention(s) sélectionnée(s)`
              : "Rechercher par nom ou IDCC..."}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command shouldFilter={false}>
            <CommandInput
              placeholder="Rechercher par nom ou IDCC..."
              value={query}
              onValueChange={handleSearch}
            />
            <CommandList>
              <CommandEmpty>
                {loading ? "Recherche..." : "Aucune convention trouvée"}
              </CommandEmpty>
              <CommandGroup>
                {results.map((ccn) => {
                  const isSelected = selected.some((s) => s.idcc === ccn.idcc);
                  const label = ccn.titre_court || ccn.titre;
                  return (
                    <CommandItem
                      key={ccn.idcc}
                      value={ccn.idcc}
                      onSelect={() => toggleItem(ccn)}
                    >
                      <Check
                        className={`mr-2 h-4 w-4 ${
                          isSelected ? "opacity-100" : "opacity-0"
                        }`}
                      />
                      <div className="flex flex-col min-w-0">
                        <span className="truncate text-sm">
                          {label}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          IDCC {ccn.idcc}
                        </span>
                      </div>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((ccn) => (
            <Badge
              key={ccn.idcc}
              variant="secondary"
              className="gap-1 pr-1"
            >
              {ccn.titre_court || ccn.titre} ({ccn.idcc})
              {!disabled && (
                <button
                  type="button"
                  onClick={() => removeItem(ccn.idcc)}
                  className="ml-0.5 rounded-full p-0.5 hover:bg-muted"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </Badge>
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Les textes seront installés automatiquement après la création.
      </p>
    </div>
  );
}
