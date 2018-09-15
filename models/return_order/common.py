# -*- coding: utf-8 -*-
# Copyright 2013-2017 Camptocamp SA
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class AmazonOrderReturn(models.Model):
    _name = 'amazon.order.return'
    _inherit = 'amazon.binding'
    _description = 'Amazon Return'

    backend_id = fields.Many2one('amazon.backend', "Backend", required=True)  # Backend
    id_return_amz = fields.Char('id_return_amz', required=True)
    date_return = fields.Datetime('date_return', required=True)
