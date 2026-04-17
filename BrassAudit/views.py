from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.db.models import OuterRef, Subquery, Exists, F, Sum, Count
from django.core.paginator import Paginator
from django.templatetags.static import static
import math
from modelmasterapp.models import *
from DayPlanning.models import *
from InputScreening.models import *
from .models import *
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
from Brass_QC.models import *
from django.utils import timezone
from datetime import timedelta
import datetime
import pytz
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Brass Audit Pick Table View
# ═══════════════════════════════════════════════════════════════
@method_decorator(login_required, name='dispatch')
class BrassAuditPickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'BrassAudit/BrassAudit_PickTable.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False

        sort = request.GET.get('sort')
        order = request.GET.get('order', 'asc')

        sort_field_mapping = {
            'serial_number': 'lot_id',
            'brass_audit_last_process_date_time': 'brass_audit_last_process_date_time',
            'plating_stk_no': 'batch_id__plating_stk_no',
            'polishing_stk_no': 'batch_id__polishing_stk_no',
            'plating_color': 'batch_id__plating_color',
            'category': 'batch_id__category',
            'polish_finish': 'batch_id__polish_finish',
            'tray_capacity': 'batch_id__tray_capacity',
            'vendor_location': 'batch_id__vendor_internal',
            'no_of_trays': 'batch_id__tray_capacity',
            'lot_qty': 'brass_qc_accepted_qty',
            'brass_audit_physical_qty': 'brass_audit_physical_qty',
            'brass_audit_accepted_qty': 'brass_audit_accepted_qty',
            'reject_qty': 'brass_rejection_total_qty',
        }

        brass_rejection_reasons = Brass_Audit_Rejection_Table.objects.all()

        queryset = TotalStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            batch_id__total_batch_quantity__gt=0
        )

        has_draft_subquery = Exists(
            Brass_Audit_Draft_Store.objects.filter(lot_id=OuterRef('lot_id'))
        )
        draft_type_subquery = Brass_Audit_Draft_Store.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('draft_type')[:1]
        brass_rejection_qty_subquery = Brass_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = queryset.annotate(
            wiping_required=F('batch_id__model_stock_no__wiping_required'),
            has_draft=has_draft_subquery,
            draft_type=draft_type_subquery,
            brass_rejection_total_qty=brass_rejection_qty_subquery,
        )

        # Filter: lots from Brass QC (accepted/partial) that are pending in Brass Audit
        queryset = queryset.filter(
            Q(brass_qc_accptance=True, brass_audit_accptance__isnull=True) |
            Q(brass_qc_accptance=True, brass_audit_accptance=False) |
            Q(brass_qc_few_cases_accptance=True, brass_onhold_picking=False) |
            Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=True)
        ).exclude(
            Q(iqf_acceptance=True) | Q(iqf_few_cases_acceptance=True)
        ).exclude(
            brass_audit_rejection=True
        ).exclude(
            Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False)
        )

        if sort and sort in sort_field_mapping:
            field = sort_field_mapping[sort]
            if order == 'desc':
                field = '-' + field
            queryset = queryset.order_by(field)
        else:
            queryset = queryset.order_by('-bq_last_process_date_time', '-lot_id')

        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            brass_qc_accepted_qty = stock_obj.brass_qc_accepted_qty or 0

            data = {
                'batch_id': batch.batch_id,
                'lot_id': stock_obj.lot_id,
                'date_time': batch.date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no,
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'wiping_required': stock_obj.wiping_required,
                'brass_onhold_picking': stock_obj.brass_onhold_picking,
                'stock_lot_id': stock_obj.lot_id,
                'brass_audit_accepted_qty': stock_obj.brass_audit_accepted_qty,
                'brass_audit_accepted_qty_verified': stock_obj.brass_audit_accepted_qty_verified,
                'brass_qc_accepted_qty': stock_obj.brass_qc_accepted_qty,
                'brass_audit_missing_qty': stock_obj.brass_audit_missing_qty,
                'brass_audit_physical_qty': stock_obj.brass_audit_physical_qty,
                'brass_audit_physical_qty_edited': stock_obj.brass_audit_physical_qty_edited,
                'accepted_Ip_stock': stock_obj.accepted_Ip_stock,
                'rejected_ip_stock': stock_obj.rejected_ip_stock,
                'few_cases_accepted_Ip_stock': stock_obj.few_cases_accepted_Ip_stock,
                'accepted_tray_scan_status': stock_obj.accepted_tray_scan_status,
                'BA_pick_remarks': stock_obj.BA_pick_remarks,
                'Bq_pick_remarks': stock_obj.Bq_pick_remarks,
                'brass_qc_accptance': stock_obj.brass_qc_accptance,
                'brass_accepted_tray_scan_status': stock_obj.brass_accepted_tray_scan_status,
                'brass_audit_accptance': getattr(stock_obj, 'brass_audit_accptance', False),
                'brass_audit_rejection': stock_obj.brass_audit_rejection,
                'brass_qc_few_cases_accptance': stock_obj.brass_qc_few_cases_accptance,
                'brass_audit_few_cases_accptance': stock_obj.brass_audit_few_cases_accptance,
                'brass_audit_onhold_picking': stock_obj.brass_audit_onhold_picking,
                'brass_audit_draft': stock_obj.brass_audit_draft,
                'iqf_acceptance': stock_obj.iqf_acceptance,
                'send_brass_qc': stock_obj.send_brass_qc,
                'send_brass_audit_to_qc': stock_obj.send_brass_audit_to_qc,
                'bq_last_process_date_time': stock_obj.bq_last_process_date_time,
                'brass_audit_last_process_date_time': stock_obj.brass_audit_last_process_date_time,
                'iqf_last_process_date_time': stock_obj.iqf_last_process_date_time,
                'iqf_accepted_qty': stock_obj.iqf_accepted_qty,
                'brass_audit_hold_lot': stock_obj.brass_audit_hold_lot,
                'brass_audit_holding_reason': stock_obj.brass_audit_holding_reason,
                'brass_audit_release_lot': stock_obj.brass_audit_release_lot,
                'brass_audit_release_reason': stock_obj.brass_audit_release_reason,
                'has_draft': stock_obj.has_draft,
                'draft_type': stock_obj.draft_type,
                'brass_rejection_total_qty': stock_obj.brass_rejection_total_qty,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                'last_process_module': stock_obj.last_process_module,
            }

            # AQL Sampling Plan
            aql_plan = AQLSamplingPlan.objects.filter(
                lot_qty_from__lte=brass_qc_accepted_qty,
                lot_qty_to__gte=brass_qc_accepted_qty
            ).first()
            data['aql_limit'] = float(aql_plan.aql_limit) if aql_plan else None
            data['sample_qty'] = aql_plan.sample_qty if aql_plan else None

            master_data.append(data)

        for data in master_data:
            brass_qc_accepted_qty = data.get('brass_qc_accepted_qty', 0)
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            lot_id = data.get('stock_lot_id')

            # LOT-INDEPENDENT tray resolution: only current lot's BrassAuditTrayId
            audit_trays = BrassAuditTrayId.objects.filter(
                lot_id=lot_id, delink_tray=False, rejected_tray=False
            )
            if audit_trays.exists():
                ba_lot_qty = audit_trays.aggregate(total=Sum('tray_quantity'))['total'] or 0
                ba_no_of_trays = audit_trays.count()
                data['display_accepted_qty'] = ba_lot_qty
                data['no_of_trays'] = ba_no_of_trays
            else:
                # Fallback: use brass_qc_accepted_qty (what QC sent)
                if brass_qc_accepted_qty > 0:
                    data['display_accepted_qty'] = brass_qc_accepted_qty
                elif data.get('brass_audit_accepted_qty', 0) > 0:
                    data['display_accepted_qty'] = data['brass_audit_accepted_qty']
                elif data.get('iqf_accepted_qty', 0) > 0:
                    data['display_accepted_qty'] = data['iqf_accepted_qty']
                else:
                    data['display_accepted_qty'] = 0

                display_qty = data.get('display_accepted_qty', 0)
                if tray_capacity > 0 and display_qty > 0:
                    data['no_of_trays'] = math.ceil(display_qty / tray_capacity)
                else:
                    data['no_of_trays'] = 0

            brass_audit_physical_qty = data.get('brass_audit_physical_qty') or 0
            brass_rejection_total_qty = data.get('brass_rejection_total_qty') or 0
            is_delink_only = (brass_audit_physical_qty > 0 and
                              brass_rejection_total_qty >= brass_audit_physical_qty and
                              data.get('brass_audit_onhold_picking', False))
            data['is_delink_only'] = is_delink_only

            # Model images
            batch_obj = ModelMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj:
                model_master = batch_obj.model_stock_no
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            data['available_qty'] = data.get('brass_audit_accepted_qty') if data.get('brass_audit_accepted_qty') and data.get('brass_audit_accepted_qty') > 0 else (data.get('brass_audit_physical_qty') if data.get('brass_audit_physical_qty') and data.get('brass_audit_physical_qty') > 0 else data.get('brass_qc_accepted_qty', 0))

            # Backend-computed flags
            data['can_delete'] = (
                not data.get('brass_audit_accptance') and
                not data.get('brass_audit_rejection') and
                not data.get('brass_accepted_tray_scan_status') and
                not data.get('brass_audit_few_cases_accptance') and
                data.get('brass_audit_accepted_qty_verified', False)
            )

            # Circle status
            if data.get('brass_audit_onhold_picking') or data.get('brass_audit_draft'):
                data['qc_circle'] = 'HALF'
            elif data.get('brass_audit_rejection') or data.get('brass_audit_accptance') or data.get('brass_audit_few_cases_accptance'):
                data['qc_circle'] = 'GREEN'
            else:
                data['qc_circle'] = 'GRAY'

            # Action state
            if data.get('brass_audit_onhold_picking') and data.get('is_delink_only'):
                data['action_state'] = 'ONHOLD_DELINK'
            elif data.get('brass_audit_onhold_picking') and not data.get('is_delink_only'):
                data['action_state'] = 'ONHOLD_TOPTRAY'
            elif data.get('brass_audit_rejection') or data.get('brass_audit_few_cases_accptance'):
                data['action_state'] = 'REJECTED'
            else:
                data['action_state'] = 'DEFAULT'

            # Lot status pill
            if data.get('brass_audit_onhold_picking') or data.get('brass_audit_draft'):
                data['lot_status'] = 'Draft'
            elif data.get('brass_audit_hold_lot'):
                data['lot_status'] = 'On Hold'
            elif data.get('brass_audit_rejection') or data.get('brass_audit_few_cases_accptance') or data.get('brass_audit_accptance'):
                data['lot_status'] = 'Yet to Release'
            elif data.get('brass_audit_accepted_qty_verified'):
                data['lot_status'] = 'Released'
            else:
                data['lot_status'] = 'Yet to Start'

            # Fallbacks
            if not data.get('brass_audit_physical_qty'):
                data['brass_audit_physical_qty'] = data.get('brass_physical_qty', 0)
            if not data.get('brass_audit_missing_qty'):
                data['brass_audit_missing_qty'] = data.get('brass_missing_qty', 0)

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
            'brass_rejection_reasons': brass_rejection_reasons,
            'pick_table_count': len(master_data),
        }
        return Response(context, template_name=self.template_name)


# ═══════════════════════════════════════════════════════════════
# Brass Audit Completed Table View
# ═══════════════════════════════════════════════════════════════
@method_decorator(login_required, name='dispatch')
class BrassAuditCompletedView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'BrassAudit/BrassAudit_Completed.html'

    def get(self, request):
        user = request.user

        sort = request.GET.get('sort')
        order = request.GET.get('order', 'asc')

        sort_field_mapping = {
            'serial_number': 'lot_id',
            'date_time': 'brass_audit_last_process_date_time',
            'plating_stk_no': 'batch_id__plating_stk_no',
            'polishing_stk_no': 'batch_id__polishing_stk_no',
            'plating_color': 'batch_id__plating_color',
            'category': 'batch_id__category',
            'polish_finish': 'batch_id__polish_finish',
            'tray_capacity': 'batch_id__tray_capacity',
            'vendor_location': 'batch_id__vendor_internal',
            'no_of_trays': 'batch_id__no_of_trays',
            'accepted_qty': 'brass_audit_accepted_qty',
            'rejected_qty': 'brass_audit_rejection_qty',
            'process_status': 'last_process_module',
            'lot_status': 'last_process_module',
            'current_stage': 'next_process_module',
            'remarks': 'BA_pick_remarks',
        }

        tz = pytz.timezone("Asia/Kolkata")
        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')

        if from_date_str and to_date_str:
            try:
                from_date = datetime.datetime.strptime(from_date_str, '%Y-%m-%d').date()
                to_date = datetime.datetime.strptime(to_date_str, '%Y-%m-%d').date()
            except ValueError:
                from_date = yesterday
                to_date = today
        else:
            from_date = yesterday
            to_date = today

        from_datetime = timezone.make_aware(datetime.datetime.combine(from_date, datetime.datetime.min.time()))
        to_datetime = timezone.make_aware(datetime.datetime.combine(to_date, datetime.datetime.max.time()))

        brass_audit_rejection_qty_subquery = Brass_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = TotalStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            batch_id__total_batch_quantity__gt=0,
            brass_audit_last_process_date_time__range=(from_datetime, to_datetime)
        ).annotate(
            brass_audit_rejection_qty=brass_audit_rejection_qty_subquery,
        ).filter(
            Q(brass_audit_accptance=True) |
            Q(brass_audit_rejection=True) |
            Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False)
        )

        if sort and sort in sort_field_mapping:
            field = sort_field_mapping[sort]
            if order == 'desc':
                field = '-' + field
            queryset = queryset.order_by(field)
        else:
            queryset = queryset.order_by('-brass_audit_last_process_date_time', '-lot_id')

        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id

            data = {
                'batch_id': batch.batch_id,
                'lot_id': stock_obj.lot_id,
                'date_time': batch.date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no if batch.model_stock_no else '',
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'stock_lot_id': stock_obj.lot_id,
                'last_process_module': stock_obj.last_process_module,
                'next_process_module': stock_obj.next_process_module,
                'brass_audit_accepted_qty_verified': stock_obj.brass_audit_accepted_qty_verified,
                'brass_audit_accepted_qty': stock_obj.brass_audit_accepted_qty,
                'brass_audit_rejection_qty': stock_obj.brass_audit_rejection_qty,
                'brass_audit_missing_qty': stock_obj.brass_audit_missing_qty,
                'brass_audit_physical_qty': stock_obj.brass_audit_physical_qty,
                'brass_qc_accepted_qty': stock_obj.brass_qc_accepted_qty,
                'accepted_Ip_stock': stock_obj.accepted_Ip_stock,
                'rejected_ip_stock': stock_obj.rejected_ip_stock,
                'few_cases_accepted_Ip_stock': stock_obj.few_cases_accepted_Ip_stock,
                'accepted_tray_scan_status': stock_obj.accepted_tray_scan_status,
                'BA_pick_remarks': stock_obj.BA_pick_remarks,
                'brass_audit_accptance': stock_obj.brass_audit_accptance,
                'brass_accepted_tray_scan_status': stock_obj.brass_accepted_tray_scan_status,
                'brass_audit_rejection': stock_obj.brass_audit_rejection,
                'brass_audit_few_cases_accptance': stock_obj.brass_audit_few_cases_accptance,
                'brass_audit_onhold_picking': stock_obj.brass_audit_onhold_picking,
                'brass_qc_accepted_qty': stock_obj.brass_qc_accepted_qty,
                'brass_audit_last_process_date_time': stock_obj.brass_audit_last_process_date_time,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                'no_of_trays': 0,
            }
            master_data.append(data)

        for data in master_data:
            brass_qc_accepted_qty = data.get('brass_qc_accepted_qty', 0)
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            lot_id = data.get('stock_lot_id')

            if brass_qc_accepted_qty and brass_qc_accepted_qty > 0:
                data['display_accepted_qty'] = brass_qc_accepted_qty
            else:
                data['display_accepted_qty'] = 0

            display_qty = data.get('display_accepted_qty', 0)
            if tray_capacity > 0 and display_qty > 0:
                data['no_of_trays'] = math.ceil(display_qty / tray_capacity)
            else:
                data['no_of_trays'] = 0

            batch_obj = ModelMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj and batch_obj.model_stock_no:
                for img in batch_obj.model_stock_no.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            if data.get('brass_audit_physical_qty') and data.get('brass_audit_physical_qty') > 0:
                data['available_qty'] = data['brass_audit_physical_qty']
            else:
                data['available_qty'] = data.get('display_accepted_qty', 0)

            data['lot_remarks'] = ''

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'from_date': from_date.strftime('%Y-%m-%d'),
            'to_date': to_date.strftime('%Y-%m-%d'),
            'date_filter_applied': bool(from_date_str and to_date_str),
        }
        return Response(context, template_name=self.template_name)


# ═══════════════════════════════════════════════════════════════
# Brass Audit Reject Table View
# ═══════════════════════════════════════════════════════════════
@method_decorator(login_required, name='dispatch')
class BrassAuditRejectTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'BrassAudit/BrassAudit_RejectTable.html'

    def get(self, request):
        user = request.user

        tz = pytz.timezone("Asia/Kolkata")
        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')

        if from_date_str and to_date_str:
            try:
                from_date = datetime.datetime.strptime(from_date_str, '%Y-%m-%d').date()
                to_date = datetime.datetime.strptime(to_date_str, '%Y-%m-%d').date()
            except ValueError:
                from_date = yesterday
                to_date = today
        else:
            from_date = yesterday
            to_date = today

        from_datetime = timezone.make_aware(datetime.datetime.combine(from_date, datetime.datetime.min.time()))
        to_datetime = timezone.make_aware(datetime.datetime.combine(to_date, datetime.datetime.max.time()))

        queryset = TotalStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            batch_id__total_batch_quantity__gt=0,
            brass_audit_rejection=True,
            brass_audit_last_process_date_time__range=(from_datetime, to_datetime)
        )

        queryset = queryset.order_by('-brass_audit_last_process_date_time', '-lot_id')

        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            data = {
                'batch_id': batch.batch_id,
                'lot_id': stock_obj.lot_id,
                'stock_lot_id': stock_obj.lot_id,
                'date_time': batch.date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no if batch.model_stock_no else '',
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                'brass_audit_last_process_date_time': stock_obj.brass_audit_last_process_date_time,
                'brass_audit_physical_qty': stock_obj.brass_audit_physical_qty,
                'brass_qc_accepted_qty': stock_obj.brass_qc_accepted_qty,
                'BA_pick_remarks': stock_obj.BA_pick_remarks,
            }
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"

            batch_obj = ModelMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj and batch_obj.model_stock_no:
                for img in batch_obj.model_stock_no.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            master_data.append(data)

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'from_date': from_date.strftime('%Y-%m-%d'),
            'to_date': to_date.strftime('%Y-%m-%d'),
        }
        return Response(context, template_name=self.template_name)


# ═══════════════════════════════════════════════════════════════
# Shared Tray Resolver — LOT-INDEPENDENT
# ═══════════════════════════════════════════════════════════════
def _resolve_lot_trays_audit(lot_id):
    """
    Shared tray resolver for Brass Audit — single source of truth.
    Returns (tray_data_list, source_name, total_qty).
    STRICTLY uses current lot data only — no cross-stage history.
    """
    tray_data = []
    source = "BrassAuditTrayId"

    # Step 1: BrassAuditTrayId (Brass Audit's own table)
    trays = BrassAuditTrayId.objects.filter(lot_id=lot_id).order_by('-top_tray', 'tray_id')
    if trays.exists():
        tray_data = [
            {"tray_id": t.tray_id, "qty": t.tray_quantity or 0,
             "is_rejected": t.rejected_tray, "is_top": t.top_tray, "is_delinked": t.delink_tray}
            for t in trays
        ]

    # Step 2: Fallback to TrayId (global table)
    if not tray_data:
        source = "TrayId"
        trays = TrayId.objects.filter(lot_id=lot_id, tray_quantity__gt=0).order_by('-top_tray', 'tray_id')
        tray_data = [
            {"tray_id": t.tray_id, "qty": t.tray_quantity or 0,
             "is_rejected": getattr(t, 'rejected_tray', False),
             "is_top": t.top_tray,
             "is_delinked": t.delink_tray}
            for t in trays
        ]

    # Step 3: Final fallback to Accepted Store
    if not tray_data:
        source = "AcceptedStore"
        accepted = Brass_Audit_Accepted_TrayID_Store.objects.filter(lot_id=lot_id)
        tray_data = [
            {"tray_id": t.tray_id, "qty": t.tray_qty or 0,
             "is_rejected": False, "is_top": False, "is_delinked": False}
            for t in accepted
        ]

    total_qty = sum(t['qty'] for t in tray_data)

    # Compute status for each tray (backend-driven)
    for t in tray_data:
        if t.get('is_delinked'):
            t['status'] = 'DELINK'
        elif t.get('is_rejected') and t.get('is_top'):
            t['status'] = 'REJECT_TOP'
        elif t.get('is_rejected'):
            t['status'] = 'REJECT'
        elif t.get('is_top'):
            t['status'] = 'ACCEPT_TOP'
        else:
            t['status'] = 'ACCEPT'

    return tray_data, source, total_qty


# ═══════════════════════════════════════════════════════════════
# Lot Qty - Verification Toggle
# ═══════════════════════════════════════════════════════════════
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_audit_toggle_verified(request):
    lot_id = request.data.get('lot_id')
    verified = request.data.get('verified', False)

    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)

    ts = TotalStockModel.objects.filter(lot_id=lot_id).first()
    if not ts:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    ts.brass_audit_accepted_qty_verified = bool(verified)
    update_fields = ['brass_audit_accepted_qty_verified']

    if bool(verified) and ts.last_process_module != 'Brass Audit':
        ts.last_process_module = 'Brass Audit'
        update_fields.append('last_process_module')

    ts.save(update_fields=update_fields)

    return JsonResponse({
        "success": True,
        "lot_id": lot_id,
        "brass_audit_accepted_qty_verified": ts.brass_audit_accepted_qty_verified,
        "last_process_module": ts.last_process_module,
    })


# ═══════════════════════════════════════════════════════════════
# Hold / Unhold Toggle with Remark
# ═══════════════════════════════════════════════════════════════
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_audit_hold_unhold(request):
    lot_id = request.data.get('lot_id')
    action = request.data.get('action')
    remark = request.data.get('remark', '').strip()

    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
    if action not in ('hold', 'unhold'):
        return JsonResponse({"success": False, "error": "action must be 'hold' or 'unhold'"}, status=400)
    if not remark:
        return JsonResponse({"success": False, "error": "Remark is required"}, status=400)
    if len(remark) > 50:
        return JsonResponse({"success": False, "error": "Remark must be 50 characters or less"}, status=400)

    ts = TotalStockModel.objects.filter(lot_id=lot_id).first()
    if not ts:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    if action == 'hold':
        ts.brass_audit_hold_lot = True
        ts.brass_audit_holding_reason = remark
        ts.brass_audit_release_lot = False
        ts.brass_audit_release_reason = ''
    else:
        ts.brass_audit_hold_lot = False
        ts.brass_audit_release_reason = remark
        ts.brass_audit_release_lot = True

    ts.save(update_fields=[
        'brass_audit_hold_lot', 'brass_audit_holding_reason',
        'brass_audit_release_lot', 'brass_audit_release_reason',
    ])

    logger.info(f"[BrassAudit] Hold/Unhold: lot_id={lot_id}, action={action}, remark={remark}")

    return JsonResponse({
        "success": True,
        "lot_id": lot_id,
        "action": action,
        "message": f"Lot {'held' if action == 'hold' else 'released'} successfully.",
    })


# ═══════════════════════════════════════════════════════════════
# Rejection Reasons - Dynamic Fetch
# ═══════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_audit_rejection_reasons(request):
    reasons = Brass_Audit_Rejection_Table.objects.all().order_by('rejection_reason_id')
    data = [
        {"id": r.id, "reason_id": r.rejection_reason_id, "reason": r.rejection_reason}
        for r in reasons
    ]
    return JsonResponse({"success": True, "reasons": data})


# ═══════════════════════════════════════════════════════════════
# Tray Reuse Logic
# ═══════════════════════════════════════════════════════════════
def compute_reuse_trays(trays, reject_qty):
    trays_sorted = sorted(trays, key=lambda x: (not x.get('is_top', False), x.get('tray_id', '')))
    reuse_trays = []
    updated_trays = []
    remaining_reject = reject_qty

    for tray in trays_sorted:
        tray_qty = tray["qty"]
        if remaining_reject <= 0:
            updated_trays.append({**tray, "remaining_qty": tray_qty})
            continue
        if remaining_reject >= tray_qty:
            remaining_reject -= tray_qty
            updated_trays.append({**tray, "used_qty": tray_qty, "remaining_qty": 0, "status": "REJECT_FULL"})
            reuse_trays.append(tray["tray_id"])
        else:
            updated_trays.append({**tray, "used_qty": remaining_reject, "remaining_qty": tray_qty - remaining_reject, "status": "REJECT_PARTIAL"})
            remaining_reject = 0

    return {"reuse_trays": reuse_trays, "updated_trays": updated_trays}


# ═══════════════════════════════════════════════════════════════
# Brass Audit Unified API Endpoint
# ═══════════════════════════════════════════════════════════════
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_audit_action(request):
    """
    UNIFIED Brass Audit API — single entry point for all actions.
    Actions: GET_TRAYS, GET_SUBMISSION_TRAYS, ALLOCATE, VALIDATE_TRAY,
             GET_REASONS, SAVE_DRAFT, GET_DRAFT, FULL_ACCEPT, FULL_REJECT,
             PARTIAL, PROCESS, SAVE_REMARK
    """
    action = request.data.get('action', '').strip()

    if action == 'GET_TRAYS':
        lot_id = request.data.get('lot_id')
        if not lot_id:
            return JsonResponse({"error": "lot_id is required"}, status=400)
        try:
            stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return JsonResponse({"error": "Lot not found"}, status=404)

        # LOT-INDEPENDENT: only resolve current lot's tray data
        tray_data, source, total_qty = _resolve_lot_trays_audit(lot_id)

        tray_capacity = 0
        if stock.batch_id:
            tray_capacity = stock.batch_id.tray_capacity or 0

        logger.info(f"[AUDIT:GET_TRAYS] lot_id={lot_id}, source={source}, trays={len(tray_data)}, total_qty={total_qty}")
        return JsonResponse({
            "lot_id": lot_id,
            "batch_id": stock.batch_id.batch_id if stock.batch_id else "",
            "total_qty": total_qty,
            "tray_capacity": tray_capacity,
            "source": source,
            "trays": tray_data,
        })

    elif action == 'GET_SUBMISSION_TRAYS':
        lot_id = request.data.get('lot_id')
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        submission = Brass_Audit_Submission.objects.filter(lot_id=lot_id, is_completed=True).order_by('-created_at').first()
        if not submission:
            return JsonResponse({"success": True, "lot_id": lot_id, "trays": [],
                                 "accepted_qty": 0, "rejected_qty": 0, "total_lot_qty": 0, "submission_type": ""})

        trays = []
        accept_data = submission.full_accept_data or submission.partial_accept_data or {}
        reject_data = submission.full_reject_data or submission.partial_reject_data or {}

        accept_qty_map = {}
        accept_top_map = {}
        for t in (accept_data.get('trays') or []):
            tid = t.get("tray_id", "")
            if tid:
                accept_qty_map[tid] = int(t.get("qty") or 0)
                accept_top_map[tid] = bool(t.get("is_top", False))

        reject_qty_map = {}
        for t in (reject_data.get('trays') or []):
            tid = t.get("tray_id", "")
            if tid:
                reject_qty_map[tid] = int(t.get("qty") or 0)

        original_qty_map = {}
        for bt in BrassAuditTrayId.objects.filter(lot_id=lot_id):
            if bt.tray_id:
                original_qty_map[bt.tray_id] = int(bt.tray_quantity or 0)
        if not original_qty_map:
            for ti in TrayId.objects.filter(lot_id=lot_id, tray_quantity__gt=0):
                original_qty_map[ti.tray_id] = int(ti.tray_quantity or 0)

        delink_trays = []
        for orig_tid, orig_qty in original_qty_map.items():
            if orig_qty <= 0:
                continue
            used = accept_qty_map.get(orig_tid, 0) + reject_qty_map.get(orig_tid, 0)
            residual = orig_qty - used
            if residual > 0:
                delink_trays.append({
                    "tray_id": orig_tid, "tray_quantity": residual,
                    "rejected_tray": False, "delink_tray": True,
                    "top_tray": False, "is_top_tray": False,
                })

        for tid, qty in accept_qty_map.items():
            trays.append({
                "tray_id": tid, "tray_quantity": qty,
                "rejected_tray": False, "delink_tray": False,
                "top_tray": accept_top_map.get(tid, False),
                "is_top_tray": accept_top_map.get(tid, False),
            })
        for tid, qty in reject_qty_map.items():
            trays.append({
                "tray_id": tid, "tray_quantity": qty,
                "rejected_tray": True, "delink_tray": False,
                "top_tray": False, "is_top_tray": False,
            })
        trays.extend(delink_trays)

        return JsonResponse({
            "success": True, "lot_id": lot_id,
            "submission_type": submission.submission_type,
            "accepted_qty": submission.accepted_qty,
            "rejected_qty": submission.rejected_qty,
            "total_lot_qty": submission.total_lot_qty,
            "trays": trays,
        })

    elif action == 'ALLOCATE':
        lot_id = request.data.get('lot_id')
        rejected_qty = int(request.data.get('rejected_qty', 0))
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        try:
            stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

        tray_data, source, total_qty = _resolve_lot_trays_audit(lot_id)
        active_trays = [t for t in tray_data if not t.get('is_delinked')]
        tray_capacity = stock.batch_id.tray_capacity or 0 if stock.batch_id else 0

        if rejected_qty < 0 or rejected_qty > total_qty:
            return JsonResponse({"success": False, "error": "Invalid rejected_qty"}, status=400)
        accepted_qty = total_qty - rejected_qty

        def compute_slots(qty, capacity):
            if qty <= 0 or capacity <= 0:
                return []
            full_trays = qty // capacity
            remainder = qty % capacity
            slots = []
            if remainder > 0:
                slots.append({"qty": remainder, "is_top": True, "tray_id": None})
            for i in range(full_trays):
                slots.append({"qty": capacity, "is_top": False, "tray_id": None})
            return slots

        accept_slots = compute_slots(accepted_qty, tray_capacity) if accepted_qty > 0 else []
        reject_slots = compute_slots(rejected_qty, tray_capacity) if rejected_qty > 0 else []
        unmapped_trays = [t for t in active_trays]

        reuse_result = compute_reuse_trays(
            [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in active_trays],
            rejected_qty
        )

        return JsonResponse({
            "success": True, "lot_id": lot_id,
            "total_qty": total_qty, "tray_capacity": tray_capacity,
            "accepted_qty": accepted_qty, "rejected_qty": rejected_qty,
            "accept_slots": accept_slots, "reject_slots": reject_slots,
            "original_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in active_trays],
            "unmapped_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in unmapped_trays],
            "reuse_trays": reuse_result["reuse_trays"],
            "reuse_count": len(reuse_result["reuse_trays"]),
            "reuse_updated_trays": reuse_result["updated_trays"],
        })

    elif action == 'VALIDATE_TRAY':
        tray_id = request.data.get('tray_id', '').strip()
        lot_id = request.data.get('lot_id', '').strip()
        if not tray_id:
            return JsonResponse({"valid": False, "error": "tray_id is required"}, status=400)
        tray = TrayId.objects.filter(tray_id=tray_id).first()
        if not tray:
            return JsonResponse({"valid": False, "error": "Tray ID not found in system"})
        if tray.lot_id and tray.lot_id != lot_id:
            return JsonResponse({"valid": False, "error": f"Tray belongs to lot {tray.lot_id}"})
        return JsonResponse({"valid": True})

    elif action == 'GET_REASONS':
        reasons = Brass_Audit_Rejection_Table.objects.all().order_by('rejection_reason_id')
        data = [
            {"id": r.id, "reason_id": r.rejection_reason_id, "reason": r.rejection_reason}
            for r in reasons
        ]
        return JsonResponse({"success": True, "reasons": data})

    elif action == 'SAVE_DRAFT':
        lot_id = request.data.get('lot_id')
        draft_payload = request.data.get('draft_data', {})
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        if not draft_payload:
            return JsonResponse({"success": False, "error": "draft_data is required"}, status=400)
        try:
            stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return JsonResponse({"success": False, "error": "Lot not found"}, status=404)
        if Brass_Audit_Submission.objects.filter(lot_id=lot_id, is_completed=True).exists():
            return JsonResponse({"success": False, "error": "Lot already submitted — cannot save draft"}, status=409)
        draft, created = Brass_Audit_Draft_Store.objects.update_or_create(
            lot_id=lot_id,
            draft_type='rejection_draft',
            defaults={
                'batch_id': stock.batch_id.batch_id if stock.batch_id else '',
                'user': request.user,
                'draft_data': draft_payload,
            }
        )
        # Generate transition lot_id for draft
        if not draft.draft_transition_lot_id:
            draft.draft_transition_lot_id = generate_new_lot_id()
            draft.save(update_fields=['draft_transition_lot_id'])
            logger.info(f"[AUDIT DRAFT TRANSITION] lot_id={lot_id} → draft_transition_lot_id={draft.draft_transition_lot_id}")
        stock.brass_audit_draft = True
        stock.brass_audit_onhold_picking = True
        stock.save(update_fields=['brass_audit_draft', 'brass_audit_onhold_picking'])
        logger.info(f"[AUDIT DRAFT] Saved for lot_id={lot_id}, user={request.user}")
        return JsonResponse({
            "success": True, "lot_id": lot_id, "draft_id": draft.id,
            "draft_transition_lot_id": draft.draft_transition_lot_id,
            "message": "Draft saved. Lot marked as Draft.",
            "lot_status": "Draft", "action_state": "ONHOLD_TOPTRAY",
        })

    elif action == 'GET_DRAFT':
        lot_id = request.data.get('lot_id')
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        draft = Brass_Audit_Draft_Store.objects.filter(lot_id=lot_id, draft_type='rejection_draft').first()
        if not draft:
            return JsonResponse({"success": True, "has_draft": False, "draft_data": None, "lot_id": lot_id})
        return JsonResponse({
            "success": True, "has_draft": True,
            "draft_data": draft.draft_data, "lot_id": lot_id,
        })

    elif action in ('FULL_ACCEPT', 'FULL_REJECT', 'PARTIAL', 'PROCESS', 'SAVE_REMARK'):
        return _handle_audit_submission(request, action)

    else:
        return JsonResponse({"success": False, "error": f"Unknown action: {action}"}, status=400)


# ═══════════════════════════════════════════════════════════════
# Submission Handler — Stage Movement for Brass Audit
# ═══════════════════════════════════════════════════════════════
def _handle_audit_submission(request, action):
    data = request.data
    # FIX 1: Accept both lot_id and stock_lot_id — enforce single contract
    lot_id = data.get("lot_id") or data.get("stock_lot_id")
    rejection_reasons = data.get("rejection_reasons", [])
    accepted_tray_ids = data.get("accepted_tray_ids", [])
    rejected_tray_ids = data.get("rejected_tray_ids", [])
    remarks = data.get("remarks", "").strip()

    logger.info(f"[AUDIT ACTION] [INPUT] lot_id={lot_id}, action={action}, user={request.user}")

    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)

    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    if action == "SAVE_REMARK":
        remark_text = remarks
        if not remark_text:
            return JsonResponse({"success": False, "error": "Remark text is required"}, status=400)
        if len(remark_text) > 100:
            return JsonResponse({"success": False, "error": "Remark must be 100 characters or less"}, status=400)
        stock.BA_pick_remarks = remark_text
        stock.save(update_fields=['BA_pick_remarks'])
        return JsonResponse({"success": True, "lot_id": lot_id, "message": "Remark saved successfully", "has_remark": True})

    existing = Brass_Audit_Submission.objects.filter(lot_id=lot_id, is_completed=True).first()
    if existing:
        return JsonResponse({
            "success": False, "error": "This lot has already been submitted",
            "existing_submission_id": existing.id, "existing_type": existing.submission_type,
        }, status=409)

    tray_data, source, total_qty = _resolve_lot_trays_audit(lot_id)
    if not tray_data:
        return JsonResponse({"success": False, "error": "No tray data found for this lot"}, status=400)
    if total_qty <= 0:
        return JsonResponse({"success": False, "error": "Total lot quantity is zero"}, status=400)

    active_trays = [t for t in tray_data if not t["is_delinked"]]

    if action == "FULL_ACCEPT":
        submission_type = "FULL_ACCEPT"
        accepted_qty = total_qty
        rejected_qty = 0
        accepted_trays = [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]} for t in active_trays]
        rejected_trays = []

    elif action == "FULL_REJECT":
        submission_type = "FULL_REJECT"
        if rejection_reasons:
            total_reject_from_reasons = sum(int(r.get("qty", 0)) for r in rejection_reasons)
            if total_reject_from_reasons != total_qty:
                logger.warning(f"[AUDIT ACTION] FULL_REJECT reason qty mismatch: reasons={total_reject_from_reasons}, lot={total_qty}")
        accepted_qty = 0
        rejected_qty = total_qty
        accepted_trays = []
        if rejected_tray_ids:
            active_tray_map = {t["tray_id"]: t for t in active_trays}
            rejected_trays = [{"tray_id": tid, "qty": active_tray_map[tid]["qty"], "is_top": active_tray_map[tid]["is_top"]}
                              for tid in rejected_tray_ids if tid in active_tray_map]
        else:
            rejected_trays = [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]} for t in active_trays]

    elif action == "PARTIAL":
        submission_type = "PARTIAL"
        if not rejection_reasons:
            return JsonResponse({"success": False, "error": "Rejection reasons are required for partial reject"}, status=400)
        total_reject_from_reasons = sum(int(r.get("qty", 0)) for r in rejection_reasons)
        if total_reject_from_reasons <= 0:
            return JsonResponse({"success": False, "error": "Rejection qty must be greater than 0"}, status=400)
        if total_reject_from_reasons >= total_qty:
            return JsonResponse({"success": False, "error": "Partial reject qty must be less than total lot qty"}, status=400)
        rejected_qty = total_reject_from_reasons
        accepted_qty = total_qty - rejected_qty
        rejected_trays = []
        accepted_trays = []
        if rejected_tray_ids:
            active_tray_map = {t["tray_id"]: t for t in active_trays}
            invalid_reject_ids = [tid for tid in rejected_tray_ids if tid not in active_tray_map]
            if invalid_reject_ids:
                return JsonResponse({"success": False, "error": f"Invalid rejected tray IDs: {invalid_reject_ids}"}, status=400)
            for t in active_trays:
                if t["tray_id"] in rejected_tray_ids:
                    rejected_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
                else:
                    accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
        else:
            remaining_reject = rejected_qty
            sorted_trays = sorted(active_trays, key=lambda t: (not t["is_top"]))
            for t in sorted_trays:
                if remaining_reject <= 0:
                    accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
                elif remaining_reject >= t["qty"]:
                    rejected_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
                    remaining_reject -= t["qty"]
                else:
                    rejected_trays.append({"tray_id": t["tray_id"], "qty": remaining_reject, "is_top": t["is_top"]})
                    accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"] - remaining_reject, "is_top": False})
                    remaining_reject = 0

    elif action == "PROCESS":
        tray_actions = data.get("tray_actions", [])
        if not tray_actions:
            return JsonResponse({"success": False, "error": "tray_actions required for PROCESS action"}, status=400)
        active_tray_map = {t["tray_id"]: t for t in active_trays}
        accepted_trays = []
        rejected_trays = []
        for ta in tray_actions:
            tid = ta.get("tray_id")
            ta_action = ta.get("action")
            is_top = bool(ta.get("is_top", False))
            if ta_action not in ("ACCEPT", "REJECT", "DELINK"):
                return JsonResponse({"success": False, "error": f"Invalid tray action '{ta_action}' for tray {tid}"}, status=400)
            tray_match = active_tray_map.get(tid)
            if not tray_match:
                if ta_action == "REJECT":
                    if not TrayId.objects.filter(tray_id=tid).exists():
                        return JsonResponse({"success": False, "error": f"Reject tray '{tid}' not found in master tray list"}, status=400)
                    slot_qty = int(ta.get("qty") or 0)
                    if slot_qty <= 0:
                        slot_qty = (stock.batch_id.tray_capacity if stock.batch_id else 0) or 0
                    rejected_trays.append({"tray_id": tid, "qty": slot_qty, "is_top": False})
                    continue
                return JsonResponse({"success": False, "error": f"Tray {tid} not found in lot"}, status=400)
            tray_entry = {"tray_id": tid, "qty": tray_match["qty"], "is_top": is_top}
            if ta_action == "ACCEPT":
                accepted_trays.append(tray_entry)
            elif ta_action == "REJECT":
                rejected_trays.append(tray_entry)
            elif ta_action == "DELINK":
                BrassAuditTrayId.objects.filter(lot_id=lot_id, tray_id=tid).update(delink_tray=True)
                TrayId.objects.filter(lot_id=lot_id, tray_id=tid).update(delink_tray=True)

        if accepted_trays:
            top_count = sum(1 for t in accepted_trays if t["is_top"])
            if top_count != 1:
                return JsonResponse({"success": False, "error": f"Exactly one accepted tray must be marked as top (found {top_count})"}, status=400)

        rejected_qty = sum(int(r.get("qty", 0)) for r in rejection_reasons) if rejection_reasons else 0
        accepted_qty = total_qty - rejected_qty
        if rejected_qty < 0 or rejected_qty > total_qty:
            return JsonResponse({"success": False, "error": "Invalid rejection quantity"}, status=400)
        if rejected_qty == 0:
            submission_type = "FULL_ACCEPT"
        elif accepted_qty == 0:
            submission_type = "FULL_REJECT"
        else:
            submission_type = "PARTIAL"
        if rejected_qty > 0 and not rejection_reasons:
            return JsonResponse({"success": False, "error": "Rejection reasons required when rejecting trays"}, status=400)

    # Store rejection reasons
    if rejection_reasons and action in ("FULL_REJECT", "PARTIAL", "PROCESS"):
        try:
            reason_store = Brass_Audit_Rejection_ReasonStore.objects.create(
                lot_id=lot_id, user=request.user, total_rejection_quantity=rejected_qty,
                batch_rejection=(action == "FULL_REJECT"), lot_rejected_comment=remarks or None,
            )
            reason_ids = []
            for r in rejection_reasons:
                reason_id = r.get("reason_id")
                qty = int(r.get("qty", 0))
                if qty > 0 and reason_id:
                    try:
                        reason_obj = Brass_Audit_Rejection_Table.objects.get(id=reason_id)
                        reason_ids.append(reason_obj.id)
                        Brass_Audit_Rejected_TrayScan.objects.create(
                            lot_id=lot_id, rejected_tray_quantity=str(qty), rejected_tray_id=None,
                            rejection_reason=reason_obj, user=request.user,
                        )
                    except Brass_Audit_Rejection_Table.DoesNotExist:
                        logger.warning(f"[AUDIT ACTION] Rejection reason not found: id={reason_id}")
            if reason_ids:
                reason_store.rejection_reason.set(reason_ids)
        except Exception as e:
            logger.error(f"[AUDIT ACTION] Error storing rejection reasons: {e}")

    # Save submission
    accept_snapshot = {"qty": accepted_qty, "trays": accepted_trays} if accepted_trays else None
    reject_snapshot = {"qty": rejected_qty, "trays": rejected_trays} if rejected_trays else None
    submission = Brass_Audit_Submission.objects.create(
        lot_id=lot_id, batch_id=stock.batch_id.batch_id if stock.batch_id else "",
        submission_type=submission_type, total_lot_qty=total_qty,
        accepted_qty=accepted_qty, rejected_qty=rejected_qty,
        full_accept_data=accept_snapshot if submission_type == "FULL_ACCEPT" else None,
        full_reject_data=reject_snapshot if submission_type == "FULL_REJECT" else None,
        partial_accept_data=accept_snapshot if submission_type == "PARTIAL" else None,
        partial_reject_data=reject_snapshot if submission_type == "PARTIAL" else None,
        snapshot_data={
            "lot_qty": total_qty, "accepted": accepted_trays, "rejected": rejected_trays,
            "rejection_reasons": rejection_reasons if rejection_reasons else [], "remarks": remarks,
        },
        is_completed=True, created_by=request.user,
    )

    # ═══ TRANSITION LOT ID — Create new lot_id for each transition ═══
    if submission_type == "FULL_ACCEPT":
        t_lot_id = generate_new_lot_id()
        t_label = "full accept from brass audit to iqf"
        submission.transition_lot_id = t_lot_id
        submission.transition_label = t_label
        submission.save(update_fields=['transition_lot_id', 'transition_label'])
        stock.brass_audit_transition_lot_id = t_lot_id
        stock.brass_audit_transition_label = t_label
        logger.info(f"[AUDIT TRANSITION] FULL_ACCEPT lot_id={lot_id} → transition_lot_id={t_lot_id}")
    elif submission_type == "FULL_REJECT":
        t_lot_id = generate_new_lot_id()
        t_label = "full reject from brass audit to brass qc"
        submission.transition_lot_id = t_lot_id
        submission.transition_label = t_label
        submission.save(update_fields=['transition_lot_id', 'transition_label'])
        stock.brass_audit_transition_lot_id = t_lot_id
        stock.brass_audit_transition_label = t_label
        logger.info(f"[AUDIT TRANSITION] FULL_REJECT lot_id={lot_id} → transition_lot_id={t_lot_id}")
    elif submission_type == "PARTIAL":
        t_accept_lot_id = generate_new_lot_id()
        t_reject_lot_id = generate_new_lot_id()
        t_label = "partial accept from brass audit to iqf | partial reject from brass audit to brass qc"
        submission.transition_accept_lot_id = t_accept_lot_id
        submission.transition_reject_lot_id = t_reject_lot_id
        submission.transition_label = t_label
        submission.save(update_fields=['transition_accept_lot_id', 'transition_reject_lot_id', 'transition_label'])
        stock.brass_audit_transition_accept_lot_id = t_accept_lot_id
        stock.brass_audit_transition_reject_lot_id = t_reject_lot_id
        stock.brass_audit_transition_label = t_label
        logger.info(f"[AUDIT TRANSITION] PARTIAL lot_id={lot_id} → accept={t_accept_lot_id}, reject={t_reject_lot_id}")

    # ═══ STAGE MOVEMENT — Brass Audit hierarchy ═══
    # Full Accept → IQF
    # Full Reject → back to Brass QC (as NEW lot context)
    # Partial → accepted portion to IQF, rejected portion marked
    if submission_type == "FULL_ACCEPT":
        stock.brass_audit_accptance = True
        stock.brass_audit_rejection = False
        stock.brass_audit_few_cases_accptance = False
        stock.brass_audit_physical_qty = accepted_qty
        stock.brass_audit_accepted_qty = accepted_qty
        stock.next_process_module = 'IQF'
        stock.last_process_module = 'Brass Audit'
    elif submission_type == "FULL_REJECT":
        stock.brass_audit_accptance = False
        stock.brass_audit_rejection = True
        stock.brass_audit_few_cases_accptance = False
        stock.brass_audit_physical_qty = 0
        stock.brass_audit_accepted_qty = 0
        stock.next_process_module = 'Brass QC'
        stock.last_process_module = 'Brass Audit'
        stock.send_brass_audit_to_qc = True
    elif submission_type == "PARTIAL":
        stock.brass_audit_few_cases_accptance = True
        stock.brass_audit_rejection = True
        stock.brass_audit_accptance = False
        stock.brass_audit_physical_qty = accepted_qty
        stock.brass_audit_accepted_qty = accepted_qty
        stock.next_process_module = 'IQF'
        stock.last_process_module = 'Brass Audit'
        stock.send_brass_audit_to_iqf = True

    # Clear draft state
    Brass_Audit_Draft_Store.objects.filter(lot_id=lot_id, draft_type='rejection_draft').delete()
    stock.brass_audit_draft = False
    stock.brass_audit_onhold_picking = False

    stock.last_process_date_time = timezone.now()
    stock.brass_audit_last_process_date_time = timezone.now()
    stock.save(update_fields=[
        'brass_audit_accptance', 'brass_audit_rejection', 'brass_audit_few_cases_accptance',
        'brass_audit_physical_qty', 'brass_audit_accepted_qty', 'next_process_module', 'last_process_module',
        'last_process_date_time', 'brass_audit_last_process_date_time',
        'brass_audit_draft', 'brass_audit_onhold_picking',
        'send_brass_audit_to_qc', 'send_brass_audit_to_iqf',
        'brass_audit_transition_lot_id', 'brass_audit_transition_accept_lot_id',
        'brass_audit_transition_reject_lot_id', 'brass_audit_transition_label',
    ])

    # FIX 4: Sync accepted trays to BrassAuditTrayId so Jig Loading can find them.
    # Clears existing records for this lot then re-creates from accepted snapshot.
    if submission_type in ("FULL_ACCEPT", "PARTIAL") and accepted_trays:
        try:
            BrassAuditTrayId.objects.filter(lot_id=lot_id).delete()
            for t in accepted_trays:
                BrassAuditTrayId.objects.create(
                    lot_id=lot_id,
                    tray_id=t.get("tray_id", ""),
                    tray_quantity=int(t.get("qty") or 0),
                    top_tray=bool(t.get("is_top", False)),
                    delink_tray=False,
                    rejected_tray=False,
                )
            logger.info(f"[AUDIT TRAY SYNC] lot_id={lot_id}, stored {len(accepted_trays)} accepted tray(s) to BrassAuditTrayId")
        except Exception as _e:
            logger.error(f"[AUDIT TRAY SYNC] Failed to sync trays for lot_id={lot_id}: {_e}")

    logger.info(f"[AUDIT ACTION] [DONE] type={submission_type}, lot_id={lot_id}, moved_to={stock.next_process_module}")

    return JsonResponse({
        "success": True,
        "message": f"Lot {submission_type.replace('_', ' ').lower()} and moved to {stock.next_process_module}",
        "lot_id": lot_id, "submission_id": submission.id, "submission_type": submission_type,
        "accepted_qty": accepted_qty, "rejected_qty": rejected_qty,
        "status": f"MOVED_TO_{stock.next_process_module.upper().replace(' ', '_')}",
        "trays": accepted_trays if submission_type != "FULL_REJECT" else rejected_trays,
        "transition_lot_id": submission.transition_lot_id,
        "transition_accept_lot_id": submission.transition_accept_lot_id,
        "transition_reject_lot_id": submission.transition_reject_lot_id,
        "transition_label": submission.transition_label,
    })


# ═══════════════════════════════════════════════════════════════
# Legacy Endpoints — Backward Compatible
# ═══════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_audit_tray_details(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return JsonResponse({"error": "lot_id is required"}, status=400)
    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return JsonResponse({"error": "Lot not found"}, status=404)

    tray_data, source, total_qty = _resolve_lot_trays_audit(lot_id)
    tray_capacity = stock.batch_id.tray_capacity or 0 if stock.batch_id else 0

    return JsonResponse({
        "lot_id": lot_id,
        "batch_id": stock.batch_id.batch_id if stock.batch_id else "",
        "total_qty": total_qty,
        "tray_capacity": tray_capacity,
        "source": source,
        "trays": tray_data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def validate_audit_tray_id(request):
    tray_id = request.GET.get('tray_id', '').strip()
    lot_id = request.GET.get('lot_id', '').strip()
    if not tray_id:
        return JsonResponse({"valid": False, "error": "tray_id is required"}, status=400)
    tray = TrayId.objects.filter(tray_id=tray_id).first()
    if not tray:
        return JsonResponse({"valid": False, "error": "Tray ID not found in system"})
    if tray.lot_id and tray.lot_id != lot_id:
        return JsonResponse({"valid": False, "error": f"Tray belongs to lot {tray.lot_id}"})
    return JsonResponse({"valid": True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def allocate_audit_trays(request):
    lot_id = request.data.get('lot_id')
    rejected_qty = int(request.data.get('rejected_qty', 0))
    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    tray_data, source, total_qty = _resolve_lot_trays_audit(lot_id)
    active_trays = [t for t in tray_data if not t.get('is_delinked')]
    tray_capacity = stock.batch_id.tray_capacity or 0 if stock.batch_id else 0

    if rejected_qty < 0 or rejected_qty > total_qty:
        return JsonResponse({"success": False, "error": "Invalid rejected_qty"}, status=400)
    accepted_qty = total_qty - rejected_qty

    def compute_slots(qty, capacity):
        if qty <= 0 or capacity <= 0:
            return []
        full_trays = qty // capacity
        remainder = qty % capacity
        slots = []
        if remainder > 0:
            slots.append({"qty": remainder, "is_top": True, "tray_id": None})
        for i in range(full_trays):
            slots.append({"qty": capacity, "is_top": False, "tray_id": None})
        return slots

    accept_slots = compute_slots(accepted_qty, tray_capacity) if accepted_qty > 0 else []
    reject_slots = compute_slots(rejected_qty, tray_capacity) if rejected_qty > 0 else []
    unmapped_trays = [t for t in active_trays]

    return JsonResponse({
        "success": True, "lot_id": lot_id,
        "total_qty": total_qty, "tray_capacity": tray_capacity,
        "accepted_qty": accepted_qty, "rejected_qty": rejected_qty,
        "accept_slots": accept_slots, "reject_slots": reject_slots,
        "original_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in active_trays],
        "unmapped_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in unmapped_trays],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_brass_audit(request):
    data = request.data
    lot_id = data.get("lot_id")
    action = data.get("action", "FULL_ACCEPT")
    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
    if action not in ("FULL_ACCEPT", "FULL_REJECT", "PARTIAL", "SAVE_REMARK", "PROCESS"):
        return JsonResponse({"success": False, "error": f"Invalid action: {action}"}, status=400)
    # Delegate to unified handler
    return _handle_audit_submission(request, action)


# ═══════════════════════════════════════════════════════════════
# Raw Submission API — stores exact UI payload
# ═══════════════════════════════════════════════════════════════
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_audit_raw_submission(request):
    data = request.data
    lot_id = data.get("lot_id", "").strip()
    batch_id = data.get("batch_id", "").strip()
    plating_stk_no = data.get("plating_stk_no", "").strip()
    submission_type = data.get("submission_type", "DRAFT").upper()

    logger.info(f"[AUDIT RAW] [INPUT] lot_id={lot_id}, type={submission_type}, user={request.user}")

    if not lot_id:
        return JsonResponse({"status": "error", "message": "lot_id is required"}, status=400)
    if submission_type not in ("DRAFT", "SUBMIT"):
        return JsonResponse({"status": "error", "message": f"Invalid submission_type: {submission_type}"}, status=400)

    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Lot not found"}, status=404)

    if submission_type == "SUBMIT":
        total_lot_qty = data.get("total_lot_qty", 0)
        summary = data.get("summary", {})
        accepted = summary.get("accepted", 0)
        rejected = summary.get("rejected", 0)
        remarks = data.get("remarks", "").strip()

        if accepted + rejected != total_lot_qty:
            msg = f"Sum check failed: {accepted} + {rejected} != {total_lot_qty}"
            return JsonResponse({"status": "error", "message": msg}, status=400)

        accept_trays = data.get("accept_trays", [])
        accept_top_count = sum(1 for t in accept_trays if t.get("is_top", False))
        if accept_top_count != 1 and len(accept_trays) > 0:
            return JsonResponse({"status": "error", "message": f"Accept must have exactly ONE top tray (found {accept_top_count})"}, status=400)

        reject_trays = data.get("reject_trays", [])
        if rejected > 0:
            reject_top_count = sum(1 for t in reject_trays if t.get("is_top", False))
            if reject_top_count > 1:
                return JsonResponse({"status": "error", "message": f"Reject cannot have more than ONE top tray (found {reject_top_count})"}, status=400)
            if rejected == total_lot_qty and not remarks:
                return JsonResponse({"status": "error", "message": "Remarks are mandatory for full rejection"}, status=400)

    # Auto-create trays if not in master
    all_trays_to_check = data.get("accept_trays", []) + data.get("reject_trays", []) + data.get("delink_trays", [])
    created_trays = []
    for tray in all_trays_to_check:
        tray_id_val = tray.get("tray_id", "").strip()
        if not tray_id_val:
            continue
        existing = TrayId.objects.filter(tray_id=tray_id_val).first()
        if not existing:
            try:
                TrayId.objects.create(
                    lot_id=lot_id, tray_id=tray_id_val,
                    tray_quantity=tray.get("qty", 0),
                    top_tray=tray.get("is_top", False),
                    delink_tray=tray_id_val in [d.get("tray_id", "") for d in data.get("delink_trays", [])]
                )
                created_trays.append({"tray_id": tray_id_val, "qty": tray.get("qty", 0), "is_top": tray.get("is_top", False)})
            except Exception as e:
                logger.error(f"[AUDIT RAW] Error creating tray {tray_id_val}: {e}")

    try:
        raw_submission = Brass_Audit_RawSubmission.objects.create(
            lot_id=lot_id, batch_id=batch_id, plating_stk_no=plating_stk_no,
            payload=data, submission_type=submission_type, created_by=request.user
        )
        return JsonResponse({
            "status": "success", "submission_type": submission_type,
            "lot_id": lot_id, "message": f"Saved successfully ({submission_type})",
            "submission_id": raw_submission.id, "created_trays": created_trays
        })
    except Exception as e:
        logger.error(f"[AUDIT RAW] Error saving: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": f"Error saving submission: {str(e)}"}, status=500)


# ═══════════════════════════════════════════════════════════════
# Rejection Details API (for Completed/Reject table view icons)
# ═══════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def brass_get_rejection_details(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    try:
        reason_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        if not reason_store:
            return Response({'success': True, 'reasons': []})

        reasons = reason_store.rejection_reason.all()
        total_qty = reason_store.total_rejection_quantity

        if reason_store.batch_rejection:
            if reasons.exists():
                data = [{'reason': r.rejection_reason, 'qty': total_qty} for r in reasons]
            else:
                data = [{'reason': 'Batch rejection: No individual reasons recorded', 'qty': total_qty}]
        else:
            data = [{'reason': r.rejection_reason, 'qty': total_qty} for r in reasons]

        return Response({'success': True, 'reasons': data})
    except Exception as e:
        traceback.print_exc()
        return Response({'success': False, 'error': str(e)}, status=500)


# ═══════════════════════════════════════════════════════════════
# Tray Details for Modal (Completed/Reject table view icons)
# ═══════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_brass_audit_tray_details_for_modal(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'})

    try:
        stock_obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if not stock_obj:
            return Response({'success': False, 'error': 'Lot not found'})

        accepted_trays = []
        rejected_trays = []
        total_accepted_qty = 0

        # Try submission data first
        submission = Brass_Audit_Submission.objects.filter(lot_id=lot_id, is_completed=True).order_by('-created_at').first()
        if submission:
            accept_data = submission.full_accept_data or submission.partial_accept_data or {}
            reject_data = submission.full_reject_data or submission.partial_reject_data or {}
            for t in (accept_data.get('trays') or []):
                qty = int(t.get('qty', 0))
                accepted_trays.append({
                    'tray_id': t.get('tray_id', ''),
                    'tray_quantity': qty,
                    'top_tray': t.get('is_top', False),
                })
                total_accepted_qty += qty
            for t in (reject_data.get('trays') or []):
                rejected_trays.append({
                    'tray_id': t.get('tray_id', ''),
                    'tray_quantity': int(t.get('qty', 0)),
                    'rejection_reason': 'Rejected',
                })
        else:
            # Fallback to BrassAuditTrayId
            trays = BrassAuditTrayId.objects.filter(lot_id=lot_id).order_by('-top_tray', 'tray_quantity')
            for tray in trays:
                if tray.rejected_tray:
                    rejected_trays.append({
                        'tray_id': tray.tray_id,
                        'tray_quantity': tray.tray_quantity or 0,
                        'rejection_reason': 'Rejected',
                    })
                else:
                    accepted_trays.append({
                        'tray_id': tray.tray_id,
                        'tray_quantity': tray.tray_quantity or 0,
                        'top_tray': tray.top_tray,
                    })
                    total_accepted_qty += tray.tray_quantity or 0

            if not trays.exists():
                # Final fallback: TrayId
                tray_objs = TrayId.objects.filter(lot_id=lot_id)
                brass_trays = {t.tray_id: t for t in BrassTrayId.objects.filter(lot_id=lot_id)}
                for tray in tray_objs:
                    brass_tray = brass_trays.get(tray.tray_id)
                    qty = brass_tray.tray_quantity if brass_tray else tray.tray_capacity or 12
                    top_tray = brass_tray.top_tray if brass_tray else False
                    accepted_trays.append({
                        'tray_id': tray.tray_id,
                        'tray_quantity': qty,
                        'top_tray': top_tray,
                    })
                    total_accepted_qty += qty

        # Sort: top tray first, then by qty
        accepted_trays.sort(key=lambda x: (not x.get('top_tray', False), x.get('tray_quantity', 0)))

        for idx, tray in enumerate(accepted_trays, 1):
            tray['s_no'] = idx
            if tray.get('top_tray'):
                tray['s_no_display'] = f"{idx} (Top Tray)"
            else:
                tray['s_no_display'] = str(idx)

        return Response({
            'success': True,
            'lot_id': lot_id,
            'model_no': stock_obj.batch_id.model_no if stock_obj.batch_id else '',
            'lot_qty': total_accepted_qty,
            'accepted_trays': accepted_trays,
            'rejected_trays': rejected_trays,
            'total_accepted_qty': total_accepted_qty,
        })

    except Exception as e:
        return Response({'success': False, 'error': str(e)})


# ═══════════════════════════════════════════════════════════════
# Completed Table - Tray List APIs
# ═══════════════════════════════════════════════════════════════
@method_decorator(csrf_exempt, name='dispatch')
class RejectTableTrayIdListAPIView(APIView):
    def get(self, request):
        lot_id = request.GET.get("lot_id")
        if not lot_id:
            return Response({"success": False, "error": "Lot ID is required"}, status=400)

        try:
            main_trays = TrayId.objects.filter(lot_id=lot_id, brass_rejected_tray=True)
            brass_audit_trays = BrassAuditTrayId.objects.filter(lot_id=lot_id, rejected_tray=True)

            all_trays = []

            for tray in main_trays:
                tray_data = {
                    "tray_id": tray.tray_id,
                    "tray_quantity": tray.tray_quantity,
                    "rejected_tray": True,
                    "delink_tray": getattr(tray, 'delink_tray', False),
                    "source": "main_table",
                }
                all_trays.append(tray_data)

            for tray in brass_audit_trays:
                exists_in_main = any(t['tray_id'] == tray.tray_id for t in all_trays)
                if not exists_in_main:
                    tray_data = {
                        "tray_id": tray.tray_id,
                        "tray_quantity": tray.tray_quantity,
                        "rejected_tray": tray.rejected_tray,
                        "delink_tray": getattr(tray, 'delink_tray', False),
                        "source": "brass_audit_table",
                    }
                    all_trays.append(tray_data)

            is_lot_rejection = False
            lot_rejection_comment = ''

            if not all_trays:
                batch_rejection_store = Brass_Audit_Rejection_ReasonStore.objects.filter(
                    lot_id=lot_id, batch_rejection=True
                ).first()
                if batch_rejection_store:
                    is_lot_rejection = True
                    lot_rejection_comment = batch_rejection_store.lot_rejected_comment or ''

                if not all_trays:
                    trays_qs = TrayId.objects.filter(lot_id=lot_id).exclude(delink_tray=True).order_by('id')
                    for index, tray in enumerate(trays_qs, start=1):
                        qty_val = getattr(tray, 'tray_quantity', None) or getattr(tray, 'tray_capacity', None) or 0
                        all_trays.append({
                            "s_no": index,
                            "tray_id": tray.tray_id,
                            "tray_quantity": qty_val,
                            "rejected_tray": True,
                            "delink_tray": False,
                            "source": "TrayId_fallback",
                        })

            return Response({
                "success": True,
                "trays": all_trays,
                "total_trays": len(all_trays),
                "is_lot_rejection": is_lot_rejection,
                "lot_rejection_comment": lot_rejection_comment,
            })
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)


# ═══════════════════════════════════════════════════════════════
# Barcode Scanner API
# ═══════════════════════════════════════════════════════════════
def generate_new_lot_id():
    from datetime import datetime as dt
    timestamp = dt.now().strftime("%d%m%Y%H%M%S")
    next_seq_no = 1
    # Iterate recent lots to find last sequential (non-UUID) lot ID
    for lot in TotalStockModel.objects.order_by('-id')[:20]:
        if lot.lot_id and lot.lot_id.startswith("LID"):
            try:
                last_seq_no = int(lot.lot_id[-4:])
                next_seq_no = last_seq_no + 1
                break
            except ValueError:
                continue
    seq_no = f"{next_seq_no:04d}"
    return f"LID{timestamp}{seq_no}"


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_lot_id_for_tray(request):
    tray_id = request.GET.get('tray_id', '').strip()
    if not tray_id:
        return JsonResponse({'success': False, 'error': 'tray_id parameter is required'})
    try:
        # Primary: BrassAuditTrayId
        audit_tray = BrassAuditTrayId.objects.filter(tray_id=tray_id).first()
        if audit_tray and audit_tray.lot_id:
            return JsonResponse({'success': True, 'lot_id': str(audit_tray.lot_id), 'source': 'BrassAuditTrayId'})

        # Fallback: BrassTrayId
        brass_tray = BrassTrayId.objects.filter(tray_id=tray_id).first()
        if brass_tray and brass_tray.lot_id:
            return JsonResponse({'success': True, 'lot_id': str(brass_tray.lot_id), 'source': 'BrassTrayId'})

        # Fallback: TrayId
        tray_obj = TrayId.objects.filter(tray_id=tray_id).first()
        if tray_obj and tray_obj.lot_id:
            return JsonResponse({'success': True, 'lot_id': str(tray_obj.lot_id), 'source': 'TrayId'})

        return JsonResponse({'success': False, 'error': f'Tray {tray_id} not found in system'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Database error: {str(e)}'})

