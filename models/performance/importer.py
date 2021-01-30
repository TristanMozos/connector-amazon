# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2020 Halltic eSolutions S.L. (https://www.halltic.com)
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
import re

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping, only_create

_logger = logging.getLogger(__name__)


class PartnerFeedbackImportMapper(Component):
    _name = 'amazon.partner.feedback.import.mapper'
    _inherit = 'amazon.import.mapper'
    _apply_on = 'amazon.res.partner.feedback'

    direct = [
        ('feedback_date', 'feedback_date'),
        ('qualification', 'qualification'),
        ('respond', 'respond'),
        ('message', 'message'),
    ]

    @mapping
    def amazon_sale_id(self, record):
        sale = self.env['amazon.sale.order'].search([('id_amazon_order','=',record['amazon_sale_id'])])
        return {'amazon_sale_id':sale.id}

    @mapping
    def backend_id(self, record):
        return {'backend_id': self.backend_record.id}

class PartnerFeedbackImporter(Component):
    _name = 'amazon.res.partner.feedback.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.res.partner.feedback']

    def _get_amazon_data(self):
        """ Return the raw Amazon data for ``self.external_id`` """
        return self.external_id[1]
