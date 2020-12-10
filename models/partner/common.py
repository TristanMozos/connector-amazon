# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# This project is based on connector-magneto, developed by Camptocamp SA

import logging

from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import job

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

    @job(default_channel='root.amazon')
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
    amz_automatic_set_margins = fields.Boolean('Automatic set margins')
    amz_change_prices = fields.Selection(string='Change prices', selection=[('1', 'Yes'), ('0', 'No'), ])
    amz_min_margin = fields.Float('Minimal margin', default=None)
    amz_max_margin = fields.Float('Maximal margin', default=None)
    amz_min_price_margin_value = fields.Float('Min price margin value', digits=(3, 2))

