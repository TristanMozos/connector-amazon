# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2018 Halltic eSolutions S.L. (https://www.halltic.com)
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
