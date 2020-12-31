# -*- coding: utf-8 -*-
# Copyright 2013-2017 Camptocamp SA
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

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
