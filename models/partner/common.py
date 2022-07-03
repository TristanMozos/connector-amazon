# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2022 Halltic Tech S.L. (https://www.halltic.com)
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

from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import Job

_logger = logging.getLogger(__name__)


class AmazonResPartner(models.Model):
    _name = 'amazon.res.partner'
    _inherit = 'amazon.binding'
    _inherits = {'res.partner':'odoo_id'}
    _description = 'Amazon Partner'

    odoo_id = fields.Many2one(comodel_name='res.partner',
                              string='Customer',
                              required=True,
                              ondelete='restrict')

    alias = fields.Char()

    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonResPartner, self)
        return _super.import_record(backend, external_id)


class AmazonPartnerAdapter(Component):
    _name = 'amazon.res.partner.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.res.partner'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.res.partner',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )
    get_supplier_stock = fields.Selection(string='Get supplier stock?', selection=[('1', 'Yes'), ('0', 'No'), ])

    automatic_export_products = fields.Boolean('Automatic export new products to Amazon?', default=False)
    backend_id = fields.Many2one('amazon.backend')
    automatic_export_all_markets = fields.Boolean('Automatic export to all backend markets?')
