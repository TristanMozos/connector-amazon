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

from odoo import api, _
from odoo.addons.component.core import Component


class FeedBatchExporter(Component):
    """
        Export the Amazon Feeds.

    """
    _name = 'amazon.feed.exporter'
    _inherit = 'amazon.batch.exporter'
    _apply_on = 'amazon.feed'

    def run(self, filters=None):
        """ Run the synchronization """
        result = None
        method = filters['method']
        arguments = filters['arguments']
        assert method

        if method in ('submit_stock_update',
                      'submit_price_update',
                      'submit_add_inventory_request',
                      'submit_stock_price_update',
                      'submit_confirm_shipment'):
            assert arguments
            result = self.backend_adapter.submit_feed(feed_name=method, arguments=arguments)
        elif method in ('get_feed_submission_result'):
            assert arguments
            result = self.backend_adapter.get_feed(feed_name=method, arguments=arguments)
        elif method == 'submit_feeds':
            result = self.backend_adapter.submit_feed(feed_name=method, arguments=None)

        return result

class AmazonSubmitFeeds(Component):
    _name = 'amazon.submit.feed.exporter'
    _inherit = 'amazon.exporter'
    _apply_on = 'amazon.feed'
    _usage = 'amazon.submit.feeds'



    def submit_feeds(self):
        feed_binding_model = self.env['amazon.feed']
        feed_binding_model.export_batch(backend=self.backend_record, filters={'method': 'submit_feeds', 'arguments': []})
