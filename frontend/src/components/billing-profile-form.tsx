"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fetchBillingProfile, saveBillingProfile, type BillingProfile } from "@/lib/billing-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { toast } from "@/lib/toast";

const COUNTRIES = [
  ["FR", "France métropolitaine"], ["GP", "Guadeloupe"], ["MQ", "Martinique"],
  ["RE", "La Réunion"], ["GF", "Guyane"], ["YT", "Mayotte"],
  ["BL", "Saint-Barthélemy"], ["PM", "Saint-Pierre-et-Miquelon"],
  ["NC", "Nouvelle-Calédonie"], ["WF", "Wallis-et-Futuna"],
  ["MF", "Saint-Martin"], ["PF", "Polynésie française"],
];
// Preserve the existing international Checkout coverage. French territories
// have explicit labels above because they determine the domestic tax route.
const REGION_NAMES = new Intl.DisplayNames(["fr"], { type: "region" });
const OTHER_COUNTRIES = (
  "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BM BN BO BQ BR BS BT BV BW BY BZ " +
  "CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO " +
  "GA GB GD GE GG GH GI GL GM GN GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP " +
  "KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MG MH MK ML MM MN MO MP MR MS MT " +
  "MU MV MW MX MY MZ NA NE NF NG NI NL NO NP NR NU NZ OM PA PE PG PH PK PL PN PR PS PT PW PY QA RO RS RU RW SA SB " +
  "SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG " +
  "UM US UY UZ VA VC VE VG VI VN VU WS YE ZA ZM ZW"
).split(" ").map((code) => [code, REGION_NAMES.of(code) ?? code])
  .sort((a, b) => a[1].localeCompare(b[1], "fr"));
const EMPTY: BillingProfile = {
  business_name: "", line1: "", line2: "", postal_code: "", city: "",
  country: "FR", professional: false,
};

export function BillingProfileForm({ token, onReady }: {
  token: string; onReady: (ready: boolean) => void;
}) {
  const [profile, setProfile] = useState<BillingProfile>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = ["MF", "PF"].includes(profile.country) ||
    (/^\d{5}$/.test(profile.postal_code) &&
      (profile.postal_code === "97150" || profile.postal_code.startsWith("987")) &&
      ["FR", "GP", "MF", "PF"].includes(profile.country));

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = await fetchBillingProfile(token);
        if (active && data) {
          setProfile(data);
          onReady(data.professional && !["MF", "PF"].includes(data.country));
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Impossible de charger les coordonnées.");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, [token, onReady]);

  function update<K extends keyof BillingProfile>(key: K, value: BillingProfile[K]) {
    setProfile((old) => ({ ...old, [key]: value }));
    onReady(false);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const saved = await saveBillingProfile(token, profile);
      setProfile(saved);
      onReady(true);
      toast.success("Coordonnées de facturation enregistrées.");
    } catch (err) {
      onReady(false);
      setError(err instanceof Error ? err.message : "Impossible d'enregistrer les coordonnées.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card id="billing-coordinates">
      <CardHeader>
        <CardTitle>Coordonnées de facturation</CardTitle>
        <CardDescription>
          L&apos;adresse de votre entreprise permet d&apos;appliquer la TVA adaptée à vos achats et renouvellements.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <fieldset disabled={loading || saving} className="grid gap-4 sm:grid-cols-2">
            {([
              ["business_name", "Nom de l'entreprise", "organization"],
              ["line1", "Adresse", "address-line1"],
              ["line2", "Complément d'adresse (facultatif)", "address-line2"],
              ["postal_code", "Code postal", "postal-code"],
              ["city", "Ville", "address-level2"],
            ] as const).map(([key, label, autoComplete]) => (
              <div key={key} className="space-y-2">
                <Label htmlFor={`billing-${key}`}>{label}</Label>
                <Input id={`billing-${key}`} value={profile[key]} autoComplete={autoComplete}
                  maxLength={key === "postal_code" ? 20 : 255} required={key !== "line2"}
                  onChange={(event) => update(key, event.target.value)} />
              </div>
            ))}
            <div className="space-y-2">
              <Label htmlFor="billing-country">Pays ou territoire de l&apos;entreprise</Label>
              <select id="billing-country" value={profile.country} autoComplete="country"
                className="border-input bg-card h-9 w-full rounded-md border px-3 text-sm"
                onChange={(event) => update("country", event.target.value)}>
                {COUNTRIES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                {OTHER_COUNTRIES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                {![...COUNTRIES, ...OTHER_COUNTRIES].some(([code]) => code === profile.country) &&
                  <option value={profile.country}>{profile.country}</option>}
              </select>
            </div>
            <label className="flex items-start gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={profile.professional} required className="mt-1"
                onChange={(event) => update("professional", event.target.checked)} />
              J&apos;achète pour les besoins professionnels de cette entreprise.
            </label>
          </fieldset>
          {blocked && <p role="alert" className="text-sm text-destructive">
            Les souscriptions ne sont pas disponibles pour les entreprises établies à Saint-Martin ou en Polynésie française.
          </p>}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={loading || saving || blocked}>
            {saving ? "Enregistrement…" : "Enregistrer les coordonnées"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
