from django.views.generic import *
from modelmasterapp.models import *
from .models import Jig, JigLoadingMaster, JigLoadTrayId, JigLoadingManualDraft, JigCompleted
from .services import JigLoadingService
from rest_framework.decorators import *
from django.http import JsonResponse
import logging
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

		# reuse TrayInfoView to get trays
		try:
			# create a fake request object reuse GET params
			trays_resp = TrayInfoView.as_view()(request._request)
			# if using as_view returned a Django response, attempt to parse
			try:
				data = json.loads(trays_resp.content)
				trays = data.get('trays', [])
			except Exception:
				trays = []
		except Exception:
			trays = []

		# If TrayInfoView returned no trays, try BrassAudit fallback directly to synthesize trays
		if not trays:
			try:
				# brass_audit_get_accepted_tray_scan_data expects a Django HttpRequest
				resp = brass_audit_get_accepted_tray_scan_data(request._request)
				if hasattr(resp, 'data'):
					adata = resp.data
				else:
					try:
						adata = json.loads(resp.content)
					except Exception:
						adata = {}

				tray_capacity = int(adata.get('tray_capacity', 16) or 16)
				available = int(adata.get('available_qty', 0) or 0)
				full_trays = available // tray_capacity if tray_capacity else 0
				top_tray_qty = available % tray_capacity if tray_capacity else 0
				counter = 1
				for i in range(full_trays):
					trays.append({
						'tray_id': f"NB-A{str(counter).zfill(5)}",
						'qty': tray_capacity,
						'top_tray': False,
						'rejected': False,
						'delinked': False,
						'is_placeholder': True,  # mark as synthetic - not a real scannable tray
					})
					counter += 1
				if top_tray_qty and top_tray_qty > 0:
					trays.append({
						'tray_id': f"NB-A{str(counter).zfill(5)}",
						'qty': top_tray_qty,
						'top_tray': True,
						'rejected': False,
						'delinked': False,
						'is_placeholder': True,  # mark as synthetic - not a real scannable tray
					})
			except Exception:
				logging.exception('InitJigLoad BrassAudit fallback failed')

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

			# `trays` expected earlier from TrayInfoView (do NOT modify tray fetch)
			remaining = int(delink_qty)
			tray_index = 0

			delink_tray_info = []
			excess_tray_info = []

			# Consume trays in strict FIFO order, splitting only the last used tray
			while remaining > 0 and tray_index < len(trays):

				tray = trays[tray_index]
				tray_id = tray.get('tray_id')
				tray_qty = int(tray.get('qty', 0) or 0)

				use_qty = min(tray_qty, remaining)
				balance_qty = tray_qty - use_qty

				# 🔹 DELINK ENTRY
				delink_tray_info.append({
					"tray_id": tray_id,
					"qty": use_qty,
					"top_tray": (remaining <= tray_capacity),
					"is_partial": balance_qty > 0
				})

				# 🔥 CRITICAL: SAME TRAY REUSED FOR EXCESS
				if balance_qty > 0:
					excess_tray_info.insert(0, {
						"tray_id": tray_id,
						"qty": balance_qty,
						"top_tray": True,
						"source": "partial_split"
					})

				remaining -= use_qty
				tray_index += 1

			# 🔹 REMAINING FULL TRAYS → EXCESS
			for i in range(tray_index, len(trays)):
				tray = trays[i]

				excess_tray_info.append({
					"tray_id": tray.get('tray_id'),
					"qty": tray.get('qty'),
					"top_tray": False,
					"source": "full_excess"
				})

				# Do NOT persist to draft here. Instead return stable computed values
				# to the frontend. The frontend will save the draft only when the user
				# explicitly clicks the Draft button.

			# Log final distribution info for debugging
			try:
				logging.info(f"[DELINK_SPLIT] Remaining after allocation: {remaining}")
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
		secondary_lots = []
		if multi_model_flag:
			try:
				secondary_lots = json.loads(request.GET.get('secondary_lots', '[]'))
			except Exception:
				secondary_lots = []
			logging.info(f"[MULTI_MODEL] Secondary lots: {secondary_lots}")

		# Build a non-persistent draft dict to return to the frontend
		resp_draft = {
			'batch_id': batch_id,
			'lot_id': lot_id,
			'original_lot_qty': int(lot_qty or 0),
			'jig_capacity': jig_capacity,
			'loaded_cases_qty': int(draft.loaded_cases_qty) if draft else 0,
			'delink_tray_info': draft.delink_tray_info if draft and draft.delink_tray_info else delink_tray_info,
			'delink_tray_qty': int(draft.delink_tray_qty) if draft else int(delink_qty or 0),
			'excess_qty': int(excess_qty or 0) if 'excess_qty' in locals() else 0,
			# model metadata
			'model_image_url': model_image_url,
			'model_image_label': model_image_label,
			'nickel_bath_type': nickel_bath_type,
			'tray_type': tray_type_name,
			'is_multi_model': True if multi_model_flag else False,
			'draft_data': {
				'primary_lot': lot_id,
				'secondary_lots': secondary_lots
			},
			'secondary_lots': secondary_lots,
		}

		# Calculate empty hooks based on business rule
		empty_hooks = 0
		try:
			lot_qty_int = int(lot_qty or 0)
			jig_capacity_int = int(jig_capacity or 0)
			_loaded = int(resp_draft.get('loaded_cases_qty', 0) or 0)
			_broken = int((draft.broken_hooks if draft and getattr(draft, 'broken_hooks', None) is not None else 0) or 0)
			
			# BUSINESS RULE: If lot_qty >= jig_capacity, empty_hooks = 0 (no calculation needed)
			if lot_qty_int >= jig_capacity_int:
				empty_hooks = 0
				logging.info(f"[EMPTY_HOOKS] lot_qty({lot_qty_int}) >= jig_capacity({jig_capacity_int}), empty_hooks=0")
			else:
				empty_hooks = max(0, jig_capacity_int - _loaded - _broken)
				logging.info(f"[EMPTY_HOOKS] lot_qty({lot_qty_int}) < jig_capacity({jig_capacity_int}), calculated empty_hooks={empty_hooks}")
			
			logging.info(f"[EMPTY_HOOKS_FINAL] capacity={jig_capacity_int}, loaded={_loaded}, broken={_broken}, result={empty_hooks}")
		except Exception:
			logging.exception('[EMPTY_HOOKS_CALC] Failed to calculate empty hooks')
			empty_hooks = 0

		return Response({
			'draft': resp_draft,
			'trays': trays,
			'lot_qty': int(lot_qty or 0),
			'empty_hooks': empty_hooks,
			'excess_qty': int(excess_qty or 0) if 'excess_qty' in locals() else 0,
			'excess_info': response_excess if 'response_excess' in locals() else {"excess_qty": 0, "excess_tray_count": 0, "excess_trays": []},
			# duplicate top-level metadata for compatibility
			'model_image_url': model_image_url,
			'model_image_label': model_image_label,
			'nickel_bath_type': nickel_bath_type,
			'tray_type': tray_type_name,
			'secondary_lots': secondary_lots,
			'scenario': 'PERFECT_FIT' if is_perfect_fit else '',
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

		# Validate tray exists in DB for this lot
		try:
			tray = JigLoadTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).first()
			if not tray:
				return Response({'status': 'error', 'message': 'Invalid tray or wrong lot'}, status=status.HTTP_400_BAD_REQUEST)
		except Exception:
			logging.exception('Error fetching tray')
			return Response({'status': 'error', 'message': 'Tray fetch error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

		tray_qty = int(tray.tray_quantity or 0)
		logging.info(f"Tray validated: {tray_id} (lot: {lot_id}) qty:{tray_qty}")

		# Persist scan to draft: update delink_tray_info, delink_tray_qty, loaded_cases_qty
		total_delink_qty = 0
		try:
			draft, _ = JigLoadingManualDraft.objects.get_or_create(
				batch_id=batch_id,
				lot_id=lot_id,
				user=request.user,
				defaults={'original_lot_qty': 0, 'jig_capacity': 0}
			)
			existing_info = list(draft.delink_tray_info or [])
			# Idempotent: skip if tray already recorded
			tray_already_in = any(
				(e.get('tray_id') if isinstance(e, dict) else None) == tray_id
				for e in existing_info
			)
			if not tray_already_in:
				existing_info.append({'tray_id': tray_id, 'qty': tray_qty})
			total_delink_qty = sum(
				int((e.get('qty') if isinstance(e, dict) else 0) or 0)
				for e in existing_info
			)
			draft.delink_tray_info = existing_info
			draft.delink_tray_qty = total_delink_qty
			draft.loaded_cases_qty = total_delink_qty
			draft.save(update_fields=['delink_tray_info', 'delink_tray_qty', 'loaded_cases_qty', 'updated_at'])
			logging.info(f"[SCAN_PERSISTED] tray={tray_id}, total={total_delink_qty}, entries={len(existing_info)}")
		except Exception:
			logging.exception('Failed to persist scan to draft')

		return Response({
			'status': 'success',
			'tray_id': tray_id,
			'tray_qty': tray_qty,
			'delink_tray_qty': total_delink_qty,
			'loaded_cases_qty': total_delink_qty,
		})

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


