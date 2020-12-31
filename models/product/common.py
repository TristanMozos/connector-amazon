# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import inspect
import logging
import os
import random

from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.addons.component.core import Component
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.queue_job.job import job
from odoo.exceptions import UserError

from ...models.config.common import AMAZON_DEFAULT_PERCENTAGE_FEE

_logger = logging.getLogger(__name__)


def chunks(items, length):
    for index in xrange(0, len(items), length):
        yield items[index:index + length]


class AmazonProductProduct(models.Model):
    _name = 'amazon.product.product'
    _inherit = 'amazon.binding'
    _inherits = {'product.product':'odoo_id'}
    _description = 'Amazon Product'

    backend_name = fields.Char('Backend name', related='backend_id.name')
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
    change_prices = fields.Selection(string='Change prices', selection=[('0', 'No'), ('1', 'Yes'), ])
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Maximal margin', default=None)
    units_to_change = fields.Float(digits=(3, 2))
    min_price_margin_value = fields.Float('Min price margin value', digits=(3, 2))

    handling_time = fields.Integer('Time to get since we received an order to send this')

    RECOMPUTE_QTY_STEP = 1000  # products at a time

    @job(default_channel='root.amazon')
    @api.model
    def import_prices(self, backend, filters):
        self._get_first_price(backend, filters)

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
                                        '(%s). The job will be retried later.' % self._name, random.randint(60, 300), True)
            raise e

    @job(default_channel='root.amazon')
    @api.model
    def export_record(self, backend, internal_id):
        _super = super(AmazonProductProduct, self)
        try:
            result = _super.export_record(backend, internal_id)
        except Exception as e:
            raise e

    @job(default_channel='root.amazon')
    @api.model
    def export_batch(self, backend):
        '''
        We will use this method to get the products, get their prices and their stocks and export this on Amazon
        :param backend:
        :return:
        '''
        if backend.stock_sync:
            self._export_stock_backend(backend)

    @job(default_channel='root.amazon')
    @api.model
    def import_changes_prices_record(self, backend, filters=None):
        # TODO delete method when the current jobs of 'receive sqs message' had been executed
        self.env['amazon.config.sqs.message']._get_messages_price_changes(backend)

    @api.model
    def generate_jobs_to_get_prices(self, backend):
        _super = super(AmazonProductProduct, self)
        self._get_products_initial_prices_and_fees(backend)

    def _export_stock_backend(self, backend):
        _logger.info('connector_amazon [%s][%s] log: Export stock init with %s backend' % (os.getpid(), inspect.stack()[0][3], backend.name))
        products = self.env['amazon.product.product'].search([('backend_id', '=', backend.id)])

        i = [detail for product in products for detail in product.product_product_market_ids if
             product.product_product_market_ids]

        for detail in i:
            if not detail.stock_sync or not detail.product_id.stock_sync:
                continue

            virtual_available = detail.product_id.odoo_id._compute_amazon_stock(products_amazon_stock_computed=[])
            handling_time = detail.product_id.odoo_id._compute_amazon_handling_time()

            if detail.stock != virtual_available:

                if not handling_time or not virtual_available or virtual_available < 1 or detail.product_id.handling_time == handling_time:
                    data = {'sku':detail.product_id.sku,
                            'Quantity':'0' if virtual_available < 0 or not handling_time else str(int(virtual_available)),
                            'id_mws':detail.marketplace_id.id_mws}

                    vals = {'backend_id':backend.id,
                            'type':'_POST_INVENTORY_AVAILABILITY_DATA_',
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
                            'type':'_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_',
                            'model':detail._name,
                            'identificator':detail.id,
                            'marketplace_id':detail.marketplace_id.id,
                            'data':data,
                            }
                    self.env['amazon.feed.tothrow'].create(vals)

                detail.product_id.handling_time = handling_time

        _logger.info('connector_amazon [%s][%s] log: Finish Export stock with %s backend' % (os.getpid(), inspect.stack()[0][3], backend.name))

    def _export_stock_prices(self, backend):
        _logger.info('connector_amazon [%s][%s] log: Export stock and prices init with %s backend' % (os.getpid(), inspect.stack()[0][3], backend.name))
        products = self.env['amazon.product.product'].search([('backend_id', '=', backend.id)])
        i = [detail for product in products for detail in product.product_product_market_ids if
             product.product_product_market_ids]
        for detail in i:
            if detail.change_prices == '0' or detail.change_prices == '0' or detail.product_id.change_prices == '0':
                continue
            # TODO test the next methods
            detail._change_price()

        _logger.info('connector_amazon [%s][%s] log: Finish export stock and prices init with %s backend' % (os.getpid(), inspect.stack()[0][3], backend.name))

    def get_products_initial_prices_and_fees(self, backend):
        _logger.info('connector_amazon [%s][%s] log: Get initial fees on backend %s' % (os.getpid(), inspect.stack()[0][3], backend.name))

        quota_control = self.env['amazon.control.request'].search([('request_name', '=', 'GetMyPriceForSKU')])

        search_first_price = self.env['amazon.product.product.detail'].search([('product_id.backend_id', '=', backend.id),
                                                                               ('stock', '>', 0),
                                                                               '|',
                                                                               ('percentage_fee', '=', False),
                                                                               ('first_price_searched', '=', False)],
                                                                              limit=quota_control.max_request_quota_time -
                                                                                    (quota_control.max_request_quota_time / 4))
        product_importer = self.env['amazon.product.product']
        user = backend.warehouse_id.company_id.user_tech_id
        if not user:
            user = self.env['res.users'].browse(self.env.uid)
        if user != self.env.user:
            product_importer = product_importer.sudo(user)

        for detail in search_first_price:
            delayable = product_importer.with_delay(priority=1, eta=datetime.now() + timedelta(minutes=5))
            delayable.description = '%s.%s' % (self._name, 'get_price_first_time()')
            delayable.import_prices(backend, filters={'method':'first_price', 'product_detail':detail.id})

        _logger.info('connector_amazon [%s][%s] log: Finish get initial fees on backend %s' % (os.getpid(), inspect.stack()[0][3], backend.name))
        return

    def _get_first_price(self, backend, filters):
        assert filters
        with backend.work_on(self._name) as work:
            importer = work.component(usage='amazon.product.price.import')
            detail = self.env['amazon.product.product.detail'].browse(filters['product_detail'])
            result = None
            if filters['method'] == 'first_price':
                result = importer.run_update_price(detail)
            elif filters['method'] == 'first_offer':
                result = importer.run_first_offer(detail)
            if not result:
                raise RetryableJobError(msg='The prices can\'t be recovered', seconds=600)

    @api.model
    def _change_price(self, force_change=False):
        for detail in self.product_product_market_ids:
            detail._change_price(force_change=force_change)

    @api.multi
    def get_market_detail_product(self, market):
        if market:
            market_id = None
            if not isinstance(market, (int,float)):
                market_id = market.id
            else:
                market_id = market

            if market_id:
                return self.product_product_market_ids.filtered(lambda detail:detail.marketplace_id.id == market_id)


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
    total_price = fields.Char('Total price', compute='_compute_margin_amount_based_on_price')
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
    first_offer_searched = fields.Boolean(default=False)
    has_buybox = fields.Boolean(string='Is the buybox winner', default=False)
    has_lowest_price = fields.Boolean(string='Is the lowest price', default=False)
    buybox_price = fields.Float('Buybox price')
    lowest_price = fields.Float('Lowest total price')
    merchant_shipping_group = fields.Char('Shipping template name')

    # Min and max margin stablished for the calculation of the price on product and product price details if these do not be informed
    stock_sync = fields.Boolean('Stock shyncronization', default=True)
    change_prices = fields.Selection(string='Change prices', selection=[('0', 'No'), ('1', 'Yes'), ])
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Maximal margin', default=None)
    margin_amount = fields.Float('Margin amount', compute='_compute_margin_amount_based_on_price')
    margin_percentage = fields.Float('Margin percentage', digits=(3, 2))
    units_to_change = fields.Float(digits=(3, 2))
    min_price_margin_value = fields.Float('Min price margin value', digits=(3, 2))

    total_fee = fields.Float('Amount of fee')
    percentage_fee = fields.Float('Percentage fee of Amazon sale')

    offer_ids = fields.One2many(comodel_name='amazon.product.offer',
                                string='Offers of the product',
                                store=False,
                                compute='_compute_real_offer')

    historic_offer_ids = fields.One2many(comodel_name='amazon.historic.product.offer',
                                         inverse_name='product_detail_id',
                                         string='Historic offers of the product')

    last_update_price_date = fields.Datetime(string='Last update price import')

    @api.onchange('margin_percentage')
    def _onchange_margin_amount_based_on_percentage(self):
        self._compute_margin_amount_based_on_percentage()

    @api.depends('margin_percentage')
    def _compute_margin_amount_based_on_percentage(self):
        if hasattr(self, '_origin'):
            price = self._origin.product_id.odoo_id._calc_amazon_price(backend=self._origin.product_id.backend_id,
                                                                       margin=self.margin_percentage,
                                                                       marketplace=self._origin.marketplace_id,
                                                                       percentage_fee=self._origin.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                       ship_price=self._origin.price_ship)
            if price:
                self.price = price
                margin = self._origin._get_margin_price(price=price, price_ship=self._origin.price_ship)
                if margin:
                    self.margin_amount = margin[0]

    @api.onchange('price', 'price_ship')
    def _onchange_margin_amount_based_on_price(self):
        self._compute_margin_amount_based_on_price()

    @api.depends('price', 'price_ship')
    def _compute_margin_amount_based_on_price(self):
        origin = None

        if hasattr(self, '_origin'):
            origin = self._origin

        for detail in self:
            if origin:
                margin = origin._get_margin_price(price=detail.price, price_ship=detail.price_ship)
            else:
                margin = detail._get_margin_price(price=detail.price, price_ship=detail.price_ship)

            if margin:
                detail.margin_amount = margin[0]
                detail.margin_percentage = margin[1]
            # Update total price
            detail.total_price = detail.price + detail.price_ship

    @api.multi
    def _compute_real_offer(self):
        for detail in self:
            detail.offer_ids = detail.get_current_offers()

    def _get_amazon_prices(self):
        with self.product_id.backend_id.work_on(self._name) as work:
            importer = work.component(model_name='amazon.product.product', usage='amazon.product.price.import')
            prices = importer.run_get_price(self)
            vals = {}
            if prices:
                price_unit = float(prices.get('price_unit') or 0.)
                price_ship = float(prices.get('price_shipping') or 0.)
                if price_unit != self.price or price_ship != self.price_ship:
                    vals['price'] = price_unit
                    vals['price_ship'] = price_ship
                if prices.get('fee'):
                    vals['percentage_fee'] = round(
                        (prices['fee']['Amount'] * 100) / (self.price + self.price_ship or 0))
                    vals['total_fee'] = prices['fee']['Final']
            else:
                vals['price'] = self.product_id.product_variant_id._calc_amazon_price(backend=self.product_id.backend_id,
                                                                                      margin=self.max_margin or self.product_id.max_margin or self.product_id.backend_id.max_margin,
                                                                                      marketplace=self.marketplace_id,
                                                                                      percentage_fee=self.percentage_fee or AMAZON_DEFAULT_PERCENTAGE_FEE,
                                                                                      ship_price=self.price_ship or 0)
            if vals:
                self.write(vals)

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

    @api.model
    def _get_margin_price(self, price=None, price_ship=None):
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

        delivery_carriers = [template_ship.delivery_standard_carrier_ids for template_ship in backend.shipping_template_ids
                             if template_ship.name == self.merchant_shipping_group and
                             template_ship.marketplace_id.id == self.marketplace_id.id]

        # Get shipping lowest cost configured
        ship_cost = None
        if delivery_carriers:
            for delivery in delivery_carriers[0]:
                try:
                    aux = delivery.get_price_from_picking(total=price, weight=self.product_id.weight or self.product_id.odoo_id.weight, volume=0, quantity=1)
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

    @api.multi
    def _change_price(self, force_change=False):
        """
        Throw the job to change price when the detail, product, backend or one of the suppliers have the flag of change prices on 'yes'
        If one of these flags of detail, product or backend is on 'no' the price doesn't change
        :return:
        """
        if force_change or self.check_change_price():
            product_binding_model = self.env['amazon.product.product']
            delayable = product_binding_model.with_delay(priority=5, eta=datetime.now())
            vals = {'method':'change_price', 'detail_product_id':self.id, 'force_change':force_change}
            delayable.description = '%s.%s' % (self._name, 'change_price(%s)' % self.sku)
            delayable.export_record(self.product_id.backend_id, vals)

    def check_change_price(self):
        if (self.change_prices == '1' or self.product_id.change_prices == '1' or self.product_id.backend_id.change_prices == '1') \
                and not (self.change_prices == '0' or self.product_id.change_prices == '0' or self.product_id.backend_id.change_prices == '0'):
            return True
        return False

    def get_current_offers(self):
        if self.historic_offer_ids:
            # We get the last offer to update
            current_historic_id = self.historic_offer_ids.sorted('offer_date', reverse=True)[0]
            # Calculate the current offers
            return current_historic_id.offer_ids

    def get_our_current_offer(self):
        current_offers = self.get_current_offers()
        if current_offers:
            return current_offers.filtered('is_our_offer')

    def is_buybox_mine(self):
        our_offer = self.get_our_current_offer()
        if our_offer:
            for offer in our_offer:
                if offer.is_buybox:
                    return True
        return False

    def write(self, vals):
        """Refresh delivery price after saving."""
        # If there are a change on merchant shipping template, we need to get the price ship too
        if vals.get('merchant_shipping_group') and vals['merchant_shipping_group'] != self.merchant_shipping_group and not vals.get('price_ship'):
            with self.product_id.backend_id.work_on(self._name) as work:
                importer = work.component(model_name='amazon.product.product', usage='amazon.product.price.import')
                prices = importer.run_get_price(self)
                if prices:
                    price_unit = float(prices.get('price_unit') or 0.)
                    price_ship = float(prices.get('price_shipping') or 0.)
                    vals['price_ship'] = price_ship
                    if prices.get('fee'):
                        vals['percentage_fee'] = round(
                            (prices['fee']['Amount'] * 100) / (price_unit + price_ship or 0))
                        vals['total_fee'] = prices['fee']['Final']
                        if not self.first_price_searched:
                            vals['first_price_searched'] = True

        return super(AmazonProductProductDetail, self).write(vals)


class SupplierInfo(models.Model):
    _inherit = 'product.supplierinfo'

    @api.model
    def create(self, vals):
        record = super(SupplierInfo, self).create(vals)
        self._event('on_record_create').notify(record, fields=vals)
        return record

    @api.model
    def write(self, vals):
        record = super(SupplierInfo, self).write(vals)
        self._event('on_record_write').notify(self, fields=vals)
        return record

    @api.multi
    def unlink(self):
        record = super(SupplierInfo, self).unlink()
        self._event('on_record_unlink').notify(record, fields=None)
        return record

    @api.multi
    def export_products_from_supplierinfo(self):
        try:
            marketplaces = self.name.backend_id.marketplace_ids
            vals = {}
            add = False
            if self.name.automatic_export_products and (self.product_id.barcode or self.product_tmpl_id.barcode) and not self.product_id.amazon_bind_ids:
                add = True
            # If we have the flag to export to all markets
            elif self.name.automatic_export_all_markets:
                # We check if we have only one product on Amazon per odoo product and the backends are the same
                if self.product_id.amazon_bind_ids and len(
                        self.product_id.amazon_bind_ids) == 1 and self.name.backend_id.id == self.product_id.amazon_bind_ids.backend_id.id:
                    markets_of_product = self.product_id.amazon_bind_ids.product_product_market_ids.mapped('marketplace_id').mapped('id')
                    marketplaces = marketplaces.filtered(lambda market:market.id not in markets_of_product)
                    vals['asin'] = self.product_id.amazon_bind_ids.asin
                    add = True if vals.get('asin') else False

            if add and marketplaces:
                vals['method'] = 'add_to_amazon_listing'
                vals['product_id'] = self.product_id.id or self.product_id.product_variant_id.id
                vals['marketplaces'] = marketplaces
                product_binding_model = self.env['amazon.product.product']
                delayable = product_binding_model.with_delay(priority=5, eta=datetime.now())
                delayable.description = '%s.%s' % (self._name, 'add_to_amazon_listing()')
                delayable.export_record(self.name.backend_id, vals)
        except Exception as e:
            _logger.error('Error generating exporting product(%s) to backend: %s' % (self.product_id.default_code, self.name.backend_id.name))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    amazon_bind_id = fields.Many2one('amazon.product.product', 'Amazon product', compute='_compute_amazon_product_id')

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.product.product',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )

    supplier_stock = fields.Float(string='Supplier stock')
    get_supplier_stock = fields.Selection(string='Get supplier stock?', selection=[('1', 'Yes'), ('0', 'No'), ])

    @api.depends('amazon_bind_ids')
    def _compute_amazon_product_id(self):
        for p in self:
            p.amazon_bind_id = p.amazon_bind_ids[:1].id

    def _get_supplier_product_qty(self):
        prod_qty = 0
        if self.product_tmpl_id.seller_ids:
            time_now = datetime.now()
            cost = None
            for supllier_prod in self.product_tmpl_id.seller_ids:
                # If the supplier stock flag on product is 1, we get supplier stock
                # If the supplier stock flag on product is False we don't get the supplier stock never
                # If the supplier stock flag on product is True or is not False and the flag on partner is True we get the stock supplier
                if ((self.get_supplier_stock == '1' or supllier_prod.name.get_supplier_stock == '1') and
                    (self.get_supplier_stock != '0' and supllier_prod.name.get_supplier_stock != '0')) and \
                        (not supllier_prod.date_end or datetime.strptime(supllier_prod.date_end, '%Y-%m-%d') > time_now) and \
                        (not cost or cost > supllier_prod.price):
                    cost = supllier_prod.price
                    prod_qty = supllier_prod.supplier_stock

        return prod_qty

    @api.multi
    def _compute_amazon_stock(self, products_amazon_stock_computed=[]):
        """
        Method to compute the stock on Amazon, we are going to get the virtual available to put on Amazon stock
        :param products_amazon_stock_computed: products computed now, it is important initialize the list on the first call
        :return:
        """
        if self.id in products_amazon_stock_computed:
            return 0
        products_amazon_stock_computed.append(self.id)
        # If the product brand is in the ban list, the stock must be 0
        if len(self.amazon_bind_ids) == 1:
            if self.env['amazon.brand.ban'].search([('brand_ban', '=', self.product_brand_id.id), ('backend_id', '=', self.amazon_bind_ids.backend_id.id)]):
                return 0
        elif len(self.amazon_bind_ids) > 1:
            for amazon_prod in self.amazon_bind_ids:
                if self.env['amazon.brand.ban'].search([('brand_ban', '=', self.product_brand_id.id), ('backend_id', '=', amazon_prod.backend_id.id)]):
                    return 0

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
                    aux = int(line_bom.product_id._compute_amazon_stock(
                        products_amazon_stock_computed=products_amazon_stock_computed) / line_bom.product_qty)
                    # If is the first ocurrence or the calc of stock avaiable with this product is lower than we are saved, we updated this field
                    if qty_bom_produced == None or aux < qty_bom_produced:
                        qty_bom_produced = aux

            qty_total_product += qty_bom_produced if qty_bom_produced else 0

        if qty_total_product < 1:
            qty_total_product = self._get_supplier_product_qty()

        return qty_total_product

    def _compute_amazon_handling_time(self):
        # Add the virtual avaiable of the product itself
        stock_available = self._get_stock_available(products_stock_computed=[])
        if not stock_available:
            return self._get_forecast_handling_time(products_computed=[])
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
            for supplier_prod in self.product_tmpl_id.seller_ids:
                if supplier_prod.supplier_stock > 0 and (not cost or cost > supplier_prod.price) and \
                        (not supplier_prod.date_end or datetime.strptime(supplier_prod.date_end, '%Y-%m-%d') > time_now):
                    cost = supplier_prod.price

        if not cost and self.product_tmpl_id.bom_ids:
            for bom in self.product_tmpl_id.bom_ids:
                for line_bom in bom.bom_line_ids:
                    cost += line_bom.product_id._get_cost() * (line_bom.product_qty or 1)
        return cost

    def _get_stock_available(self, products_stock_computed=[]):
        """

        :param products_computed:
        :return:
        """
        if self.amazon_bind_ids and self.env['amazon.brand.ban'].search([('brand_ban', '=', self.product_brand_id.id),
                                                                         ('backend_id', 'in', self.amazon_bind_ids.mapped('backend_id').mapped('id'))]):
            return 0
        # If we have a physical stock we must return this
        if self.qty_available and self.qty_available > 0:
            return self.qty_available
        if self.id in products_stock_computed:
            # There are recursive configuration on these product
            return 0
        products_stock_computed.append(self.id)
        if self.bom_ids:
            # if we have bom, we need to calculate the forecast stock
            bom_hand_time = None
            for bom in self.bom_ids:
                for line_bom in bom.bom_line_ids:
                    # We are going to get handling time of product of bom
                    aux = line_bom.product_id._get_stock_available(products_stock_computed=products_stock_computed)
                    if not bom_hand_time or bom_hand_time < aux:
                        bom_hand_time = aux
            if bom_hand_time:
                return bom_hand_time

    def _get_forecast_handling_time(self, products_computed=[]):
        """
        We are going to get the handling time of the lowest cost supplier
        :return:
        """

        if self.id in products_computed:
            # There are recursive configuration on these product
            return None
        products_computed.append(self.id)
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
                    days_to_arrive = (datetime.strptime(order.order_id.date_planned, '%Y-%m-%d %H:%M:%S') - time_now).days

                    # Get the products planned to receive
                    sum_orders_qty += order.product_qty
                    # If we get the sum of products on orders and
                    if sum_orders_qty >= units_to_arrive:
                        hand_time = days_to_arrive + 1 if days_to_arrive > 0 else 1
                        break

        # If we haven't hand_time we need get it of seller delay
        if not hand_time and self.product_tmpl_id.seller_ids:
            for supllier_prod in self.product_tmpl_id.seller_ids:
                if supllier_prod.supplier_stock and (not supllier_prod.date_end or time_now > datetime.strptime(supllier_prod.date_end, '%Y-%m-%d')) \
                        and (not cost or cost > supllier_prod.price):
                    cost = supllier_prod.price
                    hand_time = supllier_prod.delay

        if hand_time == None and self.bom_ids:
            # if we have bom, we need to calculate the forecast stock
            bom_hand_time = None
            for bom in self.bom_ids:

                for line_bom in bom.bom_line_ids:
                    # We are going to get handling time of product of bom
                    aux = line_bom.product_id._get_forecast_handling_time(products_computed=products_computed)
                    if not bom_hand_time or bom_hand_time < aux:
                        bom_hand_time = aux
            hand_time = bom_hand_time

        return hand_time

    @api.model
    def _get_amazon_margin(self, backend, amount_margin, marketplace, percentage_fee=AMAZON_DEFAULT_PERCENTAGE_FEE, ship_price=0):
        """
        Get margin of Amazon product using the amount of price
        :param margin:
        :return:
        """
        if amount_margin:
            cost = self._get_cost()
            if not cost:
                return None

            return self._calc_amazon_price(backend=backend, margin=(amount_margin / cost) * 100, marketplace=marketplace, percentage_fee=percentage_fee,
                                           ship_price=ship_price)

        return None

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

            delivery_carriers = [template_ship.delivery_standard_carrier_ids for template_ship in backend.shipping_template_ids
                                 if template_ship.marketplace_id.id == marketplace.id and template_ship.is_default]

            # Get shipping lowest cost configured
            ship_cost = None
            if delivery_carriers:
                for delivery in delivery_carriers[0]:
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

                tax_ids = self.product_tmpl_id.taxes_id or backend.env['account.tax'].browse(backend.env['ir.values'].get_default('product.template',
                                                                                                                                  'taxes_id',
                                                                                                                                  company_id=backend.company_id.id))
                final_price = 0
                for tax_id in tax_ids:
                    final_price += tax_id._compute_amazon_amount_final_price(price_without_tax, percentage_fee=percentage_fee, price_include=False)

                return final_price - ship_price

        return None

    @api.multi
    def get_products_to_recompute_stock(self, product, product_computed=[]):
        """
        Get all products depends of product
        :param product:
        :param product_computed:
        :return:
        """
        if product.type == 'product' and product.id not in product_computed:
            product_computed.append(product.id)
            # First, we are going up on the LoM relationship
            if product.bom_ids:
                for bom in product.bom_ids:
                    for line_bom in bom.bom_line_ids:
                        self.get_products_to_recompute_stock(line_bom.product_id, product_computed=product_computed)
            # Second, we are going to search if any product have this product on LoM
            bom_childs = self.env['mrp.bom.line'].search([('product_id', '=', product.id)])
            for line_bom in bom_childs:
                self.get_products_to_recompute_stock(line_bom.bom_id.product_tmpl_id.product_variant_id, product_computed=product_computed)

    @api.multi
    def recompute_amazon_stocks_product(self):
        """
        Recompute de stock on Amazon of product and all products on upper or lower relationship LoM
                         -- Prod1 --
                         |          |
                       Prod2      Prod3 --
                                          |
                                        Prod4 --> sale this
                                          |
                                        Prod5
        We need to update the stock on Amazon of all products from Prod1 to Prod5
        :param first_product: product of sale
        :param product_computed: control of product's computed for doesn't go to infinite loop
        :return:
        """
        # We pass the list of products to recompute as param
        product_computed = []
        self.get_products_to_recompute_stock(product=self, product_computed=product_computed)
        if product_computed:
            virtual_available = self._compute_amazon_stock(products_amazon_stock_computed=[])
            handling_time = self._compute_amazon_handling_time()
            products = self.env['product.product'].browse(product_computed)
            for product in products:
                if product.type == 'product' and product.amazon_bind_ids:
                    for amazon_product in product.amazon_bind_ids:
                        backend = amazon_product.backend_id
                        if amazon_product.stock_sync or backend.stock_sync:
                            for detail in amazon_product.product_product_market_ids:

                                if handling_time != None and virtual_available != None:
                                    data = {'sku':detail.product_id.sku,
                                            'Quantity':'0' if virtual_available < 0 or not handling_time else str(
                                                int(virtual_available)),
                                            'id_mws':detail.marketplace_id.id_mws}

                                    vals = {'backend_id':backend.id,
                                            'type':'_POST_INVENTORY_AVAILABILITY_DATA_',
                                            'model':detail._name,
                                            'identificator':detail.id,
                                            'data':data,
                                            }
                                    self.env['amazon.feed.tothrow'].create(vals)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_amazon_product = fields.Boolean(store=True,
                                       default=lambda self:True if self.product_variant_id.amazon_bind_ids else False)

    amazon_bind_id = fields.Many2one('amazon.product.product', 'Amazon product', related='product_variant_id.amazon_bind_id')
    product_product_market_ids = fields.One2many(comodel_name='amazon.product.product.detail', related='amazon_bind_id.product_product_market_ids')


class AmazonProductUoM(models.Model):
    _name = 'amazon.product.uom'

    product_uom_id = fields.Many2one('product.uom', 'Product UoM')
    name = fields.Char()


class AmazonOffer(models.Model):
    _name = 'amazon.product.offer'

    historic_id = fields.Many2one('amazon.historic.product.offer', ondelete='cascade', index=True)
    id_seller = fields.Char()
    price = fields.Float()
    currency_price_id = fields.Many2one('res.currency')
    price_ship = fields.Float()
    currency_ship_price_id = fields.Many2one('res.currency')
    total_price = fields.Float(compute='_compute_total_price')
    is_lower_price = fields.Boolean(default=False)
    is_buybox = fields.Boolean(default=False)
    is_prime = fields.Boolean(default=False)
    seller_feedback_rating = fields.Char()
    seller_feedback_count = fields.Char()
    country_ship_id = fields.Many2one('res.country')
    amazon_fulffilled = fields.Boolean()
    condition = fields.Char()
    is_our_offer = fields.Boolean(compute='_compute_is_our_offer', store=True)
    offer_date = fields.Char('Offer date', readonly='1')

    @api.depends('id_seller')
    def _compute_is_our_offer(self):
        for offer in self:
            if offer.historic_id.product_detail_id and offer.id_seller == offer.historic_id.product_detail_id.product_id.backend_id.seller:
                offer.is_our_offer = True
            else:
                offer.is_our_offer = False

    @api.depends('price', 'price_ship')
    def _compute_total_price(self):
        for offer in self:
            offer.total_price = (offer.price or 0) + (offer.price_ship or 0)


class AmazonHistoricOffer(models.Model):
    _name = 'amazon.historic.product.offer'

    offer_date = fields.Datetime()
    product_detail_id = fields.Many2one('amazon.product.product.detail', ondelete='cascade', index=True)
    offer_ids = fields.One2many(comodel_name='amazon.product.offer',
                                inverse_name='historic_id',
                                string='Offers of the product')

    message_body = fields.Char('XML offers', help='If the historic offer come from message, it is the body of this')


class ProductProductAdapter(Component):
    _name = 'amazon.product.product.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.product.product'

    def _call(self, method, arguments):
        try:
            return super(ProductProductAdapter, self)._call(method, arguments)
        except Exception:
            raise

    @api.model
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
