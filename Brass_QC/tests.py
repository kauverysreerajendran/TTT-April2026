import json
from django.test import TestCase, RequestFactory
from Brass_QC.views import brass_reject_check_tray_id_simple
from Brass_QC.models import BrassTrayId
from modelmasterapp.models import (
    ModelMaster, ModelMasterCreation, TrayId, TrayType, Version,
    PolishFinishType, TotalStockModel
)


class BrassQcReuseLimitTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

        # Reference data
        tray_type = TrayType.objects.create(tray_type="Jumbo", tray_capacity=12)
        version = Version.objects.create(version_name="V1")
        model_master = ModelMaster.objects.create(
            model_no="M-001",
            ep_bath_type="EP",
            tray_type=tray_type,
            tray_capacity=12,
            version="v1"
        )
        polish_finish = PolishFinishType.objects.create(
            polish_finish="PF1",
            polish_internal="PF1"
        )

        # Batch/master
        self.batch = ModelMasterCreation.objects.create(
            batch_id="BATCH-001",
            lot_id="LOT-001",
            model_stock_no=model_master,
            polish_finish="PF1",
            ep_bath_type="EP",
            tray_type="Jumbo",
            tray_capacity=12,
            version=version,
            total_batch_quantity=101,
            no_of_trays=9
        )

        # Stock for lot
        self.stock = TotalStockModel.objects.create(
            batch_id=self.batch,
            model_stock_no=model_master,
            version=version,
            total_stock=101,
            polish_finish=polish_finish,
            lot_id="LOT-001",
            brass_physical_qty=101,
            brass_missing_qty=0
        )

        # Trays: 1 top tray (5), 8 full (12) => total 101
        tray_quantities = [5] + [12] * 8
        self.tray_ids = []
        for i, qty in enumerate(tray_quantities, start=1):
            tray_id = f"T{i:03d}"
            self.tray_ids.append(tray_id)
            BrassTrayId.objects.create(
                tray_id=tray_id,
                lot_id="LOT-001",
                batch_id=self.batch,
                tray_quantity=qty,
                tray_capacity=12,
                top_tray=(i == 1),
                rejected_tray=False,
                new_tray=False
            )
            TrayId.objects.create(
                tray_id=tray_id,
                lot_id="LOT-001",
                batch_id=self.batch,
                tray_quantity=qty,
                tray_capacity=12,
                new_tray=False,
                delink_tray=False
            )

    def test_reuse_limit_enforced(self):
        # 5 trays already used in the current session, total rejection = 61
        current_session_allocations = [{
            "reason_id": "R1",
            "qty": 61,
            "tray_ids": self.tray_ids[:5],
        }]

        request = self.rf.get(
            "/brass_qc/brass_reject_check_tray_id_simple/",
            {
                "tray_id": self.tray_ids[5],  # 6th tray attempt
                "lot_id": "LOT-001",
                "rejection_qty": 61,
                "total_rejection_qty": 61,
                "rejection_reason_id": "R1",
                "current_session_allocations": json.dumps(current_session_allocations),
            },
        )

        response = brass_reject_check_tray_id_simple(request)
        payload = json.loads(response.content.decode("utf-8"))

        self.assertFalse(payload.get("valid_for_rejection"))
        self.assertEqual(payload.get("status_message"), "Reuse Limit Reached")
