import {
  EmailingSetup,
  type SetupSection,
} from "@/components/admin/emailing/setup";

export default async function EmailingPage({
  searchParams,
}: {
  searchParams: Promise<{ section?: string }>;
}) {
  const { section } = await searchParams;
  const initialSection: SetupSection =
    section === "lists" || section === "templates" || section === "sequences"
      ? section
      : "campaigns";
  return <EmailingSetup key={initialSection} initialSection={initialSection} />;
}
