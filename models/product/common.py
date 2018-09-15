# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError
from odoo.addons.queue_job.job import job

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

    RECOMPUTE_QTY_STEP = 1000  # products at a time

    @job(default_channel='root.amazon')
    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonProductProduct, self)
        try:
            result = _super.import_record(backend, external_id)
            if not result:
                raise RetryableJobError('The product of the backend %s hasn\'t could not be imported. \n %s', backend.name, external_id, 60)
        except Exception as e:
            if e.message.find('current transaction is aborted') > -1 or e.message.find('could not serialize access due to concurrent update') > -1:
                raise RetryableJobError('A concurrent job is already exporting the same record '
                                        '(%s). The job will be retried later.' % self.model._name, 60, True)
            raise e


class ProductProductDetail(models.Model):
    _name = 'amazon.product.product.detail'
    _inherits = {'product.pricelist':'odoo_id'}
    _description = 'Amazon Product Variant on Every Marketplace'

    odoo_id = fields.Many2one(comodel_name='product.pricelist',
                              string='PriceList',
                              required=True,
                              ondelete='restrict')

    product_id = fields.Many2one('amazon.product.product', 'product_data_market_ids', ondelete='cascade', required=True,
                                 readonly=True)
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
                                         ('Submmited', 'Submmited')],
                              string='Status', default='Active')
    stock = fields.Integer('Stock')
    date_created = fields.Datetime('date_created', required=False)
    category_id = fields.Many2one('amazon.config.product.category', 'Category',
                                  default=lambda self:self.env['amazon.config.product.category'].search(
                                      [('name', '=', 'default')]))
    has_buybox = fields.Boolean(string='Is the buybox winner', default=False)
    has_lowest_price = fields.Boolean(string='Is the lowest price', default=False)
    lowest_price = fields.Float('Lowest total price')
    lowest_product_price = fields.Float('Lowest product price', required=False)
    lowest_shipping_price = fields.Float('Lower shipping price', required=False)
    merchant_shipping_group = fields.Char('Shipping template name')


class ProductProduct(models.Model):
    _inherit = 'product.product'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.product.product',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )


class ProductPriceList(models.Model):
    _inherit = 'product.pricelist'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.product.product.detail',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )

    sku = fields.Char('Product reference on Amazon')

    marketplace_price_id = fields.Many2one('amazon.config.marketplace', "marketplace_id")


class AmazonProductUoM(models.Model):
    _name = 'amazon.product.uom'

    product_uom_id = fields.Many2one('product.uom', 'Product UoM')
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
