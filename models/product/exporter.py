# -*- coding: utf-8 -*-
# Copyright 2017 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)
import logging
import re
import math
from collections import Counter
from datetime import datetime, timedelta

from odoo.addons.component.core import Component

from odoo import api
from odoo.addons.queue_job.exception import RetryableJobError

from ..config.common import AMAZON_DEFAULT_PERCENTAGE_FEE, AMAZON_COSINE_NAME_MIN_VALUE, AMAZON_DEFAULT_PERCENTAGE_MARGIN

WORD = re.compile(r'\w+')

_logger = logging.getLogger(__name__)


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

    @api.multi
    def get_products_to_recompute_prices(self, product, product_computed=[]):
        if product.type == 'product' and product.id not in product_computed:
            product_computed.append(product.id)
            # First, we are going up on the LoM relationship
            if product.bom_ids:
                for bom in product.bom_ids:
                    if bom.bom_line_ids:
                        for line_bom in bom.bom_line_ids:
                            self.get_products_to_recompute_prices(line_bom.product_id, product_computed=product_computed)
            # Second, we are going to search if any product have this product on LoM
            bom_childs = self.env['mrp.bom.line'].search([('product_id', '=', product.id)])
            if bom_childs:
                for line_bom in bom_childs:
                    self.get_products_to_recompute_prices(line_bom.bom_id.product_tmpl_id.product_variant_id, product_computed=product_computed)

    @api.multi
    def recompute_amazon_prices_product(self, first_product):
        """
        Recompute de price and stock on Amazon of product and all products on upper or lower relationship LoM
                         -- Prod1 --
                         |          |
                       Prod2      Prod3 --
                                          |
                                        Prod4 --> sale this
                                          |
                                        Prod5
        We need to update the price and stock on Amazon of all products from Prod1 to Prod5
        :param product: amazon product to change
        :param product_computed: control of product's computed for doesn't go to infinite loop
        :return:
        """
        product_computed = []
        detail_to_calc = []
        self.get_products_to_recompute_prices(first_product, product_computed)
        if product_computed:
            products = self.env['product.product'].browse(product_computed)
            for product in products:
                if product.type == 'product' and product.amazon_bind_ids:
                    for amazon_product in product.amazon_bind_ids:
                        backend = amazon_product.backend_id
                        if amazon_product.stock_sync or backend.stock_sync:
                            # We are going to get ids of product market data
                            for detail_id in amazon_product.product_product_market_ids.mapped('id'):
                                # If the id is not in the list we are going to add
                                if detail_id not in detail_to_calc:
                                    detail_to_calc.append(detail_id)

        if detail_to_calc:
            details = self.env['amazon.product.product.detail'].browse(detail_to_calc)
            for detail in details:
                # Change price
                self.calc_price_to_export(id_detail=detail.id)

    @api.multi
    def _get_offers_from_mws(self, detail):
        try:
            importer = self.work.component(usage='amazon.product.offers.import')
            importer.run(detail)
        except Exception as e:
            return

    @api.multi
    def up_price_with_buybox(self, detail):
        """
        The method is going to consider the next cases to up the prices:
                    Yesterday offer     Today offer
        Seller 1            9,5              9,5
        Seller 2            10               12
        Seller 3            13               13

                    Yesterday offer     Today offer
        Seller 1            9,5              10
        Seller 2            10               12
        Seller 3            13               13

        If our last price is lower than the current price the change is not executed

        :param detail:
        :return: True if the price has been changed
        """
        # We need to know if it is posible up the price
        current_offers = detail.get_current_offers()
        our_offer = None

        if not current_offers:
            self._get_offers_from_mws(detail)

        if current_offers:
            our_offer = current_offers.filtered('is_our_offer')
        else:
            try:
                return
            except Exception as e:
                return

        if not our_offer and current_offers:
            our_offer = current_offers.filtered(lambda offer:offer.id_seller == detail.product_id.backend_id.seller)

        # If we have more than one offer we are going to get one
        if len(our_offer) > 1:
            aux = None
            for offer in our_offer:
                if offer.total_price == (detail.price + detail.price_ship):
                    aux = offer
            if aux:
                our_offer = aux
            else:
                our_offer = our_offer[0]
                our_offer.price = detail.price
                our_offer.price_ship = detail.price_ship

        # if we have the unique offer, we change the price to margin max price
        if our_offer == current_offers:
            margin_max = detail.max_margin or detail.product_id.max_margin or detail.product_id.backend_id.max_margin
            try_price = detail.product_id.odoo_id._calc_amazon_price(backend=detail.product_id.backend_id,
                                                                     margin=margin_max,
                                                                     marketplace=detail.marketplace_id,
                                                                     percentage_fee=detail.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                     ship_price=detail.price_ship)

            # The price will be changed on listener TODO test it
            detail.price = try_price
            return True

        last_our_offer = None
        # Check if we have two or more historic offers
        if detail.historic_offer_ids and len(detail.historic_offer_ids) > 1:
            last_our_offer = detail.historic_offer_ids.sorted('offer_date', reverse=True)[1].offer_ids.filtered('is_our_offer')
            if not last_our_offer:
                last_our_offer = detail.historic_offer_ids.sorted('offer_date', reverse=True)[1].offer_ids.filtered(
                    lambda offer:offer.id_seller == detail.product_id.backend_id.seller)

        # We need to know if we have the offer duplicated
        if len(last_our_offer) > 1:
            # TODO do something for a right management of the duplicate offers (several offers with the same ASIN but diferent SKU
            last_our_offer = last_our_offer[0]

        # If we need to low the offer, we don't do anything
        if not last_our_offer or last_our_offer.total_price > our_offer.total_price:
            return

        # Get the best offer from other sellers
        lower_current_compet_offer = None
        for offer in current_offers:
            if not offer.is_our_offer and (not lower_current_compet_offer or lower_current_compet_offer > offer.total_price):
                lower_current_compet_offer = offer.total_price

        # When we have the competitive other seller offer
        if lower_current_compet_offer:
            lower_last_compet_offer = None
            # We get the last offers of the ad
            if detail.historic_offer_ids and len(detail.historic_offer_ids) > 1:
                last_offers = detail.historic_offer_ids.sorted('offer_date', reverse=True)[1].offer_ids

            # We get the lower competitive offer from other seller on the last ad
            for offer in last_offers:
                if not offer.is_our_offer and (not lower_last_compet_offer or lower_last_compet_offer > offer.total_price):
                    lower_last_compet_offer = offer.total_price

            # If we have the lower last price from other seller and the difference between current competitive offer and last competivice offer from
            # others sellers is higher than 0, we up our price this difference if it is between our margins
            if lower_last_compet_offer and lower_current_compet_offer - lower_last_compet_offer > 0:
                try_price = detail.price + (lower_current_compet_offer - lower_last_compet_offer) - (our_offer.total_price - last_our_offer.total_price)
                margin_price = detail._get_margin_price(price=try_price, price_ship=detail.price_ship)
                margin_min = detail.min_margin or detail.product_id.min_margin or detail.product_id.backend_id.min_margin
                margin_max = detail.max_margin or detail.product_id.max_margin or detail.product_id.backend_id.max_margin
                if margin_min and margin_price and margin_price[1] >= margin_min and margin_price[1] <= margin_max:
                    # The price will be changed on listener TODO test it
                    detail.price = try_price
                    return True
        return False

    @api.multi
    def change_price_to_get_buybox(self, detail):
        """
        Method to check if we have the buybox, if there aren't we are going to change the prices to get it
        :param detail:
        :return:
        """
        buybox_price = 0
        buybox_ship_price = 0
        current_offers = detail.get_current_offers()
        we_have_buybox = detail.is_buybox_mine()
        if not current_offers:
            self._get_offers_from_mws(detail)

        if current_offers:
            for offer in current_offers:
                if offer.is_buybox:
                    buybox_price = offer.price
                    buybox_ship_price = offer.price_ship

        # If there aren't buybox price it is posible that there are an error getting data offer
        if not buybox_price:
            return False
            # TODO view if it is a elegible buybox product, if it isn't calc the lower price

        margin_min = detail.min_margin or detail.product_id.min_margin or detail.product_id.backend_id.min_margin
        margin_max = detail.max_margin or detail.product_id.max_margin or detail.product_id.backend_id.max_margin
        min_price_margin_value = detail.min_price_margin_value or detail.product_id.min_price_margin_value or detail.product_id.backend_id.min_price_margin_value

        units_to_change = detail.units_to_change or detail.product_id.units_to_change or detail.product_id.backend_id.units_to_change
        minus_price = ((units_to_change * buybox_price) + buybox_ship_price) / 100
        # If the buybox price is lower than our price
        try_price = 0
        if not we_have_buybox and (buybox_price + buybox_ship_price) < (detail.price + detail.price_ship):
            try_price = buybox_price + buybox_ship_price - detail.price_ship - minus_price
        elif not we_have_buybox:
            try_price = detail.price - minus_price
        # It is posible that we haven't the buybox price for multiple reasons and try_price will be negative in this case
        if try_price <= 0:
            try_price = detail.price

        margin_price = detail._get_margin_price(price=try_price, price_ship=detail.price_ship)

        throw_try_price = False
        # We need to check if the amount profit is higher than min_price_margin_value
        if margin_price and margin_price[0] < min_price_margin_value:
            try_price = detail.product_id.product_variant_id._get_amazon_margin(backend=detail.product_id.backend_id,
                                                                                amount_margin=min_price_margin_value,
                                                                                marketplace=detail.marketplace_id,
                                                                                percentage_fee=detail.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                                ship_price=detail.price_ship) or detail.price

            margin_price = detail._get_margin_price(price=try_price, price_ship=detail.price_ship)
            # If our margin is higher of min margin we are going to change the price
            if margin_price[1] >= margin_min:
                throw_try_price = True

        # If margin min is higher than margin of try_price we use that
        elif margin_min and margin_price and margin_price[1] > margin_min:
            throw_try_price = True
        elif margin_price and margin_price[1] > margin_max:
            try_price = detail.product_id.product_variant_id._calc_amazon_price(backend=detail.product_id.backend_id,
                                                                                margin=margin_max,
                                                                                marketplace=detail.marketplace_id,
                                                                                percentage_fee=detail.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                                ship_price=detail.price_ship) or detail.price
            throw_try_price = True
        if throw_try_price:
            # The price will be changed on listener TODO test it
            detail.price = try_price
            return True

        return False

    @api.model
    def calc_price_to_export(self, id_detail, force_change=False):
        """
        Method to change the prices of the detail product
        :return:
        """
        # If on product detail change_prices is 'yes'
        # If product detail change_prices is not 'no' and product change_prices is 'yes'
        # If product detail and product change_prices is not 'no' and backend change_prices is 'yes'
        detail = self.env['amazon.product.product.detail'].browse(id_detail)
        we_have_buybox = detail.is_buybox_mine()

        # We check if we can change prices
        if force_change or ((detail.change_prices == '1' or detail.product_id.change_prices == '1' or detail.product_id.backend_id.change_prices == '1') and \
                            (detail.change_prices != '0' and detail.product_id.change_prices != '0' and detail.product_id.backend_id.change_prices != '0')):
            # We are trying to get the fee of product
            try:
                if not detail.last_update_price_date or datetime.strptime(detail.last_update_price_date, '%Y-%m-%d %H:%M:%S') < datetime.today() - timedelta(
                        hours=24):
                    importer = self.work.component(usage='amazon.product.price.import')
                    importer.run_update_price(detail)
            except Exception as e:
                raise RetryableJobError(msg='An error has been produced on MWS API', seconds=60, ignore_retry=True)

            change_price = None
            # If we have the buybox now
            if we_have_buybox:
                change_price = self.up_price_with_buybox(detail)
            # If we have the buybox and we are not get this now, we to try to up the price
            else:
                change_price = self.change_price_to_get_buybox(detail)

            # If we are in this point, we are going to check if the price has been changed, if not we need to check if the price is between the margins, else we are going to update
            if not change_price:
                margin_price = detail._get_margin_price(price=detail.price, price_ship=detail.price_ship)
                margin_min = detail.min_margin or detail.product_id.min_margin or detail.product_id.backend_id.min_margin
                margin_max = detail.max_margin or detail.product_id.max_margin or detail.product_id.backend_id.max_margin
                try_price = None
                if margin_price and margin_price[1] > margin_max:
                    try_price = detail.product_id.odoo_id._calc_amazon_price(backend=detail.product_id.backend_id,
                                                                             margin=margin_max,
                                                                             marketplace=detail.marketplace_id,
                                                                             percentage_fee=detail.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                             ship_price=detail.price_ship)
                elif margin_price and margin_price[1] < margin_min:
                    try_price = detail.product_id.odoo_id._calc_amazon_price(backend=detail.product_id.backend_id,
                                                                             margin=margin_min,
                                                                             marketplace=detail.marketplace_id,
                                                                             percentage_fee=detail.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                             ship_price=detail.price_ship)
                if try_price:
                    detail.price = try_price
                    return True

    def run(self, records):
        """ Change the stock, prices and handling time on Amazon.
        :param records: list of dictionaries of products with structure [{'sku': sku1, 'price': 3.99, 'currency': 'EUR', 'id_mws': market_id},{...}]
        """
        feed_binding_model = self.env['amazon.feed']
        feed_binding_model.export_batch(backend=self.backend_record,
                                        filters={'method':'submit_stock_price_update', 'arguments':records})


class ProductInventoryExporter(Component):
    _name = 'amazon.inventory.product.exporter'
    _inherit = 'base.exporter'
    _usage = 'amazon.product.inventory.export'
    _apply_on = 'amazon.product.product'

    def run(self, records):
        """ Change the prices on Amazon.
        :param records: list of dictionaries of products with structure
        """
        feed_exporter = self.env['amazon.feed']
        return feed_exporter.export_batch(backend=self.backend_record,
                                          filters={'method':'submit_add_inventory_request',
                                                   'arguments':[records]})


class ProductExporter(Component):
    _name = 'amazon.product.product.exporter'
    _inherit = 'amazon.exporter'
    _apply_on = 'amazon.product.product'

    def get_cosine(self, a, b):
        if a and b:
            vec1 = self.text_to_vector(a.upper())
            vec2 = self.text_to_vector(b.upper())

            intersection = set(vec1.keys()) & set(vec2.keys())
            numerator = sum([vec1[x] * vec2[x] for x in intersection])

            sum1 = sum([vec1[x] ** 2 for x in vec1.keys()])
            sum2 = sum([vec2[x] ** 2 for x in vec2.keys()])
            denominator = math.sqrt(sum1) * math.sqrt(sum2)

            if not denominator:
                return 0.0
            else:
                return float(numerator) / denominator

    @api.model
    def text_to_vector(self, text):
        words = WORD.findall(text)
        return Counter(words)

    @api.model
    def _get_asin_product(self, product, marketplace, filter_title_coincidence=True):
        """
        :param product:
        :param marketplace:
        :param filter_title_coincidence: filter the cosine coincidence of
        :return:
        """

        importer_product_forid = self.work.component(model_name='amazon.product.product', usage='amazon.product.data.import')
        amazon_products = importer_product_forid.run_products_for_id(ids=[product.barcode or product.product_variant_id.barcode],
                                                                     type_id=None,
                                                                     marketplace_mws=marketplace.id_mws)

        i = 0
        ind = None
        cos = 0
        if amazon_products:
            # If the flag is a true we are going to check if the cosine coincidence is higher than 0.2
            if filter_title_coincidence:
                for amazon_product in amazon_products:
                    a = amazon_product['title']
                    b = product.name
                    cosine = self.get_cosine(a, b)
                    if cosine and cosine > AMAZON_COSINE_NAME_MIN_VALUE:
                        # We get the product with the higher coincidence
                        if cosine > cos:
                            cos = cosine
                            ind = i
                    elif amazon_product.get('brand') and product.product_brand_id and product.product_brand_id.name.lower() == amazon_product['brand'].lower():
                        # We get the product if the brand is the same
                        ind = i
                    i += 1
            else:
                ind = 0
            if ind != None:
                return amazon_products[ind]

            return {'Match name':'No'}

    def _add_listing_to_amazon(self, record):
        if isinstance(record['product_id'], (int, float)):
            product = self.env['product.product'].browse(record['product_id'])
        else:
            product = record['product_id']

        marketplaces = record['marketplaces'] if record.get('marketplaces') else self.backend_record.marketplace_ids
        margin = record['margin'] if record.get('margin') else self.backend_record.max_margin or AMAZON_DEFAULT_PERCENTAGE_MARGIN

        # Get asin if we have this
        asin = None
        if not record.get('asin') and product and product.amazon_bind_ids:
            asin = product.amazon_bind_ids.asin if len(product.amazon_bind_ids) < 2 else product.amazon_bind_ids[0].asin
        else:
            asin = record['asin'] if record.get('asin') else None

        product_doesnt_exist = True
        product_dont_match = False

        # We get the user language for match with the marketplace language
        user = self.env['res.users'].browse(self.env.uid)
        market_lang_match = marketplaces.filtered(lambda marketplace:marketplace.lang_id.code == user.lang)

        if market_lang_match and not asin:
            try:
                amazon_prod = self._get_asin_product(product, market_lang_match)
            except RetryableJobError as e:
                raise RetryableJobError('The quota is Throttled', 1800, True)
            asin = amazon_prod['asin'] if amazon_prod and amazon_prod.get('asin') else None
            product_dont_match = True if amazon_prod and amazon_prod.get('Match name') == 'No' else False

        for marketplace in marketplaces:
            # If we haven't asin and we haven't searched yet, we search this
            if not asin and market_lang_match and market_lang_match.id != marketplace.id:
                try:
                    amazon_prod = self._get_asin_product(product, market_lang_match)
                except RetryableJobError as e:
                    raise RetryableJobError('The quota is Throttled', 1800, True)
                asin = amazon_prod['asin'] if amazon_prod and amazon_prod.get('asin') else None
                product_dont_match = True if amazon_prod and amazon_prod.get('Match name') == 'No' else False

            add_product = False if not asin else True

            if not add_product:
                continue

            product_doesnt_exist = False

            price = product._calc_amazon_price(backend=self.backend_record,
                                               margin=margin,
                                               marketplace=marketplace,
                                               percentage_fee=AMAZON_DEFAULT_PERCENTAGE_FEE)

            if price:
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

    def run(self, record):
        """ Change the prices on Amazon.
        :param records: list of dictionaries of products with structure
        """
        assert record
        if record.get('method'):
            if record['method'] == 'add_to_amazon_listing':
                assert record['product_id']
                self._add_listing_to_amazon(record)
            elif record['method'] == 'change_price':
                assert record['detail_product_id']
                exporter = self.work.component(model_name='amazon.product.product', usage='amazon.product.stock.price.export')
                exporter.calc_price_to_export(record['detail_product_id'], force_change=record.get('force_change'))
            elif record['method'] == 'recompute_prices_product':
                assert record['product_id']
                exporter = self.work.component(model_name='amazon.product.product', usage='amazon.product.stock.price.export')
                exporter.recompute_amazon_prices_product(first_product=record['product_id'])
            elif record['method'] == 'delete_sqs_messages':
                assert record['message_ids']
                self.env['amazon.config.sqs.message'].browse(record['message_ids']).unlink()
