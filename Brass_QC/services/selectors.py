"""
Brass QC Selectors — DB read-only layer.

All queryset building and data-fetching logic lives here.
Views call these functions — no queryset logic directly in views.

Rule: NO writes here. Only reads.
"""

import logging
import math

from django.db.models import OuterRef, Subquery, Exists, F, Q
from django.templatetags.static import static

from modelmasterapp.models import TotalStockModel, ModelMasterCreation
from InputScreening.models import IP_Rejection_ReasonStore, IS_PartialAcceptLot, IPTrayId
from ..models import (
    Brass_QC_Draft_Store,
    Brass_QC_Rejection_ReasonStore,
    Brass_QC_Submission,
    Brass_QC_Rejection_Table,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pick Table
# ─────────────────────────────────────────────────────────────────────────────

def get_picktable_base_queryset():
    """
    Returns annotated + filtered queryset for Brass QC pick table.
    Applies all standard filters, excludes, and annotations.
    """
    has_draft_subquery = Exists(
        Brass_QC_Draft_Store.objects.filter(lot_id=OuterRef('lot_id'))
    )

    draft_type_subquery = Brass_QC_Draft_Store.objects.filter(
        lot_id=OuterRef('lot_id')
    ).values('draft_type')[:1]

    brass_rejection_qty_subquery = Brass_QC_Rejection_ReasonStore.objects.filter(
        lot_id=OuterRef('lot_id')
    ).values('total_rejection_quantity')[:1]

    queryset = TotalStockModel.objects.select_related(
        'batch_id',
        'batch_id__model_stock_no',
        'batch_id__version',
        'batch_id__location',
    ).filter(
        batch_id__total_batch_quantity__gt=0
    ).annotate(
        wiping_required=F('batch_id__model_stock_no__wiping_required'),
        has_draft=has_draft_subquery,
        draft_type=draft_type_subquery,
        brass_rejection_total_qty=brass_rejection_qty_subquery,
    ).filter(
        (
            (
                (
                    Q(brass_qc_accptance__isnull=True) | Q(brass_qc_accptance=False)
                ) &
                (
                    Q(brass_qc_rejection__isnull=True) | Q(brass_qc_rejection=False)
                ) &
                ~Q(brass_qc_few_cases_accptance=True, brass_onhold_picking=False)
                &
                (
                    Q(accepted_Ip_stock=True) |
                    Q(few_cases_accepted_Ip_stock=True, ip_onhold_picking=False)
                )
            )
            |
            Q(send_brass_qc=True)
            |
            Q(brass_qc_rejection=True, brass_onhold_picking=True)
            |
            Q(send_brass_audit_to_qc=True)
            |
            Q(next_process_module='Brass QC')
        )
    ).exclude(
        Q(iqf_rejection=True)
    ).exclude(
        Q(brass_audit_rejection=True) & ~Q(send_brass_audit_to_qc=True)
    ).exclude(
        Q(send_brass_audit_to_qc=True, brass_physical_qty=0, total_IP_accpeted_quantity=0)
    ).exclude(
        Q(next_process_module='Input Screening') |
        (Q(last_process_module='Input Screening') & ~Q(next_process_module='Brass QC'))
    ).exclude(
        Q(total_IP_accpeted_quantity__lte=0) & Q(brass_physical_qty__lte=0) &
        ~Q(accepted_tray_scan_status=True)
    ).exclude(
        remove_lot=True  # exclude consumed/split parent lots
    ).distinct()

    return queryset


# ─────────────────────────────────────────────────────────────────────────────
# Completed Table
# ─────────────────────────────────────────────────────────────────────────────

def get_completed_base_queryset(from_datetime, to_datetime):
    """
    Returns annotated + filtered queryset for Brass QC completed table.
    Excludes child lots created by PARTIAL splits.
    """
    brass_rejection_qty_subquery = Brass_QC_Rejection_ReasonStore.objects.filter(
        lot_id=OuterRef('lot_id')
    ).values('total_rejection_quantity')[:1]

    child_split_subquery = Brass_QC_Submission.objects.filter(
        Q(transition_accept_lot_id=OuterRef('lot_id')) |
        Q(transition_reject_lot_id=OuterRef('lot_id')) |
        Q(transition_lot_id=OuterRef('lot_id'))   # FULL_REJECT transition child
    )
    child_exists = Exists(child_split_subquery)

    queryset = TotalStockModel.objects.select_related(
        'batch_id',
        'batch_id__model_stock_no',
        'batch_id__version',
        'batch_id__location',
    ).filter(
        batch_id__total_batch_quantity__gt=0,
        bq_last_process_date_time__range=(from_datetime, to_datetime),
    ).annotate(
        brass_rejection_qty=brass_rejection_qty_subquery,
        child_split=child_exists,
    ).filter(
        Q(brass_qc_accptance=True) |
        Q(brass_qc_rejection=True) |
        Q(brass_qc_few_cases_accptance=True, brass_onhold_picking=False)
    ).filter(child_split=False)

    return queryset


# ─────────────────────────────────────────────────────────────────────────────
# Single lot lookup
# ─────────────────────────────────────────────────────────────────────────────

def get_lot(lot_id):
    """
    Returns TotalStockModel for the given lot_id.
    Uses select_related for batch_id to avoid N+1.
    Returns None if not found.
    """
    return TotalStockModel.objects.select_related('batch_id').filter(lot_id=lot_id).first()


def get_lot_strict(lot_id):
    """
    Returns TotalStockModel for the given lot_id.
    Raises TotalStockModel.DoesNotExist if not found.
    """
    return TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)


# ─────────────────────────────────────────────────────────────────────────────
# Draft
# ─────────────────────────────────────────────────────────────────────────────

def get_draft(lot_id):
    """Returns Brass_QC_Draft_Store for the given lot_id (rejection_draft type)."""
    return Brass_QC_Draft_Store.objects.filter(
        lot_id=lot_id, draft_type='rejection_draft'
    ).first()


# ─────────────────────────────────────────────────────────────────────────────
# IS (Input Screening) helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_is_rejection_qty(lot_id):
    """
    Returns total IS rejection quantity for a lot.
    Returns 0 if no rejection store found.
    """
    store = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
    return store.total_rejection_quantity if store and store.total_rejection_quantity else 0


def get_is_partial_accept_lot(lot_id):
    """
    Returns the latest IS_PartialAcceptLot child record for a lot.
    Returns None if not found.
    """
    return (
        IS_PartialAcceptLot.objects
        .filter(parent_lot_id=lot_id)
        .order_by('-created_at')
        .first()
    )


# ─────────────────────────────────────────────────────────────────────────────
# IQF helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_iqf_submission(lot_id):
    """
    Returns the latest completed IQF submission for a lot.
    Returns None if not found.
    """
    from IQF.models import IQF_Submitted
    return IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()


def get_iqf_tray_count(iqf_record):
    """
    Returns the count of trays in an IQF submission record.
    Used for 'no_of_trays' display in pick table.
    """
    if not iqf_record:
        return 0
    if iqf_record.submission_type == 'FULL_ACCEPT' and iqf_record.full_accept_data:
        return len([
            t for t in iqf_record.full_accept_data.get('trays', [])
            if int(t.get('qty', 0)) > 0
        ])
    elif iqf_record.submission_type == 'PARTIAL' and iqf_record.partial_accept_data:
        return len([
            t for t in iqf_record.partial_accept_data.get('trays', [])
            if int(t.get('qty', 0)) > 0
        ])
    return 0


def get_iqf_active_tray_count(lot_id):
    """
    Returns count of active IQF trays for a lot (verified, non-rejected, non-delinked).
    """
    from IQF.models import IQFTrayId, IQF_Accepted_TrayID_Store
    actual = IQFTrayId.objects.filter(
        lot_id=lot_id,
        IP_tray_verified=True,
        rejected_tray=False,
        delink_tray=False,
    ).count()
    if actual > 0:
        return actual
    return IQF_Accepted_TrayID_Store.objects.filter(lot_id=lot_id, is_save=True).count()


# ─────────────────────────────────────────────────────────────────────────────
# Rejection reasons
# ─────────────────────────────────────────────────────────────────────────────

def get_rejection_reasons_qs():
    """Returns all Brass QC rejection reasons ordered by rejection_reason_id."""
    return Brass_QC_Rejection_Table.objects.all().order_by('rejection_reason_id')


# ─────────────────────────────────────────────────────────────────────────────
# Submission lookup
# ─────────────────────────────────────────────────────────────────────────────

def get_completed_submission(lot_id):
    """
    Returns the latest completed Brass_QC_Submission for a lot.
    Returns None if not found.
    """
    return (
        Brass_QC_Submission.objects
        .filter(lot_id=lot_id, is_completed=True)
        .order_by('-created_at')
        .first()
    )


def get_submission_by_child_lot(lot_id):
    """
    Returns Brass_QC_Submission where this lot_id is a child (transition lot).
    Returns None if not found.
    """
    return (
        Brass_QC_Submission.objects.filter(
            Q(transition_accept_lot_id=lot_id) | Q(transition_reject_lot_id=lot_id),
            is_completed=True,
        )
        .order_by('-created_at')
        .first()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Model images helper
# ─────────────────────────────────────────────────────────────────────────────

def get_model_images(batch_id_str):
    """
    Returns list of image URLs for a batch.
    Falls back to placeholder image if no images found.
    """
    batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id_str).first()
    images = []
    if batch_obj and batch_obj.model_stock_no:
        for img in batch_obj.model_stock_no.images.all():
            if img.master_image:
                images.append(img.master_image.url)
    if not images:
        images = [static('assets/images/imagePlaceholder.jpg')]
    return images
