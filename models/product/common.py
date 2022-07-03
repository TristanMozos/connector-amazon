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
import inspect
import logging
import os
import random

from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.addons.component.core import Component
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import UserError

from ...models.config.common import AMAZON_DEFAULT_PERCENTAGE_FEE

_logger = logging.getLogger(__name__)


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

    stock_sync = fields.Boolean('Stock shyncronization', default=True)
    handling_time = fields.Integer('Time to get since we received an order to send this')

    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonProductProduct, self)
        try:
            result = _super.import_record(backend, external_id)
            if not result:
                raise RetryableJobError(msg='The product of the backend %s hasn\'t could not be imported. \n %s' %
                                            (backend.name, external_id),
                                        seconds=300)

        except Exception as e:
            if e.message.find('current transaction is aborted') > -1 or \
                    e.message.find('could not serialize access due to concurrent update') > -1:
                raise RetryableJobError(msg='A concurrent job is already importing the same record (%s). The job will be retried later.' % (self._name),
                                        seconds=random.randint(60, 300),
                                        ignore_retry=True)
            raise e

    @api.model
    def export_record(self, backend, internal_id):
        _super = super(AmazonProductProduct, self)
        try:
            result = _super.export_record(backend, internal_id)
        except Exception as e:
            raise e

    def get_market_detail_product(self, market):
        if market:
            market_id = None
            if not isinstance(market, (int, float)):
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
    currency_price = fields.Many2one('res.currency', 'Currency price', required=False)
    price_ship = fields.Float('Price of ship', required=False)  # This price have the tax included
    currency_ship_price = fields.Many2one('res.currency', 'Currency price ship', required=False)
    total_price = fields.Char('Total price')
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

    buybox_price = fields.Float('Buybox price')
    lowest_price = fields.Float('Lowest total price')
    merchant_shipping_group = fields.Char('Shipping template name')

    # Min and max margin stablished for the calculation of the price on product and product price details if these do not be informed
    stock_sync = fields.Boolean('Stock shyncronization', default=True)

    total_fee = fields.Float('Amount of fee')
    percentage_fee = fields.Float('Percentage fee of Amazon sale')

    last_update_price_date = fields.Datetime(string='Last update price import')


class ProductProduct(models.Model):
    _inherit = 'product.product'

    amazon_bind_id = fields.Many2one('amazon.product.product', 'Amazon product', compute='_compute_amazon_product_id')

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.product.product',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )

    @api.depends('amazon_bind_ids')
    def _compute_amazon_product_id(self):
        for p in self:
            p.amazon_bind_id = p.amazon_bind_ids[:1].id


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_amazon_product = fields.Boolean(store=True,
                                       default=lambda self:True if self.product_variant_id.amazon_bind_ids else False)

    amazon_bind_id = fields.Many2one('amazon.product.product', 'Amazon product', related='product_variant_id.amazon_bind_id')
    product_product_market_ids = fields.One2many(comodel_name='amazon.product.product.detail', related='amazon_bind_id.product_product_market_ids')


class AmazonProductUoM(models.Model):
    _name = 'amazon.uom.uom'

    product_uom_id = fields.Many2one('uom.uom', 'Product UoM')
    name = fields.Char()


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
