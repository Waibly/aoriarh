export interface EmailCampaign {
  id: string;
  name: string;
  sequence_id: string;
  sequence_name: string | null;
  brevo_list_ids: number[];
  status: string;
  scheduled_at: string | null;
  current_step: number;
  recipient_count: number;
  sent_count: number;
  created_at: string;
}

interface BranchStats {
  condition: string;
  template_name: string | null;
  sent: number;
  opened: number;
  clicked: number;
  clicked_machine: number;
  bounced: number;
  unsubscribed: number;
}

interface StepStats {
  step_position: number;
  template_name: string | null;
  delay_days: number;
  sent: number;
  opened: number;
  clicked: number;
  clicked_machine: number;
  bounced: number;
  unsubscribed: number;
  branches: BranchStats[];
}

export const CONDITION_LABELS: Record<string, string> = {
  opened_and_clicked: "Ouvert + cliqué",
  opened_not_clicked: "Ouvert, pas cliqué",
  not_opened: "Pas ouvert",
};

export interface CampaignStats {
  campaign_id: string;
  campaign_name: string;
  status: string;
  total_recipients: number;
  steps: StepStats[];
}

export const STATUS_BADGE: Record<
  string,
  {
    label: string;
    variant: "default" | "secondary" | "outline" | "destructive";
  }
> = {
  draft: { label: "Brouillon", variant: "outline" },
  running: { label: "En cours", variant: "default" },
  paused: { label: "En pause", variant: "secondary" },
  completed: { label: "Terminée", variant: "secondary" },
};
