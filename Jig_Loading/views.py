from django.views.generic import *
from modelmasterapp.models import *
from .models import Jig, JigLoadingMaster, JigLoadTrayId, JigLoadingManualDraft, JigCompleted
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
			qs = TotalStockModel.objects.filter(brass_audit_accptance=True).select_related('batch_id').order_by('-brass_audit_last_process_date_time')[:200]
			for stock in qs:
				batch = getattr(stock, 'batch_id', None)
				# Try to count accepted trays transferred/stored for this lot
				no_of_trays = 0
				try:
					from BrassAudit.models import Brass_Audit_Accepted_TrayID_Store
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
					from modelmasterapp.models import ModelMasterCreation
					model_obj = getattr(batch, 'model_stock_no', None) if batch else None
					if model_obj:
						master = JigLoadingMaster.objects.filter(model_stock_no=model_obj).first()
						if master and getattr(master, 'jig_capacity', None):
							data['jig_capacity'] = int(master.jig_capacity)
				except Exception:
					pass
				master_data.append(data)
			context['master_data'] = master_data
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
			from modelmasterapp.models import TotalStockModel
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
					from modelmasterapp.models import ModelMasterCreation
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
				from BrassAudit.views import brass_audit_get_accepted_tray_scan_data
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
					})
					counter += 1
				if top_tray_qty and top_tray_qty > 0:
					trays.append({
						'tray_id': f"NB-A{str(counter).zfill(5)}",
						'qty': top_tray_qty,
						'top_tray': True,
						'rejected': False,
						'delinked': False,
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
				from modelmasterapp.models import ModelMasterCreation
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
			# delink_qty = amount to fill the jig (cannot exceed lot or jig)
			delink_qty = min(lot_qty_int, jig_capacity_int)
			# excess_qty is remaining after jig is filled
			excess_qty = max(0, lot_qty_int - jig_capacity_int)
			# build delink trays by filling tray_capacity until delink_qty exhausted
			delink_tray_info = []
			if delink_qty > 0:
				delink_tray_count = ceil(delink_qty / tray_capacity) if tray_capacity else 0
				remaining = int(delink_qty)
				tray_no = 1
				while remaining > 0:
					qty = min(tray_capacity, remaining)
					delink_tray_info.append({
						"tray_no": tray_no,
						"qty": int(qty),
						"is_top_tray": True if qty < tray_capacity else False
					})
					remaining -= qty
					tray_no += 1
			else:
				delink_tray_count = 0

				# Do NOT persist to draft here. Instead return stable computed values
				# to the frontend. The frontend will save the draft only when the user
				# explicitly clicks the Draft button.

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
			from modelmasterapp.models import ModelMasterCreation
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
		}

		return Response({
			'draft': resp_draft,
			'trays': trays,
			'excess_qty': int(excess_qty or 0) if 'excess_qty' in locals() else 0,
			'excess_info': response_excess if 'response_excess' in locals() else {"excess_qty": 0, "excess_tray_count": 0, "excess_trays": []},
			# duplicate top-level metadata for compatibility
			'model_image_url': model_image_url,
			'model_image_label': model_image_label,
			'nickel_bath_type': nickel_bath_type,
			'tray_type': tray_type_name,
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


