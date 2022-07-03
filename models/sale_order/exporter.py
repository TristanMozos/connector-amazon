# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2022 Halltic Tech S.L. (https://www.halltic.com)
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

import re
import math
from lxml import etree as ET
from collections import Counter
from datetime import datetime

from odoo.addons.component.core import Component

from ..config.common import AMAZON_DEFAULT_PERCENTAGE_FEE, AMAZON_COSINE_NAME_MIN_VALUE

WORD = re.compile(r'\w+')


class SaleShipmentConfirmExporter(Component):
    _name = 'amazon.sale.shipment.confirm.exporter'
    _inherit = 'amazon.exporter'
    _usage = 'amazon.sale.shipment.export'
    _apply_on = ['amazon.product.product']

    def run(self, prod_stock):
        """ Change the stock on Amazon.

        :param records: list of dictionaries of products with structure [{'sku': sku1, 'Quantity': 3, 'id_mws': market_id},{...}]
        """
        feed_binding_model = self.env['amazon.feed']
        feed_binding_model.export_batch(backend=self.backend_record,
                                        filters={'method':'submit_confirm_order', 'arguments':[prod_stock]})


class SaleExporter(Component):
    _name = 'amazon.sale.order.exporter'
    _inherit = 'base.exporter'
    _usage = 'amazon.sale.export'
    _apply_on = 'amazon.sale.order'

    def run(self, records):
        """ Change the prices on Amazon.
        :param records: list of dictionaries of products with structure
        """
        feed_exporter = self.env['amazon.feed']
        return feed_exporter.export_batch(backend=self.backend_record,
                                          filters={'method':'submit_add_inventory_request',
                                                   'arguments':[records]})

    def _add_sales_to_confirm(self, record):
        product = self.env['product.product'].browse(record['product_id'])
        marketplaces = record['marketplaces'] if record.get('marketplaces') else self.backend_record.marketplace_ids
        margin = record['margin'] if record.get('margin') else self.backend_record.max_margin
        asin = record['asin'] if record.get('asin') else None

        product_doesnt_exist = True
        product_dont_match = False

        # We get the user language for match with the marketplace language
        user = self.env['res.users'].browse(self.env.uid)
        market_lang_match = marketplaces.filtered(lambda marketplace:marketplace.lang_id.code == user.lang)

        if market_lang_match and not asin:
            amazon_prod = self._get_asin_product(product, market_lang_match)
            asin = amazon_prod['asin'] if amazon_prod and amazon_prod.get('asin') else None
            product_dont_match = True if amazon_prod and amazon_prod.get('Match name') == 'No' else False

        for marketplace in marketplaces:
            # If we haven't asin and we haven't searched yet, we search this
            if not asin and market_lang_match and market_lang_match.id != marketplace.id:
                amazon_prod = self._get_asin_product(product, market_lang_match)
                asin = amazon_prod['asin'] if amazon_prod and amazon_prod.get('asin') else None
                product_dont_match = True if amazon_prod and amazon_prod.get('Match name') == 'No' else False

            add_product = False if not asin else True

            if not add_product:
                continue

            product_doesnt_exist = False

            row = {}
            row['sku'] = product.default_code or product.product_variant_id.default_code
            row['product-id'] = asin
            row['product-id-type'] = 'ASIN'
            price = product._calc_amazon_price(backend=self.backend_record,
                                               margin=margin,
                                               marketplace=marketplace,
                                               percentage_fee=AMAZON_DEFAULT_PERCENTAGE_FEE)
            row['price'] = ("%.2f" % price).replace('.', marketplace.decimal_currency_separator) if price else ''
            row['minimum-seller-allowed-price'] = ''
            row['maximum-seller-allowed-price'] = ''
            row['item-condition'] = '11'  # We assume the products are new
            row['quantity'] = '0'  # The products stocks allways is 0 when we export these
            row['add-delete'] = 'a'
            row['will-ship-internationally'] = ''
            row['expedited-shipping'] = ''
            row['merchant-shipping-group-name'] = ''
            handling_time = product._compute_amazon_handling_time() or ''
            row['handling-time'] = str(handling_time) if price else ''
            row['item_weight'] = ''
            row['item_weight_unit_of_measure'] = ''
            row['item_volume'] = ''
            row['item_volume_unit_of_measure'] = ''
            row['id_mws'] = marketplace.id_mws

            vals = {'backend_id':self.backend_record.id,
                    'type':'_POST_FLAT_FILE_INVLOADER_DATA_',
                    'model':product._name,
                    'identificator':product.id,
                    'data':row,
                    }
            self.env['amazon.feed.tothrow'].create(vals)

        if product_doesnt_exist and not product_dont_match:
            # TODO Create a list of products to create
            vals = {'product_id':product.product_tmpl_id.id}
            self.env['amazon.report.product.to.create'].create(vals)
            return

    @api.model
    def run(self, record):
        """ Change the prices on Amazon.
        :param records: list of dictionaries of products with structure
        """
        assert record
        if record.get('method'):
            if record['method'] == 'add_to_amazon_listing':
                assert record['product_id']
                self._add_listing_to_amazon(record)
