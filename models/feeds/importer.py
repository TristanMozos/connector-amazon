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
    _name = 'amazon.feed.batch.importer'
    _inherit = 'amazon.delayed.batch.importer'
    _apply_on = 'amazon.feed'

    def run(self, filters=None):
        """ Run the synchronization """
        result = None
        method = filters['method']
        assert method
        # {'method':'analize_product_exports', 'feed_ids':ids, 'products':list_products, 'backend':self.backend_id}
        if method == 'analize_product_exports':
            # TODO analize feed report from filters['feed_ids']
            try:
                assert filters
                backend = filters['backend']
                products = filters['products']
                # On the products list, it is possible that there are one same product per each marketplace
                if products:
                    # To prevent duplicates sku, we are going to save on a aux dict the sku values to import
                    aux_dict = {}
                    product_binding_model = self.env['amazon.product.product']
                    for product in products:
                        if not aux_dict.get(product['sku']):
                            delayable = product_binding_model.with_delay(priority=5, eta=datetime.now())
                            delayable.import_record(backend, product['sku'])
                            aux_dict[product['sku']] = True
                else:
                    _logger.info('search for amazon products %s has returned nothing',
                                 filters, products.keys())
            except AssertionError:
                _logger.error('There aren\'t report ids parameters for %s', method)
                raise

        return result


class ReportImporter(Component):
    _name = 'amazon.feed.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.feed']
