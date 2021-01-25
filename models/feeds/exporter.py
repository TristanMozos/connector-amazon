# -*- coding: utf-8 -*-
# Copyright 2017 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

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
