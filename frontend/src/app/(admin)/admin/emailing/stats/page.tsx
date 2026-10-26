import { EmailingStats } from "@/components/admin/emailing/stats";

export default async function EmailingStatsPage({
  searchParams,
}: {
  searchParams: Promise<{ campaign?: string }>;
}) {
  const { campaign } = await searchParams;
  return <EmailingStats key={campaign} initialCampaign={campaign} />;
}
