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
        if method in ('submit_inventory_request', 'submit_sales_request', 'submit_feedbacks_report_request', 'submit_fee_product_request'):
            result = self.backend_adapter.submit_report(report_name=method, filters=filters)
            _logger.info('Submit report amazon returned id %s', result)
        elif method == 'get_inventory':
            import wdb
            wdb.set_trace()
            try:
                assert filters
                products = self.backend_adapter.get_report(filters)
                if products:
                    _logger.info('search for amazon products %s returned %s',
                                 filters, products.keys())
                    product_binding_model = self.env['amazon.product.product']
                    for product in products.items():
                        # We check if there are other tasks with the same data
                        # if not self.backend_record.check_same_import_jobs(model=product_binding_model._name,
                        #                                                  key=product[0] if isinstance(product, (tuple, list)) else product):
                        delayable = product_binding_model.with_delay(priority=5, eta=datetime.now())
                        delayable.description = '%s.impor_record(%s)' % (product_binding_model._name, product[0])
                        delayable.import_record(self.backend_record, product)
                else:
                    _logger.info('search for amazon products %s has returned nothing',
                                 filters, products.keys())
            except AssertionError:
                _logger.error('There aren\'t report ids parameters for %s', method)
                raise
        elif method == 'get_sales':
            sales = self.backend_adapter.get_report(arguments=filters)
            _logger.info('get report of saleorders returned %s', sales.keys())
            sale_binding_model = self.env['amazon.sale.order']
            for sale in sales.items():
                delayable = sale_binding_model.with_delay(priority=4, eta=datetime.now())
                delayable.import_record(self.backend_record, sale)
        elif method == 'get_customer_feedbacks':
            feedbacks = self.backend_adapter.get_report(arguments=filters)
            _logger.info('get report of customer feedbacks returned %s', feedbacks.keys())
            feedback_binding_model = self.env['amazon.res.partner.feedback']
            for feedback in feedbacks.items():
                delayable = feedback_binding_model.with_delay(priority=9, eta=datetime.now())
                delayable.import_record(self.backend_record, feedback)
        elif method == 'get_products_fee':
            # TODO test it
            products_fee = self.backend_adapter.get_report(arguments=filters)
            _logger.info('Get report of product fee returned %s', products_fee.keys())
            feedback_binding_model = self.env['amazon.res.partner.feedback']
            for feedback in products_fee.items():
                delayable = feedback_binding_model.with_delay(priority=9, eta=datetime.now())
                delayable.import_record(self.backend_record, feedback)

        return result


class ReportImporter(Component):
    _name = 'amazon.report.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.report']
