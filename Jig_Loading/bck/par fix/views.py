from django.views.generic import *
from modelmasterapp.models import *
from .models import Jig, JigLoadingMaster, JigLoadTrayId, JigLoadingManualDraft, JigCompleted
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
		# Try batch first
		batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
		if batch_obj:
			plating_stk = getattr(batch_obj, 'plating_stk_no', '') or getattr(batch_obj, 'model_stock_no', '')
			return str(plating_stk) if plating_stk else f"Model-{lot_id}"
		
		# Fallback to lot-based lookup
		stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
		if stock and hasattr(stock, 'batch_id'):
			batch = getattr(stock, 'batch_id', None)
			if batch:
				plating_stk = getattr(batch, 'plating_stk_no', '')
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
		mm = None
		batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
		if batch_obj:
			mm = getattr(batch_obj, 'model_stock_no', None) or batch_obj
		if not mm:
			stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
			if stock and hasattr(stock, 'batch_id'):
				b = getattr(stock, 'batch_id', None)
				if b:
					mm = getattr(b, 'model_stock_no', None) or b
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
			result['model_image_label'] = getattr(mm, 'plating_stk_no', '') or getattr(mm, 'model_no', '') or ''
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
			base_qs = TotalStockModel.objects.filter(brass_audit_accptance=True).select_related('batch_id')
			# Optional exclusion: when JigView is opened to "Add Model", exclude the primary lot
			exclude_lot = self.request.GET.get('exclude_lot_id')
			primary_lot = self.request.GET.get('primary_lot_id') or self.request.GET.get('primary_lot')
			try:
				total_before = base_qs.count()
				logging.info(f"[JIG PICK] Total before exclude: {total_before}")
			except Exception:
				logging.info("[JIG PICK] Unable to count base_qs before exclude")
			if exclude_lot:
				base_qs = base_qs.exclude(lot_id=exclude_lot)
			try:
				final_count = base_qs.count()
				logging.info(f"[JIG PICK] Excluding lot: {exclude_lot} (primary: {primary_lot}) -> Final count: {final_count}")
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
					'jig_hold_lot': False,
					'jig_holding_reason': '',
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
			context['master_data'] = master_data
			# master_data provided to template; no extra JSON needed
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
					'top_tray': bool(getattr(t, 'is_top_tray', False) or False),
					'rejected': bool(getattr(t, 'is_rejected', False) or False),
					'delinked': bool(getattr(t, 'is_delinked', False) or False),
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
					'allocated_qty': primary_result['allocated_qty'],
					'tray_info': primary_result['tray_info'],
					'model_image_url': primary_img['model_image_url'],
					'model_image_label': primary_img['model_image_label'],
				})
				logging.info(f"[MULTI_MODEL] Primary {lot_id}: {primary_result['allocated_qty']} qty")
			except Exception as e:
				logging.exception(f"[MULTI_MODEL] Primary allocation failed: {e}")

			# STEP 2: SECONDARY MODEL ALLOCATIONS
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

					secondary_result = allocate_trays_for_model(
						lot_id=sec_lot_id,
						model_lot_qty=sec_lot_qty,
						effective_capacity_remaining=capacity_remaining,
						used_tray_ids=used_tray_ids
					)
					used_tray_ids.update(secondary_result['allocated_tray_ids'])
					sec_img = fetch_model_image_metadata(sec_lot_id, sec_batch_id)
					multi_model_allocation.append({
						'model': fetch_model_metadata(sec_lot_id, sec_batch_id),
						'model_name': fetch_model_metadata(sec_lot_id, sec_batch_id),
						'model_role': 'secondary',
						'lot_id': sec_lot_id,
						'batch_id': sec_batch_id,
						'sequence': seq,
						'allocated_qty': secondary_result['allocated_qty'],
						'tray_info': secondary_result['tray_info'],
						'model_image_url': sec_img['model_image_url'],
						'model_image_label': sec_img['model_image_label'],
					})
					logging.info(f"[MULTI_MODEL] Secondary {sec_lot_id}: {secondary_result['allocated_qty']} qty")
				except Exception as e:
					logging.exception(f"[MULTI_MODEL] Secondary allocation failed for {sec.get('lot_id')}: {e}")
					continue

			# Validation: no duplicate tray IDs across models
			all_tray_ids = [t['tray_id'] for m in multi_model_allocation for t in m['tray_info']]
			if len(all_tray_ids) != len(set(all_tray_ids)):
				logging.error("[MULTI_MODEL] VALIDATION FAILED: Duplicate tray IDs detected!")
			logging.info(f"[MULTI_MODEL] Final: {len(multi_model_allocation)} models, {len(all_tray_ids)} total trays")

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


		# ===== CALCULATE SERVER-AUTHORITATIVE LOADED_CASES_QTY AND EMPTY_HOOKS ==
		loaded_cases_qty = 0
		# 🔥 FIX: Use the broken_hooks value calculated earlier (from GET param OR draft)
		broken_hooks_int = int(broken_hooks or 0)  # This already includes GET param logic
		jig_capacity_int = int(jig_capacity or 0)
		lot_qty_int = int(lot_qty or 0)

		# No need to recalculate broken_hooks_int - use the value from earlier

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
			# BEFORE SCAN: use lot-based calculation
			if lot_qty_int < effective_capacity:
				empty_hooks = effective_capacity - lot_qty_int
			else:
				empty_hooks = 0

		logging.info(f"[BACKEND_STATE] lot={lot_qty_int}, cap={jig_capacity_int}, broken={broken_hooks_int}, loaded={loaded_cases_qty}, empty={empty_hooks}")

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
			# ===== NEW: MULTI-MODEL ALLOCATION (when multi_model flag is set) =====
			'multi_model_allocation': multi_model_allocation if multi_model_flag else [],
			# Flattened tray list from all models for FE delink binding in multi-model mode
			'ui_delink_tray_info': ui_delink_tray_info if ui_delink_tray_info else [],
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

# Jig Loading - Complete Table View
@method_decorator(login_required, name='dispatch')
class JigCompletedTable(TemplateView):
	"""Minimal completed table view to satisfy template reverse lookups."""
	template_name = "JigLoading/Jig_CompletedTable.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		# Provide minimal context if template expects any variables
		context.setdefault('completed_list', [])
		return context


