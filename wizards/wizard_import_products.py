# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class WizardImportOrders(models.TransientModel):
    _name = "amazon.products.import.wizard"
    _description = "Amazon Import Products Wizard"

    def import_inventory(self):
        backend_id = self._context.get('active_ids', [])
        try:
            if backend_id:
                backend = self.env['amazon.backend'].browse(backend_id)
                backend._import_product_product()

        except Exception as e:
            raise e
