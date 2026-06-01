import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.user import User
from app.schemas.emailing import (
    BrevoContact,
    BrevoList,
    CampaignStats,
    CampaignWaveRead,
    CampaignWavesOverview,
    EmailCampaignCreate,
    EmailCampaignRead,
    EmailSequenceCreate,
    EmailSequenceRead,
    EmailSequenceUpdate,
    EmailTemplateCreate,
    EmailTemplateRead,
    EmailTemplateUpdate,
    SequenceStepRead,
    StepBranchRead,
    WaveContact,
    WaveScheduleRequest,
)
from app.services.emailing_service import (
    EmailCampaignService,
    EmailSequenceService,
    EmailTemplateService,
    fetch_brevo_list_contacts,
    fetch_brevo_lists,
)

router = APIRouter()


# ──────────────────────────────────────────────
#  Templates
# ──────────────────────────────────────────────


@router.get("/templates", response_model=list[EmailTemplateRead])
async def list_templates(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[EmailTemplateRead]:
    service = EmailTemplateService(db)
    templates = await service.list_all()
    return [EmailTemplateRead.model_validate(t) for t in templates]


@router.post("/templates", response_model=EmailTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: EmailTemplateCreate,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailTemplateRead:
    service = EmailTemplateService(db)
    tpl = await service.create(name=data.name, subject=data.subject, preview_text=data.preview_text, html_body=data.html_body)
    return EmailTemplateRead.model_validate(tpl)


@router.get("/templates/{template_id}", response_model=EmailTemplateRead)
async def get_template(
    template_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailTemplateRead:
    service = EmailTemplateService(db)
    tpl = await service.get(template_id)
    return EmailTemplateRead.model_validate(tpl)


@router.put("/templates/{template_id}", response_model=EmailTemplateRead)
async def update_template(
    template_id: uuid.UUID,
    data: EmailTemplateUpdate,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailTemplateRead:
    service = EmailTemplateService(db)
    tpl = await service.update(
        template_id, name=data.name, subject=data.subject, preview_text=data.preview_text, html_body=data.html_body,
    )
    return EmailTemplateRead.model_validate(tpl)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = EmailTemplateService(db)
    await service.delete(template_id)


@router.post("/templates/{template_id}/test", status_code=status.HTTP_200_OK)
async def send_test_email(
    template_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = EmailTemplateService(db)
    to_emails = ["vanessa@aoriarh.fr", "hello@waibly.com"]
    results = await service.send_test(template_id, to_emails)
    return {"results": results}


# ──────────────────────────────────────────────
#  Sequences
# ──────────────────────────────────────────────


def _seq_to_read(seq) -> EmailSequenceRead:
    steps = []
    for s in sorted(seq.steps, key=lambda x: x.position):
        branches = []
        for b in (s.branches or []):
            branches.append(StepBranchRead(
                id=b.id,
                condition=b.condition,
                template_id=b.template_id,
                template_name=b.template.name if b.template else None,
                template_subject=b.template.subject if b.template else None,
            ))
        steps.append(SequenceStepRead(
            id=s.id,
            template_id=s.template_id,
            position=s.position,
            delay_days=s.delay_days,
            template_name=s.template.name if s.template else None,
            template_subject=s.template.subject if s.template else None,
            branches=branches,
        ))
    return EmailSequenceRead(
        id=seq.id,
        name=seq.name,
        status=seq.status,
        steps=steps,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
    )


@router.get("/sequences", response_model=list[EmailSequenceRead])
async def list_sequences(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[EmailSequenceRead]:
    service = EmailSequenceService(db)
    sequences = await service.list_all()
    return [_seq_to_read(s) for s in sequences]


@router.post("/sequences", response_model=EmailSequenceRead, status_code=status.HTTP_201_CREATED)
async def create_sequence(
    data: EmailSequenceCreate,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailSequenceRead:
    service = EmailSequenceService(db)
    steps = [s.model_dump() for s in data.steps]
    seq = await service.create(name=data.name, steps=steps)
    return _seq_to_read(seq)


@router.get("/sequences/{sequence_id}", response_model=EmailSequenceRead)
async def get_sequence(
    sequence_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailSequenceRead:
    service = EmailSequenceService(db)
    seq = await service.get(sequence_id)
    return _seq_to_read(seq)


@router.put("/sequences/{sequence_id}", response_model=EmailSequenceRead)
async def update_sequence(
    sequence_id: uuid.UUID,
    data: EmailSequenceUpdate,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailSequenceRead:
    service = EmailSequenceService(db)
    steps = [s.model_dump() for s in data.steps] if data.steps is not None else None
    seq = await service.update(sequence_id, name=data.name, steps=steps)
    return _seq_to_read(seq)


@router.delete("/sequences/{sequence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sequence(
    sequence_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = EmailSequenceService(db)
    await service.delete(sequence_id)


# ──────────────────────────────────────────────
#  Campaigns
# ──────────────────────────────────────────────


@router.get("/campaigns", response_model=list[EmailCampaignRead])
async def list_campaigns(
    status_filter: str | None = Query(None, alias="status"),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[EmailCampaignRead]:
    service = EmailCampaignService(db)
    items = await service.list_all(status_filter)
    return [EmailCampaignRead(**item) for item in items]


@router.post("/campaigns", response_model=EmailCampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    data: EmailCampaignCreate,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailCampaignRead:
    service = EmailCampaignService(db)
    campaign = await service.create(
        name=data.name,
        sequence_id=data.sequence_id,
        brevo_list_ids=data.brevo_list_ids,
        scheduled_at=data.scheduled_at,
    )
    return EmailCampaignRead(
        id=campaign.id,
        name=campaign.name,
        sequence_id=campaign.sequence_id,
        brevo_list_ids=campaign.brevo_list_ids,
        status=campaign.status,
        scheduled_at=campaign.scheduled_at,
        current_step=campaign.current_step,
        recipient_count=0,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


@router.post("/campaigns/{campaign_id}/launch", response_model=EmailCampaignRead)
async def launch_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailCampaignRead:
    service = EmailCampaignService(db)
    campaign = await service.launch(campaign_id)
    return EmailCampaignRead(
        id=campaign.id,
        name=campaign.name,
        sequence_id=campaign.sequence_id,
        brevo_list_ids=campaign.brevo_list_ids,
        status=campaign.status,
        scheduled_at=campaign.scheduled_at,
        current_step=campaign.current_step,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


@router.post("/campaigns/{campaign_id}/pause", response_model=EmailCampaignRead)
async def pause_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailCampaignRead:
    service = EmailCampaignService(db)
    campaign = await service.pause(campaign_id)
    return EmailCampaignRead(
        id=campaign.id,
        name=campaign.name,
        sequence_id=campaign.sequence_id,
        brevo_list_ids=campaign.brevo_list_ids,
        status=campaign.status,
        scheduled_at=campaign.scheduled_at,
        current_step=campaign.current_step,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


@router.post("/campaigns/{campaign_id}/resume", response_model=EmailCampaignRead)
async def resume_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> EmailCampaignRead:
    service = EmailCampaignService(db)
    campaign = await service.resume(campaign_id)
    return EmailCampaignRead(
        id=campaign.id,
        name=campaign.name,
        sequence_id=campaign.sequence_id,
        brevo_list_ids=campaign.brevo_list_ids,
        status=campaign.status,
        scheduled_at=campaign.scheduled_at,
        current_step=campaign.current_step,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = EmailCampaignService(db)
    await service.delete(campaign_id)


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
async def get_campaign_stats(
    campaign_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> CampaignStats:
    service = EmailCampaignService(db)
    stats = await service.get_stats(campaign_id)
    return CampaignStats(**stats)


# ──────────────────────────────────────────────
#  Vagues d'envoi
# ──────────────────────────────────────────────


@router.get("/campaigns/{campaign_id}/waves", response_model=CampaignWavesOverview)
async def list_campaign_waves(
    campaign_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> CampaignWavesOverview:
    service = EmailCampaignService(db)
    overview = await service.get_waves(campaign_id)
    return CampaignWavesOverview(**overview)


@router.get(
    "/campaigns/{campaign_id}/waves/preview", response_model=list[WaveContact]
)
async def preview_next_wave_contacts(
    campaign_id: uuid.UUID,
    count: int = Query(100),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[WaveContact]:
    service = EmailCampaignService(db)
    contacts = await service.preview_next_contacts(campaign_id, count)
    return [WaveContact(**c) for c in contacts]


@router.get(
    "/campaigns/{campaign_id}/waves/{wave_id}/contacts",
    response_model=list[WaveContact],
)
async def list_wave_contacts(
    campaign_id: uuid.UUID,
    wave_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[WaveContact]:
    service = EmailCampaignService(db)
    contacts = await service.list_wave_contacts(campaign_id, wave_id)
    return [WaveContact(**c) for c in contacts]


@router.post(
    "/campaigns/{campaign_id}/waves",
    response_model=CampaignWaveRead,
    status_code=status.HTTP_201_CREATED,
)
async def schedule_campaign_wave(
    campaign_id: uuid.UUID,
    data: WaveScheduleRequest,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> CampaignWaveRead:
    service = EmailCampaignService(db)
    wave = await service.schedule_wave(campaign_id, data.count, data.scheduled_at)
    return CampaignWaveRead(
        id=wave.id,
        number=wave.number,
        scheduled_at=wave.scheduled_at,
        recipient_count=wave.recipient_count,
        sent_count=0,
        done_count=0,
        status="scheduled",
    )


@router.delete(
    "/campaigns/{campaign_id}/waves/{wave_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_campaign_wave(
    campaign_id: uuid.UUID,
    wave_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = EmailCampaignService(db)
    await service.cancel_wave(campaign_id, wave_id)


# ──────────────────────────────────────────────
#  Brevo lists (read-only)
# ──────────────────────────────────────────────


@router.get("/lists", response_model=list[BrevoList])
async def list_brevo_lists(
    user: User = Depends(require_role(["admin"])),
) -> list[BrevoList]:
    lists = await fetch_brevo_lists()
    return [BrevoList(**lst) for lst in lists]


@router.get("/lists/{list_id}/contacts", response_model=list[BrevoContact])
async def list_brevo_contacts(
    list_id: int,
    user: User = Depends(require_role(["admin"])),
) -> list[BrevoContact]:
    contacts = await fetch_brevo_list_contacts(list_id)
    return [BrevoContact(**c) for c in contacts]
