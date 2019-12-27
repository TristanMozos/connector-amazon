# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import datetime

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class ReportBatchImporter(Component):
    """ Import the Amazon Reports.

    """
    _name = 'amazon.report.batch.importer'
    _inherit = 'amazon.delayed.batch.importer'
    _apply_on = 'amazon.report'

    def run(self, filters=None):
        """ Run the synchronization """
        result = None
        method = filters['method']
        assert method
        if method == 'submit_inventory_request':
            result = self.backend_adapter.submit_report(report_name=method, filters=None)
            _logger.info('submit report amazon returned id %s', result)
        elif method == 'get_inventory':
            try:
                assert filters
                products = self.backend_adapter.get_report(filters)
                if products:
                    _logger.info('search for amazon products %s returned %s',
                                 filters, products.keys())
                    product_binding_model = self.env['amazon.product.product']
                    for product in products.iteritems():
                        delayable = product_binding_model.with_delay(priority=5, eta=datetime.now())
                        delayable.import_record(self.backend_record, product)
                else:
                    _logger.info('search for amazon products %s has returned nothing',
                                 filters, products.keys())
            except AssertionError:
                _logger.error('There aren\'t report ids parameters for %s', method)
                raise
        elif method == 'submit_sales_request':
            result = self.backend_adapter.submit_report(report_name=method, filters=filters)
        elif method == 'get_sales':
            sales = self.backend_adapter.get_report(arguments=filters)
            _logger.info('get report of saleorders returned %s', sales.keys())
            sale_binding_model = self.env['amazon.sale.order']
            for sale in sales.iteritems():
                delayable = sale_binding_model.with_delay(priority=5, eta=datetime.now())
                delayable.import_record(self.backend_record, sale)

        return result


class ReportImporter(Component):
    _name = 'amazon.report.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.report']
