"""Page publique du questionnaire de fin d'essai (lien signé, sans connexion).

GET affiche le formulaire avec la raison cliquée dans l'email présélectionnée ;
seul le POST enregistre la réponse (un scanner d'emails ne fait que des GET).
"""

import json
import uuid
from html import escape

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.account import Account
from app.services.trial_feedback_service import (
    COMMENT_MAX_LENGTH,
    REASONS,
    REASONS_BY_CODE,
    record_feedback,
    verify_feedback_signature,
)

router = APIRouter()

_STYLE = """
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f5f3ff;
    margin:0; display:flex; min-height:100vh; align-items:center; justify-content:center; }
  .card { background:#fff; max-width:520px; width:92%; padding:36px 32px; border-radius:16px;
    box-shadow:0 4px 24px rgba(0,0,0,.06); margin:24px 0; }
  h1 { font-size:20px; margin:0 0 12px; color:#652BB0; }
  p { color:#3f3f46; line-height:1.5; margin:0 0 20px; }
  fieldset { border:0; padding:0; margin:0 0 20px; }
  label.choice { display:flex; gap:10px; align-items:center; padding:10px 12px; margin-bottom:8px;
    border:1px solid #e4e4e7; border-radius:10px; cursor:pointer; color:#27272a; }
  label.choice:has(input:checked) { border-color:#652BB0; background:#f5f3ff; }
  label.comment { display:block; font-weight:600; color:#27272a; margin-bottom:8px; }
  textarea { width:100%; box-sizing:border-box; min-height:110px; padding:10px 12px;
    border:1px solid #d4d4d8; border-radius:10px; font:inherit; resize:vertical; }
  .hint { font-size:13px; color:#71717a; margin:6px 0 20px; }
  button, a.button { display:inline-block; background:#652BB0; color:#fff; border:0;
    border-radius:10px; padding:12px 24px; font-size:15px; cursor:pointer; text-decoration:none; }
  .muted { font-size:13px; color:#a1a1aa; margin-top:24px; text-align:center; }
"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{escape(title)}</title><style>{_STYLE}</style></head>
<body><div class="card"><h1>{escape(title)}</h1>{body}
<div class="muted">AORIA RH</div></div></body></html>"""
    return HTMLResponse(html, status_code=status_code)


def _invalid() -> HTMLResponse:
    return _page("Lien invalide", "<p>Ce lien n'est pas valide ou a expiré.</p>", 400)


async def _resolve_account(db: AsyncSession, a: str, sig: str) -> Account | None:
    try:
        account_id = uuid.UUID(a)
    except ValueError:
        return None
    if not verify_feedback_signature(account_id, sig):
        return None
    return await db.get(Account, account_id)


def _form(a: str, sig: str, selected: str | None, comment: str = "", error: str = "") -> str:
    choices = "".join(
        f'<label class="choice"><input type="radio" name="reason" value="{r.code}" required'
        f"{' checked' if r.code == selected else ''}> {escape(r.label)}</label>"
        for r in REASONS
    )
    current = REASONS_BY_CODE.get(selected or "")
    question = current.question if current else "Souhaitez-vous préciser ?"
    questions = json.dumps({r.code: r.question for r in REASONS}, ensure_ascii=False)
    error_html = f'<p style="color:#b91c1c;">{escape(error)}</p>' if error else ""
    return f"""{error_html}
<p>Votre réponse nous aide à améliorer AORIA RH. Qu'est-ce qui vous a retenu de souscrire ?</p>
<form method="post" action="/api/v1/trial-feedback">
  <input type="hidden" name="a" value="{escape(a)}">
  <input type="hidden" name="sig" value="{escape(sig)}">
  <fieldset>{choices}</fieldset>
  <label class="comment" for="comment" id="comment-label">{escape(question)}</label>
  <textarea id="comment" name="comment" maxlength="{COMMENT_MAX_LENGTH}"
    placeholder="Facultatif">{escape(comment)}</textarea>
  <div class="hint">Facultatif. Merci de ne pas indiquer d'information personnelle.</div>
  <button type="submit">Envoyer ma réponse</button>
</form>
<script>
  const questions = {questions};
  document.querySelectorAll('input[name="reason"]').forEach((input) => {{
    input.addEventListener('change', () => {{
      document.getElementById('comment-label').textContent = questions[input.value];
    }});
  }});
</script>"""


@router.get("", response_class=HTMLResponse)
async def trial_feedback_form(
    a: str,
    sig: str,
    r: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    account = await _resolve_account(db, a, sig)
    if account is None:
        return _invalid()
    selected = r if r in REASONS_BY_CODE else None
    return _page("Votre essai AORIA RH", _form(a, sig, selected))


@router.post("", response_class=HTMLResponse)
async def trial_feedback_submit(
    a: str = Form(...),
    sig: str = Form(...),
    reason: str = Form(""),
    comment: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    account = await _resolve_account(db, a, sig)
    if account is None:
        return _invalid()
    try:
        await record_feedback(db, account, reason, comment)
    except ValueError as exc:
        selected = reason if reason in REASONS_BY_CODE else None
        return _page("Votre essai AORIA RH", _form(a, sig, selected, comment, str(exc)), 400)
    offers_url = f"{settings.frontend_url.rstrip('/')}/billing"
    return _page(
        "Merci pour votre réponse",
        "<p>Votre réponse a bien été enregistrée.</p>"
        "<p>Vos documents et conversations restent conservés jusqu'à la date indiquée "
        "dans nos emails. Vous pouvez souscrire à tout moment pour les retrouver.</p>"
        f'<p style="text-align:center;"><a class="button" href="{escape(offers_url)}">'
        "Voir les offres</a></p>",
    )
