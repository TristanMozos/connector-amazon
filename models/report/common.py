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

import time
from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import Job

_logger = logging.getLogger(__name__)


class AmazonReport(models.Model):
    _name = 'amazon.report'
    _inherit = 'amazon.binding'
    _description = 'Amazon Return'

    @api.model
    def import_batch(self, backend, filters=None):
        _super = super(AmazonReport, self)
        return _super.import_batch(backend, filters=filters)


class AmazonReportAdapter(Component):
    _name = 'amazon.report.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.report'

    def submit_report(self, report_name, filters):
        return self._call(method=report_name, arguments=filters)

    def get_report(self, arguments):
        try:
            assert arguments
            return self._call(method=arguments.pop('method'), arguments=arguments['report_id'])
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_report')
            raise


class AmazonReportProductToCreate(models.Model):
    _name = 'amazon.report.product.to.create'

    product_id = fields.Many2one('product.template')
    name = fields.Char('name', related='product_id.name')
    barcode = fields.Char('barcode', related='product_id.barcode')
    category_on_amazon = fields.Char()


class AmazonReportProductRankingSales(models.Model):
    _name = 'amazon.report.product.ranking.sales'

    product_id = fields.Many2one('product.template')
    ranking_sales = fields.Char()
