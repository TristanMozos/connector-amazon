# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2018 Halltic eSolutions S.L. (https://www.halltic.com)
#                  Tristán Mozos <tristan.mozos@halltic.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

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
