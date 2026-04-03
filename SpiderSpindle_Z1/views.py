from django.shortcuts import render
from django.http import JsonResponse
from django.views.generic import TemplateView
from rest_framework.views import APIView
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework import status
from django.core.paginator import Paginator
from django.db.models import Q, OuterRef, Subquery
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import datetime, timedelta
import pytz
import json

from modelmasterapp.models import *
from Jig_Unloading.models import JigUnloadAfterTable
from .models import SpiderSpindleZ1TrayId


def _get_input_source(jig_unload_obj):
    """Return location names with fallback chain."""
    names = [loc.location_name for loc in jig_unload_obj.location.all()]
    if not names:
        for raw_cid in (jig_unload_obj.combine_lot_ids or []):
            cid = raw_cid.rsplit('-', 1)[-1] if raw_cid and '-' in raw_cid else raw_cid
            if not cid:
                continue
            tsm = TotalStockModel.objects.filter(lot_id=cid).prefetch_related('location').select_related('batch_id__location').first()
            if tsm and tsm.location.exists():
                names = [loc.location_name for loc in tsm.location.all()]
                break
            if tsm and tsm.batch_id and tsm.batch_id.location:
                names = [tsm.batch_id.location.location_name]
                break
    return ', '.join(names)


def _get_model_images(jig_unload_obj):
    """Get model images from plating_stk_no → ModelMaster."""
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
    if not images and jig_unload_obj.combine_lot_ids:
        first_lot_id = jig_unload_obj.combine_lot_ids[0] if jig_unload_obj.combine_lot_ids else None
        if first_lot_id:
            total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
            if total_stock and total_stock.batch_id and total_stock.batch_id.model_stock_no:
                for img in total_stock.batch_id.model_stock_no.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
    return images


@method_decorator(login_required, name='dispatch')
class SSZ1PickTableView(APIView):
    """Spider Spindle Zone 1 Pick Table — IPS colors."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'SpiderSpindle_Z1/ss_z1_pick_table.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False

        # Z1 = IPS colors (jig_unload_zone_1=True)
        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_1=True
        ).values_list('id', flat=True)

        # Show lots that completed Nickel Audit (na_qc_accptance=True) and NOT yet spider-spindle-Z1 completed
        queryset = JigUnloadAfterTable.objects.select_related(
            'version', 'plating_color', 'polish_finish'
        ).prefetch_related('location').filter(
            total_case_qty__gt=0,
            plating_color_id__in=allowed_color_ids,
            na_qc_accptance=True,
            ss_z1_completed=False,
        ).order_by('-created_at', '-lot_id')

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for obj in page_obj.object_list:
            # Get linked tray for this lot (if any)
            linked_tray = SpiderSpindleZ1TrayId.objects.filter(lot_id=obj.lot_id).first()
            images = _get_model_images(obj)

            data = {
                'lot_id': obj.lot_id,
                'unload_lot_id': obj.unload_lot_id,
                'date_time': obj.created_at,
                'plating_color': obj.plating_color.plating_color if obj.plating_color else '',
                'polish_finish': obj.polish_finish.polish_finish if obj.polish_finish else '',
                'version': obj.version.version_name if obj.version else '',
                'location': _get_input_source(obj),
                'tray_type': obj.tray_type or '',
                'total_case_qty': obj.total_case_qty,
                'plating_stk_no': obj.plating_stk_no or '',
                'polishing_stk_no': obj.polish_stk_no or '',
                'category': obj.category or '',
                'last_process_module': obj.last_process_module or 'Nickel Audit',
                'spider_pick_remarks': obj.spider_pick_remarks or '',
                'spider_hold_lot': obj.spider_hold_lot,
                'spider_holding_reason': obj.spider_holding_reason or '',
                'spider_release_lot': obj.spider_release_lot,
                'spider_release_reason': obj.spider_release_reason or '',
                'linked_tray_id': linked_tray.tray_id if linked_tray else '',
                'images': images,
            }
            master_data.append(data)

        return Response({
            'master_data': master_data,
            'page_obj': page_obj,
            'is_admin': is_admin,
        })


@method_decorator(login_required, name='dispatch')
class SSZ1CompletedView(APIView):
    """Spider Spindle Zone 1 Completed Table."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'SpiderSpindle_Z1/ss_z1_completed.html'

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
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            except ValueError:
                from_date = yesterday
                to_date = today
        else:
            from_date = yesterday
            to_date = today

        from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
        to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))

        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_1=True
        ).values_list('id', flat=True)

        queryset = JigUnloadAfterTable.objects.select_related(
            'version', 'plating_color', 'polish_finish'
        ).prefetch_related('location').filter(
            total_case_qty__gt=0,
            plating_color_id__in=allowed_color_ids,
            ss_z1_completed=True,
            ss_z1_completed_at__range=(from_datetime, to_datetime),
        ).order_by('-ss_z1_completed_at', '-lot_id')

        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for obj in page_obj.object_list:
            linked_tray = SpiderSpindleZ1TrayId.objects.filter(lot_id=obj.lot_id).first()
            images = _get_model_images(obj)
            data = {
                'lot_id': obj.lot_id,
                'unload_lot_id': obj.unload_lot_id,
                'date_time': obj.created_at,
                'completed_at': obj.ss_z1_completed_at,
                'plating_color': obj.plating_color.plating_color if obj.plating_color else '',
                'polish_finish': obj.polish_finish.polish_finish if obj.polish_finish else '',
                'version': obj.version.version_name if obj.version else '',
                'location': _get_input_source(obj),
                'tray_type': obj.tray_type or '',
                'total_case_qty': obj.total_case_qty,
                'plating_stk_no': obj.plating_stk_no or '',
                'polishing_stk_no': obj.polish_stk_no or '',
                'category': obj.category or '',
                'linked_tray_id': linked_tray.tray_id if linked_tray else obj.ss_z1_tray_id or '',
                'images': images,
            }
            master_data.append(data)

        return Response({
            'master_data': master_data,
            'page_obj': page_obj,
            'from_date': from_date.strftime('%Y-%m-%d'),
            'to_date': to_date.strftime('%Y-%m-%d'),
        })


class SSZ1AddSpiderAPIView(APIView):
    """Add Spider: auto-fetch tray_id, link it to the lot, mark completed."""

    def post(self, request):
        lot_id = request.data.get('lot_id')
        tray_id = request.data.get('tray_id')

        if not lot_id or not tray_id:
            return Response({'error': 'lot_id and tray_id are required.'}, status=status.HTTP_400_BAD_REQUEST)

        jig_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id, ss_z1_completed=False).first()
        if not jig_obj:
            return Response({'error': 'Lot not found or already completed.'}, status=status.HTTP_404_NOT_FOUND)

        # Check for duplicate tray
        if SpiderSpindleZ1TrayId.objects.filter(lot_id=lot_id, tray_id=tray_id).exists():
            return Response({'error': 'This tray is already linked to this lot.'}, status=status.HTTP_400_BAD_REQUEST)

        # Create tray link
        SpiderSpindleZ1TrayId.objects.create(
            lot_id=lot_id,
            tray_id=tray_id,
            linked_by=request.user if request.user.is_authenticated else None,
        )

        # Mark completed
        jig_obj.ss_z1_completed = True
        jig_obj.ss_z1_tray_id = tray_id
        jig_obj.ss_z1_completed_at = timezone.now()
        jig_obj.ss_z1_completed_by = request.user if request.user.is_authenticated else None
        jig_obj.save(update_fields=[
            'ss_z1_completed', 'ss_z1_tray_id', 'ss_z1_completed_at', 'ss_z1_completed_by'
        ])

        return Response({'success': True, 'message': f'Spider added for lot {lot_id} with tray {tray_id}.'})


class SSZ1DelinkAPIView(APIView):
    """Delink: remove tray link and revert completion."""

    def post(self, request):
        lot_id = request.data.get('lot_id')
        if not lot_id:
            return Response({'error': 'lot_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        jig_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if not jig_obj:
            return Response({'error': 'Lot not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Delete tray link
        SpiderSpindleZ1TrayId.objects.filter(lot_id=lot_id).delete()

        # Revert completion
        jig_obj.ss_z1_completed = False
        jig_obj.ss_z1_tray_id = None
        jig_obj.ss_z1_completed_at = None
        jig_obj.ss_z1_completed_by = None
        jig_obj.save(update_fields=[
            'ss_z1_completed', 'ss_z1_tray_id', 'ss_z1_completed_at', 'ss_z1_completed_by'
        ])

        return Response({'success': True, 'message': f'Spider delinked for lot {lot_id}.'})


class SSZ1SaveRemarksAPIView(APIView):
    """Save spider pick remarks."""

    def post(self, request):
        lot_id = request.data.get('lot_id')
        remarks = request.data.get('remarks', '')
        if not lot_id:
            return Response({'error': 'lot_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        updated = JigUnloadAfterTable.objects.filter(lot_id=lot_id).update(
            spider_pick_remarks=remarks
        )
        if updated:
            return Response({'success': True})
        return Response({'error': 'Lot not found.'}, status=status.HTTP_404_NOT_FOUND)


class SSZ1GetTrayIdAPIView(APIView):
    """Auto-fetch the next available tray ID for a lot."""

    def get(self, request):
        lot_id = request.GET.get('lot_id')
        if not lot_id:
            return Response({'error': 'lot_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        jig_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if not jig_obj:
            return Response({'error': 'Lot not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Look for existing tray IDs from NickelQcTrayId or TrayId tables
        from Nickel_Inspection.models import NickelQcTrayId
        tray = NickelQcTrayId.objects.filter(
            lot_id=lot_id,
            delink_tray=False,
        ).order_by('-id').first()

        tray_id = tray.tray_id if tray else ''
        return Response({
            'tray_id': tray_id,
            'lot_id': lot_id,
            'total_case_qty': jig_obj.total_case_qty,
        })
