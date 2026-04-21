from datetime import datetime

BASE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0; padding:0; background-color:#f0fdfa; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <div style="padding:24px;">
    <div style="max-width:600px; margin:0 auto; background:#ffffff; border-radius:12px; overflow:hidden; border:1px solid #ccfbf1;">
      <div style="background-color:#0d9488; padding:28px 32px; text-align:center;">
        <h1 style="color:#ffffff; font-size:22px; margin:0; font-weight:700; letter-spacing:0.5px;">AORIA RH</h1>
      </div>
      <div style="padding:32px;">
        {content}
      </div>
      <div style="background-color:#f0fdfa; padding:16px 32px; text-align:center; font-size:12px; color:#5f6b6a;">
        <p style="margin:0 0 4px 0;">&copy; {year} AORIA RH. Tous droits réservés.</p>
        <p style="margin:0;">Cet email a été envoyé par AORIA RH. Si vous n'êtes pas concerné(e), ignorez ce message.</p>
      </div>
    </div>
  </div>
</body>
</html>"""

INVITATION_CONTENT = """\
<h2 style="margin-top:0; color:#0f766e; font-size:20px;">Vous êtes invité(e) !</h2>
<p style="color:#3f3f46; line-height:1.6;">Bonjour,</p>
<p style="color:#3f3f46; line-height:1.6;">
  <strong>{inviter_name}</strong> vous invite à rejoindre l'organisation
  <strong>{organisation_name}</strong> sur AORIA RH en tant que <strong>{role_label}</strong>.
</p>
<p style="color:#3f3f46; line-height:1.6;">Cliquez sur le bouton ci-dessous pour accepter l'invitation :</p>
<p style="text-align:center; margin:32px 0;">
  <a href="{accept_url}" style="display:inline-block; background-color:#0d9488; color:#ffffff; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:15px;">
    Accepter l'invitation
  </a>
</p>
<p style="color:#94a3b8; font-size:13px; line-height:1.5;">
  Ce lien est valable 7 jours. Si vous n'avez pas demandé cette invitation, ignorez ce message.
</p>"""


TEAM_INVITATION_CONTENT = """\
<h2 style="margin-top:0; color:#0f766e; font-size:20px;">Vous êtes invité(e) !</h2>
<p style="color:#3f3f46; line-height:1.6;">Bonjour,</p>
<p style="color:#3f3f46; line-height:1.6;">
  <strong>{inviter_name}</strong> vous invite à rejoindre l'équipe
  <strong>{account_name}</strong> sur AORIA RH en tant que <strong>{role_label}</strong>.
</p>
<p style="color:#3f3f46; line-height:1.6;">Cliquez sur le bouton ci-dessous pour accepter l'invitation :</p>
<p style="text-align:center; margin:32px 0;">
  <a href="{accept_url}" style="display:inline-block; background-color:#0d9488; color:#ffffff; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:15px;">
    Accepter l'invitation
  </a>
</p>
<p style="color:#94a3b8; font-size:13px; line-height:1.5;">
  Ce lien est valable 7 jours. Si vous n'avez pas demandé cette invitation, ignorez ce message.
</p>"""


def render_invitation_email(
    inviter_name: str,
    organisation_name: str,
    role_in_org: str,
    accept_url: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for an invitation email."""
    role_label = "Manager" if role_in_org == "manager" else "Utilisateur"
    subject = f"Invitation à rejoindre {organisation_name} sur AORIA RH"

    content = INVITATION_CONTENT.format(
        inviter_name=inviter_name,
        organisation_name=organisation_name,
        role_label=role_label,
        accept_url=accept_url,
    )
    html = BASE_TEMPLATE.format(
        subject=subject,
        content=content,
        year=datetime.now().year,
    )
    return subject, html


def render_team_invitation_email(
    inviter_name: str,
    account_name: str,
    role_in_org: str,
    accept_url: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for an account-level team invitation email."""
    role_label = "Manager" if role_in_org == "manager" else "Utilisateur"
    subject = f"Invitation à rejoindre l'équipe {account_name} sur AORIA RH"

    content = TEAM_INVITATION_CONTENT.format(
        inviter_name=inviter_name,
        account_name=account_name,
        role_label=role_label,
        accept_url=accept_url,
    )
    html = BASE_TEMPLATE.format(
        subject=subject,
        content=content,
        year=datetime.now().year,
    )
    return subject, html


# ---------------------------------------------------------------------------
# Trial lifecycle emails
# ---------------------------------------------------------------------------


TRIAL_REMINDER_CONTENT = """\
<h2 style="margin-top:0; color:#0f766e; font-size:20px;">Votre essai AORIA RH se termine {when_label}</h2>
<p style="color:#3f3f46; line-height:1.6;">Bonjour {full_name},</p>
<p style="color:#3f3f46; line-height:1.6;">
  Votre période d'essai gratuite de 14 jours prend fin <strong>{when_label}</strong>.
  Pour continuer à utiliser AORIA RH sans interruption, vous pouvez souscrire à l'offre
  qui vous convient dès maintenant.
</p>
<p style="text-align:center; margin:32px 0;">
  <a href="{upgrade_url}" style="display:inline-block; background-color:#0d9488; color:#ffffff; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:15px;">
    Choisir mon offre
  </a>
</p>
<p style="color:#3f3f46; line-height:1.6;">
  Pour rappel, nos offres commerciales :
</p>
<ul style="color:#3f3f46; line-height:1.8; padding-left:20px;">
  <li><strong>Solo</strong> — 79 €/mois · 1 utilisateur, 300 questions / mois</li>
  <li><strong>Équipe</strong> — 149 €/mois · 5 utilisateurs, 900 questions / mois</li>
  <li><strong>Groupe</strong> — 279 €/mois · 10 utilisateurs, 2 400 questions / mois</li>
</ul>
<p style="color:#94a3b8; font-size:13px; line-height:1.5; margin-top:24px;">
  Vos documents et conversations seront conservés 30 jours après la fin de l'essai.
  Vous pourrez les retrouver si vous souscrivez pendant cette période.
</p>"""


TRIAL_EXPIRED_CONTENT = """\
<h2 style="margin-top:0; color:#0f766e; font-size:20px;">Votre essai AORIA RH est terminé</h2>
<p style="color:#3f3f46; line-height:1.6;">Bonjour {full_name},</p>
<p style="color:#3f3f46; line-height:1.6;">
  Votre période d'essai gratuite est arrivée à son terme. L'accès à AORIA RH est
  temporairement suspendu, mais vos données sont conservées <strong>30 jours</strong>.
</p>
<p style="color:#3f3f46; line-height:1.6;">
  Pour réactiver votre compte et retrouver vos documents, choisissez l'offre qui
  correspond à votre besoin :
</p>
<p style="text-align:center; margin:32px 0;">
  <a href="{upgrade_url}" style="display:inline-block; background-color:#0d9488; color:#ffffff; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:15px;">
    Souscrire maintenant
  </a>
</p>
<p style="color:#94a3b8; font-size:13px; line-height:1.5; margin-top:24px;">
  Après 30 jours sans souscription, vos documents, conversations et paramètres
  seront définitivement supprimés conformément à notre politique de conservation.
</p>"""


def render_trial_reminder_email(
    full_name: str,
    days_remaining: int,
    upgrade_url: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for a trial reminder email (J-7 / J-3 / J-1)."""
    if days_remaining == 1:
        when_label = "demain"
        subject = "Votre essai AORIA RH se termine demain"
    elif days_remaining == 3:
        when_label = "dans 3 jours"
        subject = "Votre essai AORIA RH se termine dans 3 jours"
    else:
        when_label = f"dans {days_remaining} jours"
        subject = f"Votre essai AORIA RH se termine dans {days_remaining} jours"

    content = TRIAL_REMINDER_CONTENT.format(
        full_name=full_name,
        when_label=when_label,
        upgrade_url=upgrade_url,
    )
    html = BASE_TEMPLATE.format(
        subject=subject,
        content=content,
        year=datetime.now().year,
    )
    return subject, html


def render_trial_expired_email(
    full_name: str,
    upgrade_url: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for the trial expiration notification."""
    subject = "Votre essai AORIA RH est terminé"
    content = TRIAL_EXPIRED_CONTENT.format(
        full_name=full_name,
        upgrade_url=upgrade_url,
    )
    html = BASE_TEMPLATE.format(
        subject=subject,
        content=content,
        year=datetime.now().year,
    )
    return subject, html


# ---------------------------------------------------------------------------
# Over-quota (fair-use hard warning)
# ---------------------------------------------------------------------------


QUOTA_HARD_WARNING_CONTENT = """\
<h2 style="margin-top:0; color:#0f766e; font-size:20px;">Vous avez dépassé votre quota mensuel</h2>
<p style="color:#3f3f46; line-height:1.6;">Bonjour {full_name},</p>
<p style="color:#3f3f46; line-height:1.6;">
  Vous avez utilisé <strong>{used}</strong> questions ce mois-ci sur les
  <strong>{quota}</strong> incluses dans votre offre {plan_label}.
  Dans le cadre de notre politique « fair use », nous ne bloquons jamais
  vos questions &mdash; mais ce niveau d'usage suggère qu'un plan supérieur
  vous conviendrait mieux.
</p>
<p style="color:#3f3f46; line-height:1.6;">Deux options pour continuer sereinement&nbsp;:</p>
<ul style="color:#3f3f46; line-height:1.8; padding-left:20px;">
  <li><strong>Passer à l'offre supérieure</strong> &mdash; plus de questions, pas de limite à surveiller chaque mois.</li>
  <li><strong>Acheter un pack booster</strong> &mdash; +500 questions pour 25&nbsp;€, valables jusqu'à consommation complète.</li>
</ul>
<p style="text-align:center; margin:32px 0;">
  <a href="{upgrade_url}" style="display:inline-block; background-color:#0d9488; color:#ffffff; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:15px;">
    Gérer mon abonnement
  </a>
</p>
<p style="color:#94a3b8; font-size:13px; line-height:1.5;">
  Cet email est envoyé une seule fois par mois. Le quota se réinitialise au début du mois prochain.
</p>"""


def render_quota_hard_warning_email(
    full_name: str,
    plan_label: str,
    used: int,
    quota: int,
    upgrade_url: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for the over-quota upsell email."""
    subject = f"Vous avez dépassé votre quota mensuel AORIA RH ({used}/{quota})"
    content = QUOTA_HARD_WARNING_CONTENT.format(
        full_name=full_name,
        plan_label=plan_label,
        used=used,
        quota=quota,
        upgrade_url=upgrade_url,
    )
    html = BASE_TEMPLATE.format(
        subject=subject,
        content=content,
        year=datetime.now().year,
    )
    return subject, html


# ---------------------------------------------------------------------------
# Subscription confirmation + cancellation
# ---------------------------------------------------------------------------


SUBSCRIPTION_CONFIRMED_CONTENT = """\
<h2 style="margin-top:0; color:#0f766e; font-size:20px;">Bienvenue sur {plan_label} 🎉</h2>
<p style="color:#3f3f46; line-height:1.6;">Bonjour {full_name},</p>
<p style="color:#3f3f46; line-height:1.6;">
  Votre abonnement à l'offre <strong>{plan_label}</strong> ({cycle_label}) est actif.
  Vous bénéficiez immédiatement de l'ensemble des fonctionnalités&nbsp;:
</p>
<table style="width:100%; border-collapse:collapse; margin:16px 0;">
  <tr>
    <td style="padding:6px 0; color:#3f3f46;">Prochaine échéance</td>
    <td style="padding:6px 0; color:#3f3f46; text-align:right;"><strong>{next_billing_date}</strong></td>
  </tr>
</table>
<p style="text-align:center; margin:32px 0;">
  <a href="{billing_url}" style="display:inline-block; background-color:#0d9488; color:#ffffff; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:15px;">
    Gérer mon abonnement
  </a>
</p>
{invoice_section}
<p style="color:#94a3b8; font-size:13px; line-height:1.5;">
  Vous pouvez modifier ou résilier votre abonnement à tout moment depuis votre espace client.
  Un reçu officiel vous est également envoyé par Stripe à la même adresse.
</p>"""


SUBSCRIPTION_INVOICE_LINK = """\
<p style="text-align:center; margin:12px 0;">
  <a href="{invoice_url}" style="color:#0d9488; text-decoration:underline; font-size:13px;">
    Voir le reçu Stripe
  </a>
</p>"""


SUBSCRIPTION_CANCELED_CONTENT = """\
<h2 style="margin-top:0; color:#0f766e; font-size:20px;">Votre abonnement AORIA RH est résilié</h2>
<p style="color:#3f3f46; line-height:1.6;">Bonjour {full_name},</p>
<p style="color:#3f3f46; line-height:1.6;">
  Votre abonnement à l'offre <strong>{plan_label}</strong> a bien été résilié.
  Vous conservez l'accès jusqu'au <strong>{end_date}</strong> — au-delà, vos données
  seront conservées <strong>30 jours supplémentaires</strong> pour vous permettre de reprendre
  si vous changez d'avis.
</p>
<p style="text-align:center; margin:32px 0;">
  <a href="{billing_url}" style="display:inline-block; background-color:#0d9488; color:#ffffff; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:15px;">
    Réactiver mon abonnement
  </a>
</p>
<p style="color:#94a3b8; font-size:13px; line-height:1.5;">
  Après cette période de 30 jours, l'ensemble de vos documents, conversations et
  configurations seront définitivement supprimés, conformément à notre politique
  de conservation.
</p>
<p style="color:#94a3b8; font-size:13px; line-height:1.5;">
  Une remarque sur l'outil ? Un mail à hello@aoriarh.fr nous aide à l'améliorer.
</p>"""


def render_subscription_confirmed_email(
    full_name: str,
    plan_label: str,
    cycle: str,
    next_billing_date: str,
    billing_url: str,
    invoice_url: str | None = None,
) -> tuple[str, str]:
    """Return (subject, html_body) for the subscription confirmation email."""
    cycle_label = "mensuel" if cycle == "monthly" else "annuel"
    subject = f"Bienvenue sur AORIA RH {plan_label} — abonnement confirmé"

    invoice_section = ""
    if invoice_url:
        invoice_section = SUBSCRIPTION_INVOICE_LINK.format(invoice_url=invoice_url)

    content = SUBSCRIPTION_CONFIRMED_CONTENT.format(
        full_name=full_name,
        plan_label=plan_label,
        cycle_label=cycle_label,
        next_billing_date=next_billing_date,
        billing_url=billing_url,
        invoice_section=invoice_section,
    )
    html = BASE_TEMPLATE.format(
        subject=subject,
        content=content,
        year=datetime.now().year,
    )
    return subject, html


def render_subscription_canceled_email(
    full_name: str,
    plan_label: str,
    end_date: str,
    billing_url: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for the subscription cancellation email."""
    subject = "Votre abonnement AORIA RH est résilié"
    content = SUBSCRIPTION_CANCELED_CONTENT.format(
        full_name=full_name,
        plan_label=plan_label,
        end_date=end_date,
        billing_url=billing_url,
    )
    html = BASE_TEMPLATE.format(
        subject=subject,
        content=content,
        year=datetime.now().year,
    )
    return subject, html
