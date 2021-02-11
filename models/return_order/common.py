# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2021 Halltic eSolutions S.L. (https://www.halltic.com)
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

from odoo import models, fields

_logger = logging.getLogger(__name__)


class AmazonOrderReturn(models.Model):
    _name = 'amazon.order.return'
    _inherit = 'amazon.binding'
    _description = 'Amazon Return'

    backend_id = fields.Many2one('amazon.backend', "Backend", required=True)  # Backend
    id_return_amz = fields.Char('id_return_amz', required=True)
    date_return = fields.Datetime('date_return', required=True)
