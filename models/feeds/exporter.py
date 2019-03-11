# -*- coding: utf-8 -*-
# Copyright 2017 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from odoo import _
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
        assert arguments
        if method in ('submit_stock_update', 'submit_add_inventory_request', 'submit_stock_price_update'):
            result = self.backend_adapter.submit_feed(feed_name=method, arguments=arguments)

        return result
