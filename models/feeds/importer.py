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
                self.backend_adapter.get_feed(report_name='_get_result_add_products_csv', filters={})
            except AssertionError:
                _logger.error('There aren\'t report ids parameters for %s', method)
                raise

        return result


class FeedImporter(Component):
    _name = 'amazon.feed.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.feed']

    def run(self, filters=None):
        """ Get the feed result """
        result = self.backend_adapter.get_feed(feed_name='save_feed_response', arguments=[filters['feed_id']])
