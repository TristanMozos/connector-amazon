# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from datetime import datetime
import logging
import re

from odoo.fields import Datetime
from odoo import _
from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError

from ...components.backend_adapter import AMAZON_ORDER_ID_PATTERN

_logger = logging.getLogger(__name__)


class SaleOrderBatchImporter(Component):
    _name = 'amazon.sale.order.batch.importer'
    _inherit = 'amazon.direct.batch.importer'
    _apply_on = 'amazon.sale.order'

    def run(self, filters=None):
        """ Run the synchronization """
        sales = self.backend_adapter.search(filters)
        _logger.info('get report of saleorders returned %s', sales.keys())
        for sale in sales.iteritems():
            sale_binding_model = self.env['amazon.sale.order']
            delayable = sale_binding_model.with_delay(priority=5, eta=datetime.now())
            delayable.import_record(self.backend_record, sale)


class SaleOrderImportMapper(Component):
    _name = 'amazon.sale.order.mapper'
    _inherit = 'amazon.import.mapper'
    _apply_on = 'amazon.sale.order'

    direct = [('order_id', 'external_id'),
              ('order_id', 'id_amazon_order'),
              ('date_order', 'date_order'),
              ('date_order', 'date_purchase'),
              ('date_order', 'confirmation_date'),
              ('date_order', 'requested_date'),
              ('total_product_price', 'total_product_amount'),
              ('total_ship_amount', 'total_ship_amount'),
              ('earlest_delivery_date', 'date_earliest_delivery'),
              ('earlest_ship_date', 'date_earliest_ship'),
              ('lastest_delivery_date', 'date_latest_delivery'),
              ('lastest_ship_date', 'date_latest_ship'),
              ('lastest_delivery_date', 'commitment_date'),
              ('ship_service_level', 'shipment_service_level_category'),
              ('is_premium', 'is_premium'),
              ('is_business', 'is_business'),
              ('is_prime', 'is_prime'),
              ]

    children = [('lines', 'amazon_order_line_ids', 'amazon.sale.order.line'), ]

    def _add_shipping_line(self, map_record, values):
        record = map_record.source
        amount_incl = float(record.get('total_ship_amount') or 0.0)
        line_builder = self.component(usage='order.line.builder.shipping')
        # add even if the price is 0, otherwise odoo will add a shipping
        # line in the order when we ship the picking
        line_builder.price_unit = amount_incl

        if values.get('carrier_id'):
            carrier = self.env['delivery.carrier'].browse(values['carrier_id'])
            line_builder.product = carrier.product_id

        line = (0, 0, line_builder.get_line())
        values['order_line'].append(line)
        return values

    def finalize(self, map_record, values):
        values.setdefault('order_line', [])
        values = self._add_shipping_line(map_record, values)
        values.update({
            'partner_invoice_id':values['partner_id'],
            'partner_shipping_id':values['partner_id'],
        })
        onchange = self.component(usage='ecommerce.onchange.manager.sale.order')
        return onchange.play(values, values['amazon_order_line_ids'])

    @mapping
    def name(self, record):
        name = record['order_id']
        prefix = self.backend_record.sale_prefix
        if prefix:
            name = prefix + name
        return {'name':name}

    @mapping
    def customer_id(self, record):
        binder = self.binder_for('amazon.res.partner')
        partner = binder.to_internal(record['partner']['email'], unwrap=True)
        assert partner, (
                "customer_id %s should have been imported in "
                "SaleOrderImporter._import_dependency" % record['partner']['email'])
        return {'partner_id':partner.id}

    @mapping
    def partner_id(self, record):
        return {'amazon_partner_id':record.get('partner_id')}

    def sales_team(self, record):
        team = self.env['crm.team'].search([('name', '=', 'Amazon Sales')])
        if team:
            return {'team_id':team.id}

    @mapping
    def marketplace_sale_id(self, record):
        if record.get('marketplace_id'):
            return {'marketplace_sale_id':record['marketplace_id']}

    @mapping
    def fullfillment(self, record):
        if not record.get('FulfillmentChannel') or record['FulfillmentChannel'] == 'MFN' or record['FulfillmentChannel'].upper().find('AMAZ') < 0:
            return {'fullfillment_channel':'MFN'}
        return {'fullfillment_channel':'AMZ'}

    @mapping
    def warehouse_id(self, record):
        if not record.get('FulfillmentChannel') or record['FulfillmentChannel'] == 'MFN' or record['FulfillmentChannel'].upper().find('AMAZ') < 0:
            return {'warehouse_id':self.backend_record.warehouse_id.id}
        elif self.backend_record.fba_warehouse_id:
            return {'fba_warehouse_id':self.backend_record.fba_warehouse_id.id}

        return {'warehouse_id':self.backend_record.warehouse_id.id}

    @mapping
    def currency_id(self, record):
        if record.get('currency_total_amount'):
            currency = self.env['res.currency'].browse(record['currency_total_amount']) or \
                       self.env['res.currency'].search([('name', '=', record['currency_total_amount'])])
            if currency:
                return {'currency_id':currency.id}

    @mapping
    def total_product_amount(self, record):
        if record.get('lines'):
            total_product_amount = 0.
            for line in record['lines']:
                if line.get('item_price'):
                    total_product_amount += float(line['item_price'] or 0.)

            record['total_product_amount'] = total_product_amount
            return {'total_product_amount':total_product_amount}

        return

    @mapping
    def total_ship_amount(self, record):
        if record.get('lines'):
            total_ship_amount = 0.
            for line in record['lines']:
                if line.get('ship_price'):
                    total_ship_amount += float(line['ship_price'] or 0.)

            record['total_ship_amount'] = total_ship_amount
            return {'total_ship_amount':total_ship_amount}

        return

    @mapping
    def total_amount(self, record):
        if record.get('lines'):
            total_amount = 0.
            for line in record['lines']:
                if line.get('item_price') and line.get('ship_price'):
                    total_amount += float(line['item_price'] or 0.) + float(line['ship_price'] or 0.)

            record['total_amount'] = total_amount
            return {'total_amount':total_amount}

        return

    @mapping
    def order_status_id(self, record):
        if record.get('order_status_id'):
            return {'order_status_id':record['order_status_id']}

    @mapping
    def state(self, record):
        return {'state':'sale'}

    @mapping
    def total_tax_included(self, record):
        return {'total_included':True}

    # partner_id, partner_invoice_id, partner_shipping_id
    # are done in the importer

    @mapping
    def backend_id(self, record):
        return {'backend_id':self.backend_record.id}


class SaleOrderImporter(Component):
    _name = 'amazon.sale.order.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.sale.order']

    def _must_skip(self):
        """ Hook called right after we read the data from the backend.

        If the method returns a message giving a reason for the
        skipping, the import will be interrupted and the message
        recorded in the job (if the import is called directly by the
        job, not by dependencies).

        If it returns None, the import will continue normally.

        :returns: None | str | unicode
        """
        return None

    def _import_dependencies(self):
        importer = self.component(usage='record.importer', model_name='amazon.res.partner')
        importer.amazon_record = self.amazon_record['partner']
        self._import_dependency(external_id=self.amazon_record['partner']['email'], binding_model='amazon.res.partner', importer=importer)
        self.amazon_record['partner_id'] = self.env['amazon.res.partner'].search([('email', '=', self.amazon_record['partner']['email'])]).id

        # Check if the product is imported
        for line in self.amazon_record['lines']:
            product = self.env['amazon.product.product'].search([('sku', '=', line.get('sku'))])
            if not product:
                self._import_dependency([line.get('sku'), ], 'amazon.product.product')

    def _create(self, data):
        binding = super(SaleOrderImporter, self)._create(data)
        if binding.fiscal_position_id:
            binding.odoo_id._compute_tax_id()
        return binding

    def _validate_data(self, data):
        if not re.match(AMAZON_ORDER_ID_PATTERN, self.external_id):
            raise FailedJobError('The external_id validation failed %s %s', AMAZON_ORDER_ID_PATTERN, self.external_id)
        try:
            if not data.get('date_order'):
                return False
        except:
            return False

        return True

    def _get_amazon_data(self):
        if self.amazon_record and self._validate_data(self.amazon_record):
            return self.amazon_record
        return self.backend_adapter.read(external_id=self.external_id)

    def _create_data(self, map_record, **kwargs):
        return super(SaleOrderImporter, self)._create_data(
            map_record,
            tax_include=True,
            partner_id=self.amazon_record['partner_id'],
            partner_invoice_id=self.amazon_record['partner_id'],
            partner_shipping_id=self.amazon_record['partner_id'],
            **kwargs)

    def _update_data(self, map_record, **kwargs):
        return super(SaleOrderImporter, self)._update_data(
            map_record,
            tax_include=True,
            **kwargs)

    def _update(self, binding, data):
        """ Update an Odoo record, we only need updated few fields """
        vals = {}
        order_status_id = binding.order_status_id
        if order_status_id.id != data.get('order_status_id'):
            vals['order_status_id'] = data.get('order_status_id')

        vals['number_items_shipped'] = data.get('number_items_shipped')
        vals['number_items_unshipped'] = data.get('number_items_unshipped')

        binding.write(vals)
        # If the order has been shipped we call to stock.picking.do_transfer()
        if order_status_id.id != binding.order_status_id.id and \
                binding.order_status_id.name == 'Shipped':
            for pick in binding.odoo_id.picking_ids:
                pick.do_transfer()

    def _before_import(self):
        if self.amazon_record and self.amazon_record.get('lines'):
            importer = self.component(usage='amazon.product.category', model_name='amazon.product.product')
            record = {'marketplace_id':self.amazon_record['marketplace'].id,
                      'product_product_market_ids':[
                          {'marketplace_id':self.amazon_record['marketplace'].id,
                           'sku':line['sku']}
                          for line in self.amazon_record['lines']]}
            importer.run(record)
        elif self.amazon_record and not self.amazon_record.get('lines'):
            try:
                self.backend_adapter.get_lines(filters=[self.amazon_record])
                if not self.amazon_record.get('lines'):
                    status = self.backend_record.env['amazon.config.order.status'].browse(self.amazon_record.get('order_status_id')).name
                    if status and status != 'Cancelled':
                        raise FailedJobError("Error recovering lines of the record (%s)", self.amazon_record['order_id'])
                    raise RetryableJobError('The record haven\'t got the lines of items', 60, True)
            except:
                raise RetryableJobError('The record haven\'t got the lines of items', 60, True)
        return

    def _after_import(self, binding):
        """ Hook called at the end of the import
            Recalculate the prices with taxes (all the sales on Amazon have the prices included)
        """
        try:
            backend = self.backend_record
            if binding.odoo_id.order_line:
                # Compute the prices of lines without taxes
                amount_untaxed = amount_tax = 0.0
                for line in binding.odoo_id.order_line:
                    # Get the default sale tax of the company
                    if not line.tax_id:
                        line.tax_id = backend.env['account.tax'].browse(backend.env['ir.values'].get_default('product.template',
                                                                                                             'taxes_id',
                                                                                                             company_id=backend.company_id.id))
                    if not line.tax_id.price_include and line.tax_id:
                        taxes = line.tax_id._compute_amount_taxes_include(line.price_unit,
                                                                          line.product_uom_qty)
                        line.update({
                            'price_tax':taxes,
                            'price_total':line.price_unit,
                            'price_subtotal':line.price_unit - taxes,
                        })

                    amount_untaxed += line.price_subtotal
                    # FORWARDPORT UP TO 10.0
                    if binding.odoo_id.company_id.tax_calculation_rounding_method == 'round_globally':
                        price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                        taxes = line.tax_id.compute_all_with_taxes(price, line.order_id.currency_id, line.product_uom_qty,
                                                                   product=line.product_id, partner=binding.odoo_id.partner_shipping_id)
                        amount_tax += sum(t.get('amount', 0.0) for t in taxes.get('taxes', []))
                    else:
                        amount_tax += line.price_tax

                binding.odoo_id.update({
                    'amount_untaxed':binding.odoo_id.pricelist_id.currency_id.round(amount_untaxed),
                    'amount_tax':binding.odoo_id.pricelist_id.currency_id.round(amount_tax),
                    'amount_total':amount_untaxed + amount_tax,
                })

        except Exception as e:
            if e.message.find('could not serialize access due to concurrent update') > -1:
                raise RetryableJobError('', 30, True)
            raise e

        # If the order has been shipped we call to stock.picking.do_transfer()
        if binding.order_status_id.name == 'Shipped':
            for pick in binding.odoo_id.picking_ids:
                pick.do_transfer()

    def run(self, external_id, force=False):
        """ Run the synchronization

        :param external_id: identifier of the record on Amazon
        """
        if external_id and (isinstance(external_id, list) or isinstance(external_id, tuple)):
            self.external_id = external_id[0]
            self.amazon_record = external_id[1]
            self.amazon_record['marketplace'] = self.env['amazon.config.marketplace'].search([('id_mws', '=', self.amazon_record.get('marketplace_id'))])
            self.amazon_record['marketplace_id'] = self.amazon_record['marketplace'].id
        else:
            self.external_id = external_id
        _super = super(SaleOrderImporter, self)
        return _super.run(self.external_id, force)


class SaleOrderLineImportMapper(Component):
    _name = 'amazon.sale.order.line.mapper'
    _inherit = 'amazon.import.mapper'
    _apply_on = 'amazon.sale.order.line'

    direct = [('id_item', 'id_item'),
              ('product_uom_qty', 'product_uom_qty'),
              ('quantity_purchased', 'qty_ordered'),
              ('name', 'name'),
              ('item_price', 'item_price'),
              ('ship_price', 'ship_price'),
              ]

    @mapping
    def product_id(self, record):
        binder = self.binder_for('amazon.product.product')
        product = binder.to_internal(record['sku'], unwrap=True)
        assert product, (
                "product_id %s should have been imported in "
                "SaleOrderImporter._import_dependencies" % record['product_id'])
        return {'product_id':product.id}

    @mapping
    def amazon_product_id(self, record):
        product = self.env['amazon.product.product'].search([('sku', '=', record.get('sku'))])
        assert product, (
                "product_id %s should have been imported in "
                "SaleOrderImporter._import_dependencies" % record['sku'])
        return {'amazon_product_id':product.id}

    @mapping
    def price(self, record):
        if record.get('price_unit'):
            return {'price_unit':record['price_unit']}

    @mapping
    def state(self, record):
        return {'state':'sale'}

    @mapping
    def fee(self, record):
        if record.get('sku') and record.get('marketplace_id'):
            product = self.env['amazon.product.product.detail'].search([('sku', '=', record['sku']), ('marketplace_id', '=', record['marketplace_id'])])
            if product and product.category_id:
                percentage = product.category_id.percentage
            else:
                percentage = self.env['amazon.config.product.category'].search([('name', '=', 'default')]).percentage

            fee = (float(record.get('item_price') or 0.) + float(record.get('ship_price') or 0.) * percentage) / 100

            return {'fee':fee}
