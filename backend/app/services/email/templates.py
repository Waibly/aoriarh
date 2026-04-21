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
