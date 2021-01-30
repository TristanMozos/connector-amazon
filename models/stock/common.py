# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2019 Halltic eSolutions S.L. (https://www.halltic.com)
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

from odoo import models, fields


class AmazonShippingTemplate(models.Model):
    _name = 'amazon.shipping.template'

    name = fields.Char(required=True)
    backend_id = fields.Many2one('amazon.backend', required=False)
    marketplace_id = fields.Many2one('amazon.config.marketplace', required=True)
    is_default = fields.Boolean('Is the default template', default=False)
    delivery_standard_carrier_ids = fields.Many2many(comodel_name='delivery.carrier',
                                                     string='Delivery carrier associated', )
    delivery_expedited_carrier_ids = fields.Many2many(comodel_name='delivery.carrier',
                                                      relation='amz_ship_template_carrier_expedited_rel',
                                                      column1='amazon_shipping_template_id',
                                                      column2='delivery_carrier_id',
                                                      string='Expedited delivery carrier associated', )
