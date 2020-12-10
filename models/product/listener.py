# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import datetime

from odoo.addons.component.core import Component
from odoo.addons.component_event import skip_if

_logger = logging.getLogger(__name__)


class AmazonBindingProductSupplierInfoListener(Component):
    _name = 'amazon.binding.amazon.product.supplierinfo.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['product.supplierinfo']

    def throw_recalculate_stock(self, record):
        product_binding_model = self.env['amazon.product.product']
        if record.product_id.type == 'product':
            for amazon_product in record.product_id.amazon_bind_ids:
                delayable = product_binding_model.with_delay(priority=5, eta=datetime.now())
                vals = {'method':'recompute_stocks_product', 'product_id':amazon_product}
                delayable.description = 'From sale: %s.%s' % (self._name, 'recompute_amazon_stocks_product(%s)' % record.product_id.default_code)
                delayable.export_record(self.env['amazon.backend'].search([], limit=1), vals)

    def throw_change_price(self, record):
        if record.product_id.amazon_bind_ids:
            for amazon_product in record.product_id.amazon_bind_ids:
                product_binding_model = self.env['amazon.product.product']
                delayable = product_binding_model.with_delay(priority=5, eta=datetime.now())
                vals = {'method':'recompute_prices_product', 'product_id':record.product_id, 'force_change':False}
                delayable.description = '%s.%s' % (self._name, 'recompute_prices_product(%s)' % record.product_id.default_code)
                delayable.export_record(amazon_product.backend_id, vals)

    def on_record_create(self, record, fields=None):
        """
        When the product.supplierinfo is write we are going to change the price and stock of the product
        :param record:
        :param fields:
        :return:
        """
        try:
            if record.product_id.amazon_bind_ids:
                # TODO We need to diference between stock recalculate and change price
                # Throw recalculate job
                self.throw_recalculate_stock(record)
                # Throw the change price
                self.throw_change_price(record)
        except Exception as e:
            _logger.error('Connector_amazon log: exception on listener \'on_record_create\' of product.supplierinfo [%s]' % e.message)

    def on_record_write(self, record, fields=None):
        """
        When the product.supplierinfo is write we are going to change the price and stock of the product
        :param record:
        :param fields:
        :return:
        """
        # TODO Test if it
        if record.product_id.amazon_bind_ids and isinstance(fields, dict):
            if fields.get('price'):
                self.throw_change_price(record)
            elif fields.get('supplier_stock'):
                self.throw_recalculate_stock(record)

        return

    def on_record_unlink(self, record, fields=None):
        # TODO throw change stock job
        self.throw_change_price(record)


class AmazonProductProductListener(Component):
    _name = 'amazon.binding.amazon.product.product.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['amazon.product.product']

    def on_record_create(self, record, fields=None):
        self.env['amazon.report.product.to.create'].search([('product_id', '=', record.odoo_id.product_tmpl_id.id)]).unlink()


class AmazonBindingProductSupplierInfoListener(Component):
    _name = 'amazon.binding.amazon.product.detail.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['amazon.product.product.detail']

    @skip_if(lambda self, record, **kwargs: self.no_connector_export(record))
    def on_record_write(self, record, fields=None):
        # If we had saved the data of product change, we are going to change the price of detail
        if fields and ('min_margin' in fields or 'max_margin' in fields or 'change_prices' in fields or 'min_price_margin_value' in fields):
            record._change_price()

        if fields and 'price' in fields:
            # We are going to change the price in Amazon
            data = {'sku':record.sku,
                    'Price':("%.2f" % record.price).replace('.', record.marketplace_id.decimal_currency_separator) if record.price else '',
                    'Quantity':str(record.stock),
                    'handling-time':str(record.product_id.handling_time),
                    'id_mws':record.marketplace_id.id_mws}

            vals = {'backend_id':record.product_id.backend_id.id,
                    'type':'_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_',
                    'model':record._name,
                    'identificator':record.id,
                    'marketplace_id':record.marketplace_id.id,
                    'data':data,
                    }
            self.env['amazon.feed.tothrow'].create(vals)
        return


class AmazonBindingProductSupplierInfoListener(Component):
    _name = 'amazon.binding.amazon.product.product.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['amazon.product.product']

    @skip_if(lambda self, record, **kwargs: self.no_connector_export(record))
    def on_record_write(self, record, fields=None):
        # If we had saved the data of product change, we are going to change the price of detail
        if fields and ('min_margin' in fields or 'max_margin' in fields or 'change_prices' in fields or 'min_price_margin_value' in fields):
            record._change_price()


class AmazonBindingSaleOrderListener(Component):
    _name = 'amazon.binding.sale.order.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['sale.order']

    def _recompute_stocks_sale(self, record):
        """
        :param record: sale
        :return:
        """
        for line in record.order_line:
            product = line.product_id
            if product.type == 'product':
                product.recompute_amazon_stocks_product()
        return

    def on_record_create(self, record, fields=None):

        if record.state == 'sale':
            self._recompute_stocks_sale(record)

    def on_record_write(self, record, fields=None):
        if 'state' in fields and record.state in ('sale', 'cancel'):
            self._recompute_stocks_sale(record)

class AmazonBindingSaleOrderLineListener(Component):
    _name = 'amazon.binding.sale.order.line.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['sale.order.line']

    def _recompute_stocks_sale(self, record):
        """
        :param record: sale
        :return:
        """
        if record.product_id.type == 'product':
            record.product_id.recompute_amazon_stocks_product()
        return

    def on_record_create(self, record, fields=None):
        if record.state == 'sale' and record.product_id.type == 'product':
            self._recompute_stocks_sale(record)

    def on_record_write(self, record, fields=None):
        if 'state' in fields and record.state in ('sale', 'cancel'):
            self._recompute_stocks_sale(record)


class AmazonBindingPurchaseOrderListener(Component):
    _name = 'amazon.binding.purchase.order.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['purchase.order']

    def _recompute_stocks_purchase(self, record):
        """
        :param record: sale
        :return:
        """
        for line in record.order_line:
            product = line.product_id
            if product.type == 'product':
                product.recompute_amazon_stocks_product()
        return

    def on_record_create(self, record, fields=None):
        if record.state == 'purchase':
            self._recompute_stocks_purchase(record)

    def on_record_write(self, record, fields=None):
        if 'state' in fields and record.state in ('purchase', 'cancel'):
            self._recompute_stocks_purchase(record)


class AmazonBindingProductProductListener(Component):
    _name = 'amazon.binding.product.product.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['product.product']

    def on_record_write(self, record, fields=None):
        if 'barcode' in fields:
            if record.amazon_bind_ids:
                for amazon_bind in record.amazon_bind_ids:
                    data = {'marketplace_ids': amazon_bind.product_data_market_ids.mapped('marketplace_id').mapped('id'),
                            'amazon_product_id': amazon_bind.id,
                            }

                    vals = {'backend_id': amazon_bind.backend_id.id,
                            'type': 'Delete inventory products',
                            'model': self._name,
                            'identificator': self.id,
                            'data': data,
                            }
                    self.env['amazon.feed.tothrow'].create(vals)

                record.amazon_bind_ids.unlink()