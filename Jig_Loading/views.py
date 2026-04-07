from django.views.generic import *
from modelmasterapp.models import *
from .models import Jig, JigLoadingMaster, JigLoadTrayId, JigLoadingManualDraft, JigCompleted, JigLoadingRecord, JigDelinkRecord, ExcessLotRecord, ExcessLotTray
from rest_framework.decorators import *
from django.http import JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from math import ceil
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
import logging
import re
import json
from django.db import transaction
from django.core.paginator import Paginator
from datetime import datetime, timezone as dt_timezone
from django.views.generic import TemplateView
from rest_framework.permissions import IsAuthenticated
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from rest_framework import exceptions
from BrassAudit.models import Brass_Audit_Accepted_TrayID_Store
from BrassAudit.views import brass_audit_get_accepted_tray_scan_data
from modelmasterapp.models import TotalStockModel
from modelmasterapp.models import ModelMasterCreation


# ===== MULTI-MODEL HELPER FUNCTIONS =====
def allocate_trays_for_model(lot_id, model_lot_qty, effective_capacity_remaining, used_tray_ids):
	"""
	Fetch and allocate trays for a specific model.
	
	Args:
		lot_id: Model's lot ID
		model_lot_qty: Target quantity for this model
		effective_capacity_remaining: Remaining capacity in jig
		used_tray_ids: Set of tray IDs already allocated (for deduplication)
	
	Returns:
		{
			'allocated_qty': total allocated,
			'tray_info': [{'tray_id', 'qty'}, ...],
			'allocated_tray_ids': set of allocated tray IDs
		}
	"""
	try:
		allocated_tray_ids = set()
		tray_info = []
		total_allocated = 0
		
		# Fetch trays for this specific lot_id
		qs = JigLoadTrayId.objects.filter(lot_id=lot_id).order_by('id')
		
		for tray_obj in qs:
			tray_id = getattr(tray_obj, 'tray_id', '')
			
			# Skip if already used by another model
			if tray_id in used_tray_ids:
				logging.warning(f"[MULTI_MODEL] Tray {tray_id} skipped (already allocated)")
				continue
			
			tray_qty = int(getattr(tray_obj, 'tray_quantity', 0) or 0)
			
			# Stop if we've met this model's quota
			if total_allocated >= model_lot_qty:
				break
			
			# Check if full tray fits within model's remaining allocation
			if total_allocated + tray_qty <= model_lot_qty:
				# Full tray fits
				tray_info.append({
					'tray_id': tray_id,
					'qty': tray_qty
				})
				allocated_tray_ids.add(tray_id)
				total_allocated += tray_qty
			else:
				# Partial tray: take only what's needed for this model
				remaining_for_model = model_lot_qty - total_allocated
				tray_info.append({
					'tray_id': tray_id,
					'qty': remaining_for_model
				})
				allocated_tray_ids.add(tray_id)
				total_allocated += remaining_for_model
				break
		
		logging.info(f"[MULTI_MODEL] Model {lot_id}: allocated {total_allocated} qty in {len(tray_info)} trays")
		
		return {
			'allocated_qty': total_allocated,
			'tray_info': tray_info,
			'allocated_tray_ids': allocated_tray_ids
		}
	except Exception as e:
		logging.exception(f"[MULTI_MODEL] Error allocating trays for {lot_id}: {e}")
		return {
			'allocated_qty': 0,
			'tray_info': [],
			'allocated_tray_ids': set()
		}


def fetch_model_metadata(lot_id, batch_id):
	"""Fetch model metadata for display (plating_stk_no, etc.)"""
	try:
		logging.info(f'[MULTI_MODEL] fetch_model_metadata called: lot_id={lot_id}, batch_id={batch_id}')
		# Try batch first
		batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first() if batch_id else None
		if batch_obj:
			plating_stk = getattr(batch_obj, 'plating_stk_no', '') or ''
			if not plating_stk:
				# Fall back to model_stock_no FK's plating_stk_no
				model_master = getattr(batch_obj, 'model_stock_no', None)
				if model_master:
					plating_stk = getattr(model_master, 'plating_stk_no', '') or ''
			logging.info(f'[MULTI_MODEL] fetch_model_metadata resolved via batch: {plating_stk}')
			return str(plating_stk) if plating_stk else f"Model-{lot_id}"
		
		# Fallback to lot-based lookup
		stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
		if stock and hasattr(stock, 'batch_id'):
			batch = getattr(stock, 'batch_id', None)
			if batch:
				plating_stk = getattr(batch, 'plating_stk_no', '') or ''
				if not plating_stk:
					model_master = getattr(batch, 'model_stock_no', None)
					if model_master:
						plating_stk = getattr(model_master, 'plating_stk_no', '') or ''
				logging.info(f'[MULTI_MODEL] fetch_model_metadata resolved via lot fallback: {plating_stk}')
				return str(plating_stk) if plating_stk else f"Model-{lot_id}"
		
		return f"Model-{lot_id}"
	except Exception as e:
		logging.exception(f"[MULTI_MODEL] Error fetching metadata for {lot_id}: {e}")
		return f"Model-{lot_id}"


def fetch_model_image_metadata(lot_id, batch_id):
	"""Fetch model image URL and label for a given lot/batch (multi-model UI).
	Returns dict with model_image_url and model_image_label."""
	result = {
		'model_image_url': '/static/assets/images/imagePlaceholder.jpg',
		'model_image_label': ''
	}
	try:
		logging.info(f'[MULTI_MODEL] fetch_model_image_metadata called: lot_id={lot_id}, batch_id={batch_id}')
		mm = None
		batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first() if batch_id else None
		if batch_obj:
			mm = getattr(batch_obj, 'model_stock_no', None)
			# Use batch-level plating_stk_no first (more specific than model master)
			batch_plating = getattr(batch_obj, 'plating_stk_no', '') or ''
			if batch_plating:
				result['model_image_label'] = batch_plating
		if not mm:
			stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
			if stock and hasattr(stock, 'batch_id'):
				b = getattr(stock, 'batch_id', None)
				if b:
					mm = getattr(b, 'model_stock_no', None)
					# Use batch-level plating_stk_no from lot fallback
					batch_plating = getattr(b, 'plating_stk_no', '') or ''
					if batch_plating and not result['model_image_label']:
						result['model_image_label'] = batch_plating
		if mm:
			try:
				if hasattr(mm, 'images'):
					imgs = mm.images.all()
					if imgs and imgs.exists():
						first_img = imgs.first()
						if getattr(first_img, 'master_image', None):
							result['model_image_url'] = first_img.master_image.url
			except Exception:
				pass
			# Only set label from model master if batch didn't provide one
			if not result['model_image_label']:
				result['model_image_label'] = getattr(mm, 'plating_stk_no', '') or getattr(mm, 'model_no', '') or ''
		# Append lot_id suffix for multi-model disambiguation
		if result['model_image_label'] and lot_id:
			result['model_image_label'] = f"{result['model_image_label']} [{lot_id}]"
		logging.info(f'[MULTI_MODEL] fetch_model_image_metadata result: label={result["model_image_label"]}')
	except Exception as e:
		logging.exception(f"[MULTI_MODEL] Error fetching image metadata for {lot_id}: {e}")
	return result


@method_decorator(login_required, name='dispatch')
class JigView(TemplateView):
	"""Minimal Jig view to render the pick table template."""
	template_name = "JigLoading/Jig_Picktable.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		# Populate master_data with Brass Audit accepted lots so Jig Pick shows them
		try:
			from modelmasterapp.models import TotalStockModel
			master_data = []
			# Build base queryset without slicing so we can safely apply exclusions
			from django.db.models import Q as _Q
			base_qs = TotalStockModel.objects.filter(
				_Q(brass_audit_accptance=True) |
				_Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False)
			).select_related('batch_id')
			# Optional exclusion: when JigView is opened to "Add Model", exclude already-selected lots
			# Frontend sends comma-separated lot IDs: exclude_lot_id=LID1,LID2,LID3
			exclude_lot_raw = self.request.GET.get('exclude_lot_id', '')
			primary_lot = self.request.GET.get('primary_lot_id') or self.request.GET.get('primary_lot')
			exclude_list = [x.strip() for x in exclude_lot_raw.split(',') if x.strip()]
			try:
				total_before = base_qs.count()
				logging.info(f"[JIG PICK] Total before exclude: {total_before}")
			except Exception:
				logging.info("[JIG PICK] Unable to count base_qs before exclude")
			if exclude_list:
				base_qs = base_qs.exclude(lot_id__in=exclude_list)
			# Exclude lots already submitted in JigCompleted (they move to Completed table)
			try:
				submitted_records = JigCompleted.objects.filter(draft_status='submitted').only(
					'lot_id', 'is_multi_model', 'multi_model_allocation'
				)
				submitted_lot_ids = set()
				for rec in submitted_records:
					submitted_lot_ids.add(rec.lot_id)
					# For multi-model, also exclude secondary lot IDs from pick table
					if rec.is_multi_model and rec.multi_model_allocation:
						for m in rec.multi_model_allocation:
							mlot = m.get('lot_id', '') if isinstance(m, dict) else ''
							if mlot:
								submitted_lot_ids.add(mlot)
				if submitted_lot_ids:
					base_qs = base_qs.exclude(lot_id__in=list(submitted_lot_ids))
					logging.info(f"[JIG PICK] Excluded {len(submitted_lot_ids)} submitted lots from pick table")
			except Exception:
				logging.exception("[JIG PICK] Failed to exclude submitted lots")
			try:
				final_count = base_qs.count()
				logging.info(f"[JIG PICK] Excluding lots: {exclude_list} (primary: {primary_lot}) -> Final count: {final_count}")
			except Exception:
				logging.info("[JIG PICK] Unable to count base_qs after exclude")
			# Apply ordering and slicing last
			qs = base_qs.order_by('-brass_audit_last_process_date_time')[:200]
			for stock in qs:
				batch = getattr(stock, 'batch_id', None)
				# Try to count accepted trays transferred/stored for this lot
				no_of_trays = 0
				try:
					no_of_trays = Brass_Audit_Accepted_TrayID_Store.objects.filter(lot_id=stock.lot_id, is_save=True).count()
					if no_of_trays == 0:
						no_of_trays = Brass_Audit_Accepted_TrayID_Store.objects.filter(lot_id=stock.lot_id).count()
				except Exception:
					no_of_trays = 0
				data = {
					'batch_id': getattr(batch, 'batch_id', '') if batch else '',
					'stock_lot_id': getattr(stock, 'lot_id', ''),
					'plating_stk_no': getattr(batch, 'plating_stk_no', '') if batch else '',
					'polishing_stk_no': getattr(batch, 'polishing_stk_no', '') if batch else '',
					'plating_color': getattr(batch, 'plating_color', ''),
					'polish_finish': getattr(batch, 'polish_finish', ''),
					'no_of_trays': no_of_trays,
					'display_qty': getattr(stock, 'brass_audit_accepted_qty', None) or getattr(stock, 'brass_audit_physical_qty', None) or getattr(stock, 'total_stock', 0),
					# Prefer jig capacity from JigLoadingMaster (per-model) else fall back to batch.tray_capacity
					'jig_capacity': None,
					'brass_audit_last_process_date_time': getattr(stock, 'brass_audit_last_process_date_time', None),
					'model_stock_no': getattr(batch, 'model_stock_no', None) if batch else None,
					# model images: prefer batch images, else model master images
					'model_images': (getattr(batch, 'images', []) if batch and getattr(batch, 'images', None) else (getattr(batch, 'model_stock_no', None).images if batch and getattr(batch, 'model_stock_no', None) and getattr(batch.model_stock_no, 'images', None) else [])),
					'jig_hold_lot': getattr(stock, 'jig_hold_lot', False),
					'jig_holding_reason': getattr(stock, 'jig_holding_reason', ''),
				}

				# Populate jig_capacity from JigLoadingMaster when available
				try:
					model_obj = getattr(batch, 'model_stock_no', None) if batch else None
					if model_obj:
						master = JigLoadingMaster.objects.filter(model_stock_no=model_obj).first()
						if master and getattr(master, 'jig_capacity', None):
							data['jig_capacity'] = int(master.jig_capacity)
				except Exception:
					pass
				master_data.append(data)
			# Paginate master_data so pick table behaves like other modules (BrassAudit)
			from django.core.paginator import Paginator
			page_number = self.request.GET.get('page', 1)
			paginator = Paginator(master_data, 10)  # 10 records per page
			page_obj = paginator.get_page(page_number)
			# Expose paginated page as `master_data` for template compatibility and `page_obj` for pagination controls
			context['master_data'] = page_obj
			context['page_obj'] = page_obj
			# Keep full list available if other code expects it
			context['master_data_full'] = master_data
			# master_data provided to template; no extra JSON needed

			# ===== ADD HALF-FILLED / EXCESS LOT RECORDS BACK TO PICK TABLE =====
			# When a jig is submitted with excess qty, those trays (stored in half_filled_tray_info)
			# need to appear in the pick table as available for the next cycle.
			try:
				submitted_with_excess = JigCompleted.objects.filter(
					draft_status='submitted',
					half_filled_tray_qty__gt=0
				).only(
					'lot_id', 'batch_id', 'plating_stock_num', 'half_filled_tray_qty',
					'half_filled_tray_info', 'delink_tray_info', 'draft_data', 'tray_type', 'tray_capacity',
					'is_multi_model', 'multi_model_allocation', 'jig_id',
					'nickel_bath_type', 'excess_qty'
				)
				for jc in submitted_with_excess:
					# For multi-model, find which source lot the excess trays belong to
					# by cross-referencing half_filled_tray_info tray_ids with all tray data
					excess_source_lot = jc.lot_id  # default to primary
					excess_model_name = jc.plating_stock_num or ''
					if jc.is_multi_model and jc.half_filled_tray_info:
						hf_tray_ids = {t.get('tray_id') for t in jc.half_filled_tray_info if isinstance(t, dict)}
						# Build lookup from draft_data.tray_data (has ALL trays including pure excess)
						# Fallback to delink_tray_info (only has trays with delink_qty > 0)
						all_tray_map = {}
						if jc.draft_data and isinstance(jc.draft_data, dict):
							for t in jc.draft_data.get('tray_data', []):
								if isinstance(t, dict) and t.get('tray_id'):
									all_tray_map[t['tray_id']] = t
						if not all_tray_map and jc.delink_tray_info:
							for t in jc.delink_tray_info:
								if isinstance(t, dict) and t.get('tray_id'):
									all_tray_map[t['tray_id']] = t
						for hf_tid in hf_tray_ids:
							if hf_tid in all_tray_map:
								src = all_tray_map[hf_tid].get('source_lot_id', '')
								if src:
									excess_source_lot = src
									mc = all_tray_map[hf_tid].get('model_code', '')
									if mc:
										excess_model_name = mc.split(' [')[0]  # strip lot ref
									break
					
					# Look up stock model for the excess source lot
					stock = None
					try:
						stock = TotalStockModel.objects.get(lot_id=excess_source_lot)
					except TotalStockModel.DoesNotExist:
						try:
							stock = TotalStockModel.objects.get(lot_id=jc.lot_id)
						except TotalStockModel.DoesNotExist:
							pass
					batch = getattr(stock, 'batch_id', None) if stock else None
					excess_data = {
						'batch_id': jc.batch_id,
						'stock_lot_id': excess_source_lot,
						'plating_stk_no': excess_model_name if excess_model_name else (jc.plating_stock_num or ''),
						'polishing_stk_no': getattr(batch, 'polishing_stk_no', '') if batch else '',
						'plating_color': getattr(batch, 'plating_color', '') if batch else '',
						'polish_finish': getattr(batch, 'polish_finish', '') if batch else '',
						'no_of_trays': len(jc.half_filled_tray_info) if jc.half_filled_tray_info else 0,
						'display_qty': jc.half_filled_tray_qty or jc.excess_qty or 0,
						'jig_capacity': None,
						'brass_audit_last_process_date_time': jc.updated_at,
						'model_stock_no': getattr(batch, 'model_stock_no', None) if batch else None,
						'model_images': [],
						'jig_hold_lot': False,
						'jig_holding_reason': '',
						'is_excess_lot': True,
						'source_jig_id': jc.jig_id,
						'half_filled_tray_info_json': json.dumps(jc.half_filled_tray_info or []),
					}
					# Populate jig_capacity from JigLoadingMaster
					try:
						model_obj = getattr(batch, 'model_stock_no', None) if batch else None
						if model_obj:
							master = JigLoadingMaster.objects.filter(model_stock_no=model_obj).first()
							if master and getattr(master, 'jig_capacity', None):
								excess_data['jig_capacity'] = int(master.jig_capacity)
					except Exception:
						pass
					master_data.append(excess_data)
				logging.info(f"[JIG PICK] Added {submitted_with_excess.count()} excess lot entries to pick table")
			except Exception:
				logging.exception("[JIG PICK] Failed to add excess lot records to pick table")

			# ===== MARK LOTS WITH ACTIVE DRAFT STATUS =====
			try:
				all_lot_ids = [d.get('stock_lot_id', '') for d in master_data if d.get('stock_lot_id')]
				if all_lot_ids:
					draft_lot_ids = set(
						JigLoadingRecord.objects.filter(
							lot_id__in=all_lot_ids,
							status_flag='DRAFT'
						).values_list('lot_id', flat=True)
					)
					for d in master_data:
						if d.get('stock_lot_id') in draft_lot_ids:
							d['lot_status'] = 'Draft'
							d['lot_status_class'] = 'lot-status-draft'
						else:
							d.setdefault('lot_status', 'Yet to Start')
							d.setdefault('lot_status_class', 'lot-status-yet')
			except Exception:
				logging.exception('[JIG PICK] Failed to compute lot draft statuses')

		except Exception:
			logging.exception('Failed to populate master_data for Jig pick')
		return context



class TrayInfoView(APIView):
	"""Return tray records for a given lot (used by InitJigLoad).
	Simple, read-only view that returns a JSON structure with `trays`.
	"""
	permission_classes = [IsAuthenticated]

	def get(self, request, *args, **kwargs):
		lot_id = request.GET.get('lot_id')
		if not lot_id:
			return Response({'trays': []})

		try:
			qs = JigLoadTrayId.objects.filter(lot_id=lot_id).order_by('id')
			trays = []
			for t in qs:
				trays.append({
					'tray_id': getattr(t, 'tray_id', ''),
					'qty': int(getattr(t, 'tray_quantity', 0) or 0),
					'top_tray': bool(getattr(t, 'top_tray', False) or False),
					'rejected': bool(getattr(t, 'rejected_tray', False) or False),
					'delinked': bool(getattr(t, 'delink_tray', False) or False),
				})
			return Response({'trays': trays})
		except Exception:
			logging.exception('TrayInfoView failed')
			return Response({'trays': []}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InitJigLoad(APIView):
	"""Initialize or return an active JigLoadingManualDraft for the user and lot.

	Returns lot qty, jig_capacity, current draft state and tray list (from TrayInfoView).
	"""
	permission_classes = [IsAuthenticated]

	def get(self, request, *args, **kwargs):
		lot_id = request.GET.get('lot_id')
		batch_id = request.GET.get('batch_id')
		jig_capacity = request.GET.get('jig_capacity')

		if not lot_id or not batch_id:
			raise exceptions.ParseError(detail='lot_id and batch_id are required')

		# determine lot qty similar to JigView
		lot_qty = 0
		try:
			stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
			if stock:
				lot_qty = getattr(stock, 'brass_audit_accepted_qty', None) or getattr(stock, 'brass_audit_physical_qty', None) or getattr(stock, 'total_stock', 0)
		except Exception:
			logging.exception('Failed to fetch lot qty for InitJigLoad')

		try:
			if jig_capacity:
				jig_capacity = int(jig_capacity)
			else:
				# try to fetch jig_capacity from JigLoadingMaster via batch->model mapping
				try:
					batch = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
					model_obj = getattr(batch, 'model_stock_no', None) if batch else None
					if model_obj:
						master = JigLoadingMaster.objects.filter(model_stock_no=model_obj).first()
						if master and getattr(master, 'jig_capacity', None):
							jig_capacity = int(master.jig_capacity)
						else:
							jig_capacity = int(lot_qty or 0)
					else:
						jig_capacity = int(lot_qty or 0)
				except Exception:
					jig_capacity = int(lot_qty or 0)
		except Exception:
			jig_capacity = int(lot_qty or 0)

		# NOTE: Do NOT create or modify a persistent draft here. Per UI flow,
		# the draft must only be saved when the user clicks the Draft button.
		# Try to fetch an existing draft if present, but do not create one.
		draft = JigLoadingManualDraft.objects.filter(batch_id=batch_id, lot_id=lot_id, user=request.user).first()

		# Fetch trays directly from DB (single source of truth)
		try:
			trays = []
			try:
				qs = JigLoadTrayId.objects.filter(lot_id=lot_id).order_by('id')
				for t in qs:
					trays.append({
						'tray_id': getattr(t, 'tray_id', ''),
						'qty': int(getattr(t, 'tray_quantity', 0) or 0),
						'top_tray': bool(getattr(t, 'top_tray', False) or False),
						'rejected': bool(getattr(t, 'rejected_tray', False) or False),
						'delinked': bool(getattr(t, 'delink_tray', False) or False),
					})
			except Exception:
				trays = []
		except Exception:
			trays = []

		# Detect PERFECT_FIT scenario: lot == jig_capacity and no broken hooks
		is_perfect_fit = False
		try:
			is_perfect_fit = (int(lot_qty or 0) == int(jig_capacity or 0)) and (int(getattr(draft, 'broken_hooks', 0) or 0) == 0)
		except Exception:
			is_perfect_fit = False

		# ===== Stable delink calculation (do not depend on tray records for initial screen) =====
		try:
			# determine tray capacity from batch/model if available, else default to 12
			tray_capacity = None
			try:
				batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
				if batch_obj:
					tray_capacity = getattr(batch_obj, 'tray_capacity', None)
					model_obj = getattr(batch_obj, 'model_stock_no', None)
					if not tray_capacity and model_obj:
						tray_capacity = getattr(model_obj, 'tray_capacity', None)
			except Exception:
				tray_capacity = None

			# fallback to any ad-hoc data from brass audit (if available in this scope)
			adata = None
			try:
				if 'adata' in locals() and adata:
					tray_capacity = tray_capacity or int(adata.get('tray_capacity', 0) or 0)
			except Exception:
				pass

			tray_capacity = int(tray_capacity or 12)

			# STRICT DELINK: delink is only the jig fill (cases that will go onto the jig)
			lot_qty_int = int(lot_qty or 0)
			jig_capacity_int = int(jig_capacity or 0)

			# ==========================================================
			# BROKEN HOOKS 
			# ==========================================================

			# Prefer an explicit broken hooks value passed from the frontend (query param)
			# so users can live-preview splits without saving a draft.
			try:
				bh_param = request.GET.get('broken_hooks') or request.GET.get('broken_buildup_hooks')
				if bh_param is not None:
					broken_hooks = int(bh_param or 0)
				else:
					broken_hooks = int(getattr(draft, 'broken_hooks', 0) or 0)
			except Exception:
				broken_hooks = int(getattr(draft, 'broken_hooks', 0) or 0)

			effective_jig_capacity = max(0, jig_capacity_int - broken_hooks)

			delink_qty = min(lot_qty_int, effective_jig_capacity)
			excess_qty = max(0, lot_qty_int - delink_qty)

			logging.info(f"[BH] jig={jig_capacity_int}, broken={broken_hooks}, effective={effective_jig_capacity}")
			logging.info(f"[BH_SPLIT] delink={delink_qty}, excess={excess_qty}")

			# ==========================================================
			# 🔥 PARTIAL TRAY SPLIT (BROKEN HOOKS SAFE LOGIC)
			# ==========================================================


			# Allocate delink trays using LAST-TRAY deduction logic:
			# Only reduce the current overflowing tray instead of recomputing
			# cumulative remaining. This ensures e.g. 12 -> 11 when capacity
			# is exceeded by 1.
			delink_tray_info = []
			excess_tray_info = []
			total = 0
			last_delink_index = -1

			for idx, tray in enumerate(trays):
				tray_id = tray.get('tray_id')
				tray_qty = int(tray.get('qty', 0) or 0)

				# Full tray fits within effective capacity
				if total + tray_qty <= effective_jig_capacity:
					delink_tray_info.append({
						"tray_id": tray_id,
						"qty": tray_qty,
						"top_tray": False,
						"is_partial": False
					})
					total += tray_qty
					last_delink_index = idx
					continue

				# Overflow: only reduce the current tray by the excess amount
				excess = (total + tray_qty) - effective_jig_capacity
				adjusted_qty = tray_qty - excess

				if adjusted_qty > 0:
					delink_tray_info.append({
						"tray_id": tray_id,
						"qty": adjusted_qty,
						"top_tray": True,
						"is_partial": True
					})
					last_delink_index = idx

				# Allocation complete — remaining trays (if any) are excess
				break
			# Log final distribution info for debugging
			try:
				logging.info(f"[DELINK_SPLIT] total allocated: {total}, delink trays: {len(delink_tray_info)}, excess trays: {len(excess_tray_info)}")
			except Exception:
				pass

			# ==========================================================
			# 🔥 EXCESS RENDER - Half filled tray scan
			# ==========================================================
			try:
				# Use tray_capacity determined above (fallbacks already applied)
				_excess_trays = []
				if 'excess_qty' in locals() and excess_qty > 0 and tray_capacity > 0:
					full_trays = excess_qty // tray_capacity
					remainder = excess_qty % tray_capacity

					logging.info(f"[EXCESS_CALC] full={full_trays}, remainder={remainder}")

					tray_counter = 1
					for _ in range(full_trays):
						_excess_trays.append({
							"tray_id": f"JB-A{str(tray_counter).zfill(5)}",
							"qty": tray_capacity,
							"top_tray": False
						})
						tray_counter += 1

					if remainder > 0:
						# top tray displayed first in UI
						_excess_trays.insert(0, {
							"tray_id": f"JB-A{str(tray_counter).zfill(5)}",
							"qty": remainder,
							"top_tray": True
						})

				# attach to local response structure
				response_excess = {
					"excess_qty": int(excess_qty or 0),
					"excess_tray_count": len(_excess_trays),
					"excess_trays": _excess_trays
				}
			except Exception:
				logging.exception('[ERROR] Excess calculation failed')

		except Exception:
			logging.exception('Stable delink calculation failed')

		# Populate model metadata for frontend (best-effort)
		model_image_url = '/static/assets/images/imagePlaceholder.jpg'
		model_image_label = ''
		nickel_bath_type = ''
		tray_type_name = ''
		try:
			mm = None
			batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
			if batch_obj:
				mm = getattr(batch_obj, 'model_stock_no', None) or batch_obj
			# fallback to stock relation
			if not mm and 'stock' in locals() and stock:
				mm = getattr(stock, 'model_master', None) or getattr(stock, 'model', None)
			if mm:
				try:
					if hasattr(mm, 'images'):
						imgs = mm.images.all()
						if imgs and imgs.exists():
							first_img = imgs.first()
							if getattr(first_img, 'master_image', None):
								model_image_url = first_img.master_image.url
				except Exception:
					pass
				model_image_label = getattr(mm, 'plating_stk_no', '') or getattr(mm, 'model_no', '') or ''
				nickel_bath_type = getattr(mm, 'ep_bath_type', '') or getattr(mm, 'nickle_bath_type', '') or ''
				try:
					tt = getattr(mm, 'tray_type', None)
					if tt:
						tray_type_name = getattr(tt, 'tray_type', '') if not isinstance(tt, str) else tt
				except Exception:
					pass
				# Resolve abbreviation to full parent name (e.g. JB→Jumbo, ND→Normal)
				if tray_type_name:
					try:
						from modelmasterapp.models import TrayType as _TrayType
						_tt_obj = _TrayType.objects.filter(tray_type=tray_type_name).first()
						if _tt_obj and _tt_obj.tray_color:
							_parent = _TrayType.objects.filter(
								tray_capacity=_tt_obj.tray_capacity, tray_color__isnull=True
							).first()
							if _parent:
								tray_type_name = _parent.tray_type
					except Exception:
						pass
		except Exception:
			pass

		# ===== MULTI MODEL SUPPORT (NEW - NON BREAKING) =====
		multi_model_flag = request.GET.get('multi_model')
		secondary_lots_raw = request.GET.get('secondary_lots')
		secondary_lots = []
		multi_model_allocation = []

		# Step 1: Parse secondary_lots only when both params are present
		if multi_model_flag and secondary_lots_raw:
			try:
				secondary_lots = json.loads(secondary_lots_raw)
			except Exception:
				logging.warning("[MULTI_MODEL] Invalid secondary_lots JSON — skipping multi-model flow")
				secondary_lots = []

		logging.info(f"[MULTI_MODEL] Flag={multi_model_flag}, Secondary lots count={len(secondary_lots)}")

		# Step 2: Run allocation only when flag is set AND secondary_lots parsed correctly
		if multi_model_flag and secondary_lots:
			# Safe fallbacks: these variables come from the delink try-block above;
			# guard against NameError if that block threw before defining them.
			_mm_eff_cap = locals()['effective_jig_capacity'] if 'effective_jig_capacity' in locals() else max(0, int(jig_capacity or 0))
			_mm_lot_qty = locals()['lot_qty_int'] if 'lot_qty_int' in locals() else int(lot_qty or 0)

			used_tray_ids = set()

			# STEP 1: PRIMARY MODEL ALLOCATION
			try:
				primary_result = allocate_trays_for_model(
					lot_id=lot_id,
					model_lot_qty=_mm_lot_qty,
					effective_capacity_remaining=_mm_eff_cap,
					used_tray_ids=used_tray_ids
				)
				used_tray_ids.update(primary_result['allocated_tray_ids'])
				primary_img = fetch_model_image_metadata(lot_id, batch_id)
				multi_model_allocation.append({
					'model': fetch_model_metadata(lot_id, batch_id),
					'model_name': fetch_model_metadata(lot_id, batch_id),
					'model_role': 'primary',
					'lot_id': lot_id,
					'batch_id': batch_id,
					'sequence': 0,
					'model_index': 1,
					'color_class': 'model-bg-1',
					'allocated_qty': primary_result['allocated_qty'],
					'tray_info': primary_result['tray_info'],
					'model_image_url': primary_img['model_image_url'],
					'model_image_label': primary_img['model_image_label'],
				})
				logging.info(f"[MULTI_MODEL] Primary {lot_id}: {primary_result['allocated_qty']} qty")
			except Exception as e:
				logging.exception(f"[MULTI_MODEL] Primary allocation failed: {e}")

			# STEP 2: SECONDARY MODEL ALLOCATIONS (with capacity enforcement + excess → half-filled)
			mm_half_filled_tray_info = []
			mm_half_filled_tray_qty = 0

			for seq, sec in enumerate(secondary_lots, start=1):
				try:
					sec_lot_id = sec.get('lot_id')
					sec_batch_id = sec.get('batch_id')
					sec_lot_qty = int(sec.get('qty', 0) or 0)

					if not sec_lot_id:
						continue

					# Remaining capacity = effective - already allocated
					capacity_used = sum(m['allocated_qty'] for m in multi_model_allocation)
					capacity_remaining = max(0, _mm_eff_cap - capacity_used)

					# CAPACITY CONTROL: cap allocation to remaining jig capacity
					allowed_qty = min(sec_lot_qty, capacity_remaining)
					excess_for_model = max(0, sec_lot_qty - allowed_qty)
					logging.info(f"[MULTI_MODEL] Secondary {sec_lot_id}: remaining_capacity={capacity_remaining}, sec_lot_qty={sec_lot_qty}, allowed_qty={allowed_qty}, excess_qty={excess_for_model}")

					secondary_result = allocate_trays_for_model(
						lot_id=sec_lot_id,
						model_lot_qty=allowed_qty,
						effective_capacity_remaining=capacity_remaining,
						used_tray_ids=used_tray_ids
					)
					used_tray_ids.update(secondary_result['allocated_tray_ids'])
					sec_img = fetch_model_image_metadata(sec_lot_id, sec_batch_id)
					sec_model_name = fetch_model_metadata(sec_lot_id, sec_batch_id)

					# Check for partial tray: last allocated tray may be partially used
					partial_remainder = 0
					partial_tray_id = None
					if secondary_result['tray_info']:
						last_alloc = secondary_result['tray_info'][-1]
						# Find original tray qty to detect partial usage
						try:
							orig_tray = JigLoadTrayId.objects.filter(lot_id=sec_lot_id, tray_id=last_alloc['tray_id']).first()
							if orig_tray:
								orig_qty = int(getattr(orig_tray, 'tray_quantity', 0) or 0)
								if last_alloc['qty'] < orig_qty:
									partial_remainder = orig_qty - last_alloc['qty']
									partial_tray_id = last_alloc['tray_id']
									logging.info(f"[MULTI_MODEL] Partial tray detected: {partial_tray_id} used={last_alloc['qty']}, remainder={partial_remainder}")
						except Exception:
							pass

					sec_model_idx = seq + 1
					sec_color_idx = ((sec_model_idx - 1) % 5) + 1
					multi_model_allocation.append({
						'model': sec_model_name,
						'model_name': sec_model_name,
						'model_role': 'secondary',
						'lot_id': sec_lot_id,
						'batch_id': sec_batch_id,
						'sequence': seq,
						'model_index': sec_model_idx,
						'color_class': f'model-bg-{sec_color_idx}',
						'allocated_qty': secondary_result['allocated_qty'],
						'tray_info': secondary_result['tray_info'],
						'model_image_url': sec_img['model_image_url'],
						'model_image_label': sec_img['model_image_label'],
					})
					logging.info(f"[MULTI_MODEL] Secondary {sec_lot_id}: allocated {secondary_result['allocated_qty']} qty")

					# EXCESS HANDLING: collect excess trays into half_filled_tray_info
					if excess_for_model > 0:
						excess_remaining = excess_for_model

						# 1) If last allocated tray was partial, its remainder goes to half-filled
						if partial_remainder > 0 and partial_tray_id:
							hf_qty = min(partial_remainder, excess_remaining)
							mm_half_filled_tray_info.append({
								'tray_id': partial_tray_id,
								'qty': hf_qty,
								'model': sec_model_name,
							})
							excess_remaining -= hf_qty
							mm_half_filled_tray_qty += hf_qty
							logging.info(f"[MULTI_MODEL] Half-filled partial tray: {partial_tray_id} qty={hf_qty}")

						# 2) Continue with unallocated trays from same lot for remaining excess
						if excess_remaining > 0:
							try:
								excess_qs = JigLoadTrayId.objects.filter(lot_id=sec_lot_id).order_by('id')
								for tray_obj in excess_qs:
									if excess_remaining <= 0:
										break
									tid = getattr(tray_obj, 'tray_id', '')
									# Skip already allocated trays
									if tid in used_tray_ids:
										continue
									tq = int(getattr(tray_obj, 'tray_quantity', 0) or 0)
									hf_qty = min(tq, excess_remaining)
									mm_half_filled_tray_info.append({
										'tray_id': tid,
										'qty': hf_qty,
										'model': sec_model_name,
									})
									excess_remaining -= hf_qty
									mm_half_filled_tray_qty += hf_qty
									used_tray_ids.add(tid)
									logging.info(f"[MULTI_MODEL] Half-filled excess tray: {tid} qty={hf_qty}")
							except Exception as ex:
								logging.exception(f"[MULTI_MODEL] Excess tray fetch failed for {sec_lot_id}: {ex}")

						logging.info(f"[MULTI_MODEL] Excess for {sec_lot_id}: total half_filled_qty={mm_half_filled_tray_qty}, trays={len(mm_half_filled_tray_info)}")

				except Exception as e:
					logging.exception(f"[MULTI_MODEL] Secondary allocation failed for {sec.get('lot_id')}: {e}")
					continue

			# Validation: no duplicate tray IDs across models
			all_tray_ids = [t['tray_id'] for m in multi_model_allocation for t in m['tray_info']]
			if len(all_tray_ids) != len(set(all_tray_ids)):
				logging.error("[MULTI_MODEL] VALIDATION FAILED: Duplicate tray IDs detected!")
			logging.info(f"[MULTI_MODEL] Final: {len(multi_model_allocation)} models, {len(all_tray_ids)} total trays, half_filled_qty={mm_half_filled_tray_qty}")

		# Build ui_delink_tray_info: flattened tray list from multi_model_allocation for FE binding
		ui_delink_tray_info = []
		if multi_model_flag and multi_model_allocation:
			for m_alloc in multi_model_allocation:
				for t in m_alloc.get('tray_info', []):
					ui_delink_tray_info.append({
						'tray_id': t.get('tray_id', ''),
						'qty': t.get('qty', 0),
						'top_tray': False,
						'is_partial': False,
						'model': m_alloc.get('model', ''),
						'model_role': m_alloc.get('model_role', ''),
						'lot_id': m_alloc.get('lot_id', ''),
						'batch_id': m_alloc.get('batch_id', ''),
					})
			logging.info(f"[MULTI_MODEL] ui_delink_tray_info: {len(ui_delink_tray_info)} trays flattened")

		# ===== UNIFIED HALF-FILLED FIX (SINGLE + MULTI + BH SAFE) =====
		try:
			# Ensure vars are always defined before any check
			if 'mm_half_filled_tray_info' not in locals():
				mm_half_filled_tray_info = []
			if 'mm_half_filled_tray_qty' not in locals():
				mm_half_filled_tray_qty = 0

			# Step 1: TOTAL REQUESTED quantity — single source of truth
			# Use REQUESTED qty (not allocated) so BH-reduced capacity triggers overflow correctly
			if multi_model_flag and secondary_lots:
				_hf_total_qty = int(lot_qty or 0) + sum(int(s.get('qty', 0) or 0) for s in secondary_lots)
				logging.info(f"[HALF FIX] MULTI total_qty (requested): {_hf_total_qty}")
			else:
				_hf_total_qty = int(lot_qty or 0)
				logging.info(f"[HALF FIX] SINGLE total_qty: {_hf_total_qty}")

			# Step 2: Effective capacity — BH-aware (single source of truth)
			_hf_cap = effective_jig_capacity if 'effective_jig_capacity' in locals() else int(jig_capacity or 0)

			# Step 3: Only initialise if overflow AND secondary loop did not already populate
			if _hf_total_qty > _hf_cap and not mm_half_filled_tray_info:
				_hf_overflow = _hf_total_qty - _hf_cap
				logging.info(f"[HALF FIX] Overflow={_hf_overflow}, creating half-filled trays")
				_hf_tc = int(tray_capacity if tray_capacity else 12)
				mm_half_filled_tray_info = []
				_hf_rem = _hf_overflow
				while _hf_rem > 0:
					_hf_fill = min(_hf_tc, _hf_rem)
					mm_half_filled_tray_info.append({"tray_id": None, "qty": _hf_fill})
					_hf_rem -= _hf_fill
				mm_half_filled_tray_qty = sum(t['qty'] for t in mm_half_filled_tray_info)
				logging.info(f"[HALF FIX] CREATED: {mm_half_filled_tray_info}")
			else:
				logging.info(f"[HALF FIX] No overflow or already populated — skipping (total={_hf_total_qty}, cap={_hf_cap}, existing={len(mm_half_filled_tray_info)})")

		except Exception as _hf_err:
			logging.exception(f"[HALF FIX ERROR]: {_hf_err}")
			if 'mm_half_filled_tray_info' not in locals():
				mm_half_filled_tray_info = []
			if 'mm_half_filled_tray_qty' not in locals():
				mm_half_filled_tray_qty = 0

		# ===== CALCULATE SERVER-AUTHORITATIVE LOADED_CASES_QTY AND EMPTY_HOOKS ==
		loaded_cases_qty = 0
		# 🔥 FIX: Use the broken_hooks value calculated earlier (from GET param OR draft)
		broken_hooks_int = int(broken_hooks or 0)  # This already includes GET param logic
		jig_capacity_int = int(jig_capacity or 0)
		lot_qty_int = int(lot_qty or 0)

		# 🔥 MULTI-MODEL CUMULATIVE: aggregate total qty from all models
		if multi_model_flag and multi_model_allocation:
			total_multi_model_qty = sum(m.get('allocated_qty', 0) for m in multi_model_allocation)
			logging.info(f"[MULTI_MODEL] Incoming Models: {len(multi_model_allocation)}")
			logging.info(f"[MULTI_MODEL] Computed Total: {total_multi_model_qty}")
		else:
			total_multi_model_qty = lot_qty_int

		# 🔥 FIX: NO auto-loading on initial load. Only use persisted draft value if exists.
		# All initial states (including perfect fit 144/144) start with loaded_cases_qty = 0
		if draft and getattr(draft, 'loaded_cases_qty', None):
			# Use persisted draft value (user already scanned)
			loaded_cases_qty = int(draft.loaded_cases_qty)
		else:
			# Initial state: no auto-loading (user hasn't scanned yet)
			loaded_cases_qty = 0

		# empty_hooks calculation
		effective_capacity = max(0, jig_capacity_int - broken_hooks_int)

		if loaded_cases_qty > 0:
			# AFTER SCAN: use scan-based calculation
			empty_hooks = max(0, effective_capacity - loaded_cases_qty)
		else:
			# BEFORE SCAN: use cumulative lot-based calculation (multi-model aware)
			if total_multi_model_qty < effective_capacity:
				empty_hooks = effective_capacity - total_multi_model_qty
			else:
				empty_hooks = 0

		logging.info(f"[BACKEND_STATE] lot={lot_qty_int}, cap={jig_capacity_int}, broken={broken_hooks_int}, loaded={loaded_cases_qty}, empty={empty_hooks}, total_multi_model_qty={total_multi_model_qty}")
		if multi_model_flag and multi_model_allocation:
			logging.info(f"[MULTI_MODEL] Empty Hooks: {empty_hooks}")

		# Detect BH preview mode: when broken_hooks is explicitly passed via query param,
		# ALWAYS use freshly computed delink_tray_info (not stale draft data)
		bh_preview = request.GET.get('broken_hooks') is not None or request.GET.get('broken_buildup_hooks') is not None

		# Build a non-persistent draft dict to return to the frontend
		resp_draft = {
			'batch_id': batch_id,
			'lot_id': lot_id,
			'original_lot_qty': int(lot_qty or 0),
			'jig_capacity': jig_capacity,
			'effective_capacity': int(max(0, jig_capacity_int - broken_hooks_int) or 0),
			'loaded_cases_qty': int(draft.loaded_cases_qty) if draft else 0,
			'delink_tray_info': delink_tray_info if bh_preview else (draft.delink_tray_info if draft and draft.delink_tray_info else delink_tray_info),
			'delink_tray_qty': int(delink_qty or 0) if bh_preview else (int(draft.delink_tray_qty) if draft else int(delink_qty or 0)),
			'excess_qty': int(excess_qty or 0) if 'excess_qty' in locals() else 0,
			# model metadata
			'model_image_url': model_image_url,
			'model_image_label': model_image_label,
			'plating_stock_num': model_image_label,
			'nickel_bath_type': nickel_bath_type,
			'tray_type': tray_type_name,
			'is_multi_model': True if multi_model_flag else False,
			'total_multi_model_qty': int(total_multi_model_qty or 0),
			'draft_data': {
				'primary_lot': lot_id,
				'secondary_lots': secondary_lots
			},
			'secondary_lots': secondary_lots,
		}

		return Response({
			'draft': resp_draft,
			'trays': trays,
			'lot_qty': int(lot_qty or 0),
			'original_capacity': int(jig_capacity_int or 0),
			'effective_capacity': int(max(0, jig_capacity_int - broken_hooks_int) or 0),
			'loaded_cases_qty': int(loaded_cases_qty or 0),
			'broken_hooks': int(broken_hooks_int or 0),
			'empty_hooks': int(empty_hooks or 0),
			'excess_qty': int(excess_qty or 0) if 'excess_qty' in locals() else 0,
			'excess_info': response_excess if 'response_excess' in locals() else {"excess_qty": 0, "excess_tray_count": 0, "excess_trays": []},
			# Top-level delink_tray_info for refreshTrayCalculation (frontend)
			'delink_tray_info': delink_tray_info if bh_preview else (draft.delink_tray_info if draft and draft.delink_tray_info else delink_tray_info),
			# duplicate top-level metadata for compatibility
			'model_image_url': model_image_url,
			'model_image_label': model_image_label,
			'nickel_bath_type': nickel_bath_type,
			'tray_type': tray_type_name,
			'secondary_lots': secondary_lots,
			'scenario': 'PERFECT_FIT' if is_perfect_fit else '',
			'is_multi_model': True if multi_model_flag else False,
			'total_multi_model_qty': int(total_multi_model_qty or 0),
			# ===== NEW: MULTI-MODEL ALLOCATION (when multi_model flag is set) =====
			'multi_model_allocation': multi_model_allocation if multi_model_flag else [],
			# Flattened tray list from all models for FE delink binding in multi-model mode
			'ui_delink_tray_info': ui_delink_tray_info if ui_delink_tray_info else [],
			'half_filled_tray_info': mm_half_filled_tray_info if 'mm_half_filled_tray_info' in locals() else [],
			'half_filled_tray_qty': mm_half_filled_tray_qty if 'mm_half_filled_tray_qty' in locals() else 0,
		})



class ScanTray(APIView):
	"""Handle scanning (delinking) a tray for Jig Loading.

	Expected POST JSON: { lot_id, batch_id, tray_id }
	"""
	permission_classes = [IsAuthenticated]

	def post(self, request, *args, **kwargs):
		payload = request.data
		lot_id = payload.get('lot_id')
		batch_id = payload.get('batch_id')
		tray_id = payload.get('tray_id')

		if not lot_id or not batch_id or not tray_id:
			raise exceptions.ParseError(detail='lot_id, batch_id and tray_id are required')

		# Validation-only scan: do not create or modify drafts here. Return tray qty.
		try:
			tray = JigLoadTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).first()
			if not tray:
				return Response({'status': 'error', 'message': 'Invalid tray or wrong lot'}, status=status.HTTP_400_BAD_REQUEST)
		except Exception:
			logging.exception('Error fetching tray')
			return Response({'status': 'error', 'message': 'Tray fetch error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

		tray_qty = int(tray.tray_quantity or 0)

		print(f"Tray validated: {tray_id} (lot: {lot_id}) qty:{tray_qty}")

		return Response({'status': 'success', 'tray_id': tray_id, 'tray_qty': tray_qty})


# =============================================================================
# CORE COMPUTATION ENGINE (SINGLE SOURCE OF TRUTH)
# =============================================================================

def compute_jig_loading(trays, jig_capacity, broken_hooks, tray_capacity=12):
	"""
	Core computation engine for Jig Loading. Single source of truth.
	Called by: JigLoadInitAPI, JigLoadUpdateAPI, JigLoadSubmitAPI.

	BH Logic: Apply broken hooks from LAST tray → FIRST.
	- If tray qty becomes 0 → REMOVE tray from output
	- If partial → reduce qty
	- Mandatory validation: total_before - total_after == broken_hooks

	Args:
		trays: list of dicts [{'tray_id': str, 'qty': int}, ...]
		jig_capacity: total jig capacity (int)
		broken_hooks: number of broken/buildup hooks (int)
		tray_capacity: default tray capacity for excess allocation (int)

	Returns:
		dict with effective_capacity, loaded_cases_qty, empty_hooks,
		delink_tray_info, excess_info, validation, etc.
	"""
	jig_capacity = int(jig_capacity or 0)
	broken_hooks = max(0, int(broken_hooks or 0))
	tray_capacity = int(tray_capacity or 12)
	effective_capacity = max(0, jig_capacity - broken_hooks)

	total_lot_qty = sum(int(t.get('qty', 0) or 0) for t in trays)

	validation_errors = []
	if broken_hooks < 0:
		validation_errors.append('Broken hooks cannot be negative')
	if broken_hooks > jig_capacity:
		validation_errors.append('Broken hooks exceeds jig capacity')

	# Step 1: Build working list of trays (allocate up to jig_capacity, first→last)
	# Use jig_capacity (NOT effective_capacity) because BH is applied in Step 2
	working_trays = []
	total_allocated = 0
	for tray in trays:
		tray_id = tray.get('tray_id', '')
		tray_qty = int(tray.get('qty', 0) or 0)
		if tray_qty <= 0:
			continue  # Skip zero-qty trays from source
		if total_allocated >= jig_capacity:
			break
		if total_allocated + tray_qty <= jig_capacity:
			working_trays.append({
				'tray_id': tray_id,
				'qty': tray_qty,
				'original_qty': tray_qty,
				'allocated_qty_before_bh': tray_qty,
				'capacity_split_excess_qty': 0,
				'is_capacity_split': False,
				'top_tray': bool(tray.get('top_tray', False)),
			})
			total_allocated += tray_qty
		else:
			remaining = jig_capacity - total_allocated
			working_trays.append({
				'tray_id': tray_id,
				'qty': remaining,
				'original_qty': tray_qty,
				'allocated_qty_before_bh': remaining,
				'capacity_split_excess_qty': max(0, tray_qty - remaining),
				'is_capacity_split': remaining < tray_qty,
				'top_tray': bool(tray.get('top_tray', False)),
			})
			total_allocated += remaining

	# Step 2: Apply BH deduction from LAST tray → FIRST (strict tray removal)
	total_before_bh = sum(t['qty'] for t in working_trays)
	bh_remaining = broken_hooks
	if bh_remaining > 0 and working_trays:
		# Walk backwards through trays
		i = len(working_trays) - 1
		while i >= 0 and bh_remaining > 0:
			tray = working_trays[i]
			if tray['qty'] <= bh_remaining:
				# Full tray removed
				bh_remaining -= tray['qty']
				tray['qty'] = 0
			else:
				# Partial reduction
				tray['qty'] -= bh_remaining
				bh_remaining = 0
			i -= 1

	# Step 3: Remove zero-qty trays (CRITICAL — no empty trays in output)
	delink_tray_info = []
	for t in working_trays:
		if t['qty'] > 0:
			is_partial = t['qty'] < t['original_qty']
			is_bh_partial = t['qty'] < t.get('allocated_qty_before_bh', t['qty'])
			delink_tray_info.append({
				'tray_id': t['tray_id'],
				'original_qty': t['original_qty'],
				'excluded_qty': t['original_qty'] - t['qty'],
				'effective_qty': t['qty'],
				'qty': t['qty'],
				'status': 'partial' if is_partial else 'loaded',
				'top_tray': bool(t.get('top_tray', False)),  # Preserve DB flag (actual top tray)
				'is_partial': is_partial,  # Qty differs from original (due to capacity/BH)
				'is_capacity_split': bool(t.get('is_capacity_split', False)),
				'is_broken_hooks_partial': is_bh_partial,
			})

	# Step 4: Integrity validation
	total_after_bh = sum(t['qty'] for t in delink_tray_info)
	loaded_cases_qty = total_after_bh
	if broken_hooks > 0:
		expected_diff = min(broken_hooks, total_before_bh)
		actual_diff = total_before_bh - total_after_bh
		if actual_diff != expected_diff:
			validation_errors.append(
				f'BH integrity check failed: expected removal={expected_diff}, actual={actual_diff}'
			)
			logging.error(f'[BH_INTEGRITY] MISMATCH: before={total_before_bh}, after={total_after_bh}, '
						  f'bh={broken_hooks}, expected_diff={expected_diff}, actual_diff={actual_diff}')

	empty_hooks = max(0, effective_capacity - loaded_cases_qty)
	excess_qty = max(0, total_lot_qty - effective_capacity)

	# ===== TRACK REAL EXCESS TRAYS (trays not allocated to delink) =====
	# These are the actual trays from the lot that overflow the jig capacity.
	# We track them with their real tray IDs for the half-filled section.
	allocated_tray_ids = set(t['tray_id'] for t in working_trays)
	real_excess_trays = []
	if excess_qty > 0:
		excess_remaining = excess_qty
		for tray in trays:
			if excess_remaining <= 0:
				break
			tray_id = tray.get('tray_id', '')
			tray_qty = int(tray.get('qty', 0) or 0)
			if tray_qty <= 0:
				continue
			if tray_id in allocated_tray_ids:
				# Check if this tray was partially allocated (split tray)
				allocated = next((t for t in working_trays if t['tray_id'] == tray_id), None)
				if allocated and allocated.get('capacity_split_excess_qty', 0) > 0:
					# Only the capacity-overflow remainder belongs in half-filled.
					# Broken-hooks reductions must not be treated as excess trays.
					split_excess = int(allocated.get('capacity_split_excess_qty', 0) or 0)
					fill = min(split_excess, excess_remaining)
					if fill > 0:
						real_excess_trays.append({'tray_id': tray_id, 'qty': fill, 'top_tray': bool(tray.get('top_tray', False)), 'source_lot_id': tray.get('source_lot_id', '')})
						excess_remaining -= fill
				continue
			# Tray not allocated at all → fully excess
			fill = min(tray_qty, excess_remaining)
			real_excess_trays.append({'tray_id': tray_id, 'qty': fill, 'top_tray': bool(tray.get('top_tray', False)), 'source_lot_id': tray.get('source_lot_id', '')})
			excess_remaining -= fill

	# Build excess tray info (uses real_excess_trays)
	excess_trays = list(real_excess_trays) if real_excess_trays else []

	# ===== ALL TRAYS: every input tray with delink/excess qty split =====
	# Algorithm: walk through ALL input trays, distribute up to effective_capacity as delink,
	# the rest as excess. sum(delink_qty) = effective_capacity (when lot > capacity).
	# sum(excess_qty) = total_lot_qty - effective_capacity. No tray is hidden.
	all_trays = []
	cap_remaining = effective_capacity
	for tray in trays:
		t_id = tray.get('tray_id', '')
		t_qty = int(tray.get('qty', 0) or 0)
		if t_qty <= 0:
			continue
		if cap_remaining <= 0:
			d_qty = 0
			e_qty = t_qty
		elif t_qty <= cap_remaining:
			d_qty = t_qty
			e_qty = 0
			cap_remaining -= t_qty
		else:
			d_qty = cap_remaining
			e_qty = t_qty - cap_remaining
			cap_remaining = 0
		all_trays.append({
			'tray_id': t_id,
			'original_qty': t_qty,
			'delink_qty': d_qty,
			'excess_qty': e_qty,
			'top_tray': bool(tray.get('top_tray', False)),
			'source_lot_id': tray.get('source_lot_id', ''),
		})

	# ===== HALF-FILLED: STRUCTURE ONLY — no tray IDs during scanning =====
	# STRICT RULE: tray_ids are NULL until delink scan is complete.
	# Only slots (qty, type, editable) are returned here.
	# Tray ID assignment happens in the API layer after delink completion.
	half_filled_tray_info = {
		'exists': False,
		'total_qty': 0,
		'tray_count': 0,
		'slots': [],
		'tray_ids': None,  # 🚫 MUST BE NULL until delink scan complete
	}
	half_filled_tray_qty = 0
	if excess_qty > 0 and delink_tray_info:
		# Find partial delink tray: capacity-split OR last tray with qty < tray_capacity
		partial_delink = None
		for dt in delink_tray_info:
			if dt.get('is_capacity_split', False):
				partial_delink = dt
				# Take the LAST partial one (closest to the capacity boundary)

		# Also check if last delink tray is naturally partial (qty < tray_capacity)
		if not partial_delink and delink_tray_info:
			last_delink = delink_tray_info[-1]
			if last_delink['qty'] < tray_capacity:
				partial_delink = last_delink

		slots = []
		slot_index = 1

		if partial_delink:
			# Top half-filled slot: partial (will be auto-linked AFTER delink scan complete)
			top_hf_qty = min(tray_capacity - partial_delink['qty'], excess_qty)
			if top_hf_qty > 0:
				slots.append({
					'index': slot_index,
					'qty': top_hf_qty,
					'type': 'partial',
					'editable': True,
				})
				slot_index += 1
				half_filled_tray_qty += top_hf_qty
				excess_qty_remaining = excess_qty - top_hf_qty
			else:
				excess_qty_remaining = excess_qty
		else:
			excess_qty_remaining = excess_qty

		# Remaining half-filled slots: distribute into tray_capacity-sized chunks
		if excess_qty_remaining > 0 and tray_capacity > 0:
			remaining = excess_qty_remaining
			while remaining > 0:
				fill = min(tray_capacity, remaining)
				slots.append({
					'index': slot_index,
					'qty': fill,
					'type': 'auto',
					'editable': False,
				})
				slot_index += 1
				remaining -= fill
				half_filled_tray_qty += fill

		half_filled_tray_info = {
			'exists': len(slots) > 0,
			'total_qty': half_filled_tray_qty,
			'tray_count': len(slots),
			'slots': slots,
			'tray_ids': None,  # Assigned by API when delink_completed
		}

	result = {
		'effective_capacity': effective_capacity,
		'loaded_cases_qty': loaded_cases_qty,
		'empty_hooks': empty_hooks,
		'excess_qty': max(0, total_lot_qty - effective_capacity),
		'total_qty': total_lot_qty,
		'tray_count': len(delink_tray_info),
		'delink_tray_info': delink_tray_info,
		'delink_tray_qty': loaded_cases_qty,
		'all_trays': all_trays,
		'excess_info': {'excess_qty': max(0, total_lot_qty - effective_capacity), 'excess_tray_count': len(excess_trays), 'excess_trays': excess_trays},
		'half_filled_tray_info': half_filled_tray_info,
		'half_filled_tray_qty': half_filled_tray_qty,
		'validation': {'is_overloaded': total_lot_qty > effective_capacity, 'errors': validation_errors}
	}

	logging.info(json.dumps({
		'event': 'JIG_LOAD_COMPUTE',
		'input': {'jig_capacity': jig_capacity, 'broken_hooks': broken_hooks, 'tray_count': len(trays), 'total_lot_qty': total_lot_qty},
		'effective_capacity': effective_capacity,
		'loaded_cases': loaded_cases_qty,
		'empty_hooks': empty_hooks,
		'tray_count_output': len(delink_tray_info),
		'bh_integrity': f'{total_before_bh}-{total_after_bh}={total_before_bh - total_after_bh} (expected {broken_hooks})'
	}))

	return result


def assign_half_filled_tray_ids(half_filled, delink_tray_info, excess_trays, tray_capacity=12):
	"""Assign real tray IDs to half-filled slots. Called ONLY when delink scan is complete.

	Args:
		half_filled: dict with 'exists', 'slots', 'tray_ids' from compute_jig_loading
		delink_tray_info: list from compute_jig_loading
		excess_trays: list from compute_jig_loading excess_info.excess_trays
		tray_capacity: default tray capacity

	Returns:
		updated half_filled dict with tray_ids populated
	"""
	if not half_filled or not half_filled.get('exists'):
		return half_filled

	# Find partial delink tray: capacity-split OR last tray with qty < tray_capacity
	partial_delink = None
	for dt in delink_tray_info:
		if dt.get('is_capacity_split', False):
			partial_delink = dt

	# Also check if last delink tray is naturally partial (qty < tray_capacity)
	if not partial_delink and delink_tray_info:
		last_delink = delink_tray_info[-1]
		if last_delink['qty'] < tray_capacity:
			partial_delink = last_delink

	tray_ids = []
	linked_tray_id = partial_delink['tray_id'] if partial_delink else None
	excess_idx = 0

	for slot in half_filled.get('slots', []):
		if slot.get('type') == 'partial' and partial_delink:
			# Auto-link: use the partial delink tray's ID
			tray_ids.append({
				'tray_id': partial_delink['tray_id'],
				'qty': slot['qty'],
				'auto_linked': True,
				'linked_to': partial_delink['tray_id'],
				'is_top_half_filled': True,
				'editable': True,
			})
		else:
			# Skip excess tray that matches the auto-linked partial tray (avoid double use)
			while excess_idx < len(excess_trays) and excess_trays[excess_idx].get('tray_id') == linked_tray_id:
				linked_tray_id = None  # only skip once
				excess_idx += 1

			if excess_idx < len(excess_trays):
				et = excess_trays[excess_idx]
				tray_ids.append({
					'tray_id': et['tray_id'],
					'qty': slot['qty'],
					'auto_linked': False,
					'linked_to': None,
					'is_top_half_filled': False,
					'editable': False,
				})
				excess_idx += 1
			else:
				tray_ids.append({
					'tray_id': None,
					'qty': slot['qty'],
					'auto_linked': False,
					'linked_to': None,
					'is_top_half_filled': False,
					'editable': False,
				})

	half_filled['tray_ids'] = tray_ids
	return half_filled


def _half_filled_list_to_dict(hf_list, total_qty=0):
	"""Convert old half_filled list format (from multi-model) to new dict format.
	Preserves tray_ids from source entries when available (for BH recalc)."""
	if not hf_list:
		return {'exists': False, 'total_qty': 0, 'tray_count': 0, 'slots': [], 'tray_ids': None}
	slots = []
	tray_ids_list = []
	has_any_tray_id = False
	for i, hf in enumerate(hf_list):
		qty_val = int(hf.get('qty', 0) or 0)
		slots.append({
			'index': i + 1,
			'qty': qty_val,
			'type': 'partial' if i == 0 else 'auto',
			'editable': i == 0,
		})
		tid = hf.get('tray_id')
		if tid:
			has_any_tray_id = True
			tray_ids_list.append({
				'tray_id': tid, 'qty': qty_val,
				'auto_linked': i == 0, 'linked_to': tid if i == 0 else None,
				'is_top_half_filled': i == 0, 'editable': i == 0,
				'model': hf.get('model', ''),
			})
		else:
			tray_ids_list.append({
				'tray_id': None, 'qty': qty_val,
				'auto_linked': False, 'linked_to': None,
				'is_top_half_filled': i == 0, 'editable': i == 0,
				'model': hf.get('model', ''),
			})
	total = total_qty or sum(s['qty'] for s in slots)
	has_tray_ids = has_any_tray_id and len(tray_ids_list) == len(slots)
	return {
		'exists': True, 'total_qty': total, 'tray_count': len(slots), 'slots': slots,
		'tray_ids': tray_ids_list if has_tray_ids else None,
	}


def build_unified_tray_table(computed, lot_qty, jig_capacity, model_code='', tray_capacity=12):
	"""Build a unified tray table combining delink + excess trays into one flat list.

	Each row represents a tray or a split portion of a tray. The frontend renders
	this as a single <table> — no separate delink / excess sections needed.

	Args:
		computed: dict returned by compute_jig_loading()
		lot_qty: total lot quantity
		jig_capacity: original jig capacity (before BH)
		model_code: display label for the model (e.g. '1805NAD02')
		tray_capacity: default tray capacity

	Returns:
		list of row dicts, each with:
			sno, model_code, tray_id, original_qty, scan_tray_id, scan_label,
			delink_qty, status, row_type, is_scannable, is_checkbox_enabled
	"""
	delink_tray_info = computed.get('delink_tray_info', [])
	excess_info = computed.get('excess_info', {})
	excess_trays = excess_info.get('excess_trays', [])
	excess_qty = int(excess_info.get('excess_qty', 0) or 0)
	effective_capacity = int(computed.get('effective_capacity', 0) or 0)

	rows = []
	sno = 1

	# --- DELINK ROWS (trays allocated to the jig) ---
	for dt in delink_tray_info:
		tray_id = dt.get('tray_id', '')
		qty = int(dt.get('qty', 0) or 0)
		original_qty = int(dt.get('original_qty', qty) or qty)
		is_capacity_split = bool(dt.get('is_capacity_split', False))

		if is_capacity_split:
			# This tray is split: delink portion + excess portion
			split_excess = int(dt.get('capacity_split_excess_qty', 0) or (original_qty - qty))
			# Row 1: delink portion
			rows.append({
				'sno': sno,
				'model_code': model_code,
				'tray_id': tray_id,
				'original_qty': original_qty,
				'scan_tray_id': tray_id,
				'delink_qty': qty,
				'status': 'Partially Qty - Delink',
				'row_type': 'delink_partial',
				'is_scannable': True,
				'is_checkbox_enabled': True,
			})
			sno += 1
			# Row 2: excess portion of the SAME tray (mandate scan)
			# Calculate total excess for the entire lot
			total_excess_qty = excess_qty
			rows.append({
				'sno': '',  # sub-row, no separate serial number
				'model_code': '',
				'tray_id': '',
				'original_qty': '',
				'scan_tray_id': tray_id,
				'scan_label': '(Mandate Scan)',
				'delink_qty': split_excess,
				'status': f'Partial Tray - Excess Lot Tray Scan = {total_excess_qty} (new lot in jig pick table)',
				'row_type': 'partial_excess',
				'is_scannable': True,
				'is_checkbox_enabled': False,
			})
		else:
			# Fully delinked tray
			rows.append({
				'sno': sno,
				'model_code': model_code,
				'tray_id': tray_id,
				'original_qty': original_qty,
				'scan_tray_id': tray_id,
				'delink_qty': qty,
				'status': 'Fully Delinked',
				'row_type': 'delink_full',
				'is_scannable': True,
				'is_checkbox_enabled': True,
			})
			sno += 1

	# --- EXCESS ROWS (trays beyond jig capacity) ---
	for et in excess_trays:
		et_tray_id = et.get('tray_id', '')
		et_qty = int(et.get('qty', 0) or 0)

		# Skip excess entries that are capacity-split (already handled above)
		already_in_delink = any(
			r.get('tray_id') == et_tray_id and r.get('row_type') in ('delink_partial', 'partial_excess')
			for r in rows
		)
		if already_in_delink:
			continue

		rows.append({
			'sno': sno,
			'model_code': model_code,
			'tray_id': et_tray_id,
			'original_qty': et_qty,
			'scan_tray_id': et_tray_id,
			'scan_label': '',
			'delink_qty': et_qty,
			'status': 'Excess Lot Tray Scan',
			'row_type': 'excess',
			'is_scannable': True,
			'is_checkbox_enabled': True,
		})
		sno += 1

	logging.info(json.dumps({
		'event': 'UNIFIED_TRAY_TABLE_BUILT',
		'total_rows': len(rows),
		'delink_rows': sum(1 for r in rows if r['row_type'].startswith('delink')),
		'excess_rows': sum(1 for r in rows if r['row_type'] in ('excess', 'partial_excess')),
		'lot_qty': lot_qty,
		'jig_capacity': jig_capacity,
		'effective_capacity': effective_capacity,
	}))

	return rows


def build_split_panel_data(computed, lot_qty, jig_capacity, model_code='', tray_capacity=12):
	"""Build split panel data for the 2-column delink + excess UI.

	Uses computed['all_trays'] so ALL trays are shown in the delink panel
	with original_qty, delink_qty, excess_qty.  No tray is hidden.

	LEFT column = delink_panel (ALL trays with qty split)
	RIGHT column = excess_panel (trays with excess_qty > 0)
	"""
	all_trays = computed.get('all_trays', [])
	excess_info = computed.get('excess_info', {})
	excess_qty = int(excess_info.get('excess_qty', 0) or 0)
	effective_capacity = int(computed.get('effective_capacity', 0) or 0)

	# ===== LEFT: DELINK PANEL (ALL TRAYS) =====
	delink_rows = []
	sno = 1
	split_tray = None  # tray with both delink_qty > 0 and excess_qty > 0

	for at in all_trays:
		tray_id = at.get('tray_id', '')
		original_qty = int(at.get('original_qty', 0) or 0)
		delink_qty = int(at.get('delink_qty', 0) or 0)
		excess_qty_row = int(at.get('excess_qty', 0) or 0)
		is_top = bool(at.get('top_tray', False))

		is_partial = delink_qty > 0 and excess_qty_row > 0

		row = {
			'sno': sno,
			'model_code': model_code,
			'tray_id': tray_id,
			'original_qty': original_qty,
			'delink_qty': delink_qty,
			'excess_qty': excess_qty_row,
			'scan_tray_id': tray_id,
			'is_scannable': True,
			'is_checkbox_enabled': True,
			'is_top_tray': is_top,
			'is_partial': is_partial,
			'status': '',  # Empty until user action
			'state': 'default',
		}

		if is_partial:
			split_tray = {
				'tray_id': tray_id,
				'delink_qty': delink_qty,
				'excess_qty': excess_qty_row,
				'original_qty': original_qty,
			}

		delink_rows.append(row)
		sno += 1

	total_delink = sum(r['delink_qty'] for r in delink_rows)
	total_excess = sum(r['excess_qty'] for r in delink_rows)

	delink_panel = {
		'mode': 'inactive',
		'trays': delink_rows,
		'total_delink_qty': total_delink,
		'total_excess_qty': total_excess,
		'tray_count': len(delink_rows),
		'selection_limit': 0,
		'selected_count': 0,
	}

	# ===== RIGHT: EXCESS PANEL (trays with excess_qty > 0) =====
	excess_exists = excess_qty > 0
	excess_panel_trays = []
	top_tray_info = None
	ex_sno = 1

	if excess_exists:
		# 1. PARTIAL TRAY (split tray → top tray)
		if split_tray:
			top_tray_info = {
				'tray_id': split_tray['tray_id'],
				'qty': split_tray['excess_qty'],
				'is_mandate_scan': True,
				'is_top_tray': True,
				'is_editable': True,
				'scan_tray_id': split_tray['tray_id'],
				'model_code': model_code,
				'original_tray_id': split_tray['tray_id'],
			}

		# 2. FULL EXCESS TRAYS (trays with delink_qty == 0)
		for at in all_trays:
			at_delink = int(at.get('delink_qty', 0) or 0)
			at_excess = int(at.get('excess_qty', 0) or 0)
			if at_excess <= 0 or at_delink > 0:
				continue  # Skip delink-only trays and the split tray
			excess_panel_trays.append({
				'sno': ex_sno,
				'tray_id': at.get('tray_id', ''),
				'original_tray_id': at.get('tray_id', ''),
				'model_code': model_code,
				'qty': at_excess,
				'scan_tray_id': at.get('tray_id', ''),
				'row_type': 'excess',
				'is_top_tray': False,
				'is_mandate_scan': False,
				'is_editable': False,
				'is_auto': True,
				'is_checkbox_enabled': True,
				'state': 'default',
			})
			ex_sno += 1

	excess_panel = {
		'exists': excess_exists,
		'total_excess_qty': excess_qty,
		'excess_tray_count': len(excess_panel_trays),
		'top_tray': top_tray_info,
		'trays': excess_panel_trays,
		'partial_tray': split_tray,
	}

	logging.info(json.dumps({
		'event': 'SPLIT_PANEL_BUILT',
		'all_trays': len(all_trays),
		'delink_trays': len(delink_rows),
		'excess_trays': len(excess_panel_trays),
		'excess_exists': excess_exists,
		'excess_qty': excess_qty,
		'total_delink': total_delink,
		'total_excess': total_excess,
		'has_split_tray': split_tray is not None,
		'lot_qty': lot_qty,
		'jig_capacity': jig_capacity,
	}))

	return {
		'delink_panel': delink_panel,
		'excess_panel': excess_panel,
		'meta': {
			'model_name': model_code,
			'tray_placeholder': f' {model_code}' if model_code else 'Scan Tray ID',
			'excess_placeholder': 'Scan excess tray',
		},
	}


def build_split_panel_data_multi_model(multi_model_allocation, computed, lot_qty, jig_capacity, tray_capacity=12):
	"""Build split panel data for multi-model jig loading.
	Uses computed['all_trays'] so ALL trays (from all models) are shown.
	Each tray has original_qty, delink_qty, excess_qty."""

	effective_capacity = int(computed.get('effective_capacity', 0) or 0)
	excess_qty = int(computed.get('excess_qty', 0) or 0)
	all_trays = computed.get('all_trays', [])

	# Build tray→model maps for resolving model_code
	tray_model_map = {}
	lot_model_map = {}
	tray_meta_map = {}  # tray_id → {lot_id, batch_id, model_index, color_class}
	for m_alloc in multi_model_allocation:
		m_code = (m_alloc.get('model_image_label') or m_alloc.get('model_name') or m_alloc.get('model') or '').strip()
		m_lot_id = m_alloc.get('lot_id', '')
		m_batch_id = m_alloc.get('batch_id', '')
		m_index = m_alloc.get('model_index', 0)
		m_color = m_alloc.get('color_class', '')
		if m_lot_id:
			lot_model_map[m_lot_id] = m_code
		for tray in m_alloc.get('tray_info', []):
			tid = tray.get('tray_id', '')
			tray_model_map[tid] = m_code
			tray_meta_map[tid] = {'lot_id': m_lot_id, 'batch_id': m_batch_id, 'model_index': m_index, 'color_class': m_color}

	delink_rows = []
	sno = 1
	split_tray = None

	for at in all_trays:
		tray_id = at.get('tray_id', '')
		original_qty = int(at.get('original_qty', 0) or 0)
		delink_qty = int(at.get('delink_qty', 0) or 0)
		excess_qty_row = int(at.get('excess_qty', 0) or 0)
		source_lot = at.get('source_lot_id', '')

		# Resolve model from tray map → lot map fallback
		m_code = tray_model_map.get(tray_id, '')
		if not m_code and source_lot:
			m_code = lot_model_map.get(source_lot, '')
		meta = tray_meta_map.get(tray_id, {})

		is_partial = delink_qty > 0 and excess_qty_row > 0

		delink_rows.append({
			'sno': sno,
			'model_code': m_code,
			'tray_id': tray_id,
			'original_qty': original_qty,
			'delink_qty': delink_qty,
			'excess_qty': excess_qty_row,
			'scan_tray_id': tray_id,
			'is_scannable': True,
			'is_checkbox_enabled': True,
			'is_top_tray': False,
			'is_partial': is_partial,
			'status': '',
			'state': 'default',
			'lot_id': meta.get('lot_id', source_lot),
			'batch_id': meta.get('batch_id', ''),
			'model_index': meta.get('model_index', 0),
			'color_class': meta.get('color_class', ''),
		})

		if is_partial:
			split_tray = {
				'tray_id': tray_id,
				'delink_qty': delink_qty,
				'excess_qty': excess_qty_row,
				'original_qty': original_qty,
			}
		sno += 1

	total_delink = sum(r['delink_qty'] for r in delink_rows)
	total_excess = sum(r['excess_qty'] for r in delink_rows)

	delink_panel = {
		'mode': 'inactive',
		'trays': delink_rows,
		'total_delink_qty': total_delink,
		'total_excess_qty': total_excess,
		'tray_count': len(delink_rows),
		'selection_limit': 0,
		'selected_count': 0,
	}

	# Excess panel: trays with delink_qty == 0 and excess_qty > 0
	excess_exists = excess_qty > 0
	excess_panel_trays = []
	top_tray_info = None
	ex_sno = 1

	if excess_exists:
		# Partial (split) tray as top tray
		if split_tray:
			st_model = tray_model_map.get(split_tray['tray_id'], '')
			st_lot_id = ''
			if not st_model:
				for at in all_trays:
					if at.get('tray_id') == split_tray['tray_id'] and at.get('source_lot_id'):
						st_model = lot_model_map.get(at['source_lot_id'], '')
						st_lot_id = at.get('source_lot_id', '')
						break
			if not st_lot_id:
				st_meta = tray_meta_map.get(split_tray['tray_id'], {})
				st_lot_id = st_meta.get('lot_id', '')
				if not st_lot_id:
					for at in all_trays:
						if at.get('tray_id') == split_tray['tray_id']:
							st_lot_id = at.get('source_lot_id', '')
							break
			top_tray_info = {
				'tray_id': split_tray['tray_id'],
				'qty': split_tray['excess_qty'],
				'is_mandate_scan': True,
				'is_top_tray': True,
				'is_editable': True,
				'scan_tray_id': split_tray['tray_id'],
				'model_code': st_model,
				'original_tray_id': split_tray['tray_id'],
				'lot_id': st_lot_id,
			}

		# Full excess trays (delink_qty == 0)
		for at in all_trays:
			at_delink = int(at.get('delink_qty', 0) or 0)
			at_excess = int(at.get('excess_qty', 0) or 0)
			if at_excess <= 0 or at_delink > 0:
				continue
			at_tid = at.get('tray_id', '')
			et_model = tray_model_map.get(at_tid, '')
			et_lot_id = at.get('source_lot_id', '')
			if not et_model and et_lot_id:
				et_model = lot_model_map.get(et_lot_id, '')
			if not et_lot_id:
				et_meta = tray_meta_map.get(at_tid, {})
				et_lot_id = et_meta.get('lot_id', '')
			excess_panel_trays.append({
				'sno': ex_sno,
				'tray_id': at_tid,
				'original_tray_id': at_tid,
				'model_code': et_model,
				'qty': at_excess,
				'scan_tray_id': at_tid,
				'row_type': 'excess',
				'is_top_tray': False,
				'is_mandate_scan': False,
				'is_editable': False,
				'is_auto': True,
				'is_checkbox_enabled': True,
				'state': 'default',
				'lot_id': et_lot_id,
			})
			ex_sno += 1

	excess_panel = {
		'exists': excess_exists,
		'total_excess_qty': excess_qty,
		'excess_tray_count': len(excess_panel_trays),
		'top_tray': top_tray_info,
		'trays': excess_panel_trays,
		'partial_tray': split_tray,
	}

	# Build model names from allocations for meta
	model_names = []
	for ma in multi_model_allocation:
		name = (ma.get('model_image_label') or ma.get('model_name') or ma.get('model') or '').strip()
		if name:
			model_names.append(name)

	logging.info(json.dumps({
		'event': 'SPLIT_PANEL_MULTI_MODEL_BUILT',
		'all_trays': len(all_trays),
		'delink_trays': len(delink_rows),
		'excess_trays': len(excess_panel_trays),
		'model_count': len(multi_model_allocation),
	}))

	return {
		'delink_panel': delink_panel,
		'excess_panel': excess_panel,
		'meta': {
			'model_name': ', '.join(model_names) if model_names else '',
			'tray_placeholder': 'Scan Tray ID',
			'excess_placeholder': 'Scan excess tray',
		},
	}


def build_unified_tray_table_multi_model(multi_model_allocation, computed, lot_qty, jig_capacity, tray_capacity=12):
	"""Build unified tray table for multi-model jig loading.

	Merges all model allocations + excess into a single flat table.
	"""
	rows = []
	sno = 1
	effective_capacity = int(computed.get('effective_capacity', 0) or 0)
	excess_qty = int(computed.get('excess_qty', 0) or 0)

	for m_alloc in multi_model_allocation:
		model_code = (m_alloc.get('model_image_label') or m_alloc.get('model_name') or m_alloc.get('model') or '').strip()
		model_lot_id = m_alloc.get('lot_id', '')
		model_batch_id = m_alloc.get('batch_id', '')
		model_index = m_alloc.get('model_index', 0)
		color_class = m_alloc.get('color_class', '')

		for tray in m_alloc.get('tray_info', []):
			tray_id = tray.get('tray_id', '')
			qty = int(tray.get('qty', 0) or 0)
			original_qty = int(tray.get('original_qty', qty) or qty)
			is_partial = bool(tray.get('is_partial', False))

			rows.append({
				'sno': sno,
				'model_code': model_code,
				'tray_id': tray_id,
				'original_qty': original_qty,
				'scan_tray_id': tray_id,
				'delink_qty': qty,
				'status': 'Partially Qty - Delink' if is_partial else 'Fully Delinked',
				'row_type': 'delink_partial' if is_partial else 'delink_full',
				'is_scannable': True,
				'is_checkbox_enabled': True,
				'lot_id': model_lot_id,
				'batch_id': model_batch_id,
				'model_index': model_index,
				'color_class': color_class,
			})
			sno += 1

	# Add excess trays from computed excess_info
	excess_info = computed.get('excess_info', {})
	for et in excess_info.get('excess_trays', []):
		et_tray_id = et.get('tray_id', '')
		et_qty = int(et.get('qty', 0) or 0)
		already_in = any(r.get('tray_id') == et_tray_id for r in rows)
		if already_in:
			continue
		rows.append({
			'sno': sno,
			'model_code': '',
			'tray_id': et_tray_id,
			'original_qty': et_qty,
			'scan_tray_id': et_tray_id,
			'scan_label': '',
			'delink_qty': et_qty,
			'status': 'Excess Lot Tray Scan',
			'row_type': 'excess',
			'is_scannable': True,
			'is_checkbox_enabled': True,
			'lot_id': '',
			'batch_id': '',
			'model_index': 0,
			'color_class': '',
		})
		sno += 1

	logging.info(json.dumps({
		'event': 'UNIFIED_TRAY_TABLE_MULTI_MODEL_BUILT',
		'total_rows': len(rows),
		'model_count': len(multi_model_allocation),
	}))

	return rows


def fetch_lot_data(lot_id, batch_id, jig_capacity_override=None):
	"""Fetch lot qty, jig capacity, tray capacity, and model metadata from DB."""
	lot_qty = 0
	jig_capacity = 0
	tray_capacity = 12
	model_image_url = '/static/assets/images/imagePlaceholder.jpg'
	model_image_label = ''
	nickel_bath_type = ''
	tray_type_name = ''

	try:
		stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
		if stock:
			lot_qty = int(
				getattr(stock, 'brass_audit_accepted_qty', None)
				or getattr(stock, 'brass_audit_physical_qty', None)
				or getattr(stock, 'total_stock', 0) or 0
			)
	except Exception:
		logging.exception('fetch_lot_data: lot qty fetch failed')

	try:
		if jig_capacity_override:
			jig_capacity = int(jig_capacity_override)
		else:
			batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
			model_obj = getattr(batch_obj, 'model_stock_no', None) if batch_obj else None
			if model_obj:
				master = JigLoadingMaster.objects.filter(model_stock_no=model_obj).first()
				if master and getattr(master, 'jig_capacity', None):
					jig_capacity = int(master.jig_capacity)
			if not jig_capacity:
				jig_capacity = lot_qty
	except Exception:
		jig_capacity = lot_qty or 0

	try:
		batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
		if batch_obj:
			tc = getattr(batch_obj, 'tray_capacity', None)
			if not tc:
				model_obj = getattr(batch_obj, 'model_stock_no', None)
				if model_obj:
					tc = getattr(model_obj, 'tray_capacity', None)
			if tc:
				tray_capacity = int(tc)
	except Exception:
		pass

	try:
		mm = None
		batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
		if batch_obj:
			mm = getattr(batch_obj, 'model_stock_no', None) or batch_obj
		if mm:
			try:
				if hasattr(mm, 'images'):
					imgs = mm.images.all()
					if imgs.exists():
						first_img = imgs.first()
						if getattr(first_img, 'master_image', None):
							model_image_url = first_img.master_image.url
			except Exception:
				pass
			model_image_label = getattr(mm, 'plating_stk_no', '') or getattr(mm, 'model_no', '') or ''
			nickel_bath_type = getattr(mm, 'ep_bath_type', '') or ''
			try:
				tt = getattr(mm, 'tray_type', None)
				if tt:
					tray_type_name = getattr(tt, 'tray_type', '') if not isinstance(tt, str) else tt
			except Exception:
				pass
			# Resolve abbreviation to full parent name (e.g. JB→Jumbo, ND→Normal)
			if tray_type_name:
				try:
					from modelmasterapp.models import TrayType as _TrayType
					_tt_obj = _TrayType.objects.filter(tray_type=tray_type_name).first()
					if _tt_obj and _tt_obj.tray_color:
						_parent = _TrayType.objects.filter(
							tray_capacity=_tt_obj.tray_capacity, tray_color__isnull=True
						).first()
						if _parent:
							tray_type_name = _parent.tray_type
				except Exception:
					pass
	except Exception:
		pass

	return {
		'lot_qty': lot_qty,
		'jig_capacity': jig_capacity,
		'tray_capacity': tray_capacity,
		'model_image_url': model_image_url,
		'model_image_label': model_image_label,
		'nickel_bath_type': nickel_bath_type,
		'tray_type': tray_type_name,
	}


def fetch_trays_for_lot(lot_id):
	"""Fetch tray records for a lot from JigLoadTrayId."""
	trays = []
	try:
		qs = JigLoadTrayId.objects.filter(lot_id=lot_id).order_by('id')
		for t in qs:
			trays.append({
				'tray_id': getattr(t, 'tray_id', ''),
				'qty': int(getattr(t, 'tray_quantity', 0) or 0),
				'top_tray': bool(getattr(t, 'top_tray', False) or False),
				'rejected': bool(getattr(t, 'rejected_tray', False) or False),
				'delinked': bool(getattr(t, 'delink_tray', False) or False),
			})
	except Exception:
		logging.exception('fetch_trays_for_lot failed')
	return trays


def aggregate_multi_model_trays(primary_lot_id, secondary_lots):
	"""Aggregate trays from all model lots (primary + secondary) into one combined list.
	Used by JigLoadUpdateAPI and JigLoadSubmitAPI for multi-model recomputation.
	compute_jig_loading receives ALL trays and distributes up to jig_capacity."""
	all_trays = []
	seen_lot_ids = set()

	# Primary model trays first
	if primary_lot_id:
		primary_trays = fetch_trays_for_lot(primary_lot_id)
		for t in primary_trays:
			t['source_lot_id'] = primary_lot_id
		all_trays.extend(primary_trays)
		seen_lot_ids.add(primary_lot_id)

	# Secondary model trays
	for sec in (secondary_lots or []):
		sec_lot_id = sec.get('lot_id')
		if not sec_lot_id or sec_lot_id in seen_lot_ids:
			continue
		sec_trays = fetch_trays_for_lot(sec_lot_id)
		for t in sec_trays:
			t['source_lot_id'] = sec_lot_id
		all_trays.extend(sec_trays)
		seen_lot_ids.add(sec_lot_id)

	logging.info(f"[AGGREGATE] Combined {len(all_trays)} trays from {len(seen_lot_ids)} lots: {list(seen_lot_ids)}")
	return all_trays


def validate_tray_for_scan(tray_id, lot_id, already_scanned_ids=None, allow_reuse_delink=False, allow_new_half_filled=False):
	"""Validate a tray ID for scanning.
	Returns: (is_valid, tray_qty, validation_status, message)"""
	if not tray_id or not lot_id:
		return False, 0, 'error', 'tray_id and lot_id are required'
	if already_scanned_ids and tray_id in already_scanned_ids and not allow_reuse_delink:
		return False, 0, 'duplicate', 'Tray already scanned'
	try:
		tray = JigLoadTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).first()
		if not tray:
			if allow_new_half_filled:
				return True, 0, 'success', 'New tray accepted'
			return False, 0, 'invalid_tray', 'Invalid tray or wrong lot'
		tray_qty = int(tray.tray_quantity or 0)
		return True, tray_qty, 'success', 'Tray validated'
	except Exception as e:
		logging.exception(f'validate_tray_for_scan error: {e}')
		return False, 0, 'error', 'Server error during tray validation'


# =============================================================================
# NEW CONSOLIDATED APIs — ONE API PER ACTION
# =============================================================================

class JigLoadInitAPI(APIView):
	"""POST /api/jig/load/init/ — Unified initialization for Jig Loading.
	Merges init-jig-load + tray-info. Single source of truth."""
	permission_classes = [IsAuthenticated]

	def post(self, request):
		payload = request.data
		lot_id = payload.get('lot_id')
		batch_id = payload.get('batch_id')
		jig_capacity_override = payload.get('jig_capacity')
		broken_hooks = int(payload.get('broken_hooks', 0) or 0)
		multi_model_flag = payload.get('multi_model', False)
		secondary_lots = payload.get('secondary_lots', [])

		if not lot_id or not batch_id:
			return Response({'error': 'lot_id and batch_id are required'}, status=status.HTTP_400_BAD_REQUEST)

		logging.info(json.dumps({
			'event': 'JIG_LOAD_INIT',
			'lot_id': lot_id, 'batch_id': batch_id,
			'multi_model': bool(multi_model_flag)
		}))

		# 1. Fetch all data in one place
		lot_data = fetch_lot_data(lot_id, batch_id, jig_capacity_override)
		lot_qty = lot_data['lot_qty']
		jig_capacity = lot_data['jig_capacity']
		tray_capacity = lot_data['tray_capacity']
		# For multi-model, aggregate ALL model trays so excess_qty is computed globally
		if multi_model_flag and secondary_lots:
			trays = aggregate_multi_model_trays(lot_id, secondary_lots)
		else:
			trays = fetch_trays_for_lot(lot_id)

		# ===== EXCESS LOT DETECTION: If batch already submitted with half_filled_tray_qty > 0,
		# use half_filled_tray_info as the tray list and half_filled_tray_qty as lot_qty.
		# This handles excess lots appearing in the pick table after a jig is submitted.
		if not (multi_model_flag and secondary_lots):
			try:
				submitted_jig = JigCompleted.objects.filter(
					batch_id=batch_id,
					draft_status='submitted',
					half_filled_tray_qty__gt=0
				).first()
				if submitted_jig:
					hf_info = submitted_jig.half_filled_tray_info or []
					if hf_info:
						trays = [
							{
								'tray_id': t['tray_id'],
								'qty': int(t.get('qty') or 0),
								'top_tray': bool(t.get('is_top_half_filled', False)),
							}
							for t in hf_info if isinstance(t, dict) and t.get('tray_id')
						]
						lot_qty = submitted_jig.half_filled_tray_qty or submitted_jig.excess_qty or 0
						logging.info(f'[INIT_EXCESS_LOT] Batch {batch_id} already submitted — using half_filled tray info: {len(trays)} tray(s), qty={lot_qty}')
			except Exception:
				logging.exception('[INIT_EXCESS_LOT] Failed to check submitted JigCompleted — continuing with normal flow')

		# 2. Fetch draft (read-only — never created here)
		draft = JigLoadingManualDraft.objects.filter(
			batch_id=batch_id, lot_id=lot_id, user=request.user
		).first()
		# STRICT: NEVER load broken_hooks from draft — only from explicit frontend payload.
		# This prevents stale BH from previous sessions bleeding into fresh init.

		# 3. Core computation — single source of truth
		computed = compute_jig_loading(trays, jig_capacity, broken_hooks, tray_capacity)

		# 4. Separate PLANNED allocation from ACTUAL loaded (scanned) qty.
		# planned_loaded = what the plan says (for Add Model enable/disable)
		# loaded_cases_qty = what user has actually scanned (0 on fresh init)
		planned_loaded_cases_qty = computed['delink_tray_qty']
		planned_empty_hooks = max(0, computed['effective_capacity'] - planned_loaded_cases_qty)
		# Fresh init: nothing scanned yet → loaded=0, empty=full capacity
		loaded_cases_qty = 0
		empty_hooks = computed['effective_capacity']
		# Adjust empty_hooks based on total lot qty (remaining capacity after planned allocation)
		total_lot_qty_for_empty = lot_qty
		empty_hooks = max(0, empty_hooks - total_lot_qty_for_empty)

		# 5. Multi-model allocation
		multi_model_allocation = []
		half_filled_tray_info = computed.get('half_filled_tray_info', {})
		half_filled_tray_qty = computed.get('half_filled_tray_qty', 0)
		ui_delink_tray_info = []
		tray_distribution = []
		models_list = []
		total_multi_model_qty = lot_qty

		if multi_model_flag and secondary_lots:
			mm_result = self._handle_multi_model(
				lot_id, batch_id, lot_qty, secondary_lots,
				computed['effective_capacity'], tray_capacity
			)
			multi_model_allocation = mm_result['allocation']
			# Convert old list format to new dict format
			half_filled_tray_info = _half_filled_list_to_dict(mm_result['half_filled'], mm_result['half_filled_qty'])
			half_filled_tray_qty = mm_result['half_filled_qty']
			total_multi_model_qty = mm_result['total_qty']
			ui_delink_tray_info = mm_result['ui_delink']
			tray_distribution = mm_result.get('tray_distribution', [])
			models_list = mm_result.get('models', [])
			# planned allocation from total multi-model allocation (for Add Model enable/disable)
			planned_loaded_cases_qty = min(total_multi_model_qty, computed['effective_capacity'])
			planned_empty_hooks = max(0, computed['effective_capacity'] - planned_loaded_cases_qty)
			# Fresh init: nothing scanned yet → loaded=0, empty=full capacity
			loaded_cases_qty = 0
			empty_hooks = computed['effective_capacity']
			# Adjust empty_hooks based on total lot qty (remaining capacity after planned allocation)
			total_lot_qty_for_empty = total_multi_model_qty
			empty_hooks = max(0, empty_hooks - total_lot_qty_for_empty)

		# 6. Detect PERFECT_FIT — for multi-model, compare total allocation vs capacity
		if multi_model_flag and secondary_lots:
			hf_exists = half_filled_tray_info.get('exists', False) if isinstance(half_filled_tray_info, dict) else bool(half_filled_tray_info)
			is_perfect_fit = (total_multi_model_qty == computed['effective_capacity']) and (broken_hooks == 0) and (not hf_exists)
		else:
			is_perfect_fit = (lot_qty == jig_capacity) and (broken_hooks == 0)

		# 6b. Multi-model excess: total requested across ALL models minus effective capacity
		if multi_model_flag and secondary_lots:
			total_all_models_requested = lot_qty + sum(int(s.get('qty', 0) or 0) for s in secondary_lots)
			multi_model_excess = max(0, total_all_models_requested - computed['effective_capacity'])
		else:
			multi_model_excess = None  # use single-model excess

		# ✅ BUG FIX #4/#5: If scanned_trays provided (BH recalc), compute loaded/delink_completed
		scanned_trays = payload.get('scanned_trays', [])
		delink_completed_flag = False
		if scanned_trays:
			scanned_ids = set(s.get('tray_id', '') for s in scanned_trays if s.get('tray_id'))
			if multi_model_flag and multi_model_allocation:
				delink_plan = {}
				for m_alloc in multi_model_allocation:
					for t in m_alloc.get('tray_info', []):
						delink_plan[t.get('tray_id', '')] = t.get('qty', 0)
			else:
				delink_plan = {dt['tray_id']: dt['qty'] for dt in computed['delink_tray_info']}
			loaded_cases_qty = sum(delink_plan.get(sid, 0) for sid in scanned_ids)
			empty_hooks = max(0, computed['effective_capacity'] - loaded_cases_qty)
			# planned_empty_hooks stays based on planned allocation (already computed above)
			delink_count = len(delink_plan)
			delink_completed_flag = len(scanned_ids) >= delink_count and delink_count > 0
			if delink_completed_flag and isinstance(half_filled_tray_info, dict) and half_filled_tray_info.get('exists') and not half_filled_tray_info.get('tray_ids'):
				excess_trays_for_hf = computed.get('excess_info', {}).get('excess_trays', [])
				half_filled_tray_info = assign_half_filled_tray_ids(
					half_filled_tray_info, computed['delink_tray_info'],
					excess_trays_for_hf, tray_capacity
				)
			logging.info(f'[INIT_BH_RECALC] scanned={len(scanned_ids)}, loaded={loaded_cases_qty}, delink_completed={delink_completed_flag}')

		# 7a. Build unified tray table (single source of truth for delink + excess UI)
		if multi_model_flag and multi_model_allocation:
			unified_tray_table = build_unified_tray_table_multi_model(
				multi_model_allocation, computed, lot_qty, jig_capacity, tray_capacity
			)
			split_panel = build_split_panel_data_multi_model(
				multi_model_allocation, computed, lot_qty, jig_capacity, tray_capacity
			)
		else:
			model_label = lot_data.get('model_image_label', '') if isinstance(lot_data, dict) else ''
			unified_tray_table = build_unified_tray_table(
				computed, lot_qty, jig_capacity, model_label, tray_capacity
			)
			split_panel = build_split_panel_data(
				computed, lot_qty, jig_capacity, model_label, tray_capacity
			)

		# 7. Build unified response
		response = {
			'lot_id': lot_id,
			'batch_id': batch_id,
			'lot_qty': lot_qty,
			'total_qty': computed['total_qty'],
			'tray_count': computed['tray_count'],
			'jig_capacity': jig_capacity,
			'original_capacity': jig_capacity,
			'broken_hooks': broken_hooks,
			'placeholders': {
				'jig_id': f'Enter Jig ID (e.g. J{jig_capacity:03d}-0000)',
				'tray_scan': 'Scan or enter tray ID',
			},
			'effective_capacity': computed['effective_capacity'],
			'loaded_cases_qty': loaded_cases_qty,
			'empty_hooks': empty_hooks,
			'excess_qty': multi_model_excess if multi_model_excess is not None else computed['excess_qty'],
			'trays': trays,
			'delink_tray_info': computed['delink_tray_info'],
			'delink_trays': computed['delink_tray_info'],
			'delink_tray_qty': computed['delink_tray_qty'],
			'excess_info': computed['excess_info'],
			'scenario': 'PERFECT_FIT' if is_perfect_fit else '',
			'model_image_url': lot_data['model_image_url'],
			'model_image_label': lot_data['model_image_label'],
			'plating_stock_num': lot_data['model_image_label'],
			'nickel_bath_type': lot_data['nickel_bath_type'],
			'tray_type': lot_data['tray_type'],
			'tray_capacity': tray_capacity,
			'is_multi_model': bool(multi_model_flag),
			'total_multi_model_qty': total_multi_model_qty,
			'multi_model_allocation': multi_model_allocation,
			'secondary_lots': secondary_lots,
			'ui_delink_tray_info': ui_delink_tray_info,
			'tray_distribution': tray_distribution,
			'models': models_list,
			'half_filled_tray_info': half_filled_tray_info,
			'half_filled': half_filled_tray_info,
			'half_filled_tray_qty': half_filled_tray_qty,
			'delink_completed': delink_completed_flag,
			'validation': computed['validation'],
			'planned_empty_hooks': planned_empty_hooks,
			'bh_editable': True,
			'unified_tray_table': unified_tray_table,
			'split_panel': split_panel,
			# Legacy 'draft' key for frontend backward compatibility
			'draft': {
				'batch_id': batch_id,
				'lot_id': lot_id,
				'original_lot_qty': lot_qty,
				'jig_capacity': jig_capacity,
				'effective_capacity': computed['effective_capacity'],
				'loaded_cases_qty': loaded_cases_qty,
				'delink_tray_info': computed['delink_tray_info'],
				'delink_tray_qty': computed['delink_tray_qty'],
				'excess_qty': multi_model_excess if multi_model_excess is not None else computed['excess_qty'],
				'broken_hooks': broken_hooks,
				'model_image_url': lot_data['model_image_url'],
				'model_image_label': lot_data['model_image_label'],
				'plating_stock_num': lot_data['model_image_label'],
				'nickel_bath_type': lot_data['nickel_bath_type'],
				'tray_type': lot_data['tray_type'],
				'tray_capacity': tray_capacity,
				'is_multi_model': bool(multi_model_flag),
				'total_multi_model_qty': total_multi_model_qty,
				'draft_data': {'primary_lot': lot_id, 'secondary_lots': secondary_lots},
				'secondary_lots': secondary_lots,
			},
		}
		return Response(response)

	def _handle_multi_model(self, primary_lot_id, primary_batch_id, primary_lot_qty,
							secondary_lots, effective_capacity, tray_capacity):
		"""Handle multi-model tray allocation across primary + secondary models."""
		used_tray_ids = set()
		allocation = []
		half_filled_tray_info = []
		half_filled_tray_qty = 0

		# Primary model
		try:
			primary_result = allocate_trays_for_model(primary_lot_id, primary_lot_qty, effective_capacity, used_tray_ids)
			used_tray_ids.update(primary_result['allocated_tray_ids'])
			primary_img = fetch_model_image_metadata(primary_lot_id, primary_batch_id)
			primary_model_name = fetch_model_metadata(primary_lot_id, primary_batch_id)
			# Ensure model_image_label is NEVER empty — fall back to model_name
			primary_image_label = primary_img['model_image_label'] or primary_model_name or f'Model-{primary_lot_id}'
			allocation.append({
				'model': primary_model_name,
				'model_name': primary_model_name,
				'model_role': 'primary', 'lot_id': primary_lot_id, 'batch_id': primary_batch_id,
				'sequence': 0, 'allocated_qty': primary_result['allocated_qty'],
				'tray_info': primary_result['tray_info'],
				'model_image_url': primary_img['model_image_url'],
				'model_image_label': primary_image_label,
				# Backend-controlled rendering metadata
				'model_index': 1,
				'color_class': 'model-bg-1',
				'display_name': 'Model 1',
			})
		except Exception as e:
			logging.exception(f'Multi-model primary allocation failed: {e}')

		# Secondary models
		for seq, sec in enumerate(secondary_lots, start=1):
			try:
				sec_lot_id = sec.get('lot_id')
				sec_batch_id = sec.get('batch_id')
				sec_lot_qty = int(sec.get('qty', 0) or 0)
				if not sec_lot_id:
					continue
				capacity_used = sum(m['allocated_qty'] for m in allocation)
				capacity_remaining = max(0, effective_capacity - capacity_used)
				allowed_qty = min(sec_lot_qty, capacity_remaining)
				excess_for_model = max(0, sec_lot_qty - allowed_qty)

				secondary_result = allocate_trays_for_model(sec_lot_id, allowed_qty, capacity_remaining, used_tray_ids)
				used_tray_ids.update(secondary_result['allocated_tray_ids'])
				sec_img = fetch_model_image_metadata(sec_lot_id, sec_batch_id)
				sec_model_name = fetch_model_metadata(sec_lot_id, sec_batch_id)
				# Ensure model_image_label is NEVER empty — fall back to model_name
				sec_image_label = sec_img['model_image_label'] or sec_model_name or f'Model-{sec_lot_id}'
				model_idx = len(allocation) + 1  # 1-based index (primary=1, first secondary=2, etc.)
				# ✅ Modulo cycling so Model 6+ wraps back to model-bg-1 (only 5 CSS classes exist)
				normalized_color_idx = ((model_idx - 1) % 5) + 1
				allocation.append({
					'model': sec_model_name, 'model_name': sec_model_name,
					'model_role': 'secondary', 'lot_id': sec_lot_id, 'batch_id': sec_batch_id,
					'sequence': seq, 'allocated_qty': secondary_result['allocated_qty'],
					'tray_info': secondary_result['tray_info'],
					'model_image_url': sec_img['model_image_url'],
					'model_image_label': sec_image_label,
					# Backend-controlled rendering metadata — cycled so no out-of-range classes
					'model_index': model_idx,
					'color_class': f'model-bg-{normalized_color_idx}',
					'display_name': f'Model {model_idx}',
				})

				# Excess handling → half-filled trays
				if excess_for_model > 0:
					excess_remaining = excess_for_model
					if secondary_result['tray_info']:
						last_alloc = secondary_result['tray_info'][-1]
						try:
							orig_tray = JigLoadTrayId.objects.filter(lot_id=sec_lot_id, tray_id=last_alloc['tray_id']).first()
							if orig_tray:
								orig_qty = int(getattr(orig_tray, 'tray_quantity', 0) or 0)
								if last_alloc['qty'] < orig_qty:
									partial_rem = orig_qty - last_alloc['qty']
									hf_qty = min(partial_rem, excess_remaining)
									half_filled_tray_info.append({'tray_id': last_alloc['tray_id'], 'qty': hf_qty, 'model': sec_model_name})
									excess_remaining -= hf_qty
									half_filled_tray_qty += hf_qty
						except Exception:
							pass
					if excess_remaining > 0:
						try:
							for tray_obj in JigLoadTrayId.objects.filter(lot_id=sec_lot_id).order_by('id'):
								if excess_remaining <= 0:
									break
								tid = getattr(tray_obj, 'tray_id', '')
								if tid in used_tray_ids:
									continue
								tq = int(getattr(tray_obj, 'tray_quantity', 0) or 0)
								hf_qty = min(tq, excess_remaining)
								half_filled_tray_info.append({'tray_id': tid, 'qty': hf_qty, 'model': sec_model_name})
								excess_remaining -= hf_qty
								half_filled_tray_qty += hf_qty
								used_tray_ids.add(tid)
						except Exception:
							pass
			except Exception as e:
				logging.exception(f'Multi-model secondary allocation failed: {e}')
				continue

		# Build flattened UI delink tray info (with backend-controlled color/display)
		ui_delink = []
		for m_alloc in allocation:
			m_color = m_alloc.get('color_class', '')
			m_display = m_alloc.get('display_name', '')
			m_index = m_alloc.get('model_index', 0)
			for t in m_alloc.get('tray_info', []):
				ui_delink.append({
					'tray_id': t.get('tray_id', ''), 'qty': t.get('qty', 0),
					'top_tray': False, 'is_partial': False,
					'model': m_alloc.get('model', ''), 'model_role': m_alloc.get('model_role', ''),
					'lot_id': m_alloc.get('lot_id', ''), 'batch_id': m_alloc.get('batch_id', ''),
					'color_class': m_color, 'display_name': m_display, 'model_index': m_index,
				})

		# Unified half-filled fix
		total_requested = primary_lot_qty + sum(int(s.get('qty', 0) or 0) for s in secondary_lots)
		if total_requested > effective_capacity and not half_filled_tray_info:
			overflow = total_requested - effective_capacity
			tc = tray_capacity or 12
			while overflow > 0:
				fill = min(tc, overflow)
				half_filled_tray_info.append({'tray_id': None, 'qty': fill, 'model': 'Overflow'})
				overflow -= fill
			half_filled_tray_qty = sum(t['qty'] for t in half_filled_tray_info)

		# Build unified tray_distribution: delink trays + half-filled trays merged
		tray_distribution = list(ui_delink)
		for hf in half_filled_tray_info:
			tray_distribution.append({
				'tray_id': hf.get('tray_id'), 'qty': hf.get('qty', 0),
				'top_tray': False, 'is_partial': True,
				'model': hf.get('model', ''), 'model_role': 'half_filled',
				'lot_id': '', 'batch_id': '',
				'color_class': 'half-filled', 'display_name': 'Half Filled',
				'model_index': 0,
			})

		# Build models summary list for frontend (backend-controlled model identity)
		models_summary = []
		for m_alloc in allocation:
			models_summary.append({
				'model_index': m_alloc.get('model_index', 0),
				'display_name': m_alloc.get('display_name', ''),
				'color_class': m_alloc.get('color_class', ''),
				'model_no': m_alloc.get('model_image_label', ''),
				'model_image_url': m_alloc.get('model_image_url', ''),
				'model_role': m_alloc.get('model_role', ''),
				'lot_id': m_alloc.get('lot_id', ''),
				'batch_id': m_alloc.get('batch_id', ''),
				'qty': m_alloc.get('allocated_qty', 0),
			})

		return {
			'allocation': allocation, 'half_filled': half_filled_tray_info,
			'half_filled_qty': half_filled_tray_qty,
			'total_qty': sum(m['allocated_qty'] for m in allocation),
			'ui_delink': ui_delink,
			'tray_distribution': tray_distribution,
			'models': models_summary,
		}


class JigLoadUpdateAPI(APIView):
	"""POST /api/jig/load/update/ — Unified update API.
	Handles: scan_tray, unscan_tray, update_broken_hooks, save_draft.
	Always returns full recalculated state from compute_jig_loading."""
	permission_classes = [IsAuthenticated]

	def post(self, request):
		payload = request.data
		lot_id = payload.get('lot_id')
		batch_id = payload.get('batch_id')
		action = payload.get('action', 'scan_tray')
		tray_id = payload.get('tray_id')
		broken_hooks = int(payload.get('broken_hooks', 0) or 0)
		jig_capacity_override = payload.get('jig_capacity')
		scanned_trays = payload.get('scanned_trays', [])
		multi_model_flag = payload.get('multi_model', False)
		secondary_lots = payload.get('secondary_lots', [])
		primary_lot_id = payload.get('primary_lot_id', lot_id)
		primary_batch_id = payload.get('primary_batch_id', batch_id)

		if not lot_id or not batch_id:
			return Response({'error': 'lot_id and batch_id are required'}, status=status.HTTP_400_BAD_REQUEST)

		logging.info(json.dumps({'event': 'JIG_LOAD_UPDATE', 'lot_id': lot_id, 'action': action, 'tray_id': tray_id, 'multi_model': bool(multi_model_flag)}))

		# Validate tray scan if requested
		scan_result = None
		if action == 'scan_tray' and tray_id:
			allow_reuse_delink = bool(payload.get('allow_reuse_delink', False))
			allow_new_half_filled = bool(payload.get('allow_new_half_filled', False))
			already_scanned = set(s.get('tray_id', '') for s in scanned_trays if s.get('tray_id'))
			is_valid, tray_qty, validation_status, message = validate_tray_for_scan(
				tray_id,
				lot_id,
				already_scanned,
				allow_reuse_delink=allow_reuse_delink,
				allow_new_half_filled=allow_new_half_filled,
			)
			scan_result = {
				'validation_status': validation_status,
				'message': message,
				'tray_id': tray_id,
				'tray_qty': tray_qty,
			}
			if not is_valid:
				return Response(scan_result, status=status.HTTP_400_BAD_REQUEST if validation_status != 'error' else status.HTTP_500_INTERNAL_SERVER_ERROR)

		# Handle unscan: just acknowledge and recalculate with updated scanned list
		if action == 'unscan_tray' and tray_id:
			# Client sends updated scanned_trays list AFTER removing the tray
			scan_result = {
				'validation_status': 'unscan_success',
				'message': f'Tray {tray_id} removed',
				'tray_id': tray_id,
				'tray_qty': 0,
			}

		# Handle clear: FULL RESET — delete draft, zero all state
		if action == 'clear':
			broken_hooks = 0
			scanned_trays = []
			try:
				JigLoadingManualDraft.objects.filter(
					batch_id=batch_id, lot_id=lot_id, user=request.user
				).delete()
				logging.info(f'[CLEAR] Draft deleted for lot={lot_id}, batch={batch_id}')
			except Exception:
				logging.exception('JigLoadUpdateAPI: clear draft delete failed')

		# Fetch data and recompute full state (SINGLE SOURCE OF TRUTH)
		# Multi-model: use PRIMARY lot for capacity/metadata, aggregate trays from ALL lots
		if multi_model_flag and secondary_lots:
			lot_data = fetch_lot_data(primary_lot_id, primary_batch_id, jig_capacity_override)
			trays = aggregate_multi_model_trays(primary_lot_id, secondary_lots)
			logging.info(f"[UPDATE_MM] Aggregated {len(trays)} trays from primary={primary_lot_id} + {len(secondary_lots)} secondary lots")
		else:
			lot_data = fetch_lot_data(lot_id, batch_id, jig_capacity_override)
			trays = fetch_trays_for_lot(lot_id)
		computed = compute_jig_loading(trays, lot_data['jig_capacity'], broken_hooks, lot_data['tray_capacity'])

		# ===== LOADED QTY: derive from DELINK PLAN, not frontend-sent qty =====
		# Build set of ALL scanned tray IDs (used for delink_completed check)
		scanned_ids = set(s.get('tray_id', '') for s in scanned_trays if s.get('tray_id'))
		if action == 'scan_tray' and scan_result and scan_result['validation_status'] == 'success':
			scanned_ids.add(tray_id)
		# Sum PLANNED qty from delink_tray_info for each scanned tray (not raw DB qty)
		delink_plan = {dt['tray_id']: dt['qty'] for dt in computed['delink_tray_info']}
		# STRICT RULE: loaded_cases_qty = DELINK-panel scans ONLY (not excess/top-tray scans).
		# Frontend sends delink_scanned_trays (delink panel only) and scan_panel to distinguish.
		delink_scanned_trays_payload = payload.get('delink_scanned_trays', None)
		scan_panel = payload.get('scan_panel', 'delink')
		if delink_scanned_trays_payload is not None:
			# Use explicit delink-only scan list
			delink_only_ids = set(s.get('tray_id', '') for s in delink_scanned_trays_payload if s.get('tray_id'))
			if action == 'scan_tray' and scan_result and scan_result['validation_status'] == 'success' and scan_panel == 'delink':
				delink_only_ids.add(tray_id)
			loaded_cases_qty = sum(delink_plan.get(sid, 0) for sid in delink_only_ids)
		else:
			# Legacy: filter all scanned against delink_plan
			loaded_cases_qty = sum(delink_plan.get(sid, 0) for sid in scanned_ids)

		# BUG FIX: Include partial/split tray delink_qty even when scanned from excess/top panel.
		# A partial tray has both delink_qty>0 and excess_qty>0 in all_trays.
		# Its delink_qty is ALWAYS part of the jig load, regardless of which panel it was scanned from.
		all_trays_data = computed.get('all_trays', [])
		all_trays_map = {at['tray_id']: at for at in all_trays_data}
		counted_ids = delink_only_ids if delink_scanned_trays_payload is not None else scanned_ids
		for sid in scanned_ids:
			if sid in counted_ids:
				continue  # Already counted from delink panel
			at = all_trays_map.get(sid)
			if at and int(at.get('delink_qty', 0) or 0) > 0:
				loaded_cases_qty += int(at['delink_qty'])

		empty_hooks = max(0, computed['effective_capacity'] - loaded_cases_qty)

		# ===== DELINK COMPLETION: all delink trays scanned? =====
		delink_count = len(computed['delink_tray_info'])
		# Use delink_only_ids if available (more accurate), else fall back to all scanned_ids
		delink_check_ids = (delink_only_ids if delink_scanned_trays_payload is not None else scanned_ids)
		delink_completed = len(delink_check_ids) >= delink_count and delink_count > 0

		# ===== HALF-FILLED TRAY IDs: only assigned when delink is COMPLETE =====
		half_filled = computed.get('half_filled_tray_info', {})
		if delink_completed and isinstance(half_filled, dict) and half_filled.get('exists'):
			excess_trays = computed.get('excess_info', {}).get('excess_trays', [])
			half_filled = assign_half_filled_tray_ids(
				half_filled, computed['delink_tray_info'],
				excess_trays, lot_data['tray_capacity']
			)

		# Persist draft state (NOT on clear — draft already deleted above)
		if action in ('scan_tray', 'unscan_tray', 'save_draft', 'update_broken_hooks'):
			try:
				JigLoadingManualDraft.objects.update_or_create(
					batch_id=batch_id, lot_id=lot_id, user=request.user,
					defaults={
						'broken_hooks': broken_hooks,
						'loaded_cases_qty': loaded_cases_qty,
						'jig_capacity': lot_data['jig_capacity'],
						'original_lot_qty': lot_data['lot_qty'],
						'delink_tray_info': computed['delink_tray_info'],
						'delink_tray_qty': computed['delink_tray_qty'],
					}
				)
			except Exception:
				logging.exception('JigLoadUpdateAPI: draft save failed')

		# Compute total_multi_model_qty for multi-model
		if multi_model_flag and secondary_lots:
			# Total = primary lot_qty + sum of all secondary qtys
			_primary_qty = lot_data['lot_qty']
			_secondary_total = sum(int(s.get('qty', 0) or 0) for s in secondary_lots)
			total_multi_model_qty = _primary_qty + _secondary_total
			# Multi-model excess: total requested across ALL models minus effective capacity
			mm_excess_qty = max(0, total_multi_model_qty - computed['effective_capacity'])
			logging.info(f"[UPDATE_MM] total_multi_model_qty={total_multi_model_qty}, mm_excess={mm_excess_qty}")
		else:
			total_multi_model_qty = lot_data['lot_qty']
			mm_excess_qty = computed['excess_qty']

		# planned_empty_hooks: based on planned allocation (for Add Model enable/disable)
		if multi_model_flag and secondary_lots:
			planned_loaded = min(total_multi_model_qty, computed['effective_capacity'])
		else:
			planned_loaded = computed['delink_tray_qty']
		planned_empty_hooks = max(0, computed['effective_capacity'] - planned_loaded)

		# Build multi-model allocation + unified tray table for backend-driven FE rendering
		multi_model_allocation = []
		if multi_model_flag and secondary_lots:
			try:
				mm_result = JigLoadInitAPI()._handle_multi_model(
					primary_lot_id,
					primary_batch_id,
					lot_data['lot_qty'],
					secondary_lots,
					computed['effective_capacity'],
					lot_data['tray_capacity']
				)
				multi_model_allocation = mm_result.get('allocation', [])
			except Exception:
				logging.exception('JigLoadUpdateAPI: multi-model allocation build failed')
				multi_model_allocation = []

		if multi_model_flag and multi_model_allocation:
			unified_tray_table = build_unified_tray_table_multi_model(
				multi_model_allocation,
				computed,
				lot_data['lot_qty'],
				lot_data['jig_capacity'],
				lot_data['tray_capacity']
			)
			split_panel = build_split_panel_data_multi_model(
				multi_model_allocation,
				computed,
				lot_data['lot_qty'],
				lot_data['jig_capacity'],
				lot_data['tray_capacity']
			)
		else:
			unified_tray_table = build_unified_tray_table(
				computed,
				lot_data['lot_qty'],
				lot_data['jig_capacity'],
				lot_data.get('model_image_label', ''),
				lot_data['tray_capacity']
			)
			split_panel = build_split_panel_data(
				computed,
				lot_data['lot_qty'],
				lot_data['jig_capacity'],
				lot_data.get('model_image_label', ''),
				lot_data['tray_capacity']
			)

		logging.info(json.dumps({
			'event': 'JIG_LOAD_UPDATE_UNIFIED_TABLE',
			'lot_id': lot_id,
			'batch_id': batch_id,
			'action': action,
			'rows': len(unified_tray_table),
			'is_multi_model': bool(multi_model_flag),
			'model_count': len(multi_model_allocation) if multi_model_allocation else 1,
		}))

		response = {
			'lot_id': lot_id,
			'batch_id': batch_id,
			'lot_qty': lot_data['lot_qty'],
			'total_qty': computed['total_qty'],
			'total_multi_model_qty': total_multi_model_qty,
			'tray_count': computed['tray_count'],
			'jig_capacity': lot_data['jig_capacity'],
			'original_capacity': lot_data['jig_capacity'],
			'broken_hooks': broken_hooks,
			'placeholders': {
				'jig_id': 'Enter Jig ID (e.g. J{:03d}-0000)'.format(int(lot_data.get('jig_capacity', 0) or 0)),
				'tray_scan': 'Scan or enter tray ID',
			},
			'effective_capacity': computed['effective_capacity'],
			'loaded_cases_qty': loaded_cases_qty,
			'empty_hooks': empty_hooks,
			'delink_tray_info': computed['delink_tray_info'],
			'delink_trays': computed['delink_tray_info'],
			'delink_tray_qty': computed['delink_tray_qty'],
			'excess_info': computed['excess_info'],
			'excess_qty': mm_excess_qty,
			'half_filled_tray_info': half_filled,
			'half_filled': half_filled,
			'half_filled_tray_qty': computed.get('half_filled_tray_qty', 0),
			'delink_completed': delink_completed,
			'tray_capacity': lot_data['tray_capacity'],
			'model_image_url': lot_data['model_image_url'],
			'model_image_label': lot_data['model_image_label'],
			'nickel_bath_type': lot_data['nickel_bath_type'],
			'tray_type': lot_data['tray_type'],
			'is_multi_model': bool(multi_model_flag),
			'multi_model_allocation': multi_model_allocation,
			'secondary_lots': secondary_lots,
			'unified_tray_table': unified_tray_table,
			'split_panel': split_panel,
			'validation': computed['validation'],
			'planned_empty_hooks': planned_empty_hooks,
			'bh_editable': True,
		}
		if scan_result:
			response.update(scan_result)
		return Response(response)


class JigLoadSubmitAPI(APIView):
	"""POST /api/jig/load/submit/ — Final submission: validate, create JigCompleted, lock jig."""
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request):
		payload = request.data
		lot_id = payload.get('lot_id')
		batch_id = payload.get('batch_id')
		jig_id = payload.get('jig_id')
		broken_hooks = int(payload.get('broken_hooks', 0) or 0)
		jig_capacity_override = payload.get('jig_capacity')
		scanned_trays = payload.get('scanned_trays', [])
		remarks = payload.get('remarks', '')
		multi_model_flag = payload.get('multi_model', False)
		secondary_lots = payload.get('secondary_lots', [])
		primary_lot_id = payload.get('primary_lot_id', lot_id)
		primary_batch_id = payload.get('primary_batch_id', batch_id)

		if not lot_id or not batch_id or not jig_id:
			return Response(
				{'status': 'error', 'message': 'lot_id, batch_id, and jig_id are required'},
				status=status.HTTP_400_BAD_REQUEST
			)

		# Normalize jig_id to uppercase
		jig_id = jig_id.strip().upper()

		logging.info(json.dumps({
			'event': 'JIG_LOAD_SUBMIT',
			'lot_id': lot_id, 'batch_id': batch_id, 'jig_id': jig_id
		}))

		# Final computation
		lot_data = fetch_lot_data(lot_id, batch_id, jig_capacity_override)

		# --- Jig ID Format Validation ---
		# Must be "J" + 3-digit zero-padded capacity + "-" + 4 digits (e.g. J098-0000 for 98, J144-0000 for 144)
		jig_capacity_val = int(lot_data.get('jig_capacity', 0) or 0)
		expected_jig_id = f'J{jig_capacity_val:03d}-'
		if not jig_id.startswith(expected_jig_id):
			return Response(
				{'status': 'error', 'message': f'Invalid Jig ID. Expected format: {expected_jig_id}#### (e.g. {expected_jig_id}0000) for capacity {jig_capacity_val}.'},
				status=status.HTTP_400_BAD_REQUEST
			)
		if len(jig_id) != 9 or not jig_id[5:].isdigit():
			return Response(
				{'status': 'error', 'message': f'Invalid Jig ID format. Must be 9 characters: J###-#### (e.g. {expected_jig_id}0000).'},
				status=status.HTTP_400_BAD_REQUEST
			)

		# --- Jig ID Uniqueness Check ---
		# Ensure jig is not already loaded by another lot/batch/user
		already_loaded = JigCompleted.objects.filter(
			jig_id=jig_id, draft_status='submitted'
		).exclude(
			batch_id=batch_id, lot_id=lot_id, user=request.user
		).exists()
		if already_loaded:
			return Response(
				{'status': 'error', 'message': f'Jig {jig_id} is already in use. Please unload it before reuse.'},
				status=status.HTTP_409_CONFLICT
			)
		jig_obj_loaded = Jig.objects.filter(jig_qr_id=jig_id, is_loaded=True).exclude(
			current_user=request.user, batch_id=batch_id, lot_id=lot_id
		).exists()
		if jig_obj_loaded:
			return Response(
				{'status': 'error', 'message': f'Jig {jig_id} is currently loaded. Unload before reuse.'},
				status=status.HTTP_409_CONFLICT
			)
		# Multi-model: aggregate trays from ALL lots for correct computation
		if multi_model_flag and secondary_lots:
			trays = aggregate_multi_model_trays(primary_lot_id, secondary_lots)
			logging.info(f"[SUBMIT_MM] Aggregated {len(trays)} trays from primary={primary_lot_id} + {len(secondary_lots)} secondary lots")
		else:
			trays = fetch_trays_for_lot(lot_id)
		computed = compute_jig_loading(trays, lot_data['jig_capacity'], broken_hooks, lot_data['tray_capacity'])

		if computed['validation']['errors']:
			return Response(
				{'status': 'error', 'message': 'Validation failed', 'errors': computed['validation']['errors']},
				status=status.HTTP_400_BAD_REQUEST
			)

		loaded_cases_qty = sum(int(s.get('qty', 0) or 0) for s in scanned_trays)

		# 🔥 OVERRIDE: derive loaded from DELINK PLAN (backend = source of truth)
		scanned_ids_submit = set(s.get('tray_id', '') for s in scanned_trays if s.get('tray_id'))
		delink_plan_submit = {dt['tray_id']: dt['qty'] for dt in computed['delink_tray_info']}
		loaded_cases_qty = sum(delink_plan_submit.get(sid, 0) for sid in scanned_ids_submit)

		# 🔥 STRICT CAPACITY ENFORCEMENT: loaded qty must NEVER exceed effective capacity
		if loaded_cases_qty > computed['effective_capacity']:
			return Response(
				{'status': 'error', 'message': f'Loaded qty ({loaded_cases_qty}) exceeds effective capacity ({computed["effective_capacity"]}). Cannot submit.'},
				status=status.HTTP_400_BAD_REQUEST
			)

		# Validate jig not locked by another user
		try:
			jig = Jig.objects.filter(jig_qr_id=jig_id).first()
			if jig and jig.is_locked_by_other_user(request.user):
				return Response(
					{'status': 'error', 'message': f'Jig {jig_id} is locked by another user'},
					status=status.HTTP_409_CONFLICT
				)
		except Exception:
			pass

		# Collect half-filled tray data from payload (outside try for scope)
		half_filled_trays = payload.get('half_filled_trays', [])
		is_multi_model = bool(payload.get('is_multi_model', False))
		multi_model_allocation_data = payload.get('multi_model_allocation', [])

		# Build no_of_model_cases: compact per-model qty string for admin display
		no_of_model_cases_str = ''
		if is_multi_model and multi_model_allocation_data:
			parts = []
			for m in multi_model_allocation_data:
				label = m.get('model_image_label') or m.get('model') or m.get('display_name', '')
				lot = m.get('lot_id', '')
				qty = m.get('allocated_qty') or m.get('qty', 0)
				parts.append(f"{label}({lot}):{qty}")
			no_of_model_cases_str = ' | '.join(parts)

		# Create JigCompleted record
		try:
			# Compute half-filled summary — at submit time, delink IS complete, assign tray IDs
			half_filled_computed = computed.get('half_filled_tray_info', {})
			if isinstance(half_filled_computed, dict) and half_filled_computed.get('exists'):
				excess_trays_submit = computed.get('excess_info', {}).get('excess_trays', [])
				half_filled_computed = assign_half_filled_tray_ids(
					half_filled_computed, computed['delink_tray_info'],
					excess_trays_submit, lot_data['tray_capacity']
				)
			# Use frontend-sent half_filled if provided (user may have overridden tray IDs)
			half_filled_info = half_filled_trays if half_filled_trays else half_filled_computed
			half_filled_qty = sum(int(t.get('qty', 0) or 0) for t in half_filled_trays) if half_filled_trays else computed.get('half_filled_tray_qty', 0)

			# For multi-model, build combined plating_stock_num from all models
			effective_plating_stk = lot_data['model_image_label']
			if is_multi_model and multi_model_allocation_data:
				model_names = []
				for m in multi_model_allocation_data:
					mn = m.get('model') or m.get('model_name') or m.get('display_name', '')
					if mn:
						model_names.append(mn)
				if model_names:
					effective_plating_stk = ', '.join(model_names)

			# loaded_cases_qty for JigCompleted = delink_tray_qty (what was actually loaded)
			actual_loaded = computed['delink_tray_qty']

			JigCompleted.objects.update_or_create(
				batch_id=batch_id, lot_id=lot_id, user=request.user,
				defaults={
					'jig_id': jig_id,
					'jig_capacity': lot_data['jig_capacity'],
					'broken_hooks': broken_hooks,
					'loaded_cases_qty': actual_loaded,
					'original_lot_qty': lot_data['lot_qty'],
					'delink_tray_info': computed['delink_tray_info'],
					'delink_tray_qty': computed['delink_tray_qty'],
					'delink_tray_count': len(computed['delink_tray_info']),
					'draft_status': 'submitted',
					'plating_stock_num': effective_plating_stk,
					'remarks': remarks,
					'is_multi_model': is_multi_model,
					'effective_capacity': computed['effective_capacity'],
					'tray_capacity': lot_data['tray_capacity'],
					'nickel_bath_type': lot_data['nickel_bath_type'],
					'tray_type': lot_data['tray_type'],
					'half_filled_tray_info': half_filled_info,
					'half_filled_tray_qty': half_filled_qty,
					'multi_model_allocation': multi_model_allocation_data,  # full tray-level detail
					'no_of_model_cases': no_of_model_cases_str or None,
					'scanned_trays': scanned_trays,
					'empty_hooks': max(0, computed['effective_capacity'] - loaded_cases_qty),
					'excess_qty': computed.get('excess_qty', 0),
					'draft_data': {
						'scanned_trays': scanned_trays,
						'jig_id': jig_id,
						'half_filled_trays': half_filled_trays,
						'multi_model_allocation': multi_model_allocation_data,
					},
				}
			)
		except Exception as e:
			logging.exception(f'JigLoadSubmitAPI: save failed: {e}')
			return Response(
				{'status': 'error', 'message': 'Failed to save submission'},
				status=status.HTTP_500_INTERNAL_SERVER_ERROR
			)

		# Lock jig
		try:
			jig = Jig.objects.filter(jig_qr_id=jig_id).first()
			if jig:
				jig.is_loaded = True
				jig.current_user = request.user
				jig.locked_at = timezone.now()
				jig.drafted = False
				jig.batch_id = batch_id
				jig.lot_id = lot_id
				jig.save()
		except Exception:
			logging.exception('JigLoadSubmitAPI: jig lock failed')

		# Mark draft as submitted
		try:
			JigLoadingManualDraft.objects.filter(
				batch_id=batch_id, lot_id=lot_id, user=request.user
			).update(draft_status='submitted')
		except Exception:
			pass

		logging.info(json.dumps({
			'event': 'JIG_LOAD_SUBMITTED',
			'lot_id': lot_id, 'batch_id': batch_id, 'jig_id': jig_id,
			'loaded_cases_qty': loaded_cases_qty,
			'effective_capacity': computed['effective_capacity']
		}))

		return Response({
			'status': 'success',
			'message': 'Jig loading submitted successfully',
			'lot_id': lot_id,
			'batch_id': batch_id,
			'jig_id': jig_id,
			'loaded_cases_qty': loaded_cases_qty,
			'effective_capacity': computed['effective_capacity'],
			'delink_completed': True,
			'half_filled': half_filled_info,
			'model_image_label': lot_data.get('model_image_label', ''),
			'lot_qty': lot_data.get('lot_qty', 0),
			'no_of_model_cases': no_of_model_cases_str if is_multi_model else None,
		})


# Jig Loading - Complete Table View
@method_decorator(login_required, name='dispatch')
class JigCompletedTable(TemplateView):
	"""Completed jigs table — displays all submitted/finalized jigs."""
	template_name = "JigLoading/Jig_CompletedTable.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		
		# Fetch all JigCompleted records with draft_status='submitted'
		jig_completed_records = JigCompleted.objects.filter(
			draft_status='submitted'
		).select_related('user').order_by('-updated_at')
		
		# Process each record and enrich with TotalStockModel data
		jig_details = []
		for jig_rec in jig_completed_records:
			try:
				# Fetch stock model data for enrichment (plating color, polish finish, etc.)
				stock_model = None
				try:
					stock_model = TotalStockModel.objects.get(lot_id=jig_rec.lot_id)
				except TotalStockModel.DoesNotExist:
					pass
				
				# Build multi-model allocation string as comma-separated model_name:qty
				# Template expects: "model1:qty1,model2:qty2,model3:qty3" for split(",") and get_model_name/get_model_qty filters
				no_of_model_cases_str = ''
				if jig_rec.is_multi_model and jig_rec.multi_model_allocation:
					try:
						models_list = []
						for m in jig_rec.multi_model_allocation:
							if isinstance(m, dict):
								model_name = m.get('model_name', m.get('model', ''))
								qty = m.get('allocated_qty', 0)
								if model_name:
									models_list.append(f"{model_name}:{qty}")
						no_of_model_cases_str = ','.join(models_list) if models_list else ''
					except Exception as e:
						logging.warning(f"Failed to process multi_model_allocation: {e}")
				
				# Extract plating stock no — for multi-model, combine all model names
				plating_stock_num = jig_rec.plating_stock_num or ''
				if jig_rec.is_multi_model and jig_rec.multi_model_allocation:
					try:
						plating_models = []
						for m in jig_rec.multi_model_allocation:
							if isinstance(m, dict):
								model_name = m.get('model_name', m.get('model', ''))
								if model_name:
									plating_models.append(model_name)
						if plating_models:
							plating_stock_num = ', '.join(plating_models)
					except Exception:
						pass
				
				# Build enriched record
				# Use delink_tray_qty as total_cases_loaded (the actual loaded qty, not the stale loaded_cases_qty)
				enriched = {
					'id': jig_rec.id,
					'lot_id': jig_rec.lot_id,
					'batch_id': jig_rec.batch_id,
					'jig_id': jig_rec.jig_id,
					'jig_loaded_date_time': jig_rec.updated_at,
					'is_multi_model': jig_rec.is_multi_model,
					'no_of_model_cases': no_of_model_cases_str,
					'lot_plating_stk_nos': plating_stock_num,
					'lot_polishing_stk_nos': getattr(stock_model, 'lot_polishing_stk_nos', 'N/A') if stock_model else 'N/A',
					'plating_color': getattr(stock_model, 'plating_color', 'N/A') if stock_model else 'N/A',
					'polish_finish': getattr(stock_model, 'polish_finish', 'N/A') if stock_model else 'N/A',
					'lot_version_names': getattr(stock_model, 'lot_version_names', 'N/A') if stock_model else 'N/A',
					'tray_type': jig_rec.tray_type or 'N/A',
					'tray_capacity': jig_rec.tray_capacity or 0,
					'calculated_no_of_trays': jig_rec.delink_tray_count or 0,
					'total_cases_loaded': jig_rec.delink_tray_qty or jig_rec.loaded_cases_qty or 0,
					'jig_type': 'Jig',
					'jig_capacity': jig_rec.jig_capacity or 0,
					'jig_qr_id': f"J{jig_rec.jig_id[-3:]}" if jig_rec.jig_id else '',
					'half_filled_tray_qty': jig_rec.half_filled_tray_qty or 0,
					'draft_status': jig_rec.draft_status,
					'original_lot_qty': jig_rec.original_lot_qty or 0,
					'delink_tray_info': json.dumps(jig_rec.delink_tray_info or []),
					'half_filled_tray_info': json.dumps(jig_rec.half_filled_tray_info or []),
					'excess_qty': jig_rec.excess_qty or 0,
					'multi_model_allocation': jig_rec.multi_model_allocation or [],
				}
				jig_details.append(enriched)
				
			except Exception as e:
				logging.exception(f"Error processing JigCompleted record {jig_rec.id}: {e}")
				continue
		
		# Pagination
		from django.core.paginator import Paginator
		page_number = self.request.GET.get('page', 1)
		paginator = Paginator(jig_details, 10)  # 10 records per page
		page_obj = paginator.get_page(page_number)
		
		context['jig_details'] = page_obj
		context['page_obj'] = page_obj
		context['completed_list'] = jig_details  # Keep for backwards compatibility
		
		logging.info(f"[JIG COMPLETED] Loaded {len(jig_details)} submitted jigs for display")
		
		return context


# =============================================================================
# MODEL COMBINATION VALIDATION API
# =============================================================================

class ModelCombinationValidateAPI(APIView):
	"""POST /api/model-combination/validate/
	Validate which models can be added alongside the already-selected models.
	Always returns HTTP 200 — errors are in the response body.

	Input:  { "selected_models": ["2617SAA02"] }
	Output: { "eligible_models": [...], "non_eligible_models": [...],
	          "blocked_lookalike_plating_stk_nos": [...],
	          "warnings": [...], "errors": [...] }
	"""
	permission_classes = [IsAuthenticated]

	def post(self, request):
		try:
			body = request.data if hasattr(request, 'data') else {}
			selected_models = body.get('selected_models', [])
			if not isinstance(selected_models, list):
				selected_models = [str(selected_models)] if selected_models else []

			logging.info(f'[MODEL_COMBINATION_VALIDATE] POST from user={request.user} selected_models={selected_models}')

			from .model_combination_validator import validate_model_combination
			result = validate_model_combination(selected_models)

			logging.info(f'[MODEL_COMBINATION_VALIDATE] eligible={len(result["eligible_models"])} '
				f'non_eligible={len(result["non_eligible_models"])} '
				f'blocked_lookalike={len(result["blocked_lookalike_plating_stk_nos"])} '
				f'errors={result["errors"]}')

			return Response(result, status=status.HTTP_200_OK)

		except Exception as e:
			logging.exception(f'[MODEL_COMBINATION_VALIDATE] Unhandled exception: {e}')
			return Response({
				'eligible_models': [],
				'non_eligible_models': [],
				'blocked_lookalike_plating_stk_nos': [],
				'warnings': [],
				'errors': [f'Validation error: {str(e)}'],
			}, status=status.HTTP_200_OK)


# =============================================================================
# NEW CLEAN APIs — EXACT FRONTEND SNAPSHOT STORAGE
# =============================================================================

class JigSaveDraftAPI(APIView):
	"""POST /api/jig/save — Store full UI snapshot as DRAFT.
	
	No recomputation. Stores exactly what the frontend sends.
	On re-open, returns the same data for UI rehydration.
	"""
	permission_classes = [IsAuthenticated]

	def post(self, request):
		payload = request.data
		lot_id = payload.get('lot_id')
		batch_id = payload.get('batch_id')
		jig_id = payload.get('jig_id', '') or ''

		if not lot_id or not batch_id:
			return Response({'status': 'error', 'message': 'lot_id and batch_id are required'}, status=status.HTTP_400_BAD_REQUEST)

		# Extract EXACT UI values — no recalculation
		lot_qty = int(payload.get('lot_qty', 0) or 0)
		jig_capacity = int(payload.get('jig_capacity', 0) or 0)
		effective_capacity = int(payload.get('effective_capacity', 0) or 0)
		broken_hooks = int(payload.get('broken_hooks', 0) or 0)
		loaded_cases_qty = int(payload.get('loaded_cases_qty', 0) or 0)
		empty_hooks = int(payload.get('empty_hooks', 0) or 0)
		tray_data = payload.get('tray_data', [])
		total_delink_qty = int(payload.get('total_delink_qty', 0) or 0)
		total_excess_qty = int(payload.get('total_excess_qty', 0) or 0)
		scanned_trays = payload.get('scanned_trays', [])
		multi_model_allocation = payload.get('multi_model_allocation', [])
		half_filled_tray_info = payload.get('half_filled_tray_info', [])
		is_multi_model = bool(payload.get('is_multi_model', False))
		nickel_bath_type = payload.get('nickel_bath_type', '') or ''
		tray_type = payload.get('tray_type', '') or ''
		tray_capacity = int(payload.get('tray_capacity', 12) or 12)
		plating_stock_num = payload.get('plating_stock_num', '') or ''
		remarks = payload.get('remarks', '') or ''

		logging.info(json.dumps({
			'event': 'JIG_SAVE_DRAFT',
			'lot_id': lot_id, 'batch_id': batch_id, 'jig_id': jig_id,
			'lot_qty': lot_qty, 'jig_capacity': jig_capacity,
			'total_delink_qty': total_delink_qty, 'total_excess_qty': total_excess_qty,
			'tray_count': len(tray_data), 'scanned_count': len(scanned_trays),
			'payload_keys': list(payload.keys()),
		}))

		# Validation — sums must be consistent
		validation_errors = []
		sum_orig = sum(int(t.get('original_qty', 0) or 0) for t in tray_data)
		sum_delink = sum(int(t.get('delink_qty', 0) or 0) for t in tray_data)
		sum_excess = sum(int(t.get('excess_qty', 0) or 0) for t in tray_data)

		# Per-tray integrity: delink + excess must equal original across all trays
		if sum_orig > 0 and (sum_delink + sum_excess) != sum_orig:
			validation_errors.append(f'sum(delink_qty)+sum(excess_qty)={sum_delink + sum_excess} != sum(original_qty)={sum_orig}')
		if sum_delink != total_delink_qty:
			validation_errors.append(f'sum(delink_qty)={sum_delink} != total_delink_qty={total_delink_qty}')
		if sum_excess != total_excess_qty:
			validation_errors.append(f'sum(excess_qty)={sum_excess} != total_excess_qty={total_excess_qty}')

		if validation_errors:
			logging.warning(json.dumps({'event': 'JIG_SAVE_DRAFT_VALIDATION_WARN', 'errors': validation_errors}))
			# Warn but don't block — draft should always save

		try:
			record, created = JigLoadingRecord.objects.update_or_create(
				lot_id=lot_id, batch_id=batch_id, user=request.user,
				defaults={
					'jig_id': jig_id.strip().upper() if jig_id else None,
					'lot_qty': lot_qty,
					'jig_capacity': jig_capacity,
					'effective_capacity': effective_capacity,
					'broken_hooks': broken_hooks,
					'loaded_cases_qty': loaded_cases_qty,
					'empty_hooks': empty_hooks,
					'nickel_bath_type': nickel_bath_type,
					'tray_type': tray_type,
					'tray_capacity': tray_capacity,
					'plating_stock_num': plating_stock_num,
					'remarks': remarks,
					'is_multi_model': is_multi_model,
					'tray_data': tray_data,
					'total_delink_qty': total_delink_qty,
					'total_excess_qty': total_excess_qty,
					'scanned_trays': scanned_trays,
					'multi_model_allocation': multi_model_allocation,
					'half_filled_tray_info': half_filled_tray_info,
					'status_flag': 'DRAFT',
				}
			)
			logging.info(json.dumps({
				'event': 'JIG_DRAFT_STORED',
				'record_id': record.id, 'created': created,
				'lot_id': lot_id, 'batch_id': batch_id,
				'tray_count': len(tray_data),
				'total_delink_qty': total_delink_qty,
				'total_excess_qty': total_excess_qty,
			}))
		except Exception as e:
			logging.exception(f'JigSaveDraftAPI: save failed: {e}')
			return Response({'status': 'error', 'message': 'Failed to save draft'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

		return Response({
			'status': 'success',
			'message': 'Draft saved successfully',
			'record_id': record.id,
			'lot_id': lot_id,
			'batch_id': batch_id,
			'status_flag': 'DRAFT',
		})

	def get(self, request):
		"""GET /api/jig/save?lot_id=X&batch_id=Y — Fetch existing draft for rehydration."""
		lot_id = request.query_params.get('lot_id')
		batch_id = request.query_params.get('batch_id')

		if not lot_id or not batch_id:
			return Response({'status': 'error', 'message': 'lot_id and batch_id required'}, status=status.HTTP_400_BAD_REQUEST)

		record = JigLoadingRecord.objects.filter(
			lot_id=lot_id, batch_id=batch_id, user=request.user, status_flag='DRAFT'
		).first()

		if not record:
			return Response({'status': 'not_found', 'message': 'No draft found'}, status=status.HTTP_404_NOT_FOUND)

		return Response({
			'status': 'success',
			'record_id': record.id,
			'status_flag': record.status_flag,
			'jig_id': record.jig_id or '',
			'lot_id': record.lot_id,
			'batch_id': record.batch_id,
			'lot_qty': record.lot_qty,
			'jig_capacity': record.jig_capacity,
			'effective_capacity': record.effective_capacity,
			'broken_hooks': record.broken_hooks,
			'loaded_cases_qty': record.loaded_cases_qty,
			'empty_hooks': record.empty_hooks,
			'nickel_bath_type': record.nickel_bath_type or '',
			'tray_type': record.tray_type or '',
			'tray_capacity': record.tray_capacity,
			'plating_stock_num': record.plating_stock_num or '',
			'remarks': record.remarks or '',
			'is_multi_model': record.is_multi_model,
			'tray_data': record.tray_data,
			'total_delink_qty': record.total_delink_qty,
			'total_excess_qty': record.total_excess_qty,
			'scanned_trays': record.scanned_trays,
			'multi_model_allocation': record.multi_model_allocation,
			'half_filled_tray_info': record.half_filled_tray_info,
			'updated_at': record.updated_at.isoformat() if record.updated_at else None,
		})


class JigSubmitFinalAPI(APIView):
	"""POST /api/jig/submit-final — Submit jig with full snapshot + delink + excess lot creation.
	
	Steps:
	1. Update JigLoadingRecord.status_flag = 'SUBMITTED'
	2. Create JigDelinkRecord for each tray with delink_qty > 0
	3. Create ExcessLotRecord + ExcessLotTray for trays with excess_qty > 0
	4. Lock jig + update JigCompleted (for backward compat)
	
	NO RECOMPUTATION. All data from frontend payload.
	"""
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request):
		payload = request.data
		lot_id = payload.get('lot_id')
		batch_id = payload.get('batch_id')
		jig_id = (payload.get('jig_id', '') or '').strip().upper()

		if not lot_id or not batch_id or not jig_id:
			return Response({'status': 'error', 'message': 'lot_id, batch_id, and jig_id are required'}, status=status.HTTP_400_BAD_REQUEST)

		# Extract EXACT UI values — NO recomputation
		lot_qty = int(payload.get('lot_qty', 0) or 0)
		jig_capacity = int(payload.get('jig_capacity', 0) or 0)
		effective_capacity = int(payload.get('effective_capacity', 0) or 0)
		broken_hooks = int(payload.get('broken_hooks', 0) or 0)
		loaded_cases_qty = int(payload.get('loaded_cases_qty', 0) or 0)
		empty_hooks = int(payload.get('empty_hooks', 0) or 0)
		tray_data = payload.get('tray_data', [])
		total_delink_qty = int(payload.get('total_delink_qty', 0) or 0)
		total_excess_qty = int(payload.get('total_excess_qty', 0) or 0)
		scanned_trays = payload.get('scanned_trays', [])
		multi_model_allocation = payload.get('multi_model_allocation', [])
		half_filled_tray_info = payload.get('half_filled_tray_info', [])
		is_multi_model = bool(payload.get('is_multi_model', False))
		nickel_bath_type = payload.get('nickel_bath_type', '') or ''
		tray_type = payload.get('tray_type', '') or ''
		tray_capacity = int(payload.get('tray_capacity', 12) or 12)
		plating_stock_num = payload.get('plating_stock_num', '') or ''
		remarks = payload.get('remarks', '') or ''

		logging.info(json.dumps({
			'event': 'JIG_SUBMIT_FINAL',
			'lot_id': lot_id, 'batch_id': batch_id, 'jig_id': jig_id,
			'lot_qty': lot_qty, 'jig_capacity': jig_capacity,
			'total_delink_qty': total_delink_qty, 'total_excess_qty': total_excess_qty,
			'tray_count': len(tray_data), 'scanned_count': len(scanned_trays),
		}))

		# ===== VALIDATION (sum checks — no recomputation) =====
		validation_errors = []
		sum_orig = sum(int(t.get('original_qty', 0) or 0) for t in tray_data)
		sum_delink = sum(int(t.get('delink_qty', 0) or 0) for t in tray_data)
		sum_excess = sum(int(t.get('excess_qty', 0) or 0) for t in tray_data)

		# Per-tray integrity: delink + excess must equal original across all trays
		# NOTE: For multi-model, lot_qty is the primary model's qty, but tray_data
		# spans ALL models. So sum(original_qty) != lot_qty is expected.
		# The correct check is: sum(delink) + sum(excess) == sum(original).
		if sum_orig > 0 and (sum_delink + sum_excess) != sum_orig:
			validation_errors.append(f'sum(delink_qty)+sum(excess_qty)={sum_delink + sum_excess} != sum(original_qty)={sum_orig}')
		if sum_delink != total_delink_qty:
			validation_errors.append(f'sum(delink_qty)={sum_delink} != total_delink_qty={total_delink_qty}')
		if sum_excess != total_excess_qty:
			validation_errors.append(f'sum(excess_qty)={sum_excess} != total_excess_qty={total_excess_qty}')

		if validation_errors:
			logging.error(json.dumps({'event': 'JIG_SUBMIT_VALIDATION_FAILED', 'errors': validation_errors}))
			return Response({
				'status': 'error',
				'message': 'Validation failed: data integrity mismatch',
				'errors': validation_errors,
			}, status=status.HTTP_400_BAD_REQUEST)

		# ===== Jig ID validations =====
		lot_data = fetch_lot_data(lot_id, batch_id, jig_capacity)
		jig_capacity_val = int(lot_data.get('jig_capacity', 0) or 0) or jig_capacity
		expected_jig_prefix = f'J{jig_capacity_val:03d}-'
		if not jig_id.startswith(expected_jig_prefix):
			return Response({
				'status': 'error',
				'message': f'Invalid Jig ID. Expected format: {expected_jig_prefix}#### for capacity {jig_capacity_val}.',
			}, status=status.HTTP_400_BAD_REQUEST)
		if len(jig_id) != 9 or not jig_id[5:].isdigit():
			return Response({
				'status': 'error',
				'message': f'Invalid Jig ID format. Must be 9 characters: J###-####.',
			}, status=status.HTTP_400_BAD_REQUEST)

		# Jig uniqueness check
		already_loaded = JigCompleted.objects.filter(
			jig_id=jig_id, draft_status='submitted'
		).exclude(batch_id=batch_id, lot_id=lot_id, user=request.user).exists()
		if already_loaded:
			return Response({'status': 'error', 'message': f'Jig {jig_id} is already in use.'}, status=status.HTTP_409_CONFLICT)
		jig_obj_loaded = Jig.objects.filter(jig_qr_id=jig_id, is_loaded=True).exclude(
			current_user=request.user, batch_id=batch_id, lot_id=lot_id
		).exists()
		if jig_obj_loaded:
			return Response({'status': 'error', 'message': f'Jig {jig_id} is currently loaded.'}, status=status.HTTP_409_CONFLICT)

		# Check jig not locked by another user
		jig = Jig.objects.filter(jig_qr_id=jig_id).first()
		if jig and jig.is_locked_by_other_user(request.user):
			return Response({'status': 'error', 'message': f'Jig {jig_id} is locked by another user.'}, status=status.HTTP_409_CONFLICT)

		# ===== STEP 1: Save/Update JigLoadingRecord with status_flag='SUBMITTED' =====
		try:
			record, _ = JigLoadingRecord.objects.update_or_create(
				lot_id=lot_id, batch_id=batch_id, user=request.user,
				defaults={
					'jig_id': jig_id,
					'lot_qty': lot_qty,
					'jig_capacity': jig_capacity,
					'effective_capacity': effective_capacity,
					'broken_hooks': broken_hooks,
					'loaded_cases_qty': loaded_cases_qty,
					'empty_hooks': empty_hooks,
					'nickel_bath_type': nickel_bath_type,
					'tray_type': tray_type,
					'tray_capacity': tray_capacity,
					'plating_stock_num': plating_stock_num,
					'remarks': remarks,
					'is_multi_model': is_multi_model,
					'tray_data': tray_data,
					'total_delink_qty': total_delink_qty,
					'total_excess_qty': total_excess_qty,
					'scanned_trays': scanned_trays,
					'multi_model_allocation': multi_model_allocation,
					'half_filled_tray_info': half_filled_tray_info,
					'status_flag': 'SUBMITTED',
				}
			)
			logging.info(json.dumps({'event': 'JIG_SUBMIT_RECORD_SAVED', 'record_id': record.id}))
		except Exception as e:
			logging.exception(f'JigSubmitFinalAPI: record save failed: {e}')
			return Response({'status': 'error', 'message': 'Failed to save submission record'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

		# ===== STEP 2: Create JigDelinkRecord entries =====
		delink_created = 0
		try:
			# Clear old delink records for this submission
			JigDelinkRecord.objects.filter(jig_loading_record=record).delete()

			for tray in tray_data:
				d_qty = int(tray.get('delink_qty', 0) or 0)
				if d_qty <= 0:
					continue
				# Find matching scanned tray to get actual scanned ID
				tray_id = tray.get('tray_id', '')
				scanned_id = tray_id  # default
				for st in scanned_trays:
					if st.get('tray_id', '') and st.get('lot_id', '') == tray.get('source_lot_id', lot_id):
						# Match by position in same lot or by tray_id reference
						pass
				# Try direct match from scanned list
				for st in scanned_trays:
					scan_tid = st.get('tray_id', '')
					if scan_tid:
						scanned_id = scan_tid
						break

				JigDelinkRecord.objects.create(
					jig_loading_record=record,
					jig_id=jig_id,
					lot_id=tray.get('source_lot_id', '') or lot_id,
					batch_id=batch_id,
					tray_id=tray_id,
					delink_qty=d_qty,
					original_qty=int(tray.get('original_qty', 0) or 0),
					model_code=tray.get('model_code', '') or plating_stock_num,
					scanned_tray_id=tray_id,
				)
				delink_created += 1

			logging.info(json.dumps({'event': 'JIG_DELINK_RECORDS_CREATED', 'count': delink_created, 'record_id': record.id}))
		except Exception as e:
			logging.exception(f'JigSubmitFinalAPI: delink records failed: {e}')
			return Response({'status': 'error', 'message': 'Failed to create delink records'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

		# ===== STEP 3: Create ExcessLotRecord + ExcessLotTray =====
		excess_lot_id = None
		excess_trays_created = 0
		if total_excess_qty > 0:
			try:
				# Generate excess lot ID: EX-<parent_lot>-<timestamp>
				import time
				ts = int(time.time() * 1000) % 100000
				excess_lot_id = f'EX-{lot_id}-{ts:05d}'

				# Ensure uniqueness
				while ExcessLotRecord.objects.filter(new_lot_id=excess_lot_id).exists():
					ts = (ts + 1) % 100000
					excess_lot_id = f'EX-{lot_id}-{ts:05d}'

				excess_lot = ExcessLotRecord.objects.create(
					jig_loading_record=record,
					new_lot_id=excess_lot_id,
					parent_lot_id=lot_id,
					parent_batch_id=batch_id,
					lot_qty=total_excess_qty,
					jig_id=jig_id,
				)

				for tray in tray_data:
					e_qty = int(tray.get('excess_qty', 0) or 0)
					if e_qty <= 0:
						continue
					ExcessLotTray.objects.create(
						excess_lot=excess_lot,
						lot_id=excess_lot_id,
						tray_id=tray.get('tray_id', ''),
						qty=e_qty,
						original_qty=int(tray.get('original_qty', 0) or 0),
						model_code=tray.get('model_code', '') or plating_stock_num,
					)
					excess_trays_created += 1

				logging.info(json.dumps({
					'event': 'JIG_EXCESS_LOT_CREATED',
					'new_lot_id': excess_lot_id,
					'parent_lot_id': lot_id,
					'lot_qty': total_excess_qty,
					'tray_count': excess_trays_created,
				}))
			except Exception as e:
				logging.exception(f'JigSubmitFinalAPI: excess lot creation failed: {e}')
				return Response({'status': 'error', 'message': 'Failed to create excess lot'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

		# ===== STEP 4: Lock Jig =====
		try:
			if jig:
				jig.is_loaded = True
				jig.current_user = request.user
				jig.locked_at = timezone.now()
				jig.drafted = False
				jig.batch_id = batch_id
				jig.lot_id = lot_id
				jig.save()
		except Exception:
			logging.exception('JigSubmitFinalAPI: jig lock failed')

		# ===== STEP 5: Backward compat — also update JigCompleted =====
		try:
			no_of_model_cases_str = ''
			# For multi-model, build combined plating_stock_num from all models (M1, M2, M3 format)
			effective_plating_stock_num = plating_stock_num
			if is_multi_model and multi_model_allocation:
				parts = []
				model_names = []
				for m in multi_model_allocation:
					label = m.get('model_image_label') or m.get('model') or m.get('display_name', '')
					mlot = m.get('lot_id', '')
					mqty = m.get('allocated_qty') or m.get('qty', 0)
					parts.append(f"{label}({mlot}):{mqty}")
					# Collect model names for plating_stock_num display
					model_name = m.get('model') or m.get('model_name') or m.get('display_name', '')
					if model_name:
						model_names.append(model_name)
				no_of_model_cases_str = ' | '.join(parts)
				if model_names:
					effective_plating_stock_num = ', '.join(model_names)

			# loaded_cases_qty for JigCompleted = total_delink_qty (what was actually loaded into jig)
			actual_loaded_cases = total_delink_qty

			JigCompleted.objects.update_or_create(
				batch_id=batch_id, lot_id=lot_id, user=request.user,
				defaults={
					'jig_id': jig_id,
					'jig_capacity': jig_capacity,
					'broken_hooks': broken_hooks,
					'loaded_cases_qty': actual_loaded_cases,
					'original_lot_qty': lot_qty,
					'delink_tray_info': [t for t in tray_data if int(t.get('delink_qty', 0) or 0) > 0],
					'delink_tray_qty': total_delink_qty,
					'delink_tray_count': delink_created,
					'draft_status': 'submitted',
					'plating_stock_num': effective_plating_stock_num,
					'remarks': remarks,
					'is_multi_model': is_multi_model,
					'effective_capacity': effective_capacity,
					'tray_capacity': tray_capacity,
					'nickel_bath_type': nickel_bath_type,
					'tray_type': tray_type,
					'half_filled_tray_info': half_filled_tray_info,
					'half_filled_tray_qty': sum(int(t.get('qty', 0) or 0) for t in half_filled_tray_info) if isinstance(half_filled_tray_info, list) else 0,
					'multi_model_allocation': multi_model_allocation,
					'no_of_model_cases': no_of_model_cases_str or None,
					'scanned_trays': scanned_trays,
					'empty_hooks': empty_hooks,
					'excess_qty': total_excess_qty,
					'draft_data': {
						'scanned_trays': scanned_trays,
						'jig_id': jig_id,
						'tray_data': tray_data,
						'half_filled_tray_info': half_filled_tray_info,
						'multi_model_allocation': multi_model_allocation,
					},
				}
			)
		except Exception:
			logging.exception('JigSubmitFinalAPI: JigCompleted backward compat failed (non-fatal)')

		# Mark old draft as submitted
		try:
			JigLoadingManualDraft.objects.filter(
				batch_id=batch_id, lot_id=lot_id, user=request.user
			).update(draft_status='submitted')
		except Exception:
			pass

		logging.info(json.dumps({
			'event': 'JIG_SUBMIT_FINAL_COMPLETE',
			'lot_id': lot_id, 'batch_id': batch_id, 'jig_id': jig_id,
			'loaded_cases_qty': loaded_cases_qty,
			'delink_records': delink_created,
			'excess_lot_id': excess_lot_id,
			'excess_trays': excess_trays_created,
			'record_id': record.id,
		}))

		return Response({
			'status': 'success',
			'message': 'Jig loading submitted successfully',
			'record_id': record.id,
			'lot_id': lot_id,
			'batch_id': batch_id,
			'jig_id': jig_id,
			'loaded_cases_qty': loaded_cases_qty,
			'effective_capacity': effective_capacity,
			'total_delink_qty': total_delink_qty,
			'total_excess_qty': total_excess_qty,
			'delink_records_created': delink_created,
			'excess_lot_id': excess_lot_id,
			'excess_trays_created': excess_trays_created,
		})


# =============================================================================
# JIG LOADING HOLD/UNHOLD API
# =============================================================================

class JigHoldToggleAPI(APIView):
	"""
	POST /api/hold-toggle/ — Save hold/unhold reason for jig loading
	
	Request:
	{
		"lot_id": "LID070420260947350002",
		"batch_id": "BATCH-20260407094059434767-84",
		"action": "hold" or "unhold",
		"reason": "Quality issue" (required for hold, optional for unhold)
	}
	
	Response:
	{
		"success": true/false,
		"hold_status": true/false,
		"message": "Lot moved to hold" or "Lot released from hold"
	}
	"""
	permission_classes = [IsAuthenticated]

	def post(self, request):
		try:
			data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
			lot_id = data.get('lot_id', '').strip()
			batch_id = data.get('batch_id', '').strip()
			action = data.get('action', '').strip().lower()
			reason = data.get('reason', '').strip()

			# ===== VALIDATION =====
			if not lot_id:
				return Response({'success': False, 'error': 'lot_id is required'}, status=status.HTTP_400_BAD_REQUEST)
			if not batch_id:
				return Response({'success': False, 'error': 'batch_id is required'}, status=status.HTTP_400_BAD_REQUEST)
			if action not in ['hold', 'unhold']:
				return Response({'success': False, 'error': 'action must be hold or unhold'}, status=status.HTTP_400_BAD_REQUEST)
			if action == 'hold' and not reason:
				return Response({'success': False, 'error': 'reason is required for hold action'}, status=status.HTTP_400_BAD_REQUEST)

			# ===== FETCH LOT =====
			lot_obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
			if not lot_obj:
				return Response({'success': False, 'error': 'Lot not found'}, status=status.HTTP_404_NOT_FOUND)

			# ===== UPDATE LOT STATUS =====
			logging.info(json.dumps({
				'event': 'JIG_HOLD_TOGGLE',
				'lot_id': lot_id,
				'batch_id': batch_id,
				'action': action,
				'user': request.user.username,
			}))

			if action == 'hold':
				lot_obj.jig_hold_lot = True
				lot_obj.jig_holding_reason = reason
				# clear any previous release flags when newly holding
				lot_obj.jig_release_lot = False
				lot_obj.jig_release_reason = ''
				message = 'Lot moved to hold'
				hold_status = True
			else:  # unhold
				# mark as released; preserve previous holding reason and record release reason if provided
				lot_obj.jig_hold_lot = False
				if reason:
					lot_obj.jig_release_lot = True
					lot_obj.jig_release_reason = reason
				else:
					# still mark as released even if no explicit reason provided
					lot_obj.jig_release_lot = True
					lot_obj.jig_release_reason = ''
				message = 'Lot released from hold'
				hold_status = False

			lot_obj.save(update_fields=['jig_hold_lot', 'jig_holding_reason', 'jig_release_lot', 'jig_release_reason'])

			logging.info(json.dumps({
				'event': 'JIG_HOLD_TOGGLE_COMPLETE',
				'lot_id': lot_id,
				'action': action,
				'hold_status': hold_status,
			}))

			return Response({
				'success': True,
				'hold_status': hold_status,
				'message': message,
			}, status=status.HTTP_200_OK)

		except Exception as e:
			logging.error(f'JigHoldToggleAPI error: {str(e)}')
			return Response({
				'success': False,
				'error': str(e)
			}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


