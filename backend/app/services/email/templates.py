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
