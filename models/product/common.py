# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import inspect
import logging
import random

from datetime import datetime

from odoo import models, fields, api, _
from odoo.addons.component.core import Component
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.queue_job.job import job
from odoo.exceptions import UserError

from ...models.config.common import AMAZON_DEFAULT_PERCENTAGE_FEE, AMAZON_DEFAULT_PERCENTAGE_MARGIN

_logger = logging.getLogger(__name__)


def chunks(items, length):
    for index in xrange(0, len(items), length):
        yield items[index:index + length]


class AmazonProductProduct(models.Model):
    _name = 'amazon.product.product'
    _inherit = 'amazon.binding'
    _inherits = {'product.product':'odoo_id'}
    _description = 'Amazon Product'

    odoo_id = fields.Many2one(comodel_name='product.product',
                              string='Product',
                              required=True,
                              ondelete='restrict')

    asin = fields.Char('ASIN', readonly=True)
    id_type_product = fields.Selection(selection=[('GCID', 'GCID'),
                                                  ('UPC', 'UPC'),
                                                  ('EAN', 'EAN'),
                                                  ('ISBN', 'ISBN'),
                                                  ('JAN', 'JAN')],
                                       string='Type product Id')

    id_product = fields.Char()
    status = fields.Char('status', required=False)
    sku = fields.Char('SKU', required=True, readonly=True)
    brand = fields.Char('Brand')
    created_at = fields.Date('Created At (on Amazon)')
    updated_at = fields.Date('Updated At (on Amazon)')
    amazon_qty = fields.Float(string='Computed Quantity',
                              help="Last computed quantity to send "
                                   "on Amazon.")

    product_product_market_ids = fields.One2many('amazon.product.product.detail', 'product_id',
                                                 string='Product data on marketplaces', copy=True)
    height = fields.Float('Height', default=0)
    length = fields.Float('Length', default=0)
    weight = fields.Float('Weight', default=0)
    width = fields.Float('Width', default=0)

    # Min and max margin stablished for the calculation of the price on product and product price details if these do not be informed
    # If these fields do not be informed, gets the margin limits of backend
    stock_sync = fields.Boolean('Stock shyncronization', default=True)
    change_prices = fields.Boolean('Change the prices', default=True)
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Minimal margin', default=None)
    units_to_change = fields.Float(digits=(3, 2))
    type_unit_to_change = fields.Selection(selection=[('price', 'Price (€)'),
                                                      ('percentage', 'Percentage (%)')],
                                           string='Type of unit',
                                           default='price')

    handling_time = fields.Integer('Time to get since we received an order to send this')

    RECOMPUTE_QTY_STEP = 1000  # products at a time

    @job(default_channel='root.amazon')
    @api.model
    def import_record_details(self, backend):
        _super = super(AmazonProductProduct, self)
        self._get_products_initial_fees(backend)
        # self._get_products_initial_prices(backend)
        # self._process_notification_messages(backend)

    @job(default_channel='root.amazon')
    @api.model
    def import_changes_prices_record(self, backend):
        _super = super(AmazonProductProduct, self)
        self._get_messages_price_changes(backend)

    @job(default_channel='root.amazon')
    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonProductProduct, self)
        try:
            result = _super.import_record(backend, external_id)
            if not result:
                raise RetryableJobError(msg='The product of the backend %s hasn\'t could not be imported. \n %s' % (backend.name, external_id),
                                        seconds=random.randint(90, 600))

        except Exception as e:
            if e.message.find('current transaction is aborted') > -1 or e.message.find('could not serialize access due to concurrent update') > -1:
                raise RetryableJobError('A concurrent job is already exporting the same record '
                                        '(%s). The job will be retried later.' % self.model._name, random.randint(60, 300), True)
            raise e

    @job(default_channel='root.amazon')
    @api.model
    def export_batch(self, backend):
        '''
        We will use this method to get the products, get their prices and their stocks and export this on Amazon
        :param backend:
        :return:
        '''

        if backend.stock_sync and backend.change_prices:
            self._export_stock_prices(backend)
        elif backend.stock_sync:
            self._export_stock(backend)

    def _export_stock(self, backend):
        _logger.info('Connector-amazon [%s] log: Export stock init with %s backend' % (inspect.stack()[0][3], backend.name))
        products = self.env['amazon.product.product'].search([('backend_id', '=', backend.id)])

        i = [detail for product in products for detail in product.product_product_market_ids if
             product.product_product_market_ids]
        for detail in i:
            if not detail.stock_sync or not detail.product_id.stock_sync:
                continue

            virtual_available = detail.product_id.odoo_id._compute_amazon_stock()
            handling_time = detail.product_id.odoo_id._compute_amazon_handling_time()

            if detail.stock != virtual_available:

                if not handling_time or not virtual_available or virtual_available < 1 or detail.product_id.handling_time == handling_time:
                    data = {'sku':detail.product_id.sku,
                            'Quantity':'0' if virtual_available < 0 or not handling_time else str(int(virtual_available)),
                            'id_mws':detail.marketplace_id.id_mws}

                    vals = {'backend_id':backend.id,
                            'type':'Update_stock',
                            'model':detail._name,
                            'identificator':detail.id,
                            'data':data,
                            }
                    self.env['amazon.feed.tothrow'].create(vals)


                else:

                    data = {'sku':detail.sku,
                            'Price':("%.2f" % detail.price).replace('.', detail.marketplace_id.decimal_currency_separator) if detail.price else '',
                            'Quantity':'0' if virtual_available < 0 else str(int(virtual_available)),
                            'handling-time':str(handling_time) if handling_time and handling_time > 0 else '1',
                            'id_mws':detail.marketplace_id.id_mws}

                    vals = {'backend_id':backend.id,
                            'type':'Update_stock_price',
                            'model':detail._name,
                            'identificator':detail.id,
                            'marketplace_id':detail.marketplace_id.id,
                            'data':data,
                            }
                    self.env['amazon.feed.tothrow'].create(vals)

                detail.product_id.handling_time = handling_time

        _logger.info('Connector-amazon [%s] log: Finish Export stock with %s backend' % (inspect.stack()[0][3], backend.name))

    def _export_stock_prices(self, backend):
        _logger.info('Connector-amazon [%s] log: Export stock and prices init with %s backend' % (inspect.stack()[0][3], backend.name))
        products = self.env['amazon.product.product'].search([('backend_id', '=', backend.id)])
        i = [detail for product in products for detail in product.product_product_market_ids if
             product.product_product_market_ids]
        for detail in i:
            # TODO test the next methods
            try:
                virtual_available = detail.product_id.odoo_id._compute_amazon_stock()
                price = detail._compute_amazon_price()
                handling_time = detail.product_id.odoo_id._compute_amazon_handling_time()
                detail.product_id.handling_time = handling_time
                detail.stock = virtual_available
                # If we haven't handling_time we assume that there isn't product to sell on stock and seller
                if handling_time is None:
                    virtual_available = 0

                data = {'sku':detail.sku,
                        'Price':("%.2f" % price).replace('.', detail.marketplace_id.decimal_currency_separator) if price else '',
                        'Quantity':'0' if virtual_available < 0 else str(int(virtual_available)),
                        'handling-time':str(handling_time) if handling_time and handling_time > 0 else '1',
                        'id_mws':detail.marketplace_id.id_mws}

                vals = {'backend_id':backend.id,
                        'type':'Update_stock_price',
                        'model':detail._name,
                        'identificator':detail.id,
                        'marketplace_id':detail.marketplace_id.id,
                        'data':data,
                        }
                self.env['amazon.feed.tothrow'].create(vals)

            except Exception as e:
                _logger.error(e.message)

        _logger.info('Connector-amazon [%s] log: Finish export stock and prices init with %s backend' % (inspect.stack()[0][3], backend.name))

    def _get_products_initial_fees(self, backend):
        _logger.info('Connector-amazon [%s] log: Get initial fees on backend %s' % (inspect.stack()[0][3], backend.name))
        detail_products = self.env['amazon.product.product.detail'].search([('product_id.backend_id', '=', backend.id),
                                                                            ('percentage_fee', '=', False),
                                                                            ('stock', '>', 0)])
        with backend.work_on(self._name) as work:
            importer = work.component(usage='amazon.product.price.import')
            for detail in detail_products:
                prices = importer.run(detail)
                if prices:
                    price_unit = float(prices.get('price_unit') or 0.)
                    price_ship = float(prices.get('price_shipping') or 0.)
                    if price_unit != detail.price or price_ship != detail.price_ship:
                        detail.price = price_unit
                        detail.price_ship = price_ship
                    if prices.get('fee'):
                        detail.percentage_fee = round((prices['fee']['Amount'] * 100) / (detail.price + detail.price_ship or 0))
                        detail.total_fee = prices['fee']['Final']

        _logger.info('Connector-amazon [%s] log: Finish get initial fees on backend %s' % (inspect.stack()[0][3], backend.name))
        return

    def _get_products_initial_prices(self, backend):
        """
        :return:
        """
        _logger.info('Connector-amazon [%s] log: Get initial prices on backend %s' % (inspect.stack()[0][3], backend.name))
        detail_products = self.env['amazon.product.product.detail'].search([('product_id.backend_id', '=', backend.id),
                                                                            ('first_price_searched', '=', False),
                                                                            ('stock', '>', 0)])
        with backend.work_on(self._name) as work:
            importer = work.component(usage='amazon.product.lowestprice')
            for detail in detail_products:
                try:
                    importer.run(detail)
                except Exception as e:
                    _logger.error(e.message)
        _logger.info('Connector-amazon [%s] log: Finish get initial prices on backend %s' % (inspect.stack()[0][3], backend.name))

    def _process_notification_messages(self, backend):
        with backend.work_on(self._name) as work:
            importer = work.component(usage='amazon.product.lowestprice')
            importer.run_process_messages_offers(backend)

    def _get_messages_price_changes(self, backend):
        with backend.work_on(self._name) as work:
            importer = work.component(usage='amazon.product.lowestprice')
            importer.run_get_offers_changed()
        return


class AmazonProductProductDetail(models.Model):
    _name = 'amazon.product.product.detail'
    _description = 'Amazon Product Variant on Every Marketplace'

    product_id = fields.Many2one('amazon.product.product', 'product_data_market_ids', ondelete='cascade', required=True,
                                 readonly=True)

    sku = fields.Char('SKU', related='product_id.sku')
    title = fields.Char('Product_name', required=False)
    price = fields.Float('Price', required=False)  # This price have the tax included
    min_allowed_price = fields.Float('Min allowed price', required=False)  # This is the min price allowed
    max_allowed_price = fields.Float('Max allowed price', required=False)  # This is the max price allowed
    currency_price = fields.Many2one('res.currency', 'Currency price', required=False)
    price_ship = fields.Float('Price of ship', required=False)  # This price have the tax included
    currency_ship_price = fields.Many2one('res.currency', 'Currency price ship', required=False)
    marketplace_id = fields.Many2one('amazon.config.marketplace', "marketplace_id")
    status = fields.Selection(selection=[('Active', 'Active'),
                                         ('Inactive', 'Inactive'),
                                         ('Unpublished', 'Unpublished'),
                                         ('Submmited', 'Submmited'),
                                         ('Incomplete', 'Incomplete'), ],
                              string='Status', default='Active')
    stock = fields.Integer('Stock')
    date_created = fields.Datetime('Product created at', required=False)
    category_id = fields.Many2one('amazon.config.product.category', 'Category',
                                  default=lambda self:self.env['amazon.config.product.category'].search(
                                      [('name', '=', 'default')]))
    category_searched = fields.Boolean(default=False)
    first_price_searched = fields.Boolean(default=False)
    has_buybox = fields.Boolean(string='Is the buybox winner', default=False)
    has_lowest_price = fields.Boolean(string='Is the lowest price', default=False)
    buybox_price = fields.Float('Buybox price')
    lowest_price = fields.Float('Lowest total price')
    merchant_shipping_group = fields.Char('Shipping template name')

    # Min and max margin stablished for the calculation of the price on product and product price details if these do not be informed
    stock_sync = fields.Boolean('Stock shyncronization', default=True)
    change_prices = fields.Boolean('Change the prices', default=True)
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Minimal margin', default=None)
    units_to_change = fields.Float(digits=(3, 2))
    type_unit_to_change = fields.Selection(selection=[('price', 'Price (€)'),
                                                      ('percentage', 'Percentage (%)')],
                                           string='Status', default='price')
    total_fee = fields.Float('Amount of fee')
    percentage_fee = fields.Float('Percentage fee of Amazon sale')

    offer_ids = fields.One2many(comodel_name='amazon.product.offer',
                                inverse_name='product_detail_id',
                                string='Offers of the product')

    historic_offer_ids = fields.One2many(comodel_name='amazon.historic.product.offer',
                                         inverse_name='product_detail_id',
                                         string='Historic offers of the product')

    def _get_amazon_prices(self):
        with self.product_id.backend_id.work_on(self._name) as work:
            importer = work.component(model_name='amazon.product.product', usage='amazon.product.price.import')
            prices = importer.run(self)
            if prices:
                price_unit = float(prices.get('price_unit') or 0.)
                price_ship = float(prices.get('price_shipping') or 0.)
                if price_unit != self.price or price_ship != self.price_ship:
                    self.price = price_unit
                    self.price_ship = price_ship
                if prices.get('fee'):
                    self.percentage_fee = round(
                        (prices['fee']['Amount'] * 100) / (self.price + self.price_ship or 0))
                    self.total_fee = prices['fee']['Final']
            else:
                self.price = self.product_id.product_variant_id._calc_amazon_price(backend=self.product_id.backend_id,
                                                                                   margin=self.max_margin or self.product_id.max_margin or self.product_id.backend_id.max_margin,
                                                                                   marketplace=self.marketplace_id,
                                                                                   percentage_fee=self.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                                   ship_price=self.price_ship or 0)

    def _get_detail_minimum_price(self):
        self._get_amazon_prices()
        margin_min = self.min_margin or self.product_id.min_margin or self.product_id.backend_id.min_margin
        margin_price = self._get_margin_price(price=self.price, price_ship=self.price_ship)
        if margin_price and margin_price[1] < margin_min:
            return self.product_id.product_variant_id._calc_amazon_price(backend=self.product_id.backend_id,
                                                                         margin=margin_min,
                                                                         marketplace=self.marketplace_id,
                                                                         percentage_fee=self.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                         ship_price=self.price_ship)
        return self.price

    def _compute_amazon_price(self):
        """
        Method to change the prices of the detail product (it is correspond with the same product on each marketplace)
        :return:
        """
        # If on product detail change_prices is True
        # If product detail change_prices is not False and product change_prices is True
        # If product detail and product change_prices is not False and backend change_prices is True
        # If one of the last three conditions is True, We change the prices
        margin_min = self.min_margin or self.product_id.min_margin or self.product_id.backend_id.min_margin
        margin_max = self.max_margin or self.product_id.max_margin or self.product_id.backend_id.max_margin
        if self.change_prices or \
                (self.change_prices not in False and self.product_id.change_prices) or \
                (self.product_id.change_prices not in True and self.product_id.backend_id.change_prices):
            if not self.first_price_searched or self.has_buybox or not self.offer_ids:
                return self._get_detail_minimum_price()
                # TODO analyze the last prices to know if it is possible up the price

            buybox_price = 0
            buybox_ship_price = 0
            for offer in self.offer_ids:
                if offer.is_buybox:
                    buybox_price = offer.price
                    buybox_ship_price = offer.price_ship

            type_unit_to_change = self.type_unit_to_change or self.product_id.type_unit_to_change or self.product_id.backend_id.type_unit_to_change
            units_to_change = self.units_to_change or self.product_id.units_to_change or self.product_id.backend_id.units_to_change
            minus_price = units_to_change if type_unit_to_change == 'price' else ((units_to_change * buybox_price) + buybox_ship_price) / 100
            try_price = buybox_price + buybox_ship_price - self.price_ship - minus_price
            # It is posible that we haven't the buybox price for multiple reasons and try_price will be negative in this case
            if try_price <= 0:
                try_price = self.price
            margin_price = self._get_margin_price(price=try_price, price_ship=self.price_ship)
            if margin_min and margin_price and margin_price[1] > margin_min:
                return try_price
            if margin_price and margin_price[1] > margin_max:
                return self.product_id.product_variant_id._calc_amazon_price(backend=self.product_id.backend_id,
                                                                             margin=margin_max,
                                                                             marketplace=self.marketplace_id,
                                                                             percentage_fee=self.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                             ship_price=self.price_ship) or self.price

        self._get_amazon_prices()
        return self.price

    @api.model
    def _get_margin_price(self, price, price_ship):
        """
        Get margin of a price if it is sell
        :param price:
        :param price_ship:
        :return: tuple with margin price on currency and percentage of margin (€,%)
        """
        total_sell_price = (price or self.price) + (price_ship or self.price_ship)
        amazon_fee = (total_sell_price * self.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE) / 100
        backend = self.product_id.backend_id
        taxe_ids = self.product_id.taxes_id or backend.env['account.tax'].browse(backend.env['ir.values'].get_default('product.template',
                                                                                                                      'taxes_id',
                                                                                                                      company_id=backend.company_id.id))
        taxes_amount = 0
        for tax_id in taxe_ids:
            taxes_amount += tax_id._compute_amount_taxes(total_sell_price)

        delivery_carriers = [template_ship.delivery_standar_carrier_ids for template_ship in backend.shipping_template_ids
                             if template_ship.name == self.merchant_shipping_group and
                             template_ship.marketplace_id.id == self.marketplace_id.id]

        # Get shipping lowest cost configured
        ship_cost = None
        for delivery in delivery_carriers:
            try:
                aux = delivery.get_price_from_picking(total=price, weight=self.product_id.weight, volume=0, quantity=1)
            except UserError as e:
                aux = None
            if not ship_cost or (aux and aux < ship_cost):
                ship_cost = aux

        # Get the cost of product supplier
        cost = self.product_id.odoo_id._get_cost()

        if not cost:
            return None

        margin_price = total_sell_price - amazon_fee - taxes_amount - cost - (ship_cost or 0)
        return (margin_price, margin_price / cost * 100)


class SupplierInfo(models.Model):
    _inherit = 'product.supplierinfo'

    supplier_stock = fields.Float('Supplier stock')
    get_supplier_stock = fields.Boolean('Get supplier stock?', default=None)

    @api.model
    def create(self, vals):
        record = super(SupplierInfo, self).create(vals)
        self._event('on_record_create').notify(record, fields=vals.keys())
        return record

    def export_products_from_supplierinfo(self):
        if self.name.automatic_export_products and (self.product_id.barcode or self.product_tmpl_id.barcode):
            for marketplace in self.name.backend_id.marketplace_ids:
                supr = self.env['amazon.feed.tothrow'].search([('backend_id', '=', self.name.backend_id.id),
                                                               ('type', '=', 'Add_products_csv'),
                                                               ('launched', '=', False),
                                                               ('model', '=', self.product_id._name),
                                                               ('identificator', '=', self.product_id.id),
                                                               ('marketplace_id', '=', marketplace.id)])

                data = {'sku':self.product_id.default_code or self.product_id.product_variant_id.default_code}
                data['product-id'] = self.product_id.barcode or self.product_tmpl_id.barcode
                data['product-id-type'] = 'EAN'
                price = self.product_id.product_variant_id._calc_amazon_price(backend=self.name.backend_id,
                                                                              margin=self.name.backend_id.max_margin or AMAZON_DEFAULT_PERCENTAGE_MARGIN,
                                                                              marketplace=marketplace,
                                                                              percentage_fee=AMAZON_DEFAULT_PERCENTAGE_FEE)
                data['price'] = ("%.2f" % price).replace('.', marketplace.decimal_currency_separator) if price else ''
                data['minimum-seller-allowed-price'] = ''
                data['maximum-seller-allowed-price'] = ''
                data['item-condition'] = '11'  # We assume the products are new
                data['quantity'] = '0'  # The products stocks allways is 0 when we export these
                data['add-delete'] = 'a'
                data['will-ship-internationally'] = ''
                data['expedited-shipping'] = ''
                data['merchant-shipping-group-name'] = ''
                handling_time = self.product_id.product_variant_id._compute_amazon_handling_time() or ''
                data['handling-time'] = str(handling_time) if price else ''
                data['item_weight'] = ''
                data['item_weight_unit_of_measure'] = ''
                data['item_volume'] = ''
                data['item_volume_unit_of_measure'] = ''
                data['id_mws'] = marketplace.id_mws
                vals = {'backend_id':self.name.backend_id.id,
                        'type':'Add_products_csv',
                        'model':self.product_id._name,
                        'identificator':self.product_id.id,
                        'marketplace_id':marketplace.id,
                        'data':data,
                        }
                if supr:
                    supr.write(vals)
                else:
                    self.env['amazon.feed.tothrow'].create(vals)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.product.product',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )

    def _get_supplier_product_qty(self):
        prod_qty = 0
        if self.product_tmpl_id.seller_ids:
            time_now = datetime.now()
            cost = None
            for supllier_prod in self.product_tmpl_id.seller_ids:
                # If the supplier stock flag on product is False we don't get the supplier stock never
                # If the supplier stock flag on product is True or is not False and the flag on partner is True we get the stock supplier
                if supllier_prod.get_supplier_stock != '0' and (supllier_prod.name.get_supplier_stock == '1' or supllier_prod.get_supplier_stock == '1') and \
                        (not supllier_prod.date_end or datetime.strptime(supllier_prod.date_end, '%Y-%m-%d') > time_now) and \
                        (not cost or cost > supllier_prod.price):
                    cost = supllier_prod.price
                    prod_qty = supllier_prod.supplier_stock

        return prod_qty

    def _compute_amazon_stock(self):
        qty_total_product = 0
        # Add the virtual avaiable of the product itself
        if self.virtual_available and self.virtual_available > 0:
            qty_total_product = self.virtual_available
        # Add the calc of the stock avaiable counting with the BoM stock
        if self.bom_ids:
            # if we have bom, we need to calculate the forecast stock
            qty_bom_produced = None
            for bom in self.bom_ids:

                for line_bom in bom.bom_line_ids:
                    # We are going to divide the product bom stock for quantity of bom
                    aux = int(line_bom.product_id._compute_amazon_stock() / line_bom.product_qty)
                    # If is the first ocurrence or the calc of stock avaiable with this product is lower than we are saved, we updated this field
                    if qty_bom_produced == None or aux < qty_bom_produced:
                        qty_bom_produced = aux

            qty_total_product += qty_bom_produced if qty_bom_produced else 0

        if qty_total_product < 1:
            qty_total_product = self._get_supplier_product_qty()

        return qty_total_product

    def _compute_amazon_handling_time(self):
        # Add the virtual avaiable of the product itself
        stock_available = self._get_stock_available()
        if not stock_available:
            return self._get_forecast_handling_time()
        return 1

    @api.model
    def _get_cost(self):
        cost = 0
        if self.virtual_available > 0:
            line_purchases = self.env['purchase.order.line'].search([('order_id.state', '=', 'purchase'), ('product_id', '=', self.id)],
                                                                    order='date_planned desc')

            if line_purchases:
                cost = line_purchases[0].price_unit

        elif self.product_tmpl_id.seller_ids:
            time_now = datetime.now()
            for supllier_prod in self.product_tmpl_id.seller_ids:
                if (not cost or cost > supllier_prod.price) and \
                        (not supllier_prod.date_end or datetime.strptime(supllier_prod.date_end, '%Y-%m-%d') > time_now):
                    cost = supllier_prod.price
        elif self.product_tmpl_id.bom_ids:
            for bom in self.product_tmpl_id.bom_ids:
                for line_bom in bom.bom_line_ids:
                    cost += line_bom.product_id._get_cost() * line_bom.product_qty or 0
        return cost

    def _get_stock_available(self):
        if self._compute_amazon_stock() > 0 and self.qty_available and self.qty_available > 0:
            return self.qty_available
        if self.bom_ids:
            # if we have bom, we need to calculate the forecast stock
            bom_hand_time = None
            for bom in self.bom_ids:
                for line_bom in bom.bom_line_ids:
                    # We are going to get handling time of product of bom
                    aux = line_bom.product_id._get_stock_available()
                    if not bom_hand_time or bom_hand_time < aux:
                        bom_hand_time = aux
            if bom_hand_time:
                return bom_hand_time

    def _get_forecast_handling_time(self):
        """
        We are going to get the handling time of the lowest cost supplier
        :return:
        """
        hand_time = None
        # TODO test calc the handling time when we are waiting arrived products from a purchase
        cost = None
        time_now = datetime.now()
        # If we haven't stock now but we have forecast to receive units, we get when
        if self.qty_available < 1 and self.virtual_available > 0:
            # Get the purchase order by date planned to receive
            pending_purchase = self.env['purchase.order.line'].search([('order_id.state', '=', 'purchase'), ('product_id', '=', self.id)],
                                                                      order='date_planned desc')
            # If we have purchase of this product
            if pending_purchase:
                # Get units to arrive
                units_to_arrive = self.virtual_available - self.qty_available
                sum_orders_qty = 0
                # Loop on orders
                for order in pending_purchase:
                    # Per order calc days to arrive
                    days_to_arrive = (time_now - datetime.strptime(order.order_id.date_planned, '%Y-%m-%d %H:%M:%S')).days

                    # Get the products planned to receive
                    sum_orders_qty += order.product_qty
                    # If we get the sum of products on orders and
                    if sum_orders_qty >= units_to_arrive:
                        hand_time = days_to_arrive + 1 if days_to_arrive > 0 else 1
                        break

        # If we haven't hand_time we need get it of seller delay
        if not hand_time and self.product_tmpl_id.seller_ids:
            for supllier_prod in self.product_tmpl_id.seller_ids:
                if (not supllier_prod.date_end or time_now > datetime.strptime(supllier_prod.date_end, '%Y-%m-%d')) and (
                        not cost or cost > supllier_prod.price):
                    cost = supllier_prod.price
                    hand_time = supllier_prod.delay

        if hand_time == None and self.bom_ids:
            # if we have bom, we need to calculate the forecast stock
            bom_hand_time = None
            for bom in self.bom_ids:

                for line_bom in bom.bom_line_ids:
                    # We are going to get handling time of product of bom
                    aux = line_bom.product_id._get_forecast_handling_time()
                    if not bom_hand_time or bom_hand_time < aux:
                        bom_hand_time = aux
            hand_time = bom_hand_time

        return hand_time

    def _calc_amazon_price(self, backend, margin, marketplace, percentage_fee=AMAZON_DEFAULT_PERCENTAGE_FEE, ship_price=0):
        """
        Get initial price passing margin wished to export product to Amazon
        :param margin:
        :return:
        """
        if margin:
            cost = self._get_cost()
            if not cost:
                return None
            margin_amount = cost * margin / 100

            delivery_carriers = [template_ship.delivery_standar_carrier_ids for template_ship in backend.shipping_template_ids
                                 if template_ship.marketplace_id.id == marketplace.id and template_ship.is_default]

            # Get shipping lowest cost configured
            ship_cost = None
            for delivery in delivery_carriers:
                try:
                    aux = delivery.get_price_from_picking(total=0, weight=self.weight or self.product_tmpl_id.weight, volume=0, quantity=1)
                except UserError as e:
                    aux = None
                if not ship_cost or (aux and aux < ship_cost):
                    ship_cost = aux

            if not ship_cost:
                raise UserError(_('The configuration beetwen delivery carrier and marketplace(%s) of the backend(%s) is missing for the product: \'%s\'' %
                                  (marketplace.name, backend.name, self.name)))

            price_without_tax = cost + margin_amount + ship_cost

            taxe_ids = self.product_tmpl_id.taxes_id or backend.env['account.tax'].browse(backend.env['ir.values'].get_default('product.template',
                                                                                                                               'taxes_id',
                                                                                                                               company_id=backend.company_id.id))
            final_price = 0
            for tax_id in taxe_ids:
                final_price += tax_id._compute_amazon_amount_final_price(price_without_tax, percentage_fee=percentage_fee, price_include=False)

            return final_price - ship_price

        return None


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_amazon_product = fields.Boolean(store=True,
                                       default=lambda self:True if self.product_variant_id.amazon_bind_ids else False)


class AmazonProductUoM(models.Model):
    _name = 'amazon.product.uom'

    product_uom_id = fields.Many2one('product.uom', 'Product UoM')
    name = fields.Char()


class AmazonOffer(models.Model):
    _name = 'amazon.product.offer'

    product_detail_id = fields.Many2one('amazon.product.product.detail', ondelete='cascade')
    historic_id = fields.Many2one('amazon.historic.product.offer', ondelete='cascade')
    id_seller = fields.Char()
    price = fields.Float()
    currency_price_id = fields.Many2one('res.currency')
    price_ship = fields.Float()
    currency_ship_price_id = fields.Many2one('res.currency')
    is_lower_price = fields.Boolean()
    is_buybox = fields.Boolean()
    is_prime = fields.Boolean()
    seller_feedback_rating = fields.Char()
    seller_feedback_count = fields.Char()
    country_ship_id = fields.Many2one('res.country')
    amazon_fulffilled = fields.Boolean()
    condition = fields.Char()


class AmazonHistoricOffer(models.Model):
    _name = 'amazon.historic.product.offer'

    offer_date = fields.Datetime()
    product_detail_id = fields.Many2one('amazon.product.product.detail', ondelete='cascade')
    offer_ids = fields.One2many(comodel_name='amazon.product.offer',
                                inverse_name='historic_id',
                                string='Offers of the product')


class ProductProductAdapter(Component):
    _name = 'amazon.product.product.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.product.product'

    def _call(self, method, arguments):
        try:
            return super(ProductProductAdapter, self)._call(method, arguments)
        except Exception:
            raise

    def get_lowest_price(self, arguments):
        try:
            assert arguments
            return self._call(method='get_lowest_price_and_buybox', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_lowest_price')
            raise

    def get_my_price(self, arguments):
        try:
            assert arguments
            return self._call(method='get_my_price_product', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_my_price')
            raise

    def get_category(self, arguments):
        try:
            assert arguments
            return self._call(method='get_category_product', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_category_product')
            raise

    def get_products_for_id(self, arguments):
        try:
            assert arguments
            return self._call(method='get_products_for_id', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_products_for_id')
            raise

    def get_offers_changed(self):
        try:
            return self._call(method='get_offers_changed', arguments=None)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_offers_changed')
            raise
