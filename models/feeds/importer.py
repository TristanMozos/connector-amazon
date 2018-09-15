# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping

from ...components.mapper import normalize_datetime

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
                external_ids = self.backend_adapter.get_report(filters)
                _logger.info('search for amazon products %s returned %s',
                             filters, external_ids.keys())
                product_binding_model = self.env['amazon.product.product']
                for external_id in external_ids.iteritems():
                    product_binding_model.import_record(self.backend_record, external_id)


            except AssertionError:
                _logger.error('There aren\'t report ids parameters for %s', method)
                raise
        elif method == 'submit_sales_request':
            result = self.backend_adapter.submit_report(report_name=method, filters=filters)
        elif method == 'get_sales':
            external_ids = self.backend_adapter.get_report(arguments=filters)
            _logger.info('get report of saleorders returned %s', external_ids.keys())
            sale_binding_model = self.env['amazon.sale.order']
            for external_id in external_ids.iteritems():
                sale_binding_model.import_record(self.backend_record, external_id)

        elif method == 'submit_updated_sales_request':
            result = self.backend_adapter.submit_report(report_name=method, filters=filters)
        elif method == 'get_updated_sales':
            self.backend_adapter.get_report(arguments=filters)

        return result


class ReportImporter(Component):
    _name = 'amazon.report.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.report']
