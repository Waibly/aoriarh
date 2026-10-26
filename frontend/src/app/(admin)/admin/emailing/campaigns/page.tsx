import { redirect } from "next/navigation";

export default function LegacyEmailingPage() {
  redirect("/admin/emailing?section=campaigns");
}
