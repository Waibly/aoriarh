import { Fragment } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CONDITION_LABELS, type CampaignStats } from "./types";

export const pct = (n: number, total: number) =>
  total > 0 ? `${Math.round((n / total) * 100)} %` : "—";

export function StatsTable({ stats }: { stats: CampaignStats }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Étape</TableHead>
          <TableHead className="text-right">Envoyés</TableHead>
          <TableHead className="text-right">Ouverts</TableHead>
          <TableHead className="text-right">Cliqués</TableHead>
          <TableHead className="text-right">Échoués</TableHead>
          <TableHead className="text-right">Désinscrits</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {stats.steps.map((step) => (
          <Fragment key={step.step_position}>
            <TableRow>
              <TableCell>
                <div>
                  <span className="font-medium">Jour {step.delay_days}</span>
                  {step.template_name && (
                    <span className="text-muted-foreground ml-2 text-xs">
                      {step.template_name}
                    </span>
                  )}
                  {step.branches.length > 0 && !step.template_name && (
                    <span className="text-muted-foreground ml-2 text-xs">
                      (branchement)
                    </span>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-right">{step.sent}</TableCell>
              <TableCell className="text-right">
                {step.opened}{" "}
                <span className="text-muted-foreground text-xs">
                  ({pct(step.opened, step.sent)})
                </span>
              </TableCell>
              <TableCell className="text-right">
                {step.clicked}{" "}
                <span className="text-muted-foreground text-xs">
                  ({pct(step.clicked, step.sent)})
                </span>
                {(step.clicked_machine ?? 0) > 0 && (
                  <span className="text-muted-foreground block text-[10px]">
                    {step.clicked_machine} bot
                    {step.clicked_machine > 1 ? "s" : ""} filtré
                    {step.clicked_machine > 1 ? "s" : ""}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-right">{step.bounced}</TableCell>
              <TableCell className="text-right">{step.unsubscribed}</TableCell>
            </TableRow>
            {step.branches.map((branch) => (
              <TableRow
                key={`${step.step_position}-${branch.condition}`}
                className="bg-muted/30"
              >
                <TableCell className="pl-8">
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-muted-foreground">↳</span>
                    <Badge variant="outline" className="text-xs">
                      {CONDITION_LABELS[branch.condition] ?? branch.condition}
                    </Badge>
                    {branch.template_name && (
                      <span className="text-muted-foreground">
                        {branch.template_name}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-right text-xs">
                  {branch.sent}
                </TableCell>
                <TableCell className="text-right text-xs">
                  {branch.opened}{" "}
                  <span className="text-muted-foreground">
                    ({pct(branch.opened, branch.sent)})
                  </span>
                </TableCell>
                <TableCell className="text-right text-xs">
                  {branch.clicked}{" "}
                  <span className="text-muted-foreground">
                    ({pct(branch.clicked, branch.sent)})
                  </span>
                  {(branch.clicked_machine ?? 0) > 0 && (
                    <span className="text-muted-foreground block text-[10px]">
                      {branch.clicked_machine} bot
                      {branch.clicked_machine > 1 ? "s" : ""} filtré
                      {branch.clicked_machine > 1 ? "s" : ""}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right text-xs">
                  {branch.bounced}
                </TableCell>
                <TableCell className="text-right text-xs">
                  {branch.unsubscribed}
                </TableCell>
              </TableRow>
            ))}
          </Fragment>
        ))}
      </TableBody>
    </Table>
  );
}
