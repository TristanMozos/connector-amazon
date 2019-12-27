# -*- coding: utf-8 -*-
# Copyright 2017 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from odoo import _
from odoo.addons.component.core import Component


class ProductStockExporter(Component):
    _name = 'amazon.product.stock.exporter'
    _inherit = 'amazon.exporter'
    _usage = 'amazon.product.stock.export'
    _apply_on = ['amazon.product.product']

    def run(self, prod_stock):
        """ Change the stock on Amazon.

        :param records: list of dictionaries of products with structure [{'sku': sku1, 'Quantity': 3, 'id_mws': market_id},{...}]
        """
        feed_binding_model = self.env['amazon.feed']
        feed_binding_model.export_batch(backend=self.backend_record,
                                        filters={'method':'submit_stock_update', 'arguments':[prod_stock]})


class ProductStockPriceExporter(Component):
    _name = 'amazon.product.stock.price.exporter'
    _inherit = 'amazon.exporter'
    _usage = 'amazon.product.stock.price.export'
    _apply_on = 'amazon.product.product'

    def run(self, records):
        """ Change the stock, prices and handling time on Amazon.
        :param records: list of dictionaries of products with structure [{'sku': sku1, 'price': 3.99, 'currency': 'EUR', 'id_mws': market_id},{...}]
        """
        feed_exporter = self.env['amazon.feed']
        feed_exporter.export_batch(backend=self.backend_record,
                                   filters={'method':'submit_stock_price_update',
                                            'arguments':records})  # Test one product


class ProductProductExporter(Component):
    _name = 'amazon.product.product.exporter'
    _inherit = 'base.exporter'
    _usage = 'amazon.product.export'
    _apply_on = 'amazon.product.product'

    def run(self, records):
        """ Change the prices on Amazon.
        :param records: list of dictionaries of products with structure
        """
        feed_exporter = self.env['amazon.feed']
        return feed_exporter.export_batch(backend=self.backend_record,
                                          filters={'method':'submit_add_inventory_request',
                                                   'arguments':[records]})
