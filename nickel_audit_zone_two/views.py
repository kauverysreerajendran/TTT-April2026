from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.db.models import OuterRef, Subquery, Exists, F
from django.core.paginator import Paginator
from django.templatetags.static import static
import math
from modelmasterapp.models import *
from DayPlanning.models import *
from InputScreening.models import *
from Brass_QC.models import *
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
import traceback
from rest_framework import status
from django.http import JsonResponse
import json
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.http import require_GET
from math import ceil
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from IQF.models import *
from BrassAudit.models import *
from Nickel_Audit.models import *
from Nickel_Inspection.models import *
from Jig_Unloading.models import *
from Jig_Unloading.tray_utils import get_upstream_tray_distribution, get_model_master_tray_info
from Inprocess_Inspection.models import InprocessInspectionTrayCapacity
from django.contrib.auth.decorators import login_required


def _get_input_source(jig_unload_obj):
    """Return location names with fallback chain: M2M → TotalStockModel → TrayId → ModelMasterCreation."""
    names = [loc.location_name for loc in jig_unload_obj.location.all()]
    if not names:
        for raw_cid in (jig_unload_obj.combine_lot_ids or []):
            # combine_lot_ids entries are formatted "-LIDxxx" or "JLOT-xxx-LIDxxx" — extract plain lot_id
            cid = raw_cid.rsplit('-', 1)[-1] if raw_cid and '-' in raw_cid else raw_cid
            if not cid:
                continue
            # Try TotalStockModel first
            tsm = TotalStockModel.objects.filter(lot_id=cid).prefetch_related('location').select_related('batch_id__location').first()
            if tsm and tsm.location.exists():
                names = [loc.location_name for loc in tsm.location.all()]
                break
            if tsm and tsm.batch_id and tsm.batch_id.location:
                names = [tsm.batch_id.location.location_name]
                break
            # Fallback: LID... lot_ids belong to TrayId — trace TrayId.batch_id.location
            tray = TrayId.objects.filter(lot_id=cid).select_related('batch_id__location').first()
            if tray and tray.batch_id and tray.batch_id.location:
                names = [tray.batch_id.location.location_name]
                break
    return ', '.join(names)
  


@method_decorator(login_required, name='dispatch')
class NA_Zone_PickTableView(APIView):
    """Nickel Audit Zone 2 Pick Table — mirrors NA_PickTableView (Zone 1) with zone_2 filter."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Nickel_Audit - Zone_two/NickelAudit_PickTable_zone_two.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False

        nq_rejection_reasons = Nickel_Audit_Rejection_Table.objects.all()

        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_2=True
        ).values_list('id', flat=True)

        queryset = JigUnloadAfterTable.objects.select_related(
            'version', 'plating_color', 'polish_finish'
        ).prefetch_related('location').filter(
            total_case_qty__gt=0,
            plating_color_id__in=allowed_color_ids
        )

        has_draft_subquery = Exists(
            Nickel_Audit_Draft_Store.objects.filter(lot_id=OuterRef('lot_id'))
        )
        draft_type_subquery = Nickel_Audit_Draft_Store.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('draft_type')[:1]

        brass_rejection_qty_subquery = Nickel_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = queryset.annotate(
            has_draft=has_draft_subquery,
            draft_type=draft_type_subquery,
            brass_rejection_total_qty=brass_rejection_qty_subquery,
        )

        queryset = queryset.filter(
            (
                (
                    Q(na_qc_accptance__isnull=True) | Q(na_qc_accptance=False)
                ) &
                (
                    Q(na_qc_rejection__isnull=True) | Q(na_qc_rejection=False)
                ) &
                ~Q(na_qc_few_cases_accptance=True, na_onhold_picking=False)
                &
                (
                    Q(nq_qc_accptance=True) |
                    Q(nq_qc_few_cases_accptance=True, nq_onhold_picking=False)
                )
            )
            |
            Q(na_qc_rejection=True, na_onhold_picking=True)
        ).distinct().order_by('-nq_last_process_date_time', '-lot_id')

        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for jig_unload_obj in page_obj.object_list:
            data = {
                'batch_id': jig_unload_obj.unload_lot_id,
                'lot_id': jig_unload_obj.lot_id,
                'date_time': jig_unload_obj.created_at,
                'model_stock_no__model_no': 'Combined Model',
                'plating_color': jig_unload_obj.plating_color.plating_color if jig_unload_obj.plating_color else '',
                'polish_finish': jig_unload_obj.polish_finish.polish_finish if jig_unload_obj.polish_finish else '',
                'version__version_name': jig_unload_obj.version.version_name if jig_unload_obj.version else '',
                'vendor_internal': '',
                'location__location_name': _get_input_source(jig_unload_obj),
                'tray_type': get_model_master_tray_info(jig_unload_obj.plating_stk_no, jig_unload_obj.tray_type or '')[0],
                'tray_capacity': get_model_master_tray_info(jig_unload_obj.plating_stk_no, jig_unload_obj.tray_type or '', jig_unload_obj.tray_capacity or 0)[1],
                'stock_lot_id': jig_unload_obj.lot_id,
                'total_IP_accpeted_quantity': jig_unload_obj.total_case_qty,
                'na_ac_accepted_qty_verified': jig_unload_obj.na_ac_accepted_qty_verified,
                'nq_qc_accepted_qty': jig_unload_obj.nq_qc_accepted_qty,
                'na_missing_qty': jig_unload_obj.na_missing_qty,
                'na_physical_qty': jig_unload_obj.na_physical_qty,
                'accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,
                'na_pick_remarks': jig_unload_obj.na_pick_remarks,
                'nq_qc_accptance': jig_unload_obj.nq_qc_accptance,
                'na_accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,
                'na_qc_rejection': jig_unload_obj.na_qc_rejection,
                'na_qc_few_cases_accptance': jig_unload_obj.na_qc_few_cases_accptance,
                'na_onhold_picking': jig_unload_obj.na_onhold_picking,
                'send_to_nickel_brass': jig_unload_obj.send_to_nickel_brass,
                'nq_last_process_date_time': jig_unload_obj.nq_last_process_date_time,
                'iqf_last_process_date_time': None,
                'na_hold_lot': jig_unload_obj.na_hold_lot,
                'na_holding_reason': jig_unload_obj.na_holding_reason,
                'na_release_lot': jig_unload_obj.na_release_lot,
                'na_release_reason': jig_unload_obj.na_release_reason,
                'has_draft': jig_unload_obj.has_draft,
                'draft_type': jig_unload_obj.draft_type,
                'brass_rejection_total_qty': jig_unload_obj.brass_rejection_total_qty,
                'plating_stk_no': jig_unload_obj.plating_stk_no or '',
                'polishing_stk_no': jig_unload_obj.polish_stk_no or '',
                'category': jig_unload_obj.category or '',
                'last_process_module': jig_unload_obj.last_process_module or 'Jig Unload',
                'combine_lot_ids': jig_unload_obj.combine_lot_ids,
                'unload_lot_id': jig_unload_obj.unload_lot_id,
                'na_qc_acceptance': jig_unload_obj.na_qc_accptance,
                'audit_check': jig_unload_obj.audit_check,
            }

            images = []
            if jig_unload_obj.plating_stk_no:
                plating_stk_no = str(jig_unload_obj.plating_stk_no)
                if len(plating_stk_no) >= 4:
                    model_no_prefix = plating_stk_no[:4]
                    try:
                        model_master = ModelMaster.objects.filter(
                            model_no__startswith=model_no_prefix
                        ).prefetch_related('images').first()
                        if model_master:
                            for img in model_master.images.all():
                                if img.master_image:
                                    images.append(img.master_image.url)
                    except Exception:
                        pass
            if not images and data['combine_lot_ids']:
                first_lot_id = data['combine_lot_ids'][0] if data['combine_lot_ids'] else None
                if first_lot_id:
                    total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
                    if total_stock and total_stock.batch_id and total_stock.batch_id.model_stock_no:
                        for img in total_stock.batch_id.model_stock_no.images.all():
                            if img.master_image:
                                images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images
            master_data.append(data)

        for data in master_data:
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            lot_id = data.get('stock_lot_id')

            total_rejection_qty = 0
            rejection_store = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            if rejection_store and rejection_store.total_rejection_quantity:
                total_rejection_qty = rejection_store.total_rejection_quantity

            jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if jig_unload_obj and total_rejection_qty > 0:
                data['display_accepted_qty'] = max(jig_unload_obj.nq_qc_accepted_qty - total_rejection_qty, 0)
            else:
                data['display_accepted_qty'] = jig_unload_obj.nq_qc_accepted_qty if jig_unload_obj else 0

            na_physical_qty = data.get('na_physical_qty') or 0
            brass_rejection_total_qty = data.get('brass_rejection_total_qty') or 0
            data['is_delink_only'] = (na_physical_qty > 0 and
                                      brass_rejection_total_qty >= na_physical_qty and
                                      data.get('na_onhold_picking', False))

            display_qty = data.get('display_accepted_qty', 0)
            data['no_of_trays'] = math.ceil(display_qty / tray_capacity) if tray_capacity > 0 and display_qty > 0 else 0

            data['available_qty'] = na_physical_qty if na_physical_qty > 0 else data.get('total_IP_accpeted_quantity', 0)

            display_accepted_qty = data.get('display_accepted_qty', 0)
            aql_plan = AQLSamplingPlan.objects.filter(
                lot_qty_from__lte=display_accepted_qty,
                lot_qty_to__gte=display_accepted_qty
            ).first()
            if aql_plan:
                data['aql_limit'] = float(aql_plan.aql_limit)
                data['sample_qty'] = aql_plan.sample_qty
            else:
                data['aql_limit'] = None
                data['sample_qty'] = None

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
            'nq_rejection_reasons': nq_rejection_reasons,
            'pick_table_count': len(master_data),
        }
        return Response(context, template_name=self.template_name)


@method_decorator(login_required, name='dispatch')
class NA_Zone_CompletedView(APIView):
    """Nickel Audit Zone 2 Completed Table — mirrors NACompletedView (Zone 1) with zone_2 filter."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Nickel_Audit - Zone_two/NickelAudit_Completed_zone_two.html'

    def get(self, request):
        from django.utils import timezone
        from datetime import datetime, timedelta
        import pytz

        user = request.user
        tz = pytz.timezone("Asia/Kolkata")
        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        from_date_str = request.GET.get("from_date")
        to_date_str = request.GET.get("to_date")
        if from_date_str and to_date_str:
            try:
                from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
                to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
            except ValueError:
                from_date = yesterday
                to_date = today
        else:
            from_date = yesterday
            to_date = today

        from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
        to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))

        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_2=True
        ).values_list("id", flat=True)

        na_rejection_qty_subquery = Nickel_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef("lot_id")
        ).values("total_rejection_quantity")[:1]

        queryset = (
            JigUnloadAfterTable.objects.select_related("version", "plating_color", "polish_finish")
            .prefetch_related("location")
            .filter(
                total_case_qty__gt=0,
                plating_color_id__in=allowed_color_ids,
            )
            .annotate(
                na_rejection_qty=na_rejection_qty_subquery,
            )
            .filter(
                Q(na_qc_accptance=True)
                | Q(na_qc_rejection=True)
                | Q(na_qc_few_cases_accptance=True, na_onhold_picking=False)
            )
            .filter(na_last_process_date_time__range=(from_datetime, to_datetime))
            .order_by("-na_last_process_date_time", "-lot_id")
        )

        page_number = request.GET.get("page", 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for jig_unload_obj in page_obj.object_list:
            data = {
                "batch_id": jig_unload_obj.unload_lot_id,
                "lot_id": jig_unload_obj.lot_id,
                "date_time": jig_unload_obj.created_at,
                "model_stock_no__model_no": "Combined Model",
                "plating_color": jig_unload_obj.plating_color.plating_color if jig_unload_obj.plating_color else "",
                "polish_finish": jig_unload_obj.polish_finish.polish_finish if jig_unload_obj.polish_finish else "",
                "version__version_name": jig_unload_obj.version.version_name if jig_unload_obj.version else "",
                "vendor_internal": "",
                "location__location_name": _get_input_source(jig_unload_obj),
                "tray_type": get_model_master_tray_info(jig_unload_obj.plating_stk_no, jig_unload_obj.tray_type or "")[0],
                "tray_capacity": jig_unload_obj.tray_capacity or 0,
                "stock_lot_id": jig_unload_obj.lot_id,
                "last_process_module": jig_unload_obj.last_process_module or "Jig Unload",
                "total_IP_accpeted_quantity": jig_unload_obj.total_case_qty,
                "na_qc_accptance": jig_unload_obj.na_qc_accptance,
                "na_qc_rejection": jig_unload_obj.na_qc_rejection,
                "na_qc_few_cases_accptance": jig_unload_obj.na_qc_few_cases_accptance,
                "na_onhold_picking": jig_unload_obj.na_onhold_picking,
                "na_hold_lot": jig_unload_obj.na_hold_lot,
                "na_holding_reason": jig_unload_obj.na_holding_reason,
                "na_release_lot": jig_unload_obj.na_release_lot,
                "na_release_reason": jig_unload_obj.na_release_reason,
                "na_physical_qty": jig_unload_obj.na_physical_qty,
                "na_missing_qty": jig_unload_obj.na_missing_qty or 0,
                "na_pick_remarks": jig_unload_obj.na_pick_remarks,
                "na_accepted_tray_scan_status": jig_unload_obj.na_accepted_tray_scan_status,
                "na_ac_accepted_qty_verified": jig_unload_obj.na_ac_accepted_qty_verified,
                "na_qc_accepted_qty": jig_unload_obj.na_qc_accepted_qty or 0,
                "na_last_process_date_time": jig_unload_obj.na_last_process_date_time,
                "plating_stk_no": jig_unload_obj.plating_stk_no or "",
                "polishing_stk_no": jig_unload_obj.polish_stk_no or "",
                "category": jig_unload_obj.category or "",
                "combine_lot_ids": jig_unload_obj.combine_lot_ids,
                "unload_lot_id": jig_unload_obj.unload_lot_id,
                "audit_check": jig_unload_obj.audit_check,
                "display_accepted_qty": jig_unload_obj.na_physical_qty or 0,
            }

            images = []
            if jig_unload_obj.plating_stk_no:
                plating_stk_no = str(jig_unload_obj.plating_stk_no)
                if len(plating_stk_no) >= 4:
                    model_no_prefix = plating_stk_no[:4]
                    model_master = (
                        ModelMaster.objects.filter(model_no__startswith=model_no_prefix)
                        .prefetch_related("images")
                        .first()
                    )
                    if model_master:
                        for img in model_master.images.all():
                            if img.master_image:
                                images.append(img.master_image.url)
            if not images and data["combine_lot_ids"]:
                first_lot_id = data["combine_lot_ids"][0] if data["combine_lot_ids"] else None
                if first_lot_id:
                    total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
                    if total_stock and total_stock.batch_id and total_stock.batch_id.model_stock_no:
                        for img in total_stock.batch_id.model_stock_no.images.all():
                            if img.master_image:
                                images.append(img.master_image.url)
            if not images:
                images = [static("assets/images/imagePlaceholder.jpg")]
            data["model_images"] = images
            master_data.append(data)

        context = {
            "master_data": master_data,
            "page_obj": page_obj,
            "paginator": paginator,
            "user": user,
            "from_date": from_date.strftime("%Y-%m-%d"),
            "to_date": to_date.strftime("%Y-%m-%d"),
            "date_filter_applied": bool(from_date_str and to_date_str),
        }
        return Response(context, template_name=self.template_name)
