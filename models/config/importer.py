# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class ProductCategoryImporter(Component):
    _name = 'amazon.config.category.importer'
    _inherit = 'amazon.importer'
    _usage = 'amazon.config.category'

    def run(self, record):
        if record.marketplace_id:
            try:
                data = self.backend_adapter.get_category([record.sku, record.marketplace_id.id_mws])
            except Exception as e:
                data = None
            self._update_category(record, data)
